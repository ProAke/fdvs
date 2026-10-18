# ROADMAP — FDVS สู่แอป 5 แพลตฟอร์ม

**เอกสารนี้คือแผนงาน** สำหรับพัฒนา FDVS (เว็บแดชบอร์ด Python) ให้เป็นแอปจริงบน
macOS · Windows · iOS · Android (และ Linux)

| | |
|---|---|
| **เวอร์ชันฐาน** | FDVS v1.0.0 (เว็บแดชบอร์ด Python stdlib) |
| **Commit ฐาน** | `fc348f5` |
| **Repo** | https://github.com/ProAke/fdvs |
| **สถานะเวอร์ชันนี้** | ใช้งานได้จริง · 58/58 tests ผ่าน · รันที่ `127.0.0.1:4477` |
| **วันที่วางแผน** | 2026-10-18 +07 |
| **ผู้วางแผน** | Hermes Agent + อ.เอก |

---

## 1. สรุปผู้บริหาร

**คำแนะนำ: Tauri v2** เป็นทางเดียวที่ครอบทั้ง 5 แพลตฟอร์มด้วยโค้ดเบสเดียว
และเป็นตัวเดียวที่ **ใช้ `public/index.html` เดิมซ้ำได้เกือบทั้งหมด**

**แต่ต้องเข้าใจก่อนตัดสินใจ:** mobile ไม่ใช่การ "port" เวอร์ชันนี้ — เป็น **คนละผลิตภัณฑ์**
เพราะ iOS และ Android **ห้าม**ให้แอปสแกนโฟลเดอร์/ไดรฟ์ตามอำเภอใจ

| แพลตฟอร์ม | "สแกนโฟลเดอร์ไหนก็ได้" | ผลต่อผลิตภัณฑ์ |
|---|---|---|
| macOS | ✅ ได้ (หลังผู้ใช้อนุญาต TCC) | เหมือนเวอร์ชันปัจจุบัน |
| Windows | ✅ ได้ | เหมือนเวอร์ชันปัจจุบัน |
| Linux | ✅ ได้ | เหมือนเวอร์ชันปัจจุบัน |
| **iOS** | ❌ **ไม่ได้** — เฉพาะโฟลเดอร์ที่ผู้ใช้เลือกผ่าน Document Picker | ต้องออกแบบ UI ใหม่ |
| **Android** | ❌ **ไม่ได้** — ขอได้ทีละโฟลเดอร์ และ 3 ตำแหน่งขอไม่ได้เลย | ต้องออกแบบ UI ใหม่ |

**ข้อสรุปเชิงกลยุทธ์:** ทำ desktop ให้เสร็จและแข็งแรงก่อน (ได้คุณค่าเต็ม)
แล้วค่อยทำ mobile เป็น "เวอร์ชันเลือกโฟลเดอร์" ที่ลดขอบเขตลง — ไม่ใช่พยายามเลียนแบบ desktop

---

## 2. ข้อจำกัดแพลตฟอร์ม (ข้อเท็จจริงอ้างอิงได้)

ส่วนนี้คือหัวใจของแผน — ถ้าไม่เข้าใจข้อจำกัดนี้ จะออกแบบ mobile ผิดตั้งแต่ต้น

### 2.1 iOS — App Sandbox

อ้างอิง: Apple Developer Documentation — *Providing access to directories*, *Accessing files from the macOS App Sandbox*

| เรื่อง | รายละเอียด |
|---|---|
| ขอบเขตการเข้าถึง | เฉพาะโฟลเดอร์ที่ผู้ใช้เลือกผ่าน `UIDocumentPickerViewController` (iOS 13+ เลือกโฟลเดอร์ได้) |
| รูปแบบที่ได้ | security-scoped URL |
| การใช้งาน | **ต้อง**เรียก `startAccessingSecurityScopedResource()` ก่อน และ `stopAccessingSecurityScopedResource()` หลัง |
| ถ้าไม่ balance | **เสียสิทธิ์เข้าถึงถาวรจนปิดแอป** (kernel resource leak) |
| จำนวนพร้อมกัน | มีจำกัด — ถ้าไม่ release จะเปิดอันใหม่ไม่ได้ |
| เก็บถาวร | ต้องทำ security-scoped bookmark + entitlement `com.apple.security.files.bookmarks.app-scope` |
| ถ้าลืม entitlement | `resolve()` ล้มเหลวด้วย `AccessDenied` |
| `/Volumes/*` | **ไม่มี** — ไม่มีแนวคิด external drive |
| File coordination | ต้องใช้ `NSFileCoordinator` สำหรับอ่าน/เขียน |

