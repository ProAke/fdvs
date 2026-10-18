"""
FDVS — Folder VS.

A local Python dashboard that compares two folders (on any mounted volume),
reports file/folder/size differences, and can copy the missing or differing
files so both sides become equal.

Run:
    python3 -m app.server            # http://127.0.0.1:4477
    python3 -m app.server --port 8080
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .compare import DEFAULT_IGNORE_GLOBS, DEFAULT_IGNORES, compare_trees, estimate_scan
from .sync import PlanError, execute_plan, plan_sync
from .volumes import SYSTEM_SETTINGS_URLS, list_dir, list_volumes, probe_access, request_access

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
PUBLIC_DIR = os.path.join(ROOT_DIR, "public")
REPORTS_DIR = os.path.join(ROOT_DIR, "reports")
STATE_FILE = os.path.join(ROOT_DIR, ".fdvs-state.json")
DEFAULT_PORT = 4477
MAX_BODY = 8 * 1024 * 1024

__version__ = "2.0.0"

# ─── In-memory job registry (single-user local tool) ────────────────────────
JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
REPORTS: dict[str, dict] = {}


def _job(job_id: str) -> dict:
    with JOBS_LOCK:
        return JOBS.setdefault(
            job_id,
            {"id": job_id, "status": "idle", "progress": {}, "result": None, "error": None, "log": []},
        )


def _log(job_id: str, message: str) -> None:
    j = _job(job_id)
    j["log"].append(f"{time.strftime('%H:%M:%S')} {message}")
    j["log"] = j["log"][-200:]


def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
    except OSError:
        pass


# ─── Background workers ─────────────────────────────────────────────────────


def run_compare(job_id: str, left: str, right: str, options: dict) -> None:
    j = _job(job_id)
    j["status"] = "running"
    j["started_at"] = time.time()
    _log(job_id, f"scan: {left}")
    _log(job_id, f"scan: {right}")
    try:
        def progress(p: dict) -> None:
            j["progress"] = p

        report = compare_trees(
            left,
            right,
            hash_mode=options.get("hash_mode", "auto"),
            compare_mtime=bool(options.get("compare_mtime", True)),
            mtime_tolerance=float(options.get("mtime_tolerance", 2.0)),
            follow_symlinks=bool(options.get("follow_symlinks", False)),
            ignore_names=set(DEFAULT_IGNORES) | set(options.get("ignore_names") or []),
            ignore_globs=list(DEFAULT_IGNORE_GLOBS) + list(options.get("ignore_globs") or []),
            progress=progress,
        )
        report_id = uuid.uuid4().hex[:12]
        report["id"] = report_id
        REPORTS[report_id] = report
        os.makedirs(REPORTS_DIR, exist_ok=True)
        with open(os.path.join(REPORTS_DIR, f"{report_id}.json"), "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False)
        j["result"] = {"report_id": report_id, "summary": report["summary"]}
        j["status"] = "done"
        s = report["summary"]
        _log(job_id, f"เสร็จ: {s['same']} ไฟล์เท่ากัน, {s['different']} ต่างกัน")
    except Exception as exc:  # noqa: BLE001
        j["status"] = "error"
        j["error"] = f"{type(exc).__name__}: {exc}"
        _log(job_id, traceback.format_exc(limit=3))
    finally:
        j["finished_at"] = time.time()


def run_sync(job_id: str, report_id: str, direction: str, options: dict) -> None:
    j = _job(job_id)
    j["status"] = "running"
    _log(job_id, f"sync {direction} (dry_run={options.get('dry_run', True)})")
    try:
        report = REPORTS.get(report_id)
        if report is None:
            path = os.path.join(REPORTS_DIR, f"{report_id}.json")
            if not os.path.exists(path):
                raise PlanError(f"ไม่พบ report {report_id} — กรุณาสแกนใหม่")
            with open(path, encoding="utf-8") as fh:
                report = json.load(fh)

        plan = plan_sync(
            report,
            direction,
            delete_extras=bool(options.get("delete_extras", False)),
            statuses=options.get("statuses"),
        )

        def progress(p: dict) -> None:
            j["progress"] = p

        result = execute_plan(
            plan,
            dry_run=bool(options.get("dry_run", True)),
            verify=bool(options.get("verify", True)),
            backup=bool(options.get("backup", True)),
            progress=progress,
        )
        j["result"] = result
        j["status"] = "done"
        s = result["summary"]
        _log(job_id, f"เสร็จ: copy {s['copied']} / fail {s['failed']}")
    except Exception as exc:  # noqa: BLE001
        j["status"] = "error"
        j["error"] = f"{type(exc).__name__}: {exc}"
        _log(job_id, traceback.format_exc(limit=3))
    finally:
        j["finished_at"] = time.time()


# ─── HTTP handler ───────────────────────────────────────────────────────────

SECRET_PATTERNS = re.compile(r"(^\.env|\.pem$|\.key$|\.ppk$|\.p12$|credentials|secrets|\.git/config$)", re.I)


class Handler(BaseHTTPRequestHandler):
    server_version = "FDVS/1.0"
    protocol_version = "HTTP/1.1"

    # ── helpers ──
    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400, **extra: Any) -> None:
        self._json({"error": message, **extra}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("payload too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8")) if raw else {}

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter console
        if os.environ.get("FDVS_VERBOSE"):
            super().log_message(fmt, *args)

    # ── routing ──
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        try:
            if path == "/api/health":
                return self._json({"ok": True, "app": "FDVS", "version": __version__, "pid": os.getpid()})

            if path == "/api/volumes":
                return self._json(list_volumes())

            if path == "/api/browse":
                target = (query.get("path") or [os.path.expanduser("~")])[0]
                hidden = (query.get("hidden") or ["0"])[0] in ("1", "true")
                return self._json(list_dir(target, show_hidden=hidden))

            if path == "/api/access":
                target = (query.get("path") or [""])[0]
                if not target:
                    return self._error("ต้องระบุ path")
                return self._json(probe_access(target))

            if path == "/api/access/request":
                target = (query.get("path") or [""])[0]
                if not target:
                    return self._error("ต้องระบุ path")
                return self._json(request_access(target))

            if path == "/api/access/settings-urls":
                return self._json(SYSTEM_SETTINGS_URLS)

            if path == "/api/estimate":
                left = (query.get("left") or [""])[0]
                right = (query.get("right") or [""])[0]
                if not left or not right:
                    return self._error("ต้องระบุ folder ทั้งสองฝั่ง")
                for side, p in (("left", left), ("right", right)):
                    access = probe_access(p)
                    if access["status"] != "ok":
                        return self._error(
                            f"เข้าถึง folder ฝั่ง {side} ไม่ได้: {access.get('error')}",
                            403,
                            access=access,
                            side=side,
                        )
                est = estimate_scan(
                    left,
                    right,
                    hash_mode=(query.get("hash_mode") or ["auto"])[0],
                    compare_mtime=(query.get("compare_mtime") or ["1"])[0] not in ("0", "false"),
                    follow_symlinks=(query.get("follow_symlinks") or ["0"])[0] in ("1", "true"),
                    budget_s=float((query.get("budget_s") or ["8"])[0]),
                )
                return self._json(est)

            if path == "/api/state":
                return self._json(load_state())

            if path == "/api/jobs":
                job_id = (query.get("id") or [""])[0]
                if job_id:
                    with JOBS_LOCK:
                        job = JOBS.get(job_id)
                    if job is None:
                        return self._error("ไม่พบ job", 404)
                    return self._json(job)
                with JOBS_LOCK:
                    return self._json({"jobs": list(JOBS.values())[-20:]})

            if path == "/api/report":
                report_id = (query.get("id") or [""])[0]
                if not report_id:
                    return self._error("ต้องระบุ id")
                report = REPORTS.get(report_id)
                if report is None:
                    fp = os.path.join(REPORTS_DIR, f"{report_id}.json")
                    if not os.path.exists(fp):
                        return self._error("ไม่พบ report", 404)
                    with open(fp, encoding="utf-8") as fh:
                        report = json.load(fh)
                return self._json(report)

            if path == "/api/reports":
                os.makedirs(REPORTS_DIR, exist_ok=True)
                files = sorted(
                    (f for f in os.listdir(REPORTS_DIR) if f.endswith(".json")),
                    reverse=True,
                )[:50]
                out = []
                for f in files:
                    fp = os.path.join(REPORTS_DIR, f)
                    try:
                        with open(fp, encoding="utf-8") as fh:
                            r = json.load(fh)
                        out.append(
                            {
                                "id": r.get("id", f[:-5]),
                                "generated_at": r.get("generated_at"),
                                "left": r.get("left", {}).get("root"),
                                "right": r.get("right", {}).get("root"),
                                "summary": r.get("summary", {}),
                            }
                        )
                    except (OSError, json.JSONDecodeError):
                        continue
                return self._json({"reports": out})

            if path.startswith("/api/report/") and path.endswith("/export"):
                report_id = path.split("/")[3]
                fmt = (query.get("format") or ["json"])[0]
                fp = os.path.join(REPORTS_DIR, f"{report_id}.json")
                if not os.path.exists(fp):
                    return self._error("ไม่พบ report", 404)
                with open(fp, encoding="utf-8") as fh:
                    report = json.load(fh)
                if fmt == "csv":
                    lines = ["relpath,status,left_size,right_size,left_mtime,right_mtime,reasons"]
                    for it in report.get("items", []):
                        lf, rf = it.get("left") or {}, it.get("right") or {}
                        lines.append(
                            ",".join(
                                [
                                    '"' + it["relpath"].replace('"', '""') + '"',
                                    it["status"],
                                    str(lf.get("size", "")),
                                    str(rf.get("size", "")),
                                    str(int(lf.get("mtime", 0)) or ""),
                                    str(int(rf.get("mtime", 0)) or ""),
                                    '"' + ",".join(it.get("reasons", [])) + '"',
                                ]
                            )
                        )
                    body = "\n".join(lines).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="fdvs-{report_id}.csv"')
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return self._json(report)

            if path.startswith("/api/"):
                return self._error("ไม่พบ endpoint", 404)

            return self._static(path)

        except ValueError as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._body()

            if path == "/api/compare":
                left = (payload.get("left") or "").strip()
                right = (payload.get("right") or "").strip()
                if not left or not right:
                    return self._error("ต้องระบุ folder ทั้งสองฝั่ง")
                if os.path.abspath(os.path.expanduser(left)) == os.path.abspath(os.path.expanduser(right)):
                    return self._error("folder ทั้งสองฝั่งเป็นอันเดียวกัน")
                for side, p in (("left", left), ("right", right)):
                    access = probe_access(p)
                    if access["status"] != "ok":
                        return self._error(
                            f"เข้าถึง folder ฝั่ง {side} ไม่ได้: {access.get('error')}",
                            403,
                            access=access,
                            side=side,
                        )
                job_id = uuid.uuid4().hex[:12]
                _job(job_id)
                threading.Thread(
                    target=run_compare,
                    args=(job_id, left, right, payload.get("options") or {}),
                    daemon=True,
                ).start()
                state = load_state()
                state["last_left"] = left
                state["last_right"] = right
                state["last_options"] = payload.get("options") or {}
                save_state(state)
                return self._json({"job_id": job_id}, 202)

            if path == "/api/sync":
                report_id = (payload.get("report_id") or "").strip()
                direction = payload.get("direction") or "left_to_right"
                if not report_id:
                    return self._error("ต้องระบุ report_id")
                if payload.get("dry_run") is False and payload.get("confirm") is not True:
                    return self._error("การคัดลอกจริงต้องส่ง confirm=true")
                job_id = uuid.uuid4().hex[:12]
                _job(job_id)
                threading.Thread(
                    target=run_sync,
                    args=(job_id, report_id, direction, payload),
                    daemon=True,
                ).start()
                return self._json({"job_id": job_id}, 202)

            if path == "/api/state":
                state = load_state()
                state.update(payload or {})
                save_state(state)
                return self._json({"ok": True, "state": state})

            return self._error("ไม่พบ endpoint", 404)

        except json.JSONDecodeError:
            return self._error("JSON ไม่ถูกต้อง", 400)
        except ValueError as exc:
            return self._error(str(exc), 400)
        except Exception as exc:  # noqa: BLE001
            return self._error(f"{type(exc).__name__}: {exc}", 500)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/report":
            report_id = (parse_qs(parsed.query).get("id") or [""])[0]
            if not report_id:
                return self._error("ต้องระบุ id")
            REPORTS.pop(report_id, None)
            fp = os.path.join(REPORTS_DIR, f"{report_id}.json")
            if os.path.exists(fp):
                os.remove(fp)
            return self._json({"ok": True})
        return self._error("ไม่พบ endpoint", 404)

    # ── static files ──
    def _static(self, path: str) -> None:
        if path in ("/", "/index.html"):
            rel = "index.html"
        else:
            rel = path.lstrip("/")

        if SECRET_PATTERNS.search(rel) or ".." in rel.split("/"):
            return self._error("forbidden", 403)

        target = os.path.abspath(os.path.join(PUBLIC_DIR, rel))
        if not target.startswith(os.path.abspath(PUBLIC_DIR)):
            return self._error("forbidden", 403)

        if os.path.isdir(target):
            return self._error("forbidden", 403)

        if not os.path.exists(target):
            return self._error("not found", 404)

        ext = os.path.splitext(target)[1].lower()
        ctypes = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
            ".woff2": "font/woff2",
        }
        try:
            with open(target, "rb") as fh:
                body = fh.read()
        except OSError:
            return self._error("read error", 500)

        self.send_response(200)
        self.send_header("Content-Type", ctypes.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    os.makedirs(PUBLIC_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="FDVS — Folder VS dashboard")
    parser.add_argument("--port", type=int, default=int(os.environ.get("FDVS_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=os.environ.get("FDVS_HOST", "127.0.0.1"))
    parser.add_argument("--open", action="store_true", help="เปิด browser อัตโนมัติ")
    args = parser.parse_args()

    httpd = build_server(args.port, args.host)
    url = f"http://{args.host}:{args.port}/"
    print(f"FDVS — Folder VS  →  {url}")
    print(f"public: {PUBLIC_DIR}")
    print("Ctrl+C เพื่อหยุด")
    if args.open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nปิดระบบ")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
