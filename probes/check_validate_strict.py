#!/usr/bin/env python3
"""T1.1 verdict check: strict plugin validation + fresh-env package import.

Four sub-checks, all must PASS:
  (a) `claude plugin validate --strict .` from the repo root
  (b) a fresh `uv`-created env, package installed non-editable from
      pyproject.toml, `import hyperspace` succeeds and reports the version
  (c) `.mcp.json`'s server command is the project env's interpreter at its
      portable spelling (`.hyperspace/env/bin/python -m hyperspace.mcp`), and
      spawning it with no env fails loudly (no process, never a silent hang)
  (d) both plugin manifests and `.mcp.json` parse as JSON

Usage: probes/check_validate_strict.py --out <path>
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _mcp_launch import mcp_launch  # noqa: E402
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hyperspace.venv_paths import native_python  # noqa: E402


def _trim(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


#: The system directories kept on PATH for `claude plugin validate`.
_SYSTEM_PATH = (
    [r"C:\Windows\System32", r"C:\Windows"] if sys.platform == "win32"
    else ["/usr/bin", "/bin", "/usr/local/bin"]
)


def check_validate_strict(evidence: dict) -> bool:
    claude = shutil.which("claude")
    if claude is None:
        evidence["validate_strict"] = {
            "command": "claude plugin validate --strict .",
            "error": "`claude` not found on PATH",
        }
        return False

    import os

    path = os.pathsep.join([str(Path(claude).parent), *_SYSTEM_PATH])
    env = {"CLAUDE_CONFIG_DIR": "", "PATH": path}
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "USERPROFILE", "PATHEXT"):
        if key in os.environ:  # Windows processes need these to start at all
            env[key] = os.environ[key]
    with tempfile.TemporaryDirectory() as config_dir:
        env["CLAUDE_CONFIG_DIR"] = config_dir
        proc = subprocess.run(
            [claude, "plugin", "validate", "--strict", "."],
            cwd=ROOT,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )
    evidence["validate_strict"] = {
        "command": "claude plugin validate --strict .",
        "exit_code": proc.returncode,
        "stdout": _trim(proc.stdout),
        "stderr": _trim(proc.stderr),
    }
    return proc.returncode == 0


def check_fresh_env_import(evidence: dict) -> bool:
    uv = shutil.which("uv")
    if uv is None:
        evidence["fresh_env_import"] = {"error": "`uv` not found on PATH"}
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env_dir = tmp_path / "env"

        venv_proc = subprocess.run(
            [uv, "venv", str(env_dir)],
            capture_output=True,
            encoding="utf-8", errors="replace",
        )
        install_proc = subprocess.run(
            [uv, "pip", "install", "--python", str(native_python(env_dir)), str(ROOT)],
            capture_output=True,
            encoding="utf-8", errors="replace",
        )
        # cwd is the empty temp dir, never the repo root — `python -c` puts
        # cwd on sys.path[0], and importing from the repo root would find the
        # source tree directly rather than the installed package, producing
        # a false PASS on the "fresh install" claim.
        import_proc = subprocess.run(
            [str(native_python(env_dir)), "-c",
             "import hyperspace, sys; print(hyperspace.__version__)"],
            cwd=tmp_path,
            capture_output=True,
            encoding="utf-8", errors="replace",
        )

        evidence["fresh_env_import"] = {
            "venv": {
                "command": f"uv venv {env_dir}",
                "exit_code": venv_proc.returncode,
                "stderr": _trim(venv_proc.stderr),
            },
            "install": {
                "command": f"uv pip install --python {native_python(env_dir)} {ROOT}",
                "exit_code": install_proc.returncode,
                "stdout": _trim(install_proc.stdout),
                "stderr": _trim(install_proc.stderr),
            },
            "import": {
                "command": f"{native_python(env_dir)} -c \"import hyperspace; print(hyperspace.__version__)\"",
                "exit_code": import_proc.returncode,
                "stdout": _trim(import_proc.stdout),
                "stderr": _trim(import_proc.stderr),
            },
        }

        return (
            venv_proc.returncode == 0
            and install_proc.returncode == 0
            and import_proc.returncode == 0
            and import_proc.stdout.strip() == "0.1.3"
        )


def check_mcp_command(evidence: dict) -> bool:
    with tempfile.TemporaryDirectory() as empty_project:
        command, args = mcp_launch(ROOT, empty_project)
        expected = (Path(empty_project) / ".hyperspace" / "env" / "bin" / "python").as_posix()
        try:
            subprocess.run([command, *args], capture_output=True, timeout=30)
            missing_env = "spawned — expected no process without an environment"
            refused = False
        except FileNotFoundError as exc:
            missing_env = f"FileNotFoundError: {exc}"
            refused = True

    evidence["mcp_command"] = {
        "command": command,
        "args": args,
        "expected_command": expected,
        "missing_env_spawn": missing_env,
    }
    return command == expected and args == ["-m", "hyperspace.mcp"] and refused


def check_manifests_parse(evidence: dict) -> bool:
    targets = [
        ROOT / ".claude-plugin" / "marketplace.json",
        ROOT / ".claude-plugin" / "plugin.json",
        ROOT / ".mcp.json",
    ]
    results = {}
    ok = True
    for target in targets:
        try:
            json.loads(target.read_text(encoding="utf-8"))
            results[str(target.relative_to(ROOT))] = "parsed OK"
        except Exception as exc:  # noqa: BLE001
            results[str(target.relative_to(ROOT))] = f"FAILED: {exc}"
            ok = False
    evidence["manifests_parse"] = results
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    evidence: dict = {}
    a = check_validate_strict(evidence)
    b = check_fresh_env_import(evidence)
    c = check_mcp_command(evidence)
    d = check_manifests_parse(evidence)

    result = "PASS" if (a and b and c and d) else "FAIL"
    write_verdict(args.out, probe="validate_strict", result=result, evidence=evidence)

    print(f"validate_strict: {result} (validate={a} fresh_import={b} mcp_command={c} manifests={d})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