### 2.2 Android — Scoped Storage (API 30+)

อ้างอิง: Android Developer Documentation — *Storage updates in Android 11*

| เรื่อง | รายละเอียด |
|---|---|
| รูปแบบการเข้าถึง | **grant** ต่อ URI ไม่ใช่ path — ผ่าน `ACTION_OPEN_DOCUMENT_TREE` (SAF) |
| ขอไม่ได้เลย | ① root ของ internal storage ② root ของ SD card ที่ถือว่า reliable ③ **`Download`** |
| ขอไม่ได้ทุกกรณี | `Android/data/` และ `Android/obb/` (แม้ถือ `MANAGE_EXTERNAL_STORAGE`) |
| เก็บถาวร | ต้องเรียก `takePersistableUriPermission()` — หลุดถ้าโฟลเดอร์ถูกย้าย/ลบ |
| Direct file path | **ไม่มี** สำหรับ non-media → ต้อง stream ผ่าน `ContentResolver` |
| `MANAGE_EXTERNAL_STORAGE` | มี แต่ **Google Play กั้นนโยบาย** — ต้องยื่นขออนุมัติ มีโอกาสถูกปฏิเสธ |
| MediaStore | ไม่ช่วย — ไฟล์ `.md`, `.txt`, ไฟล์ทั่วไปไม่ถูก scan |

### 2.3 ผลกระทบตรงต่อโค้ด FDVS ปัจจุบัน

| กลไกในโค้ดเดิม | desktop | iOS | Android |
|---|---|---|---|
| `os.scandir()` เดินต้นไม้ | ✅ | ⚠️ ต้อง enumerate ผ่าน scoped URL | ⚠️ ต้อง enumerate ผ่าน ContentResolver |
| `os.path.join()` สร้าง path | ✅ | ❌ ใช้ URL | ❌ ใช้ URI |
| `shutil.copy2()` | ✅ | ⚠️ ต้อง file coordination | ❌ ต้อง stream |
| `os.replace()` (atomic rename) | ✅ | ⚠️ จำกัด | ❌ **ทำไม่ได้** |
| `os.lstat()` / symlink | ✅ | ❌ | ❌ |
| `os.utime()` | ✅ | ⚠️ | ❌ |
| xattr / ACL | ⚠️ (ยังไม่ทำ) | ❌ | ❌ |
| `probe_access()` TCC check | ✅ (macOS) | → เปลี่ยนเป็น permission prompt | → เปลี่ยนเป็น SAF grant |
| **ตรรกะเทียบ (compare)** | ✅ | ✅ **ย้ายได้** | ✅ **ย้ายได้** |
| **ตรรกะวางแผน (plan)** | ✅ | ✅ **ย้ายได้** | ✅ **ย้ายได้** |

**อ่านตารางนี้แล้วสรุปได้ว่า:** `compare.py` และ `sync.py` (ส่วนวางแผน) ย้ายข้ามแพลตฟอร์มได้
แต่ `volumes.py` + ส่วน I/O ของ `sync.py` **ต้องเขียนใหม่แยกตามแพลตฟอร์ม**

---

## 3. ทางเลือกทางเทคนิค (เปรียบเทียบ)

