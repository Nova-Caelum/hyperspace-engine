#!/usr/bin/env python3
"""probes/probe_store_contract.py — T4: the local store is a single SQLite
file and serves the console's REST + MCP contract, with the field lists the
console's types actually name.

Composes `probes/check_http_contract.py`'s seed/serve/GET helpers (never
re-implemented) and reads the field lists straight out of
`hyperspace/store/schema.sql`'s CREATE TABLE statements — that file's own
header names itself the authoritative, verbatim-from-the-console source.

Usage: imported by probes/run.py; PROBE = "store_contract"; run(out_dir, opts) -> bool.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _proc import stop_tree  # noqa: E402
from _verdict import write_verdict  # noqa: E402
import check_http_contract as chc  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROBE = "store_contract"

_TABLES_FOR_FIELDS = ["projects", "modules", "work_items", "cycles", "initiatives"]


def _table_columns(schema_text: str, table: str) -> list[str]:
    m = re.search(rf"CREATE TABLE {re.escape(table)} \((.*?)\n\);", schema_text, re.S)
    if not m:
        raise ValueError(f"no CREATE TABLE {table!r} found in schema.sql")
    cols = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        head = line.split()[0].upper()
        if head in ("UNIQUE", "PRIMARY", "FOREIGN", "CHECK"):
            continue
        cols.append(line.split()[0])
    return cols


def _missing_fields(row: dict, columns: list[str]) -> list[str]:
    return [c for c in columns if c not in row]


def _single_db_file(hyperspace_dir: Path) -> dict:
    db_files = sorted(p.name for p in hyperspace_dir.glob("*.db"))
    other_db_like = sorted(
        p.name for p in hyperspace_dir.iterdir()
        if p.is_file() and p.suffix in (".sqlite", ".sqlite3") and p.name not in db_files
    )
    side_files = sorted(
        p.name for p in hyperspace_dir.iterdir()
        if p.is_file() and db_files and p.name != db_files[0] and p.name.startswith(db_files[0])
    )
    return {
        "db_files": db_files, "other_db_like_files": other_db_like,
        "side_files_named": side_files, "single_db_file": len(db_files) == 1 and not other_db_like,
    }


def run(out_dir, opts) -> bool:
    schema_text = (ROOT / "hyperspace" / "store" / "schema.sql").read_text(encoding="utf-8")
    columns = {t: _table_columns(schema_text, t) for t in _TABLES_FOR_FIELDS}

    evidence: dict = {"columns": columns}
    all_ok = True
    route_table: dict[str, str] = {}
    field_findings: dict[str, list[str]] = {}
    db_check: dict = {}

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        project_dir = Path(tmp)
        db_path = project_dir / ".hyperspace" / "graph.db"

        init_proc = subprocess.run(
            [str(chc._hyperspace_bin()), "init", "--dir", str(project_dir)],
            capture_output=True, encoding="utf-8", errors="replace",
        )
        route_table["hyperspace init"] = f"exit={init_proc.returncode}"
        if init_proc.returncode != 0:
            evidence.update({"error": "hyperspace init failed", "route_table": route_table})
            write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="FAIL", evidence=evidence)
            return False

        wi_row = chc._seed(db_path)

        port = chc._free_port()
        serve_proc = subprocess.Popen(
            [str(chc._hyperspace_bin()), "serve", "--port", str(port), "--dir", str(project_dir)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
        )
        try:
            # 60 s, as the installer probe allows: a fresh CI runner's first
            # `hyperspace serve` imports every dependency cold.
            if not chc._wait_for_port("127.0.0.1", port, timeout=60.0):
                all_ok = False
                evidence["error"] = "server never came up"
                evidence["serve_exit_code"] = serve_proc.poll()
            else:
                base_url = f"http://127.0.0.1:{port}"
                code = "http-check"

                for table, path in {
                    "projects": "/api/projects",
                    "modules": f"/api/projects/{code}/modules",
                    "work_items": f"/api/projects/{code}/work-items",
                    "cycles": f"/api/projects/{code}/cycles",
                }.items():
                    status, _ctype, body = chc._http_get(base_url, path)
                    route_table[f"GET {path}"] = f"{status} {chc._top_level_shape(body)}"
                    if status != 200:
                        all_ok = False
                        continue
                    missing: set[str] = set()
                    for row in json.loads(body):
                        missing.update(_missing_fields(row, columns[table]))
                    if missing:
                        field_findings[table] = sorted(missing)
                        all_ok = False

                status, _ctype, body = chc._http_get(base_url, f"/api/modules/{code}:mod-1")
                route_table["GET /api/modules/<id>"] = f"{status} {chc._top_level_shape(body)}"
                if status == 200:
                    missing = _missing_fields(json.loads(body), columns["modules"])
                    if missing:
                        field_findings["modules (by id)"] = missing
                        all_ok = False
                else:
                    all_ok = False

                status, _ctype, body = chc._http_get(base_url, f"/api/work-items/{wi_row['external_id']}")
                route_table["GET /api/work-items/<id>"] = f"{status} {chc._top_level_shape(body)}"
                if status == 200:
                    missing = _missing_fields(json.loads(body), columns["work_items"])
                    if missing:
                        field_findings["work_items (by id)"] = missing
                        all_ok = False
                else:
                    all_ok = False

                status, _ctype, body = chc._http_get(base_url, "/api/initiatives")
                route_table["GET /api/initiatives"] = f"{status} {chc._top_level_shape(body)}"
                init_id = None
                if status == 200:
                    rows = json.loads(body)
                    missing = set()
                    for row in rows:
                        missing.update(_missing_fields(row, columns["initiatives"]))
                        if row.get("external_id") == "http-check-init":
                            init_id = row.get("id")
                    if missing:
                        field_findings["initiatives"] = sorted(missing)
                        all_ok = False
                else:
                    all_ok = False

                if init_id:
                    status, _ctype, body = chc._http_get(base_url, f"/api/initiatives/{init_id}")
                    route_table["GET /api/initiatives/<id>"] = f"{status} {chc._top_level_shape(body)}"
                    if status == 200:
                        missing = _missing_fields(json.loads(body), columns["initiatives"])
                        if missing:
                            field_findings["initiatives (by id)"] = missing
                            all_ok = False
                    else:
                        all_ok = False
                else:
                    all_ok = False
                    route_table["GET /api/initiatives/<id>"] = "skipped: no initiative id found"

                status, data = chc._http_post_mcp(base_url, "list_initiative_links", {"initiative": "http-check-init"})
                is_error = isinstance(data.get("result"), dict) and data["result"].get("isError")
                route_table["POST /mcp list_initiative_links"] = f"{status} isError={bool(is_error)}"
                if status != 200 or is_error:
                    all_ok = False

                status, data = chc._http_post_mcp(base_url, "get_recent_activity", {"limit": 5})
                is_error = isinstance(data.get("result"), dict) and data["result"].get("isError")
                route_table["POST /mcp get_recent_activity"] = f"{status} isError={bool(is_error)}"
                if status != 200 or is_error:
                    all_ok = False
        finally:
            stop_tree(serve_proc)
            out, err = serve_proc.communicate(timeout=10)
            if evidence.get("error") == "server never came up":
                evidence["serve_output"] = {"stdout": (out or "")[-2000:], "stderr": (err or "")[-2000:]}

        db_check = _single_db_file(db_path.parent)
        if not db_check.get("single_db_file"):
            all_ok = False

    evidence.update({"route_table": route_table, "field_findings": field_findings, "single_db_file": db_check})
    write_verdict(Path(out_dir) / f"{PROBE}.json", probe=PROBE, result="PASS" if all_ok else "FAIL", evidence=evidence)
    return all_ok
