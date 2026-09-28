"""T4.3 — hsp-ui-bundle: prebuilt console page shipped inside the plugin.

Covers: the built `ui/dist/` exists and references its own assets;
`ui/SOURCE.md` names the pinned Caelos commit, the build command, and a
bundle size; `ui/build.sh` is a valid, executable POSIX script; the bundle
was built with a relative API base (no absolute host baked into the HTML,
and a relative `/api/` marker present in the built JS).

Finding recorded (2026-09-26, engineer, T4.3 RED): `FOUNDRY_DEMO_PROJECT`
(App.tsx ~line 74, name "Foundry calibration") is a module-scope exported
const referenced unconditionally in `ProjectViewLayeredShell`'s parent
component body — Vite/Rollup cannot tree-shake it regardless of
`foundryMode`'s runtime value, because the reference itself, not just the
data, is unconditional at the module graph level. Per the brief's own
fallback (step 2d): if the sentinel is bundled as unreachable dead code,
record that fact and assert the runtime fetch target instead (done at
probe step 6 — `ui_page_check.mjs`'s `api_requests` capture — not here).
`test_mock_sentinel_absent_or_documented` enforces exactly that trade:
either the sentinel is gone, or its presence is written down in
`ui/SOURCE.md` as a known dead-code inclusion.
"""
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "ui" / "dist"
SOURCE_MD = ROOT / "ui" / "SOURCE.md"
BUILD_SH = ROOT / "ui" / "build.sh"
PINNED_COMMIT = "dfcb46d"
MOCK_SENTINEL = "Foundry calibration"


def _index_html() -> str:
    return (DIST / "index.html").read_text(encoding="utf-8")


def _all_built_js_text() -> str:
    assets = DIST / "assets"
    chunks = []
    for js_file in assets.glob("*.js"):
        chunks.append(js_file.read_text(errors="replace", encoding="utf-8"))
    return "\n".join(chunks)


def test_dist_index_html_references_js_and_css_assets():
    index_html = DIST / "index.html"
    assert index_html.exists(), "ui/dist/index.html must exist (built bundle)"
    html = index_html.read_text(encoding="utf-8")
    assert re.search(r'assets/[^"\']+\.js', html), "index.html must reference at least one assets/*.js"
    assert re.search(r'assets/[^"\']+\.css', html), "index.html must reference at least one assets/*.css"


def test_source_md_names_pin_command_and_size():
    assert SOURCE_MD.exists(), "ui/SOURCE.md must exist"
    text = SOURCE_MD.read_text(encoding="utf-8")
    assert PINNED_COMMIT in text, "ui/SOURCE.md must name the pinned commit"
    assert "npm run build" in text, "ui/SOURCE.md must record the build command"
    assert re.search(r"\d+(\.\d+)?\s*[KMG](i?B)?", text), "ui/SOURCE.md must record a bundle size"


def test_build_sh_executable_and_syntax_clean():
    assert BUILD_SH.exists(), "ui/build.sh must exist"
    # The mode git records and every clone reproduces — read from the index,
    # since NTFS has no POSIX execute bit for `stat` to report.
    index = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-s", "--", "ui/build.sh"],
                           capture_output=True, encoding="utf-8")
    if index.returncode == 0 and index.stdout.strip():
        assert index.stdout.startswith("100755 "), "ui/build.sh must be executable (git mode 100755)"
    else:
        assert BUILD_SH.stat().st_mode & stat.S_IXUSR, "ui/build.sh must be executable"
    proc = subprocess.run(["sh", "-n", str(BUILD_SH)], capture_output=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, f"ui/build.sh must be sh -n clean: {proc.stderr}"


def test_index_html_has_no_absolute_api_host():
    html = _index_html()
    # A relative-base build must not bake an absolute host into the shipped HTML.
    for m in re.finditer(r'https?://[^\s"\'<>]+', html):
        url = m.group(0)
        # Allow non-API infra URLs the toolchain itself may embed (fonts, sourcemap
        # comments are absent from index.html; nothing legitimate here should point
        # at an API host) — fail on anything found, since none is expected.
        raise AssertionError(f"index.html contains an absolute URL: {url}")


def test_built_js_contains_relative_api_marker():
    js_text = _all_built_js_text()
    assert js_text, "ui/dist/assets must contain at least one built .js file"
    assert ("./api/" in js_text) or ("/api/" in js_text), (
        "built JS must contain a relative API path marker ('./api/' or '/api/'), "
        "proving the relative VITE_API_BASE_URL took effect"
    )


def test_mock_sentinel_absent_or_documented():
    js_text = _all_built_js_text()
    if MOCK_SENTINEL not in js_text:
        return  # tree-shaken cleanly — the strong result
    # Sentinel present as unreachable dead code (see module docstring finding) —
    # acceptable ONLY if recorded in ui/SOURCE.md so the trade-off is not silent.
    assert SOURCE_MD.exists(), "mock sentinel present in bundle but ui/SOURCE.md missing to record it"
    source_text = SOURCE_MD.read_text(encoding="utf-8")
    assert "FOUNDRY_DEMO_PROJECT" in source_text or "dead code" in source_text.lower(), (
        "mock sentinel string is present in the built JS as apparent dead code; "
        "ui/SOURCE.md must record this finding"
    )