| ทางเลือก | แพลตฟอร์ม | ใช้ UI เดิมซ้ำ | ต้องเขียนใหม่ | ไบนารี | ข้อดี | ข้อเสีย |
|---|---|---|---|---|---|---|
| **A. Tauri v2** ⭐ | Mac/Win/Linux/iOS/Android | ✅ ~90% | Rust core (~600 บรรทัด) | 600KB–10MB | ครบ 5 แพลตฟอร์มโค้ดเบสเดียว · ใช้ WebView ของ OS · UI เดิมใช้ซ้ำ | Rust learning curve · mobile toolchain ยุ่ง |
| B. Python + PyInstaller | Mac/Win/Linux | ✅ 100% | ไม่ต้อง | 30–80MB | **เร็วที่สุด** — แพ็กได้ในวันเดียว · ไม่ต้องเขียนโค้ดใหม่ | **mobile ทำไม่ได้** · ปิดประตูถาวร |
| C. Flutter | ทั้งหมด | ❌ | ทั้งหมด | 15–40MB | mobile UI ดี | file access desktop อ่อน · ต้องเขียนใหม่หมด |
| D. .NET MAUI | Win/Mac(Catalyst)/iOS/Android | ❌ | ทั้งหมด | 20–50MB | Microsoft stack | ไม่มี Linux · ต้องเขียนใหม่หมด |
| E. Kotlin Multiplatform | ทั้งหมด | ❌ | ทั้งหมด | กลาง | mobile เนทีฟ | desktop ยังไม่ mature · ต้องเขียนใหม่หมด |

### เหตุผลที่เลือก A (Tauri v2)

1. **`public/index.html` เป็น vanilla JS ไม่มี build step** — เหมาะกับ Tauri ที่สุด
   (Tauri ต้องการ static output ไม่รองรับ SSR — และ FDVS เป็น static อยู่แล้ว)
2. เป็นทางเดียวที่ **mobile + desktop โค้ดเบสเดียว** จริง
3. ใช้ WebView ของ OS → ไบนารีเล็กมาก
4. ข้อจำกัด OS บน mobile **ยังอยู่ไม่ว่าจะเลือกอะไร** — Tauri ไม่ได้ทำให้แย่ลง
5. ถ้าอนาคตต้องการ TPS/Afterklass dashboards เป็นแอป ก็ใช้โครงเดิมได้

---

## 4. สถาปัตยกรรมเป้าหมาย

### 4.1 โครงสร้าง

```
fdvs-app/
├── src/                          # frontend (ย้ายจาก public/index.html)
│   ├── index.html
│   ├── app.js                    # เปลี่ยน fetch() → invoke()
│   └── styles.css
├── src-tauri/                    # Tauri + Rust
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   ├── capabilities/
│   └── src/
│       ├── lib.rs                # entry point (mobile + desktop)
│       ├── main.rs               # desktop entry
│       ├── commands.rs           # #[tauri::command] แทน HTTP endpoints
│       ├── core/
│       │   ├── compare.rs        # ← พอร์ตจาก app/compare.py
│       │   ├── sync.rs           # ← พอร์ตจาก app/sync.py
│       │   └── hash.rs           # SHA-256 streaming
│       └── platform/             # ★ แยกตามแพลตฟอร์ม
│           ├── mod.rs            # trait FsBackend
│           ├── desktop.rs        # std::fs — path-based
│           ├── ios.rs            # security-scoped URL + bookmark
│           └── android.rs        # SAF + ContentResolver
└── .github/workflows/build.yml   # CI build 5 แพลตฟอร์ม
```

### 4.2 Abstraction ที่ต้องมี (สำคัญที่สุด)

ทั้งหมดขึ้นกับ trait เดียว — `FsBackend`:

```rust
/// ทุกแพลตฟอร์ม implement trait นี้ — core logic ไม่รู้ว่าอยู่บนอะไร
pub trait FsBackend: Send + Sync {
    /// ระบุโฟลเดอร์ (desktop: path, mobile: ให้ผู้ใช้เลือกผ่าน picker)
    fn pick_folder(&self) -> Result<FolderHandle, FsError>;

    /// เดินต้นไม้ — คืน path แบบ relative เท่านั้น (ไม่ผูกกับ path จริงของ OS)
    fn walk(&self, handle: &FolderHandle) -> Result<Vec<Entry>, FsError>;

    /// อ่านไฟล์เป็น stream (mobile ทำได้แค่ stream)
    fn open_read(&self, handle: &FolderHandle, rel: &str) -> Result<Box<dyn Read>, FsError>;

    /// เขียนไฟล์
    fn open_write(&self, handle: &FolderHandle, rel: &str) -> Result<Box<dyn Write>, FsError>;

    /// rename (desktop: atomic · mobile: copy+delete)
    fn finalize(&self, handle: &FolderHandle, rel: &str, tmp: &str) -> Result<(), FsError>;

    /// ลบ
    fn remove(&self, handle: &FolderHandle, rel: &str) -> Result<(), FsError>;

    /// ความสามารถที่แพลตฟอร์มนี้มี
    fn capabilities(&self) -> Capabilities;
}

/// UI ใช้ตัวนี้เพื่อซ่อน/ปิดฟีเจอร์ที่ทำไม่ได้
pub struct Capabilities {
    pub atomic_rename: bool,      // desktop: true · android: false
    pub symlinks: bool,           // desktop: true · mobile: false
    pub set_mtime: bool,          // desktop: true · ios: partial · android: false
    pub browse_volumes: bool,     // desktop: true · mobile: false
    pub delete: bool,             // ทุกที่: true (แต่ต้องยืนยัน)
}
```

