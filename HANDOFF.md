# HANDOFF — FDVS (Folder VS)

**โปรเจกต์:** เทียบ & ซิงค์สองโฟลเดอร์/ไดรฟ์
**ที่ตั้ง:** `/Volumes/MNG/apps/fdvs/`
**Repo:** https://github.com/ProAke/fdvs (public, `master` @ `b7a9bfa`)
**รัน:** `python3 -m app.server --port 4477` → http://127.0.0.1:4477
**อัปเดตล่าสุด:** 2026-10-18 12:58 +07

---

## สถานะ: เสร็จและใช้งานได้จริง ✅

เซิร์ฟเวอร์รันอยู่ที่ port 4477 (PID 42563, cwd `/Volumes/MNG/apps/fdvs`)
ทดสอบ **58/58 pass** และทดสอบ UI จริงครบวงจรผ่านเบราว์เซอร์

---

## สิ่งที่สร้าง

แดชบอร์ด Python stdlib (ไม่พึ่งไลบรารีภายนอก) 3 ขั้นตอนในหน้าเดียว:

1. **เลือกโฟลเดอร์สองฝั่ง** — ตัวเลือกโฟลเดอร์แสดงทุกวอลุ่มที่ mount พร้อมพื้นที่ว่าง
   และตรวจสิทธิ์การเข้าถึงทันทีที่เลือก
2. **สแกนและเทียบ** — verdict, การ์ดสรุปยอด, ตารางรายไฟล์ 8 สถานะ + แท็บกรอง + export CSV/JSON
3. **ทำให้สองฝั่งเท่ากัน** — เลือกทิศทาง → dry-run → คัดลอกจริง (มี backup + SHA-256 verify)

### ไฟล์

| ไฟล์ | ขนาด | หน้าที่ |
|---|---|---|
| `app/compare.py` | 12.6 KB | `walk_tree`, `compare_trees`, `hash_file` |
| `app/sync.py` | 11.7 KB | `plan_sync`, `execute_plan` |
| `app/volumes.py` | 9.0 KB | `list_volumes`, `probe_access`, `request_access`, `list_dir` |
| `app/server.py` | 19.3 KB | HTTP API + static + security guards |
| `public/index.html` | 46.9 KB | แดชบอร์ด vanilla JS (ไม่มี build step) |
| `tests/test_fdvs.py` | 25.2 KB | 58 tests (unittest, stdlib) |
| `README.md` | 12.7 KB | เอกสารผู้ใช้ |
| `SKILL.md` | 8.8 KB | คู่มือ AI agent + pitfalls |

---

## หลักฐานการทดสอบจริง

### Test suite — 58/58 PASS
```
python3 -m unittest discover -s tests -t .
Ran 58 tests in 1.780s
OK
```
ครอบคลุม: walk_tree + ignore patterns, เทียบครบ 8 สถานะ, hash modes 3 แบบ,
mtime tolerance, plan ทั้ง 3 ทิศทาง, dry-run ไม่แตะข้อมูล, copy จริงแล้วเท่ากัน,
backup, checksum, path traversal, cancel กลางทาง, API ทุก endpoint, security

### UI end-to-end ผ่านเบราว์เซอร์จริง
ทดสอบ `.uitest/A` (4 ไฟล์) vs `.uitest/B` (3 ไฟล์):

| ขั้น | ผล |
|---|---|
| สแกน | "พบความต่าง 3 จาก 5 รายการ" · A 39 B / B 25 B · ต่าง 14 B |
| dry-run | "ทั้งหมด 2 รายการ · คัดลอก 0" · B **ไม่ถูกแตะ** (ยืนยันด้วย `ls`) |
| คัดลอกจริง | "คัดลอก 2 · ล้มเหลว 0" · `beta.txt`, `docs/deep.txt` → SHA-256 recorded |
| สแกนซ้ำ | "4 เท่ากัน / 1 ต่าง" — เหลือ `gamma.txt` (ไฟล์ส่วนเกินฝั่ง B) |
| เปิด delete_extras | "ลบ 1 · ล้มเหลว 0" |
| สแกนสุดท้าย | **"✓ สองโฟลเดอร์เหมือนกันทั้งหมด — 4 ไฟล์เท่ากัน ขนาดรวม 39 B"** · A 39 B == B 39 B |

ยืนยันด้วย `diff -r` ว่าเท่ากันจริง

### ตัวเลือกโฟลเดอร์
แสดง 5 วอลุ่มพร้อมพื้นที่ว่าง: Macintosh HD (system root) 14.3 GB ·
MNG 130 GB · Macintosh HD 14.3 GB · PLAY 711 GB · Recovery 14.3 GB
นำทางขึ้น/ลงได้, เลือกได้

### สิทธิ์การเข้าถึง
- `/System/Library` → `ok` (อ่านอย่างเดียว)
- `/Volumes/PLAY` → `ok` (อ่าน/เขียน)
- โฟลเดอร์ chmod 000 → `permission_required` + `pane: "Files and Folders → Removable Volumes"`
  + `settings_url: x-apple.systempreferences:...?Privacy_FilesAndFolders`

### ค่าเริ่มต้นปลอดภัย (ตรวจในเบราว์เซอร์)
`optDelete=false` · `optVerify=true` · `optBackup=true` · `followLinks=false` · `hashMode=auto`

---

