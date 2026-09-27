#!/usr/bin/env python3
"""T1.1 verdict check: strict plugin validation + fresh-env package import.

Four sub-checks, all must PASS:
  (a) `claude plugin validate --strict .` from the repo root
  (b) a fresh `uv`-created env, package installed non-editable from
      pyproject.toml, `import hyperspace` succeeds and reports the version
  (c) the launcher's shell syntax is valid, and it refuses (exit 1, naming
      `.hyperspace/env`) when the isolated env is missing
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
from _verdict import write_verdict  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def _trim(text: str, limit: int = 4000) -> str:
    if text is None:
        return ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"


def check_validate_strict(evidence: dict) -> bool:
    claude = shutil.which("claude")
    if claude is None:
        evidence["validate_strict"] = {
            "command": "claude plugin validate --strict .",
            "error": "`claude` not found on PATH",
        }
        return False

    path = f"{Path(claude).parent}:/usr/bin:/bin:/usr/local/bin"
    with tempfile.TemporaryDirectory() as config_dir:
        proc = subprocess.run(
            [claude, "plugin", "validate", "--strict", "."],
            cwd=ROOT,
            env={"CLAUDE_CONFIG_DIR": config_dir, "PATH": path},
            capture_output=True,
            text=True,
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
            text=True,
        )
        install_proc = subprocess.run(
            [uv, "pip", "install", "--python", str(env_dir / "bin" / "python"), str(ROOT)],
            capture_output=True,
            text=True,
        )
        # cwd is the empty temp dir, never the repo root — `python -c` puts
        # cwd on sys.path[0], and importing from the repo root would find the
        # source tree directly rather than the installed package, producing
        # a false PASS on the "fresh install" claim.
        import_proc = subprocess.run(
            [str(env_dir / "bin" / "python"), "-c",
             "import hyperspace, sys; print(hyperspace.__version__)"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
        )

        evidence["fresh_env_import"] = {
            "venv": {
                "command": f"uv venv {env_dir}",
                "exit_code": venv_proc.returncode,
                "stderr": _trim(venv_proc.stderr),
            },
            "install": {
                "command": f"uv pip install --python {env_dir}/bin/python {ROOT}",
                "exit_code": install_proc.returncode,
                "stdout": _trim(install_proc.stdout),
                "stderr": _trim(install_proc.stderr),
            },
            "import": {
                "command": f"{env_dir}/bin/python -c \"import hyperspace; print(hyperspace.__version__)\"",
                "exit_code": import_proc.returncode,
                "stdout": _trim(import_proc.stdout),
                "stderr": _trim(import_proc.stderr),
            },
        }

        return (
            venv_proc.returncode == 0
            and install_proc.returncode == 0
            and import_proc.returncode == 0
            and import_proc.stdout.strip() == "0.1.2"
        )


def check_launcher(evidence: dict) -> bool:
    launcher = ROOT / "bin" / "hyperspace-mcp"

    syntax_proc = subprocess.run(
        ["sh", "-n", str(launcher)],
        capture_output=True,
        text=True,
    )

    with tempfile.TemporaryDirectory() as empty_project:
        run_proc = subprocess.run(
            ["sh", str(launcher)],
            env={"CLAUDE_PROJECT_DIR": empty_project, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
        )

    evidence["launcher"] = {
        "syntax_check": {
            "command": f"sh -n {launcher}",
            "exit_code": syntax_proc.returncode,
            "stderr": _trim(syntax_proc.stderr),
        },
        "missing_env_run": {
            "command": f"CLAUDE_PROJECT_DIR=<empty tmp dir> sh {launcher}",
            "exit_code": run_proc.returncode,
            "stderr": _trim(run_proc.stderr),
        },
    }

    return (
        syntax_proc.returncode == 0
        and run_proc.returncode == 1
        and ".hyperspace/env" in run_proc.stderr
    )


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
            json.loads(target.read_text())
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
    c = check_launcher(evidence)
    d = check_manifests_parse(evidence)

    result = "PASS" if (a and b and c and d) else "FAIL"
    write_verdict(args.out, probe="validate_strict", result=result, evidence=evidence)

    print(f"validate_strict: {result} (validate={a} fresh_import={b} launcher={c} manifests={d})")
    return 0 if result == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