**`core/compare.rs` และ `core/sync.rs` ใช้ trait นี้เท่านั้น — ไม่แตะ `std::fs` โดยตรง**
นี่คือสิ่งที่ทำให้โค้ดเบสเดียวทำงานได้จริงบน 5 แพลตฟอร์ม

### 4.3 Endpoint → Command mapping

| HTTP เดิม | Tauri command |
|---|---|
| `GET /api/health` | — (ไม่ต้องมี, ไม่มี server) |
| `GET /api/volumes` | `list_volumes()` |
| `GET /api/browse?path=` | `browse(path)` (desktop เท่านั้น) |
| `GET /api/access?path=` | `probe_access(path)` |
| `GET /api/access/request?path=` | `request_access(path)` (desktop) / `request_picker()` (mobile) |
| `POST /api/compare` | `compare(left, right, options)` |
| `GET /api/jobs?id=` | → Tauri events (`app.emit("progress", ...)`) |
| `GET /api/report?id=` | `get_report(id)` |
| `GET /api/reports` | `list_reports()` |
| `POST /api/sync` | `plan_sync(...)` + `execute_sync(...)` |
| `GET/POST /api/state` | `load_state()` / `save_state()` (→ Tauri store plugin) |

**งานส่วนนี้เป็น mechanical** — เปลี่ยน `fetch()` เป็น `invoke()` ประมาณ 15 จุด

---

## 5. แผนดำเนินงานเป็นเฟส

### เฟส 0 — เตรียม toolchain (คุณต้องทำ — ต้องกดยืนยัน/ใส่รหัสเอง)

สถานะเครื่องนี้ (ตรวจแล้ว 2026-10-18):

