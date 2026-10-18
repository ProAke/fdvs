---
name: fdvs-folder-compare-sync
description: Use when comparing or syncing two folders/drives. FDVS dashboard.
version: 1.0.0
author: hermes + @worapot
license: MIT
metadata:
  hermes:
    tags: [folder-compare, sync, dashboard, python, backup, diff, macos-tcc]
    related_skills: [dashboard-fullstack, macos-external-storage-cleanup, static-dashboard-builder]
---

# FDVS — Folder VS (เทียบ & ซิงค์สองโฟลเดอร์)

แดชบอร์ด Python stdlib สำหรับเทียบสองโฟลเดอร์บนวอลุ่มใดก็ได้ และคัดลอกไฟล์ให้เท่ากัน
โปรเจกต์อยู่ที่ `/Volumes/MNG/apps/fdvs/` รันที่ **port 4477** โดยค่าเริ่มต้น

## When to Load

- ผู้ใช้ถามว่า "สองโฟลเดอร์นี้เหมือนกันไหม" / "เทียบ folder" / "ไฟล์ไหนขาด" / "ก๊อปให้เท่ากัน"
- ผู้ใช้พูดถึง FDVS / Folder VS
- ต้องเทียบข้อมูลข้ามไดรฟ์ (เช่น `/Volumes/MNG` กับ `/Volumes/PLAY`)
- ต้องสำเนา/ซิงค์โฟลเดอร์สำรอง แล้วอยากได้หลักฐานว่าเท่ากันจริง
- เจอปัญหา macOS ปฏิเสธการเข้าถึงวอลุ่มถอดได้ (TCC)

## Quick Start

```bash
cd /Volumes/MNG/apps/fdvs
python3 -m app.server --port 4477        # → http://127.0.0.1:4477
python3 -m unittest discover -s tests -t . -v   # 58 tests
```

ตรวจว่าเซิร์ฟเวอร์ยังรันอยู่ (อย่าเชื่อว่าเปิดค้างไว้):

```bash
curl -s http://127.0.0.1:4477/api/health
```

ถ้าไม่ตอบ แปลว่ายังไม่รัน — สตาร์ทใหม่ด้วย `background=true` แล้ว health-check แยกอีกรอบ

## Architecture

| ไฟล์ | หน้าที่ |
|---|---|
| `app/compare.py` | `walk_tree()`, `compare_trees()`, `hash_file()` — เดินต้นไม้ + เทียบ |
| `app/sync.py` | `plan_sync()`, `execute_plan()` — วางแผน + คัดลอกแบบ transactional |
| `app/volumes.py` | `list_volumes()`, `probe_access()`, `request_access()`, `list_dir()` |
| `app/server.py` | HTTP server (stdlib) + API + static + security |
| `public/index.html` | แดชบอร์ด vanilla JS — ไม่มี build step |

## Workflow: เทียบให้เท่ากัน (ผ่าน API)

```bash
BASE=http://127.0.0.1:4477

# 1) ตรวจสิทธิ์ก่อน — ถ้าไม่ ok ห้ามสแกน
curl -s "$BASE/api/access?path=/Volumes/PLAY/backup" | python3 -m json.tool

# 2) สแกน
JOB=$(curl -s -X POST $BASE/api/compare -H 'Content-Type: application/json' \
  -d '{"left":"/Volumes/MNG/src","right":"/Volumes/PLAY/backup","options":{"hash_mode":"all"}}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
sleep 2 && curl -s "$BASE/api/jobs?id=$JOB" | python3 -m json.tool

# 3) dry-run ก่อนเสมอ
curl -s -X POST $BASE/api/sync -H 'Content-Type: application/json' \
  -d '{"report_id":"<id>","direction":"left_to_right","dry_run":true}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])'

# 4) คัดลอกจริง — ต้องมี confirm:true
curl -s -X POST $BASE/api/sync -H 'Content-Type: application/json' \
  -d '{"report_id":"<id>","direction":"left_to_right","dry_run":false,"confirm":true}'

# 5) สแกนซ้ำ — ต้องได้ identical:true
```

## Pitfalls (เจอจริงแล้ว)

