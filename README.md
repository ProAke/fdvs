# FDVS — Folder VS

แดชบอร์ด Python สำหรับ **เทียบและซิงค์สองโฟลเดอร์** ที่อยู่บนไดรฟ์/วอลุ่มใดก็ได้ที่เสียบเข้าเครื่อง
สแกนด้วย Python, ขออนุญาตการเข้าถึงก่อนแตะข้อมูล, แสดงผลเทียบสองฝั่ง, สรุปจำนวนไฟล์/ขนาด,
และคัดลอกไฟล์ที่ขาดหรือต่างกันเพื่อทำให้สองฝั่งเท่ากัน — พร้อมตรวจ SHA-256 ทุกไฟล์ที่คัดลอก

![status](https://img.shields.io/badge/status-working-brightgreen)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![deps](https://img.shields.io/badge/dependencies-none-success)

---

## ทำอะไรได้

- **เลือกโฟลเดอร์จากวอลุ่มไหนก็ได้** — ตัวเลือกไฟล์แสดงทุกไดรฟ์ที่ mount อยู่ (`/Volumes/*`) พร้อมพื้นที่ว่าง, โฟลเดอร์บ้าน, Desktop/Documents/Downloads
- **ขออนุญาตการเข้าถึงก่อน** — ตรวจสิทธิ์ทุกเส้นทางก่อนสแกน (macOS TCC: Full Disk Access / Files and Folders / Removable Volumes) ถ้าไม่ผ่านจะไม่สแกน แต่เปิด System Settings ให้กดอนุญาต
- **สแกนด้วย Python** — เดินต้นไม้ไดเรกทอรีด้วย `os.scandir`, ไม่พึ่งไลบรารีภายนอก
- **เทียบสองฝั่ง** — A (ซ้าย) / B (ขวา) แสดงสถานะรายไฟล์
- **สรุปยอด** — ไฟล์เท่ากันกี่ไฟล์, ต่างกี่ไฟล์, เฉพาะ A, เฉพาะ B, ขนาดรวมแต่ละฝั่ง, ขนาดรวมเท่ากันหรือไม่
- **คัดลอกให้เท่ากัน** — dry-run ก่อนเสมอ, คัดลอกจริงต้องยืนยัน, สำรองไฟล์เดิมก่อนทับ, ตรวจ checksum
- **ประวัติการสแกน** — เก็บ report เป็น JSON, โหลดกลับมาดูซ้ำได้, export CSV/JSON

## สถานะรายไฟล์

| สถานะ | ความหมาย |
|---|---|
| `same` | เท่ากัน |
| `size_differs` | ขนาดไฟล์ต่างกัน |
| `content_differs` | ขนาดเท่ากันแต่เนื้อหาต่าง (ตรวจด้วย SHA-256) |
| `mtime_differs` | เนื้อหาเท่ากันแต่เวลาแก้ไขต่าง |
| `left_only` | มีเฉพาะฝั่ง A |
| `right_only` | มีเฉพาะฝั่ง B |
| `type_differs` | ชนิดไม่ตรงกัน (ไฟล์ vs โฟลเดอร์ vs อื่น) |
| `symlink_differs` | symlink ชี้ไปคนละที่ |

## เริ่มใช้งาน

ไม่ต้องติดตั้งอะไรเพิ่ม — Python 3.10+ และ standard library เท่านั้น

```bash
cd /Volumes/MNG/apps/fdvs
python3 -m app.server                 # → http://127.0.0.1:4477
python3 -m app.server --port 8080     # เปลี่ยนพอร์ต
python3 -m app.server --open          # เปิดเบราว์เซอร์อัตโนมัติ
```

เปิดเบราว์เซอร์ที่ **http://127.0.0.1:4477** แล้วทำตาม 3 ขั้นในหน้าเว็บ

### ขั้นตอนในแดชบอร์ด

1. **เลือกโฟลเดอร์สองฝั่ง** — กด "เลือกโฟลเดอร์" แล้วเลือกไดรฟ์/โฟลเดอร์ ระบบตรวจสิทธิ์ให้ทันที
2. **สแกนและเทียบ** — ดู verdict, การ์ดสรุปยอด, และตารางรายไฟล์ (กรอง/แบ่งแท็บตามสถานะได้)
3. **ทำให้เท่ากัน** — เลือกทิศทาง → กด "ดูตัวอย่าง (dry-run)" → ตรวจแผน → กด "คัดลอกจริง"

## ตัวเลือกการเทียบ

| ตัวเลือก | ค่า | ผล |
|---|---|---|
| โหมดเทียบ | `auto` (ค่าเริ่มต้น) | เทียบขนาด+เวลา; hash เฉพาะเมื่อขนาดเท่าแต่เวลาไม่ตรง |
| | `all` | hash ทุกไฟล์ที่อยู่ทั้งสองฝั่ง — แม่นที่สุด ช้าที่สุด |
| | `none` | เทียบขนาด+เวลาเท่านั้น — เร็วที่สุด |
| เทียบเวลาแก้ไข | เปิด/ปิด | ปิดเพื่อเทียบเฉพาะขนาด/เนื้อหา |
| คลาดเคลื่อน (วินาที) | ตัวเลข | กันเวลาเพี้ยนจากการคัดลอก (ค่าเริ่มต้น 2 วินาที) |
| ตาม symlink | เปิด/ปิด | ปิดเป็นค่าเริ่มต้น (ไม่ตามออกนอกโฟลเดอร์) |

> **หมายเหตุความแม่นยำ:** โหมด `auto` เทียบขนาด + เวลาเหมือน rsync ตามค่าเริ่มต้น
> ถ้าไฟล์ขนาดเท่ากันและเวลาเท่ากันแต่เนื้อหาต่าง ต้องใช้โหมด `all` จึงจะจับได้

## ทิศทางการซิงค์

| ทิศทาง | ผล |
|---|---|
| `A → B` | คัดลอกจาก A ไป B (B กลายเป็นสำเนาของ A) |
| `B → A` | คัดลอกจาก B ไป A |
| `สองทาง` | ไฟล์ที่มีฝั่งเดียวคัดลอกไปอีกฝั่ง; ไฟล์ที่ต่างกันให้ "ไฟล์ใหม่กว่าชนะ" |

**ไฟล์ส่วนเกินไม่ถูกลบโดยค่าเริ่มต้น** ต้องติ๊ก "ลบไฟล์ส่วนเกิน (อันตราย)" เอง

## ความปลอดภัยของการคัดลอก

- คัดลอกจริงต้องส่ง `confirm=true` ไม่งั้น API ปฏิเสธ
- คัดลอกลงไฟล์ชั่วคราวในโฟลเดอร์ปลายทาง → ตรวจ SHA-256 → `os.replace()` แบบ atomic
- เปิดสำรองไว้ ไฟล์เดิมที่ถูกทับ/ลบจะถูกเก็บใน `.fdvs-backup-<วันเวลา>/`
- ปฏิเสธพาธที่หลุดออกนอกโฟลเดอร์ราก (`../`)
- เซิร์ฟเวอร์ static บล็อก `.env`, `.pem`, `.key`, `.ppk`, `.p12`, `credentials*`, `secrets*`, `.git/config`, และ directory listing

## API

| Method | Endpoint | หน้าที่ |
|---|---|---|
| GET | `/api/health` | สถานะเซิร์ฟเวอร์ |
| GET | `/api/volumes` | วอลุ่มที่ mount + โฟลเดอร์บ้าน + สิทธิ์ |
| GET | `/api/browse?path=` | อ่านหนึ่งระดับไดเรกทอรี (ตัวเลือกโฟลเดอร์) |
| GET | `/api/access?path=` | ตรวจสิทธิ์เข้าถึง |
| GET | `/api/access/request?path=` | ขออนุญาต + คืน URL System Settings |
| POST | `/api/compare` | เริ่มงานสแกน → `{job_id}` (202) |
| GET | `/api/jobs?id=` | สถานะ/ความคืบหน้า/ผลของงาน |
| GET | `/api/report?id=` | report เต็ม |
| GET | `/api/reports` | ประวัติการสแกน |
| GET | `/api/report/<id>/export?format=csv\|json` | export |
| DELETE | `/api/report?id=` | ลบ report |
| POST | `/api/sync` | สร้าง+รันแผนซิงค์ |
| GET/POST | `/api/state` | จำโฟลเดอร์ล่าสุด |

ตัวอย่าง:

```bash
# สแกน
JOB=$(curl -s -X POST http://127.0.0.1:4477/api/compare \
  -H 'Content-Type: application/json' \
  -d '{"left":"/Volumes/MNG/A","right":"/Volumes/PLAY/B","options":{"hash_mode":"all"}}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')

curl -s "http://127.0.0.1:4477/api/jobs?id=$JOB"

# คัดลอกจริง (ต้องมี confirm)
curl -s -X POST http://127.0.0.1:4477/api/sync \
  -H 'Content-Type: application/json' \
  -d '{"report_id":"<id>","direction":"left_to_right","dry_run":false,"confirm":true}'
```

## โครงสร้างโปรเจกต์

```
fdvs/
├── app/
│   ├── __init__.py
│   ├── server.py      # HTTP server + API routing (stdlib http.server)
│   ├── compare.py     # เดินต้นไม้ + เทียบ (walk_tree, compare_trees, hash_file)
│   ├── sync.py        # วางแผน + คัดลอก (plan_sync, execute_plan)
│   └── volumes.py     # วอลุ่ม, สิทธิ์, browse (list_volumes, probe_access, list_dir)
├── public/
│   └── index.html     # แดชบอร์ด (vanilla JS, ไม่มี build step)
├── tests/
│   └── test_fdvs.py   # 58 tests (unittest, stdlib)
├── reports/           # report JSON ที่เก็บไว้ (สร้างอัตโนมัติ)
├── README.md
├── SKILL.md           # คู่มือสำหรับ AI agent
└── LICENSE
```

## ทดสอบ

```bash
cd /Volumes/MNG/apps/fdvs
python3 -m unittest discover -s tests -t . -v
```

ครอบคลุม: เดินต้นไม้ + ignore patterns, เทียบทั้ง 8 สถานะ, hash modes ทั้งสาม,
mtime tolerance, การวางแผนซิงค์ทั้ง 3 ทิศทาง, dry-run ไม่แตะข้อมูล,
คัดลอกจริงแล้วเท่ากันจริง, backup, checksum, กันพาธ traversal,
การยกเลิกกลางทาง, API ทุก endpoint, และ security (traversal/secret files)

## แผนพัฒนาเป็นแอป (macOS / Windows / iOS / Android / Linux)

ดู [ROADMAP.md](ROADMAP.md) — แผนงานพร้อมข้อจำกัดแพลตฟอร์มที่ต้องรู้ก่อนตัดสินใจ

**สรุปสั้น:** แนะนำ **Tauri v2** (โค้ดเบสเดียว 5 แพลตฟอร์ม, ใช้ UI เดิมซ้ำได้)
โดยทำ desktop 3 OS ก่อน (4–6 วัน) แล้วค่อย mobile (2–3 สัปดาห์)

**สิ่งที่ต้องรู้ก่อน:** mobile ไม่ใช่การ port — iOS App Sandbox และ Android Scoped Storage
**ห้าม**ให้แอปสแกนโฟลเดอร์/ไดรฟ์ตามอำเภอใจ บนมือถือจะเลือกได้ทีละโฟลเดอร์ที่ผู้ใช้อนุญาตเท่านั้น
(รายละเอียดใน ROADMAP.md ข้อ 2)

## ข้อจำกัดที่ต้องรู้

- **macOS TCC** — โฟลเดอร์ที่ระบบป้องกัน (Desktop/Documents/Downloads, วอลุ่มถอดได้) ต้องอนุญาตให้ Terminal หรือแอปที่รัน FDVS ก่อน ระบบจะแจ้งพร้อมปุ่มเปิด System Settings
- **โหมด auto ไม่จับ content ที่ขนาดและเวลาเท่ากัน** — ใช้โหมด `all` ถ้าต้องการแม่นยำระดับไบต์
- **ไม่ใช่ two-way sync แบบเรียลไทม์** — เป็นการเทียบและคัดลอกตามคำสั่ง ครั้งต่อครั้ง
- **ไม่เก็บประวัติเวอร์ชันไฟล์** — สำรองเฉพาะตอนทับ/ลบในรอบนั้น
- **ไม่ตรวจ extended attributes / ACL / resource fork** — เทียบขนาด เวลา เนื้อหา ชนิด
- **ผู้ใช้คนเดียวในเครื่อง** — ไม่มีระบบ login ผูกกับ `127.0.0.1` เท่านั้น อย่าเปิดออกอินเทอร์เน็ต

## License

MIT — ดู [LICENSE](LICENSE)