| ต้องมี | สถานะ | คำสั่งติดตั้ง |
|---|---|---|
| Rust + Cargo | ✅ 1.99.0 | — (แต่มา Homebrew) |
| **rustup** | ❌ **ไม่มี** | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \| sh` |
| Node / npm | ✅ 20.12.2 / 10.5.0 | — |
| Homebrew | ✅ 7.0.9 | — |
| **Xcode.app** | ❌ **ไม่มี** (มีแต่ CLT) | App Store (~10–15 GB) → `sudo xcode-select -s /Applications/Xcode.app` |
| **CocoaPods** | ❌ ไม่มี | `brew install cocoapods` |
| **Android Studio + SDK + NDK** | ❌ ไม่มี | ดาวน์โหลดจาก developer.android.com |
| `JAVA_HOME` | ❌ ไม่ตั้ง | ตั้งใน shell profile |
| Tauri CLI | ❌ ไม่มี | `cargo install tauri-cli --version "^2"` |

**สำคัญ:** `rustc` จาก Homebrew ใช้กับ mobile target ไม่ได้ — **ต้องมี rustup** เพื่อ `rustup target add`
**iOS build ต้องมี Xcode.app เต็ม** — CommandLineTools อย่างเดียวไม่พอ

> **ข้ามข้อ Xcode/Android ได้** ถ้าเริ่มจาก desktop-only ก่อน (แนะนำ)

### เฟส 1 — Desktop: macOS + Windows + Linux ⭐ เริ่มได้เลย

**สิ่งที่ทำได้ทันทีไม่ต้องรอ toolchain ข้างบน** (ใช้ GitHub Actions runner ของ Windows/Linux)

| งาน | รายละเอียด | ประมาณ |
|---|---|---|
| 1.1 Scaffold | `cargo create-tauri-app` + ตั้งค่า `tauri.conf.json` | 2 ชม. |
| 1.2 พอร์ต core | `compare.py` → `core/compare.rs` (~350 บรรทัด) | 1 วัน |
| 1.3 พอร์ต sync | `sync.py` → `core/sync.rs` (~350 บรรทัด) | 1 วัน |
| 1.4 `FsBackend` desktop | `std::fs` implement trait | 4 ชม. |
| 1.5 Commands | 15 endpoints → 15 commands + progress events | 4 ชม. |
| 1.6 ต่อ UI | `fetch()` → `invoke()` ใน `index.html` | 4 ชม. |
| 1.7 TCC / permission | macOS Full Disk Access + Windows UAC | 4 ชม. |
| 1.8 CI | GitHub Actions matrix → .dmg/.msi/.AppImage | 4 ชม. |
| 1.9 ทดสอบ | พอร์ต 58 tests → Rust + ทดสอบแอปจริง 3 OS | 1 วัน |

**ผลลัพธ์:** `.dmg` (Mac) · `.msi` (Windows) · `.AppImage`/`.deb` (Linux) — **ใช้ได้จริงทั้ง 3 OS**
**รวม: 4–6 วัน**

### เฟส 2 — Mobile: iOS + Android

| งาน | รายละเอียด | ประมาณ |
|---|---|---|
| 2.1 iOS backend | security-scoped bookmark + `NSFileCoordinator` + RAII guard | 3 วัน |
| 2.2 Android backend | SAF + `takePersistableUriPermission` + stream I/O | 3 วัน |
| 2.3 ปรับ `sync.rs` | atomic rename → stream + verify + cleanup | 1 วัน |
| 2.4 UI mobile | เปลี่ยน "browse ไดรฟ์" → "เลือก 2 โฟลเดอร์" · ซ่อนฟีเจอร์ที่ทำไม่ได้ | 3 วัน |
| 2.5 Capability gating | UI อ่าน `capabilities()` แล้วปิดปุ่มที่ไม่รองรับ | 1 วัน |
| 2.6 ทดสอบบนอุปกรณ์จริง | iPhone/iPad + Android (หลายเวอร์ชัน) | 3 วัน |
| 2.7 Background/ขนาดไฟล์ | mobile มีข้อจำกัด memory — ต้อง stream chunk | 2 วัน |

**ผลลัพธ์:** `.ipa` (iOS) · `.apk`/`.aab` (Android)
**รวม: 2–3 สัปดาห์**

> ⚠️ **ต้องเตือนล่วงหน้า:** mobile จะ **ไม่เหมือน** desktop
> - เลือกโฟลเดอร์ได้ทีละอัน ไม่ใช่ browse ทั้งไดรฟ์
> - Android ขอ `Download` ไม่ได้ → ต้องบอกผู้ใช้ให้ย้ายโฟลเดอร์
> - ลบ/ย้ายโฟลเดอร์ต้นทาง = grant หลุด ต้องขอใหม่
> - ไฟล์ใหญ่มากต้อง stream เป็น chunk

### เฟส 3 — Distribution (Store)

| แพลตฟอร์ม | ต้องมี | ค่าใช้จ่าย | หมายเหตุ |
|---|---|---|---|
| macOS (ไม่ผ่าน Store) | Developer ID + notarization | $99/ปี | แจก .dmg ตรงได้ — **แนะนำ** |
| Mac App Store | Apple Developer + sandbox | $99/ปี | sandbox บังคับ → ต้องใช้ security-scoped bookmark |
| Windows | Code signing cert | ~$100–400/ปี | ไม่ sign ได้ แต่ผู้ใช้จะเจอคำเตือน SmartScreen |
| Microsoft Store | บัญชี Partner Center | ครั้งเดียว ~$19 | ทางเลือก |
| **iOS App Store** | Apple Developer + Xcode | $99/ปี | ต้องผ่าน App Review |
| **Google Play** | บัญชี Play Console | $25 ครั้งเดียว | ⚠️ ถ้าใช้ `MANAGE_EXTERNAL_STORAGE` ต้องยื่นขออนุมัติ — **มีโอกาสถูกปฏิเสธ** |

**ความเสี่ยงสูงสุดของทั้งโปรเจกต์:** Google Play policy เรื่อง `MANAGE_EXTERNAL_STORAGE`
ถ้าไม่ผ่าน → Android ใช้ SAF เท่านั้น → จำกัดว่า "เลือกทีละโฟลเดอร์" (ซึ่งก็สอดคล้องกับแผน 2.4 อยู่แล้ว)

---

## 6. กลยุทธ์ที่แนะนำ (ลำดับความสำคัญ)

```
┌─ ขั้น 1: Desktop ให้เสร็จ (เฟส 1) ──────────────────────┐
│  • ได้คุณค่าเต็ม 100% — ตรงกับที่ผู้ใช้ต้องการจริง       │
│  • เริ่มได้เลย ไม่ต้องรอ Xcode / Android Studio          │
│  • ถ้าหยุดที่นี่ ก็ยังได้ของใช้ได้ 3 OS                  │
└──────────────────────────────────────────────────────────┘
                          ↓
