# HANDOFF — FDVS (Folder VS) v2.0

**โปรเจกต์:** เทียบ & ซิงค์สองโฟลเดอร์/ไดรฟ์ พร้อมประเมินก่อนสแกน + นาฬิกาถอยหลัง
**ที่ตั้ง:** `/Volumes/MNG/apps/fdvs/`
**Repo:** https://github.com/ProAke/fdvs (public, `master` @ `71c0dbe`)
**รัน:** `python3 -m app.server --port 4477` → http://127.0.0.1:4477
**อัปเดตล่าสุด:** 2026-10-18 13:55 +07

---

## สถานะ: เสร็จและใช้งานได้จริง ✅ (v2.0)

เซิร์ฟเวอร์รันที่ port 4477 (PID 59086, cwd `/Volumes/MNG/apps/fdvs`)
ทดสอบ **72/72 pass** และทดสอบ UI จริงครบวงจรผ่านเบราว์เซอร์

---

## สิ่งที่เปลี่ยนใน v2.0

### 1. ดีไซน์ใหม่ตาม `design_guide.webp`

ดึงพาเลตต์จากภาพด้วย **โค้ด** (vision ใช้ไม่ได้กับโมเดลนี้ — 404 no image input)
ไม่ใช่การเดาสี:

| token | ค่า | ที่มา |
|---|---|---|
| page bg | `#c3cbdf` | สีที่พบมากสุด 21.2% ของภาพ |
| card | `#ffffff` | 13.9% |
| accent | `#7163ba` | สีม่วงหลัก 15.6% |
| accent deep | `#534597` | สีเข้มสุด (ใช้กับตัวอักษร) |
| text | `#2f2a4a` / `#5a517d` | พิกเซลที่มืดสุด = `#524594` |
| grey | `#ececee` | พื้นรอง |

เปลี่ยนจาก **dark navy** (v1) → **light lavender + purple** (ตามภาพ)
ยืนยันในเบราว์เซอร์: `getComputedStyle(body).backgroundColor` = `rgb(195, 203, 223)` ✅

### 2. ประเมินก่อนสแกน (ใหม่)

`GET /api/estimate` เดินดูทั้งสองฝั่ง **โดยไม่ hash** แล้วคืน:
จำนวนไฟล์/โฟลเดอร์/ขนาดต่อฝั่ง + **เวลาที่คาดว่าจะสแกน**

UI แสดงการ์ดซ้าย (ฝั่ง A) / นาฬิกา (กลาง) / การ์ดขวา (ฝั่ง B)

### 3. นาฬิกาถอยหลัง (ใหม่)

วงแหวน SVG นับถอยหลังตามเวลาที่ประเมิน:
- ระหว่างประเมิน → นับขึ้น + ป้าย "กำลังประเมิน"
- ระหว่างสแกน → **นับถอยหลัง** + วงแหวนเติมตามเวลา
- เกินประเมิน → เปลี่ยนเป็นสีเหลือง + นับขึ้น (`+0:05`)
- เสร็จ → สีเขียว + สรุป "ใช้เวลา X · เร็วกว่า/ช้ากว่าประมาณ N%"

---

## หลักฐานการทดสอบจริง

### Test suite — 72/72 PASS
```
python3 -m unittest discover -s tests -t .
Ran 72 tests in 2.300s
OK
```
เพิ่มจาก 58 → 72: `estimate_tree`, `estimate_scan`, `/api/estimate`,
และ regression test ว่าความเร็วที่วัดได้สะท้อนงานจริง

### UI end-to-end ผ่านเบราว์เซอร์จริง

ทดสอบ `.v2test/A` (42 ไฟล์) vs `.v2test/B` (36 ไฟล์):

| ขั้น | ผล |
|---|---|
| ประเมิน | ฝั่ง A 42 ไฟล์ / ฝั่ง B 36 ไฟล์ — **ตรงกับจำนวนจริงเป๊ะ** |
| นาฬิกา | นับถอยหลัง 0:03 → 0:01 → เสร็จ (จริง 1 วิ) |
| สแกน | "พบความต่าง 8 จาก 43 รายการ" |
| dry-run | 7 รายการ · คัดลอก 0 · **B ไม่ถูกแตะ** |
| คัดลอกจริง | 7 ไฟล์ · ล้มเหลว 0 · สำรองไว้ที่ `.fdvs-backup-20261018-134911` |
| delete_extras | ลบ 1 · ล้มเหลว 0 |
| สแกนสุดท้าย | **"✓ สองโฟลเดอร์เหมือนกันทั้งหมด — 42 ไฟล์เท่ากัน · 846 B == 846 B"** |