## Pitfalls ที่เจอและแก้แล้ว (บันทึกใน SKILL.md)

1. **`hash_mode:"auto"` ไม่จับเนื้อหาที่ขนาด+เวลาเท่ากัน** — ทำงานเหมือน rsync;
   ไฟล์ขนาดเท่า+เวลาเท่าแต่เนื้อหาต่างจะถูกรายงานว่า `same` (ผิด)
   → ใช้ `hash_mode:"all"` เมื่อต้องการความแม่นยำระดับไบต์ (เจอตอนเทสต์ล้ม 1 ตัว)
2. **`os.DirEntry` ไม่มี `.lstat()`** — ใช้ `os.lstat(entry.path)` (เจอจาก Pyright)
3. **ไฟล์ส่วนเกินไม่ถูกลบโดย default** — หลัง sync ยังไม่ `identical` จนเปิด `delete_extras`
   ห้ามรายงานว่า "เท่ากันแล้ว" ถ้ายังเหลือ — ดู `summary.different`
4. **`/api/reports` คืน report ที่โฟลเดอร์ต้นทางถูกลบแล้ว** (ค้างจาก tempfile ของเทสต์)
   → กรองจาก path ไม่ใช่หยิบตัวแรก
5. **`Privacy_RemovableVolumes` ไม่ใช่ pane จริงใน System Settings**
   → Removable Volumes อยู่ใต้ Files and Folders (แก้แล้ว commit `b7a9bfa`)
6. **การคัดลอกจริงต้องส่ง `confirm:true`** — ไม่งั้น 400 (กันอุบัติเหตุ ไม่ใช่บั๊ก)

---

## MNG Dashboard Card

เพิ่มการ์ด `fdvs` ใน `/Volumes/MNG/index.html` แล้ว:
- ตำแหน่ง: หลัง `tps-project` (เป็น project ที่ 2 จาก 18)
- `stat: "live"` · `folder: "/apps/fdvs/"`
- ลิงก์ 3 อัน: FDVS Dashboard (:4477), GitHub repo, README
- **backup:** `/Volumes/MNG/index.html.bak-20261018-125037-before-fdvs-card`

**ยืนยันว่าไม่ทำข้อมูลเดิมเสียหาย:**
- ข้อความนอก `const SOURCE` เหมือนเดิมทุกไบต์
- `tasks` ไม่เปลี่ยน · metadata อื่น (`source`, `importedAt`, `sourceSha256`) ไม่เปลี่ยน
- การ์ดเดิมทั้ง 17 ใบอยู่ครบและค่าเท่าเดิม
- ตรวจในเบราว์เซอร์: "18 projects · Hub import" และ "FDVS — Folder VS" ปรากฏในรายการ

> หมายเหตุ: ระหว่างแก้ ผมเผลอเขียนทับฟิลด์ `sourceSha256` (มันคือ hash ของ**แหล่งที่มา**
> ไม่ใช่ hash ของไฟล์ตัวเอง) แล้วกู้คืนค่าจริง `a1feb296...6af30` เรียบร้อย

---

## ข้อจำกัดที่ต้องรู้

- **macOS TCC** — Desktop/Documents/Downloads และวอลุ่มถอดได้ต้องอนุญาตก่อน
  หน้านี้แจ้ง + มีปุ่มเปิด System Settings ให้ตรง
- **`auto` mode ไม่จับ content ที่ขนาด+เวลาเท่ากัน** — ใช้ `all` ถ้าต้องการแม่นระดับไบต์
- **ไม่ใช่ two-way realtime sync** — สั่งทีละครั้ง
- **ไม่เก็บประวัติเวอร์ชันไฟล์** — สำรองเฉพาะรอบที่ทับ/ลบ
- **ไม่ตรวจ xattr / ACL / resource fork** — เทียบขนาด เวลา เนื้อหา ชนิด
- **ไม่มี login** — ผูก `127.0.0.1` เท่านั้น อย่าเปิดออกอินเทอร์เน็ต

---

## ขั้นต่อไป (ถ้าต้องการ)

1. เพิ่ม ignore list ที่แก้ได้ใน UI (ตอนนี้ใช้ค่า default + glob ในโค้ด)
2. เพิ่มโหมด "sync แล้วปิดเครื่อง" / scheduled compare ผ่าน cron
3. เทียบระดับไบต์แบบ partial (rsync delta) สำหรับไฟล์ใหญ่ — ตอนนี้คัดลอกทั้งไฟล์
4. เก็บ report ลง SQLite แทน JSON ต่อไฟล์ ถ้าประวัติเยอะขึ้น
5. เพิ่ม unit test สำหรับ UI (ตอนนี้ UI ทดสอบด้วยมือผ่านเบราว์เซอร์)

---

## คำสั่งที่ใช้บ่อย

```bash
cd /Volumes/MNG/apps/fdvs

# รัน
python3 -m app.server --port 4477

# ทดสอบ
python3 -m unittest discover -s tests -t . -v

# ตรวจว่าเซิร์ฟเวอร์ยังอยู่
curl -s http://127.0.0.1:4477/api/health

# เทียบผ่าน CLI
curl -s -X POST http://127.0.0.1:4477/api/compare \
  -H 'Content-Type: application/json' \
  -d '{"left":"/path/A","right":"/path/B","options":{"hash_mode":"all"}}'
```
