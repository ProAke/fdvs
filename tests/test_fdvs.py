"""
FDVS test suite — stdlib unittest, no third-party dependencies.

Run:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.compare import compare_trees, hash_file, walk_tree  # noqa: E402
from app.server import build_server  # noqa: E402
from app.sync import PlanError, execute_plan, plan_sync  # noqa: E402
from app.volumes import list_dir, list_volumes, probe_access  # noqa: E402


def write(path: str, content: str | bytes, mtime: float | None = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "wb" if isinstance(content, bytes) else "w"
    with open(path, mode) as fh:
        fh.write(content)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


class TempTree(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="fdvs-test-")
        self.left = os.path.join(self.tmp, "left")
        self.right = os.path.join(self.tmp, "right")
        os.makedirs(self.left)
        os.makedirs(self.right)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


# ═══════════════════ compare ═══════════════════


class TestWalkTree(TempTree):
    def test_counts_and_bytes(self):
        write(os.path.join(self.left, "a.txt"), "hello")
        write(os.path.join(self.left, "sub", "b.txt"), "world!")
        os.makedirs(os.path.join(self.left, "empty"))
        r = walk_tree(self.left)
        self.assertEqual(r["file_count"], 2)
        self.assertEqual(r["dir_count"], 2)  # sub + empty
        self.assertEqual(r["total_bytes"], 11)
        self.assertTrue(r["exists"])

    def test_ignores_ds_store(self):
        write(os.path.join(self.left, "keep.txt"), "x")
        write(os.path.join(self.left, ".DS_Store"), "junk")
        r = walk_tree(self.left)
        self.assertEqual(r["file_count"], 1)
        self.assertEqual(r["skipped"], 1)

    def test_ignores_custom_glob(self):
        write(os.path.join(self.left, "keep.txt"), "x")
        write(os.path.join(self.left, "backup.swp"), "junk")
        r = walk_tree(self.left)
        self.assertEqual(r["file_count"], 1)

    def test_missing_root_is_reported_not_raised(self):
        r = walk_tree(os.path.join(self.tmp, "nope"))
        self.assertFalse(r["exists"])
        self.assertEqual(r["file_count"], 0)
        self.assertTrue(r["errors"])

    def test_symlink_recorded(self):
        write(os.path.join(self.left, "real.txt"), "data")
        os.symlink("real.txt", os.path.join(self.left, "link.txt"))
        r = walk_tree(self.left)
        self.assertEqual(r["files"]["link.txt"]["type"], "symlink")
        self.assertEqual(r["files"]["link.txt"]["target"], "real.txt")


class TestCompare(TempTree):
    def test_identical_trees(self):
        for side in (self.left, self.right):
            write(os.path.join(side, "a.txt"), "same", 1700000000)
            write(os.path.join(side, "d", "b.txt"), "also", 1700000000)
        rep = compare_trees(self.left, self.right)
        s = rep["summary"]
        self.assertTrue(s["identical"])
        self.assertEqual(s["same"], 2)
        self.assertEqual(s["different"], 0)
        self.assertTrue(s["sizes_equal"])
        self.assertEqual(s["same_bytes"], 8)

    def test_size_differs_detected(self):
        write(os.path.join(self.left, "a.txt"), "short", 1700000000)
        write(os.path.join(self.right, "a.txt"), "muchlonger", 1700000000)
        rep = compare_trees(self.left, self.right)
        item = rep["items"][0]
        self.assertEqual(item["status"], "size_differs")
        self.assertIn("size", item["reasons"])
        self.assertFalse(rep["summary"]["identical"])

    def test_left_and_right_only(self):
        write(os.path.join(self.left, "only_left.txt"), "L", 1700000000)
        write(os.path.join(self.right, "only_right.txt"), "R", 1700000000)
        rep = compare_trees(self.left, self.right)
        s = rep["summary"]
        self.assertEqual(s["left_only"], 1)
        self.assertEqual(s["right_only"], 1)
        self.assertEqual(s["different"], 2)
        self.assertEqual(s["left_total_bytes"], 1)
        self.assertEqual(s["right_total_bytes"], 1)

    def test_same_size_different_content_hash_auto(self):
        write(os.path.join(self.left, "a.txt"), "AAAA", 1700000000)
        write(os.path.join(self.right, "a.txt"), "BBBB", 1700000100)  # same size, mtime differs
        rep = compare_trees(self.left, self.right, hash_mode="auto")
        item = rep["items"][0]
        self.assertEqual(item["status"], "content_differs")
        self.assertTrue(item["hashed"])

    def test_same_content_different_mtime_resolves_to_same(self):
        write(os.path.join(self.left, "a.txt"), "identical", 1700000000)
        write(os.path.join(self.right, "a.txt"), "identical", 1700009999)
        rep = compare_trees(self.left, self.right, hash_mode="auto")
        self.assertEqual(rep["items"][0]["status"], "same")
        self.assertTrue(rep["summary"]["identical"])

    def test_mtime_differs_when_hash_disabled(self):
        write(os.path.join(self.left, "a.txt"), "identical", 1700000000)
        write(os.path.join(self.right, "a.txt"), "identical", 1700009999)
        rep = compare_trees(self.left, self.right, hash_mode="none")
        self.assertEqual(rep["items"][0]["status"], "mtime_differs")

    def test_mtime_tolerance_respected(self):
        write(os.path.join(self.left, "a.txt"), "x", 1700000000)
        write(os.path.join(self.right, "a.txt"), "x", 1700000001.5)
        rep = compare_trees(self.left, self.right, hash_mode="none", mtime_tolerance=2.0)
        self.assertEqual(rep["items"][0]["status"], "same")

    def test_hash_all_mode(self):
        write(os.path.join(self.left, "a.txt"), "same", 1700000000)
        write(os.path.join(self.right, "a.txt"), "same", 1700000000)
        rep = compare_trees(self.left, self.right, hash_mode="all")
        self.assertTrue(rep["items"][0]["hashed"])
        self.assertEqual(rep["items"][0]["status"], "same")

    def test_dir_diff_report(self):
        os.makedirs(os.path.join(self.left, "only_in_left"))
        os.makedirs(os.path.join(self.right, "only_in_right"))
        os.makedirs(os.path.join(self.left, "both"))
        os.makedirs(os.path.join(self.right, "both"))
        rep = compare_trees(self.left, self.right)
        self.assertEqual(rep["dirs_only_left"], ["only_in_left"])
        self.assertEqual(rep["dirs_only_right"], ["only_in_right"])
        self.assertEqual(rep["summary"]["dirs_common"], 1)

    def test_progress_callback_called(self):
        for i in range(500):
            write(os.path.join(self.left, f"f{i}.txt"), "x", 1700000000)
        seen = []
        compare_trees(self.left, self.right, progress=lambda p: seen.append(p.get("phase")))
        self.assertIn("scan-left", seen)
        self.assertIn("compare", seen)

    def test_hash_file_is_stable(self):
        p = os.path.join(self.left, "h.txt")
        write(p, "abc")
        self.assertEqual(hash_file(p), hash_file(p))
        self.assertEqual(len(hash_file(p)), 64)
        self.assertEqual(hash_file(os.path.join(self.left, "missing")), "")


# ═══════════════════ sync ═══════════════════


class TestPlan(TempTree):
    def _report(self, **kw):
        return compare_trees(self.left, self.right, **kw)

    def test_left_to_right_copies_missing(self):
        write(os.path.join(self.left, "a.txt"), "hello", 1700000000)
        write(os.path.join(self.right, "extra.txt"), "x", 1700000000)
        plan = plan_sync(self._report(), "left_to_right")
        copies = [o for o in plan["ops"] if o["action"] == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["relpath"], "a.txt")
        self.assertEqual(plan["summary"]["deletes"], 0)

    def test_delete_extras_opt_in(self):
        write(os.path.join(self.right, "extra.txt"), "x", 1700000000)
        plan = plan_sync(self._report(), "left_to_right", delete_extras=True)
        dels = [o for o in plan["ops"] if o["action"] == "delete"]
        self.assertEqual(len(dels), 1)
        self.assertEqual(dels[0]["relpath"], "extra.txt")

    def test_right_to_left_direction(self):
        write(os.path.join(self.right, "b.txt"), "world", 1700000000)
        plan = plan_sync(self._report(), "right_to_left")
        copies = [o for o in plan["ops"] if o["action"] == "copy"]
        self.assertEqual(copies[0]["src"], os.path.join(self.right, "b.txt"))
        self.assertEqual(copies[0]["dst"], os.path.join(self.left, "b.txt"))

    def test_bidirectional_newer_wins(self):
        write(os.path.join(self.left, "a.txt"), "old", 1700000000)
        write(os.path.join(self.right, "a.txt"), "newer!!", 1700009999)
        plan = plan_sync(self._report(hash_mode="none"), "bidirectional")
        copies = [o for o in plan["ops"] if o["action"] == "copy"]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0]["src"], os.path.join(self.right, "a.txt"))

    def test_bidirectional_copies_both_unique(self):
        write(os.path.join(self.left, "L.txt"), "l", 1700000000)
        write(os.path.join(self.right, "R.txt"), "r", 1700000000)
        plan = plan_sync(self._report(), "bidirectional")
        copies = {o["relpath"]: o["src"] for o in plan["ops"] if o["action"] == "copy"}
        self.assertEqual(copies["L.txt"], os.path.join(self.left, "L.txt"))
        self.assertEqual(copies["R.txt"], os.path.join(self.right, "R.txt"))

    def test_mkdir_ops_for_dir_only_left(self):
        os.makedirs(os.path.join(self.left, "newdir"))
        plan = plan_sync(self._report(), "left_to_right")
        mkdirs = [o for o in plan["ops"] if o["action"] == "mkdir"]
        self.assertEqual(mkdirs[0]["relpath"], "newdir")

    def test_status_filter(self):
        write(os.path.join(self.left, "a.txt"), "short", 1700000000)
        write(os.path.join(self.right, "a.txt"), "longer!!", 1700000000)
        write(os.path.join(self.left, "b.txt"), "b", 1700000000)
        plan = plan_sync(self._report(), "left_to_right", statuses=["size_differs"])
        copies = [o["relpath"] for o in plan["ops"] if o["action"] == "copy"]
        self.assertEqual(copies, ["a.txt"])

    def test_unknown_direction_raises(self):
        with self.assertRaises(PlanError):
            plan_sync(self._report(), "sideways")

    def test_traversal_path_rejected(self):
        rep = self._report()
        rep["items"] = [{"relpath": "../../etc/passwd", "status": "left_only",
                         "left": {"size": 1, "type": "file", "mtime": 0}, "right": None, "reasons": []}]
        with self.assertRaises(PlanError):
            plan_sync(rep, "left_to_right")


class TestExecute(TempTree):
    def test_dry_run_changes_nothing(self):
        write(os.path.join(self.left, "a.txt"), "hello", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right")
        res = execute_plan(plan, dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["summary"]["copied"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.right, "a.txt")))

    def test_real_copy_makes_equal(self):
        write(os.path.join(self.left, "a.txt"), "hello", 1700000000)
        write(os.path.join(self.left, "d", "b.txt"), "nested", 1700000000)
        rep = compare_trees(self.left, self.right)
        plan = plan_sync(rep, "left_to_right")
        res = execute_plan(plan, dry_run=False)
        self.assertTrue(res["summary"]["ok"])
        self.assertEqual(res["summary"]["copied"], 2)
        after = compare_trees(self.left, self.right)
        self.assertTrue(after["summary"]["identical"], after["summary"])
        self.assertEqual(after["summary"]["same"], 2)

    def test_overwrite_creates_backup(self):
        # hash_mode="all" is required: same size AND same mtime means "auto" (rsync-like)
        # cannot distinguish the files, so it correctly reports them as same.
        write(os.path.join(self.left, "a.txt"), "NEWCONTENT", 1700000000)
        write(os.path.join(self.right, "a.txt"), "OLDCONTENT", 1700000000)
        rep = compare_trees(self.left, self.right, hash_mode="all")
        self.assertEqual(rep["items"][0]["status"], "content_differs")
        plan = plan_sync(rep, "left_to_right")
        res = execute_plan(plan, dry_run=False, backup=True)
        with open(os.path.join(self.right, "a.txt")) as fh:
            self.assertEqual(fh.read(), "NEWCONTENT")
        backup_root = res["backup_root"]
        self.assertTrue(os.path.isdir(backup_root))
        with open(os.path.join(backup_root, "a.txt")) as fh:
            self.assertEqual(fh.read(), "OLDCONTENT")

    def test_same_size_same_mtime_is_same_in_auto_mode(self):
        # Documented tradeoff: auto mode = size + mtime, like rsync's default.
        write(os.path.join(self.left, "a.txt"), "AAAA", 1700000000)
        write(os.path.join(self.right, "a.txt"), "BBBB", 1700000000)
        rep = compare_trees(self.left, self.right, hash_mode="auto")
        self.assertEqual(rep["items"][0]["status"], "same")
        self.assertFalse(rep["items"][0]["hashed"])

    def test_checksum_recorded(self):
        write(os.path.join(self.left, "a.txt"), "verify-me", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right")
        res = execute_plan(plan, dry_run=False, verify=True)
        rec = [r for r in res["results"] if r["action"] == "copy"][0]
        self.assertIn("sha256", rec)
        self.assertEqual(rec["sha256"], hash_file(os.path.join(self.left, "a.txt")))

    def test_no_temp_files_left_behind(self):
        write(os.path.join(self.left, "a.txt"), "x", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right")
        execute_plan(plan, dry_run=False)
        leftovers = [f for f in os.listdir(self.right) if ".fdvs-tmp" in f]
        self.assertEqual(leftovers, [])

    def test_missing_source_reported_not_raised(self):
        write(os.path.join(self.left, "a.txt"), "x", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right")
        os.remove(os.path.join(self.left, "a.txt"))
        res = execute_plan(plan, dry_run=False)
        self.assertEqual(res["summary"]["failed"], 1)
        self.assertIn("missing", res["results"][0]["error"])

    def test_cancel_stops_early(self):
        for i in range(10):
            write(os.path.join(self.left, f"f{i}.txt"), "x", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right")
        state = {"n": 0}

        def stop():
            state["n"] += 1
            return state["n"] > 3

        res = execute_plan(plan, dry_run=False, should_stop=stop)
        self.assertLess(res["summary"]["copied"], 10)

    def test_delete_removes_extra(self):
        write(os.path.join(self.right, "extra.txt"), "x", 1700000000)
        plan = plan_sync(compare_trees(self.left, self.right), "left_to_right", delete_extras=True)
        res = execute_plan(plan, dry_run=False)
        self.assertEqual(res["summary"]["deleted"], 1)
        self.assertFalse(os.path.exists(os.path.join(self.right, "extra.txt")))


# ═══════════════════ volumes ═══════════════════


class TestVolumes(TempTree):
    def test_list_volumes_has_root(self):
        v = list_volumes()
        self.assertTrue(any(x["path"] == "/" for x in v["volumes"]))
        self.assertIn("home", v)

    def test_probe_access_ok(self):
        p = probe_access(self.left)
        self.assertEqual(p["status"], "ok")
        self.assertTrue(p["readable"])

    def test_probe_access_missing(self):
        p = probe_access(os.path.join(self.tmp, "nope"))
        self.assertEqual(p["status"], "not_found")

    def test_probe_access_not_a_directory(self):
        write(os.path.join(self.left, "f.txt"), "x")
        p = probe_access(os.path.join(self.left, "f.txt"))
        self.assertEqual(p["status"], "not_a_directory")

    def test_list_dir_dirs_first(self):
        os.makedirs(os.path.join(self.left, "zzz_dir"))
        write(os.path.join(self.left, "aaa.txt"), "x")
        r = list_dir(self.left)
        self.assertTrue(r["entries"][0]["is_dir"])
        self.assertEqual(r["counts"]["dirs"], 1)
        self.assertEqual(r["counts"]["files"], 1)

    def test_list_dir_hidden_filter(self):
        write(os.path.join(self.left, ".hidden"), "x")
        write(os.path.join(self.left, "shown"), "x")
        self.assertEqual(list_dir(self.left)["counts"]["files"], 1)
        self.assertEqual(list_dir(self.left, show_hidden=True)["counts"]["files"], 2)


# ═══════════════════ HTTP API ═══════════════════


class TestAPI(TempTree):
    @classmethod
    def setUpClass(cls):
        cls.httpd = build_server(0, "127.0.0.1")
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=20) as r:
            return r.status, json.loads(r.read().decode())

    def post(self, path, payload):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())

    def post_expect_error(self, path, payload):
        try:
            self.post(path, payload)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode())
        self.fail("expected HTTPError")

    def wait_job(self, job_id, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, job = self.get("/api/jobs?id=" + job_id)
            if job["status"] in ("done", "error"):
                return job
            time.sleep(0.2)
        self.fail("job timed out")

    def test_health(self):
        code, data = self.get("/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["app"], "FDVS")

    def test_volumes_endpoint(self):
        code, data = self.get("/api/volumes")
        self.assertEqual(code, 200)
        self.assertTrue(data["volumes"])

    def test_browse_endpoint(self):
        write(os.path.join(self.left, "seen.txt"), "x")
        code, data = self.get("/api/browse?path=" + self.left)
        self.assertEqual(code, 200)
        self.assertEqual(data["counts"]["files"], 1)

    def test_access_endpoint(self):
        code, data = self.get("/api/access?path=" + self.left)
        self.assertEqual(code, 200)
        self.assertEqual(data["status"], "ok")

    def test_index_served(self):
        with urllib.request.urlopen(self.base + "/", timeout=10) as r:
            body = r.read().decode()
        self.assertIn("FDVS", body)
        self.assertIn("Folder VS", body)

    def test_static_traversal_blocked(self):
        try:
            urllib.request.urlopen(self.base + "/../app/server.py", timeout=10)
            self.fail("expected 403/404")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (400, 403, 404))

    def test_secret_files_blocked(self):
        os.makedirs(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public"), exist_ok=True)
        try:
            urllib.request.urlopen(self.base + "/.env", timeout=10)
            self.fail("expected 403")
        except urllib.error.HTTPError as e:
            self.assertIn(e.code, (403, 404))

    def test_unknown_api_404(self):
        try:
            self.get("/api/nope")
            self.fail("expected 404")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 404)

    def test_compare_requires_both_paths(self):
        code, data = self.post_expect_error("/api/compare", {"left": self.left})
        self.assertEqual(code, 400)

    def test_compare_rejects_same_folder(self):
        code, data = self.post_expect_error("/api/compare", {"left": self.left, "right": self.left})
        self.assertEqual(code, 400)

    def test_compare_rejects_missing_folder(self):
        code, data = self.post_expect_error(
            "/api/compare", {"left": self.left, "right": os.path.join(self.tmp, "nope")}
        )
        self.assertEqual(code, 403)

    def test_full_compare_flow(self):
        write(os.path.join(self.left, "a.txt"), "hello", 1700000000)
        write(os.path.join(self.right, "b.txt"), "world", 1700000000)
        code, data = self.post("/api/compare", {"left": self.left, "right": self.right})
        self.assertEqual(code, 202)
        job = self.wait_job(data["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))

        _, rep = self.get("/api/report?id=" + job["result"]["report_id"])
        self.assertEqual(rep["summary"]["left_only"], 1)
        self.assertEqual(rep["summary"]["right_only"], 1)

    def test_full_sync_flow_makes_equal(self):
        write(os.path.join(self.left, "a.txt"), "hello", 1700000000)
        write(os.path.join(self.left, "sub", "b.txt"), "nested", 1700000000)
        _, data = self.post("/api/compare", {"left": self.left, "right": self.right})
        job = self.wait_job(data["job_id"])
        rid = job["result"]["report_id"]

        _, dry = self.post("/api/sync", {"report_id": rid, "direction": "left_to_right", "dry_run": True})
        dry_job = self.wait_job(dry["job_id"])
        self.assertEqual(dry_job["status"], "done")
        self.assertEqual(dry_job["result"]["summary"]["copied"], 0)
        self.assertFalse(os.path.exists(os.path.join(self.right, "a.txt")))

        _, real = self.post(
            "/api/sync",
            {"report_id": rid, "direction": "left_to_right", "dry_run": False, "confirm": True},
        )
        real_job = self.wait_job(real["job_id"])
        self.assertEqual(real_job["status"], "done", real_job.get("error"))
        self.assertEqual(real_job["result"]["summary"]["copied"], 2)

        _, data2 = self.post("/api/compare", {"left": self.left, "right": self.right})
        job2 = self.wait_job(data2["job_id"])
        _, rep2 = self.get("/api/report?id=" + job2["result"]["report_id"])
        self.assertTrue(rep2["summary"]["identical"], rep2["summary"])

    def test_sync_without_confirm_refused(self):
        write(os.path.join(self.left, "a.txt"), "x", 1700000000)
        _, data = self.post("/api/compare", {"left": self.left, "right": self.right})
        job = self.wait_job(data["job_id"])
        code, err = self.post_expect_error(
            "/api/sync",
            {"report_id": job["result"]["report_id"], "direction": "left_to_right", "dry_run": False},
        )
        self.assertEqual(code, 400)
        self.assertIn("confirm", err["error"])

    def test_sync_missing_report_404ish(self):
        _, data = self.post("/api/sync", {"report_id": "deadbeef", "direction": "left_to_right", "dry_run": True})
        job = self.wait_job(data["job_id"])
        self.assertEqual(job["status"], "error")

    def test_reports_history(self):
        write(os.path.join(self.left, "h.txt"), "x", 1700000000)
        _, data = self.post("/api/compare", {"left": self.left, "right": self.right})
        self.wait_job(data["job_id"])
        code, hist = self.get("/api/reports")
        self.assertEqual(code, 200)
        self.assertTrue(any(r["left"] == self.left for r in hist["reports"]))

    def test_state_persist_roundtrip(self):
        code, _ = self.post("/api/state", {"last_left": self.left, "last_right": self.right})
        self.assertEqual(code, 200)
        _, st = self.get("/api/state")
        self.assertEqual(st["last_left"], self.left)

    def test_export_csv(self):
        write(os.path.join(self.left, "a.txt"), "x", 1700000000)
        _, data = self.post("/api/compare", {"left": self.left, "right": self.right})
        job = self.wait_job(data["job_id"])
        rid = job["result"]["report_id"]
        with urllib.request.urlopen(f"{self.base}/api/report/{rid}/export?format=csv", timeout=10) as r:
            body = r.read().decode()
            self.assertIn("text/csv", r.headers["Content-Type"])
        self.assertIn("relpath,status", body)
        self.assertIn("a.txt", body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