### ความแม่นยำของการประเมิน

| เคส | ประเมิน | จริง | ผล |
|---|---|---|---|
| `/Volumes/MNG/apps` vs `/Volumes/MNG/Work/TPS` | 1.9 วิ | 0.7 วิ | ✅ |
| `.v2test/A` vs `.v2test/B` | 3 วิ | 1 วิ | ✅ |

**ความเร็วจริงที่วัดได้** (ต่างกัน ~16 เท่าระหว่างวอลุ่ม — ค่าคงที่ค่าเดียวใช้ไม่ได้):
- `/Volumes/MNG` ≈ 4,000–8,000 entries/วิ
- `/Volumes/PLAY` ≈ 260 entries/วิ

---

## 3 บั๊กการคิดเวลาที่เจอและแก้ (สำคัญ)

ทั้งหมดเจอเพราะ **วัดเทียบกับของจริง** ไม่ใช่เชื่อโค้ด:

### บั๊ก 1 — วัด walk rate สูงเกินจริง ~20 เท่า
`_measure_walk_rate` นับ entry จาก `os.scandir` เปล่า ๆ แต่ `walk_tree` เรียก
`entry.stat()` ทุกไฟล์ ซึ่งเป็นค่าใช้จ่ายหลักบนวอลุ่มช้า
→ ตัววัดต้องทำงานเหมือน `walk_tree` เป๊ะ ๆ
→ ตอนนี้ใช้ `observed_walk_rate` จาก **การเดินจริงในรอบนั้น** (warm cache, ต้นไม้เดียวกัน)

### บั๊ก 2 — เอาเวลาของขั้นประเมินเองไปบวกในเวลาที่จะสแกน
ขั้นประเมินจบไปแล้วก่อนนาฬิกาจะเริ่ม → สแกน 2 วิ กลายเป็น "ประเมิน 23 วิ"
→ แก้: ประเมินเฉพาะเวลาสแกน

### บั๊ก 3 — `hash_mode: all` คิดว่า hash ทุกไบต์ทั้งสองฝั่ง
จริง ๆ hash เกิดเฉพาะไฟล์ที่มี **ทั้งสองฝั่ง** — ไฟล์ที่มีฝั่งเดียวถูกคัดลอก ไม่ถูก hash
→ ต้องคิดจาก `min(left_bytes, right_bytes)`
→ เคส disjoint trees: 0.7 วิ จริง แต่ประเมิน 20 วิ (19 วิ เป็นงานที่ไม่มีจริง)

---

## ไฟล์

| ไฟล์ | ขนาด | หน้าที่ |
|---|---|---|
| `app/compare.py` | 19 KB | `walk_tree`, `compare_trees`, `hash_file`, **`estimate_tree`, `estimate_scan`** |
| `app/sync.py` | 12 KB | `plan_sync`, `execute_plan` |
| `app/volumes.py` | 9 KB | `list_volumes`, `probe_access`, `request_access`, `list_dir` |
| `app/server.py` | 20 KB | HTTP API + static + security (เพิ่ม `/api/estimate`) |
| `public/index.html` | 63 KB | แดชบอร์ด 4 ขั้น + นาฬิกาถอยหลัง |
| `tests/test_fdvs.py` | 33 KB | 72 tests |
| `README.md` | 15 KB | เอกสารผู้ใช้ |
| `SKILL.md` | 13 KB | คู่มือ AI agent + 11 pitfalls |
| `ROADMAP.md` | 30 KB | แผนพัฒนาเป็นแอป 5 แพลตฟอร์ม |

---

## ข้อจำกัดที่ต้องรู้

- **การประเมินเป็นค่าประมาณ** เมื่อต้นไม้ใหญ่เกินงบเวลา (ค่าเริ่มต้น 8 วิ)
  → ตัวเลขถูกขยายผลจากส่วนที่เดินได้ + ทำเครื่องหมาย `extrapolated`
  จำนวนที่แน่นอนต้องสแกนจริง
