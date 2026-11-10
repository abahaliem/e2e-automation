# QA Agent — Sub-proyek 2: Pengujian Android

- **Tanggal:** 2026-11-09
- **Status:** Disetujui untuk langsung dikerjakan (pengguna memilih tanpa sesi tanya-jawab; keputusan di bawah adalah keputusan builder kecuali disebut "disepakati").
- **Dibangun di atas:** mesin `qa_agent` + dashboard sub-proyek 1. TDD.
- **Mockup acuan:** `docs/design/mockups/02-run-baru-android.html`, `02b-run-baru-android-apk.html`.

## 1. Tujuan

QA bisa menguji aplikasi Android dari dashboard yang sama dengan web: pilih HP yang tersambung lewat USB, pilih aplikasi yang sudah terpasang **atau** upload APK (dipasang otomatis), lalu agent menjelajah / menguji satu modul dengan layar live + intervensi, dan menghasilkan dokumen yang sama (Excel/HTML/PDF).

**Kriteria sukses**
1. Halaman **Perangkat** menampilkan HP/emulator yang terdeteksi `adb` (model, versi Android, status) dan petunjuk bila belum ada / belum diizinkan USB debugging / adb belum terpasang.
2. **Run baru > Android**: pilih perangkat, pilih aplikasi terpasang (daftar paket pihak ketiga, bisa dicari) atau upload `.apk` → terpasang → terpilih.
3. Explore + run modul berjalan di HP dengan mesin yang sama (AgentLoop, Guard, intervensi, laporan).
4. Layar live menampilkan layar HP (≈1–3 fps) dan kotak elemen; ambil alih (tap, ketik, tombol, swipe) bekerja.
5. Crash aplikasi dan dialog ANR/"telah berhenti" tercatat sebagai bukti teknis → test case **Fail**.
6. Semua test lama tetap lulus.

## 2. Keputusan

| Aspek | Keputusan |
|---|---|
| Kontrol perangkat (disepakati: HP fisik via USB utama, emulator opsional) | `adb` langsung via subprocess; **tidak memasang aplikasi pembantu apa pun di HP**. Emulator yang sudah berjalan otomatis terlihat sebagai perangkat adb; menyalakan emulator dari dashboard di luar cakupan. |
| Membaca layar | `uiautomator dump` → XML → `Element` (role, nama dari text/content-desc/resource-id, bbox dari bounds, `password="true"` → input_type password). |
| Aksi | `input tap/swipe/keyevent/text` (teks di-escape; karakter non-ASCII ditolak dengan pesan jelas). |
| Layar live | `adb exec-out screencap -p` beruntun di thread terpisah selama ada penonton, diubah ke JPEG lebar maks 720 px. scrcpy tidak dipakai (perlu install & decoding video, berat untuk laptop pengguna). |
| Lokasi layar | `android://<paket>/<activity>#<kunci-layar>`; kunci = hash struktur elemen interaktif, supaya aplikasi satu-activity tetap punya banyak "layar". |
| Navigasi ke layar | Driver mencatat jalur tap dari awal aplikasi ke setiap layar; `goto` = jalankan ulang aplikasi lalu putar ulang jalur. Jalur disimpan di `app_map.json` (`ScreenInfo.nav_path`) sehingga run modul bisa ke layar awal test case. |
| Sesi login | Aplikasi menyimpan sesinya sendiri; "sesi baru" = force-stop + buka aplikasi (data tidak dihapus). |
| Mode production di Android | Hanya Guard kata kunci (tidak ada filter jaringan seperti di browser); UI memberi peringatan. |
| Aplikasi di indeks | `apps.platform = "android"`, `url = android://<paket>`; domain yang diizinkan = paket. Perangkat dipilih per run (`device_serial` di opsi run); satu run per perangkat. |
| Upload APK | Disimpan di `<data>/apks/`, `adb install -r -g`; paket hasil instalasi ditentukan dari selisih daftar paket (fallback: pengguna memilih dari daftar). Maks 300 MB. |

## 3. Error handling

| Kondisi | Perilaku |
|---|---|
| adb tidak ada | API perangkat 503 dengan petunjuk pasang platform-tools; halaman Perangkat menampilkan langkahnya. |
| HP `unauthorized` | Status "Izinkan USB debugging di HP" di daftar perangkat. |
| HP dicabut di tengah run | Driver crash → run Terhenti, laporan parsial, bisa dilanjutkan. |
| `uiautomator dump` gagal (animasi) | Coba ulang 2× dengan jeda; tetap gagal → observasi tanpa elemen + sinyal. |
| Aplikasi crash / ANR | Sinyal `page_error` "Aplikasi tertutup/berhenti" + ringkasan logcat crash → Fail. |
| Teks non-ASCII untuk diketik | Aksi gagal dengan pesan "adb input text tidak mendukung karakter ini". |

## 4. Testing

FakeAdb (respons terskrip) untuk unit test adb, parser UI, driver, guard, explorer dengan putar-ulang jalur, API perangkat, RunManager android; Vitest untuk tab Android di Run baru dan halaman Perangkat. Uji dengan HP sungguhan dilakukan manual oleh pengguna (butuh adb terpasang).

## 5. Di luar cakupan

Menyalakan/membuat emulator dari dashboard, scrcpy, iOS, WebView di dalam aplikasi (diperlakukan seperti elemen native seadanya), input teks non-ASCII (butuh keyboard khusus di HP).