┌─ ขั้น 2: ใช้จริง 2–4 สัปดาห์ → เก็บ feedback ───────────┐
│  • รู้ว่าอะไรใช้จริง อะไรไม่ใช้                          │
│  • อาจพบว่า mobile ไม่จำเป็นเลย → ประหยัด 2–3 สัปดาห์    │
└──────────────────────────────────────────────────────────┘
                          ↓
┌─ ขั้น 3: Mobile (เฟส 2) เฉพาะเมื่อมีเหตุผลชัด ──────────┐
│  • ลดขอบเขต: "เทียบ 2 โฟลเดอร์ที่เลือก" ไม่ใช่ "browse" │
│  • ยอมรับข้อจำกัด OS แทนที่จะฝ่าฝืน                      │
└──────────────────────────────────────────────────────────┘
```

**ถ้าต้องการเร็วที่สุด:** ทางเลือก B (PyInstaller) — ได้ Mac+Windows ใน 1 วัน
แต่ **mobile ปิดประตูถาวร** และไม่ได้ Linux/iOS/Android

---

## 7. ความเสี่ยงและแนวทางรับมือ

| # | ความเสี่ยง | ระดับ | แนวทางรับมือ |
|---|---|---|---|
| 1 | Google Play ปฏิเสธ `MANAGE_EXTERNAL_STORAGE` | 🔴 สูง | ออกแบบให้ใช้ SAF เป็นหลักตั้งแต่ต้น — อย่าพึ่ง permission นี้ |
| 2 | iOS หมดสิทธิ์เข้าถึงเพราะไม่ balance start/stop | 🔴 สูง | ใช้ RAII guard ใน Rust — `stop` เรียกตอน `Drop` อัตโนมัติ |
| 3 | Mobile ไม่มี atomic rename → ไฟล์เสียหายกลางทาง | 🟠 กลาง | เขียน temp + verify SHA-256 + cleanup ใน `Drop` |
| 4 | ไฟล์ใหญ่ทำ mobile แอป crash (memory) | 🟠 กลาง | stream เป็น chunk 1 MB (มีอยู่แล้วใน `hash_file`) |
| 5 | Rust learning curve ทำให้งานช้า | 🟠 กลาง | พอร์ตทีละไฟล์ + เทียบผลกับ Python ทุกขั้น (มี 58 tests เป็นตัวอ้างอิง) |
| 6 | Toolchain mobile ตั้งค่ายุ่ง | 🟡 ต่ำ | ทำ desktop ก่อน — toolchain ง่ายกว่ามาก |
| 7 | Windows build บน Mac ทำไม่ได้ | 🟢 แก้แล้ว | GitHub Actions `windows-latest` (gh login พร้อม) |
| 8 | Store review ใช้เวลา | 🟡 ต่ำ | แจก .dmg/.msi ตรงก่อน ไม่ต้องรอ Store |

---

## 8. เกณฑ์ความสำเร็จ

### เฟส 1 ถือว่าสำเร็จเมื่อ
- [ ] `cargo test` ผ่านทั้งหมด (พอร์ตจาก 58 tests)
- [ ] `.dmg` เปิดบน macOS แล้วเทียบโฟลเดอร์จริงได้
- [ ] `.msi` ติดตั้งบน Windows แล้วเทียบได้ (ทดสอบผ่าน CI artifact)
- [ ] `.AppImage` รันบน Linux ได้
- [ ] เทียบผลลัพธ์กับเวอร์ชัน Python — ต้องได้ `identical` ตรงกันทุกกรณี
- [ ] คัดลอกจริงแล้วสแกนซ้ำได้ `identical: true`
- [ ] ไฟล์ส่วนเกิน / symlink / mtime ทำงานเหมือนเวอร์ชัน Python

### เฟส 2 ถือว่าสำเร็จเมื่อ
- [ ] เลือก 2 โฟลเดอร์บน iOS ผ่าน Document Picker ได้
- [ ] bookmark เก็บไว้ → เปิดแอปใหม่ยังเข้าถึงได้
- [ ] Android เลือกโฟลเดอร์ผ่าน SAF + persist permission ได้
- [ ] เทียบโฟลเดอร์ขนาดกลาง (100+ ไฟล์) บนมือถือได้โดยไม่ crash
- [ ] UI ซ่อน/ปิดฟีเจอร์ที่แพลตฟอร์มไม่รองรับอย่างถูกต้อง
- [ ] ทดสอบบนอุปกรณ์จริงอย่างน้อย iOS 1 เครื่อง + Android 2 เวอร์ชัน

---

## 9. สิ่งที่ต้องตัดสินใจ

ก่อนเริ่มเฟส 1 ต้องตอบ 3 ข้อ:

1. **ขอบเขต:** Desktop 3 OS ก่อน แล้วค่อย mobile? หรือพยายามทั้ง 5 พร้อมกัน?
   → *แนะนำ: desktop ก่อน*

2. **ภาษา core:** Rust (Tauri) หรือเก็บ Python ไว้แล้วทำ desktop-only?
   → *แนะนำ: Rust ถ้าตั้งใจจะไป mobile จริง / Python ถ้าต้องการแค่ Mac+Windows เร็วๆ*

3. **การแจกจ่าย:** แจกไฟล์ตรง (.dmg/.msi) หรือขึ้น Store?
   → *แนะนำ: แจกตรงก่อน — ไม่ต้องรอ review และไม่มีค่าใช้จ่ายรายปี*

---

## 10. อ้างอิง

- Tauri v2 — https://v2.tauri.app/ (CLI, distribute, mobile setup)
- Tauri mobile prerequisites — https://v2.tauri.app/start/prerequisites/
- Apple — *Providing access to directories* — https://developer.apple.com/documentation/uikit/providing-access-to-directories
- Apple — *Accessing files from the macOS App Sandbox* — https://developer.apple.com/documentation/security/accessing-files-from-the-macos-app-sandbox
- Android — *Storage updates in Android 11* — https://developer.android.com/about/versions/11/privacy/storage
- Android — SAF (`ACTION_OPEN_DOCUMENT_TREE`) — developer.android.com/training/data-storage/shared/documents-files

### เอกสารในโปรเจกต์
- `README.md` — วิธีใช้เวอร์ชันปัจจุบัน
- `SKILL.md` — คู่มือ AI agent + 8 pitfalls
- `HANDOFF.md` — สถานะที่ตรวจสอบแล้วของเวอร์ชันปัจจุบัน
- `ROADMAP.md` — เอกสารนี้

---

## ภาคผนวก A — สรุป URL

**Repo เวอร์ชันนี้:** https://github.com/ProAke/fdvs

| ลิงก์ | URL |
|---|---|
| Repo | https://github.com/ProAke/fdvs |
| README | https://github.com/ProAke/fdvs/blob/master/README.md |
| ROADMAP (เอกสารนี้) | https://github.com/ProAke/fdvs/blob/master/ROADMAP.md |
| SKILL.md | https://github.com/ProAke/fdvs/blob/master/SKILL.md |
| HANDOFF.md | https://github.com/ProAke/fdvs/blob/master/HANDOFF.md |
| โค้ดเทียบ | https://github.com/ProAke/fdvs/blob/master/app/compare.py |
| โค้ดซิงค์ | https://github.com/ProAke/fdvs/blob/master/app/sync.py |
| เทสต์ | https://github.com/ProAke/fdvs/blob/master/tests/test_fdvs.py |
| Clone | `git clone https://github.com/ProAke/fdvs.git` |

**รันเวอร์ชันนี้:**
```bash
git clone https://github.com/ProAke/fdvs.git
cd fdvs
python3 -m app.server --port 4477
# → http://127.0.0.1:4477
```