- **งานสั้นกว่า ~4 วิ** — นาฬิกาเปลี่ยนเป็นป้าย "งานเล็ก" เพราะการยืนยันเวลาไม่มีความหมาย
- **`hash_mode: auto`** ไม่จับ content ที่ขนาด+เวลาเท่ากัน — ใช้ `all` ถ้าต้องการแม่นระดับไบต์
- **macOS TCC** — Desktop/Documents/Downloads และวอลุ่มถอดได้ต้องอนุญาตก่อน
- ไม่ใช่ realtime two-way sync · ไม่เก็บประวัติเวอร์ชันไฟล์ · ไม่ตรวจ xattr/ACL
- ไม่มี login — ผูก `127.0.0.1` เท่านั้น

---

## ขั้นต่อไป

1. เพิ่มช่องปรับ `budget_s` ใน UI (ตอนนี้ 8 วิ คงที่) สำหรับโฟลเดอร์ใหญ่มาก
2. ให้ผู้ใช้เลือกได้ว่า "ประเมินละเอียด" (ไม่จำกัดเวลา) หรือ "เร็ว"
3. จำ `observed_walk_rate` ต่อวอลุ่มไว้ใช้ข้ามรอบ (ตอนนี้อยู่ในหน่วยความจำ)
4. แสดง breakdown เวลา (walk/hash/compare) ใน UI — ตอนนี้อยู่ใน API แล้วแต่ยังไม่โชว์
5. ตาม `ROADMAP.md` — เริ่มเฟส 1 (desktop 3 OS ด้วย Tauri)

---

## คำสั่งที่ใช้บ่อย

```bash
cd /Volumes/MNG/apps/fdvs

# รัน
python3 -m app.server --port 4477

# ทดสอบ
python3 -m unittest discover -s tests -t .

# ตรวจว่าเซิร์ฟเวอร์ยังอยู่
curl -s http://127.0.0.1:4477/api/health

# ประเมินก่อนสแกน
curl -s "http://127.0.0.1:4477/api/estimate?left=/path/A&right=/path/B&hash_mode=auto"

# ตรวจความแม่นยำของการประเมิน (pred vs actual)
python3 -c "
import sys,time; sys.path.insert(0,'.')
from app.compare import estimate_scan, compare_trees, _WALK_RATE_CACHE, _HASH_RATE_CACHE
_WALK_RATE_CACHE.clear(); _HASH_RATE_CACHE.clear()
L,R='/Volumes/MNG/apps','/Volumes/MNG/Work/TPS'
est=estimate_scan(L,R,hash_mode='all',budget_s=8)
t0=time.time(); compare_trees(L,R,hash_mode='all'); act=time.time()-t0
print('pred',est['seconds']['total'],'actual',round(act,2),'ratio',round(act/est['seconds']['total'],2))
"
```

---

## Backup migration — 2026-10-18 14:40 +07

ย้าย backup ของ MNG Dashboard จากที่กระจัดกระจาย 3 ที่ → `/Volumes/MNG/Home_Backup/MNG-Dashboard/`

| จาก | ไป | จำนวน |
|---|---|---|
| `/Volumes/MNG/index.html.bak*` (top level) | `top-level/` | 11 |
| `/Volumes/MNG/.backup/` (ไฟล์) | `dot-backup/` | 49 |
| `/Volumes/MNG/.backup/*/` (snapshot) | `dot-backup/snapshots/` | 20 |
| `/Volumes/MNG/Backup/index.html.*` | `Backup-folder/` | 12 |
| `/Volumes/MNG/Backup/tmp/` | `Backup-folder/tmp/` | 3 |

- **63 รายการ · 1,626,815 ไบต์** · ทุกไฟล์ verify SHA-256 ก่อนลบต้นทาง
- ลบ container ว่างแล้ว: `.backup/`, `Backup/tmp/`
- **ไม่ย้าย:** `Backup/vulcananti-scale.com.*` (เว็บลูกค้า) · `Backup/revslider*.zip` (ปลั๊กอิน)
- ไฟล์ประกอบใน `Home_Backup/MNG-Dashboard/`: `README.md`, `MIGRATION-MANIFEST.json`, `rollback.sh`
- สคริปต์: `scripts/migrate_backups.py`

**กฎใหม่: สำรอง index.html ไปที่ `Home_Backup/MNG-Dashboard/top-level/` เสมอ**
