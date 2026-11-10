# QA Agent — Skrip regresi tanpa AI & Data uji

- **Tanggal:** 2026-11-10
- **Permintaan pengguna:** kerjakan peningkatan #1 (rekam jadi skrip regresi tanpa AI) lalu #2 (data uji & persiapan kondisi).
- **Masalah nyata (WFM Biznet):** regresi lambat dan hasilnya berubah-ubah karena setiap langkah memanggil AI. Test case juga Blocked karena data/kondisi tidak tersedia (WO hanya bisa ditutup sekali, form lembur hanya muncul setelah 9 jam kerja).

## 1. Skrip regresi tanpa AI

**Rekam.** Setiap kali test case selesai **Pass** (oleh AI, atau diakhiri QA "Akhiri: Pass"), langkah yang benar-benar dijalankan disimpan sebagai skrip di `scripts.json` folder run. Isinya:
- Aksi: klik / ketik / pilih / gulir / kembali / tunggu / navigasi, dengan pengenal elemen (role, nama, selector) dan nilai.
- Input manual QA saat Ambil alih.

**Keamanan nilai.** Password asli tidak pernah masuk skrip. Nilai yang sama dengan rahasia akun diganti `{{password}}`. AI memang tidak pernah melihat password asli; penggantian ini terutama untuk ketikan manual QA.

**Pemeriksaan akhir.** Skrip menyimpan teks penanda layar akhir: teks yang muncul di layar akhir tetapi tidak ada di layar awal. Teks yang berisi angka panjang (tanggal, jam) dibuang. Bila tidak ada teks penanda, yang dipakai adalah lokasi layar akhir.

**Putar ulang.** "Ulang dengan test case sama" memakai skrip run sumber secara default ("Putar ulang skrip rekaman tanpa AI").
- Langkah dijalankan langsung lewat driver, tanpa AI.
- Safety Guard dan mode production tetap berlaku.
- Jeda dan Hentikan tetap berlaku.
- Screenshot setiap langkah tetap disimpan sebagai evidence, dengan pelaku "skrip".

**Hasil putar ulang:**
- Semua langkah berhasil dan penanda akhir terpenuhi (≥60% teks) → **Pass**. Catatan: "Dijalankan dari skrip rekaman (tanpa AI)".
- Ada error server/aplikasi (HTTP 5xx, crash, error JavaScript) → **Fail**, seperti aturan biasa.
- Elemen tidak ditemukan atau penanda akhir tidak cocok → **perbaikan oleh AI (self-healing, default aktif)**. AI melanjutkan test case dari layar saat itu dengan catatan langkah skrip yang gagal. Bila AI berhasil, skrip baru direkam dan catatan menyebut "skrip diperbaiki AI". Bila self-healing dimatikan → **Perlu Review** dengan alasan langkah yang gagal.

**Bukan tujuan:** ekspor ke Playwright/Maestro (bisa menyusul) dan menyunting skrip langkah demi langkah di UI.

## 2. Data uji & persiapan kondisi

**Data uji per aplikasi.**
- Disimpan di menu Aplikasi, kartu "Data uji". Bentuknya kumpulan bernama berisi daftar nilai, misalnya `wo_id`: 000090014541, 000090014542.
- Setiap nilai berstatus *tersedia* atau *terpakai* (beserta run/test case pemakainya), dan bisa dikembalikan ke *tersedia*.
- Dipakai dengan penanda `{{data:wo_id}}` di langkah, test data, atau pre-condition test case, juga di tulisan alur bisnis.
- Saat test case mulai, setiap penanda diganti nilai tersedia berikutnya, lalu nilai itu ditandai terpakai. Test case dan laporan menampilkan nilai yang benar-benar dipakai.
- Penanda yang sama dalam satu test case memakai nilai yang sama.
- Nilai data uji bukan rahasia; AI boleh melihatnya untuk memilih kartu WO yang tepat.
- Bila nilai habis, test case **Blocked** dengan pesan "Data uji 'wo_id' habis. Tambahkan di Aplikasi > Data uji".
- AI menyusun test case dengan mengetahui nama kumpulan data yang ada beserta contohnya, supaya ia memakai penanda alih-alih mengarang data.

**Persiapan (HTTP) per aplikasi**, opsional.
- Isinya permintaan HTTP: method, URL, header, dan body JSON. Penanda `{{data:...}}` boleh dipakai di dalamnya.
- Dijalankan **sebelum run** atau **sebelum setiap test case**.
- Hasil JSON bisa disimpan ke kumpulan data lewat path bertitik, misalnya `data.id` → `wo_id`. Contoh: endpoint internal yang membuat WO baru, lalu id-nya langsung dipakai test case.
- Gagal (status bukan 2xx) → run dijeda dengan pesan jelas.
- Header berisi token sebaiknya memakai `{{secret:nama}}`. Nilainya disimpan di penyimpanan rahasia, tidak di database.
- Dapat dimatikan per run.

## Pengujian
- Unit: rekam trace di loop, pembuatan skrip (redaksi password, penanda akhir), pemutar skrip (berhasil / elemen hilang / penanda tidak cocok / Guard), DeepRunner (putar ulang, self-heal, rekam ulang).
- Data uji: alokasi nilai, habis → Blocked, penggantian penanda.
- Persiapan HTTP: tangkap nilai ke data, gagal → jeda.
- Server: API data uji & persiapan; run regresi memakai skrip run sumber.
- Vitest: pilihan putar ulang di Run baru; kartu Data uji & Persiapan di Aplikasi.