### 1. `hash_mode: "auto"` ไม่จับเนื้อหาที่ขนาด+เวลาเท่ากัน
`auto` ทำงานเหมือน rsync ค่าเริ่มต้น — เทียบขนาด + mtime แล้ว hash เฉพาะเมื่อขนาดเท่าแต่เวลาไม่ตรง
ถ้าไฟล์ขนาดเท่ากัน **และ** เวลาเท่ากันแต่เนื้อหาต่าง → `auto` รายงานว่า `same` (ผิด)
**ใช้ `hash_mode: "all"` เมื่อต้องการความแม่นยำระดับไบต์** (ยอมรับว่าช้ากว่า)

### 2. `DirEntry` ไม่มี `.lstat()`
`os.DirEntry` มี `.stat()`, `.is_dir()`, `.is_file()`, `.is_symlink()` แต่ **ไม่มี `.lstat()`**
ใช้ `os.lstat(entry.path)` แทน ไม่งั้นได้ AttributeError

### 3. ไฟล์ส่วนเกินไม่ถูกลบโดยค่าเริ่มต้น
`plan_sync(direction="left_to_right")` จะ **ข้าม** ไฟล์ที่มีเฉพาะฝั่งปลายทาง
ผลคือหลัง sync แล้วยังไม่ `identical` จนกว่าจะเปิด `delete_extras=True`
อย่ารายงานว่า "เท่ากันแล้ว" ถ้ายังเหลือไฟล์ส่วนเกิน — ดู `summary.different` และ `dirs_only_*`

### 4. `/api/reports` คืน report ที่โฟลเดอร์ต้นทางถูกลบไปแล้ว
เทสต์ใช้ `tempfile.mkdtemp()` แล้วลบทิ้งใน tearDown — report ยังค้างใน `reports/`
เวลาเลือก report ให้กรองจาก path ไม่ใช่หยิบตัวแรกสุด:

```bash
curl -s "$BASE/api/reports" | python3 -c "
import sys,json
for r in json.load(sys.stdin)['reports']:
    if '/path/ที่ต้องการ' in (r['left'] or ''): print(r['id']); break"
```

### 5. macOS TCC บล็อก Desktop/Documents/Downloads และวอลุ่มถอดได้
`probe_access()` คืน `permission_required` พร้อม `hint` — **อย่าเดาว่าเป็น bug ของโค้ด**
เส้นทางแก้: System Settings → Privacy & Security → Full Disk Access / Files and Folders
เพิ่ม Terminal (หรือแอปที่รัน) แล้วกด "ตรวจสอบสิทธิ์อีกครั้ง"
ในหน้านี้มีปุ่ม + URL `x-apple.systempreferences:` ให้กดเปิดตรงได้
(`/api/access/request?path=` คืน `settings_url` + `instructions`)

### 6. การคัดลอกจริงต้องส่ง `confirm: true`
`dry_run: false` เดี่ยวๆ จะได้ 400 — เป็นการกันอุบัติเหตุ ไม่ใช่บั๊ก

### 7. อย่าลืมตรวจหลัง sync
หลังคัดลอกจริง **สแกนซ้ำเสมอ** และยืนยัน `summary.identical == true`
ผลลัพธ์ `ok: true` จาก `execute_plan` แปลว่าไม่มีข้อผิดพลาดระหว่างคัดลอก
ไม่ได้แปลว่าสองฝั่งเท่ากันแล้ว (ไฟล์ส่วนเกินยังอยู่ได้)

## Verification ที่ผ่านแล้ว

- **58/58 tests** — `python3 -m unittest discover -s tests -t .`
- **end-to-end จริง**: สแกน `.demo/A` vs `.demo/B` → 5 ต่าง → dry-run (0 copied) →
  คัดลอกจริง 4 ไฟล์ (SHA-256 verified) → เปิด `delete_extras` ลบ 1 → สแกนซ้ำได้
  `identical: true, same: 5, different: 0, bytes A: 43 == bytes B: 43`
- **permission probe**: Desktop/Documents/Library/MNG/PLAY → `ok`
- **browse**: `/Volumes` แสดง MNG, PLAY, Macintosh HD, Recovery
- **CSV export**: ได้ header `relpath,status,left_size,right_size,left_mtime,right_mtime,reasons`

## ข้อจำกัด

- ไม่ใช่ two-way realtime sync — สั่งทีละครั้ง
- ไม่เก็บประวัติเวอร์ชันไฟล์ (สำรองเฉพาะรอบที่ทับ/ลบ)
- ไม่ตรวจ xattr / ACL / resource fork
- ไม่มี login — ผูก `127.0.0.1` เท่านั้น อย่าเปิดออกอินเทอร์เน็ต
