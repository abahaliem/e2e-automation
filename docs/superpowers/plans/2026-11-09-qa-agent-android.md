# QA Agent Android Implementation Plan

> Native + TDD. Spec: `docs/superpowers/specs/2026-11-09-qa-agent-android-design.md`.

**Goal:** Pengujian aplikasi Android (HP via USB / emulator) dari dashboard yang sama dengan web.

## Global Constraints
- Tidak memasang apa pun di HP selain APK yang diupload pengguna.
- Semua test memakai FakeAdb; tidak ada test yang butuh HP sungguhan.
- Teks UI Bahasa Indonesia, tanpa em dash. 308 test Python + 69 test frontend lama tetap lulus.
- Commit diakhiri `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Tasks
1. **Adb wrapper** (`qa_agent/drivers/adb.py`): `Adb(serial, adb_path, run)`; `devices()`, `shell`, `exec_out`, `packages(third_party)`, `install(apk)`, `launch(pkg)`, `force_stop`, `screencap`, `dump_ui`, `tap`, `swipe`, `text`, `keyevent`, `screen_size`, `current_activity`, `pidof`, `crash_log`; `find_adb()`; `AdbError`, `AdbNotFound`. Test: parsing `devices -l`, `wm size`, `dumpsys window`, escaping teks, install error.
2. **Parser UI** (`qa_agent/drivers/android_dom.py`): `parse_ui(xml, max_elements) -> list[Element]`, `screen_key(elements)`. Test: role/nama/bbox/password/visibility/limit.
3. **AndroidDriver** (`qa_agent/drivers/android.py`): Driver protocol + `manual_input`, `viewport_size`, frame sink/streaming thread, jalur navigasi (`path_to`, `register_paths`), sinyal crash/ANR. Test dengan FakeAdb.
4. **Mesin**: `TargetCfg.platform` + url `android://`, Guard skema `android`, `ScreenInfo.nav_path`, Explorer menyimpan jalur, prompt catatan Android, `build_runtime` memilih driver, platform diteruskan ke AgentLoop. Test.
5. **Server**: endpoint `/api/devices`, `/api/devices/{serial}/packages`, `/api/devices/{serial}/install`; AppIn platform android; `RunRequest.device_serial`; RunManager membangun config android + satu run per perangkat + `register_paths` untuk deep. Test.
6. **Frontend**: tipe/api perangkat, halaman Perangkat, tab Android di Run baru (perangkat, aplikasi terpasang / upload APK), LiveView potret. Vitest.
7. **Dokumentasi + verifikasi**: README bagian Android, semua test lulus, update Notion.
