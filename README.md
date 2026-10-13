# WebGIS Makam Keputih

Proyek lokal untuk tiga blok makam TPU Keputih. FastAPI + Leaflet, SQLite untuk memulai di laptop, PostgreSQL/PostGIS untuk hosting. Tidak ada polygon, identitas, atau foto palsu pada database awal.

## Menjalankan di Windows

Instal Python 3.12. Ekstrak ZIP dan buka terminal pada folder proyek.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\setup_admin.py
.venv\Scripts\python.exe scripts\run.py
```

Buka http://127.0.0.1:8000. Biarkan terminal tetap berjalan. Tutup dengan Ctrl+C. Jika `py` tidak tersedia, gunakan `python`. Leaflet 1.9.4 dan Esri Leaflet 3.0.19 disertakan dalam ZIP. Jika aset Leaflet hilang, jalankan `python scripts/vendor_leaflet.py`. Untuk memulihkan Esri Leaflet, salin kembali `app/static/vendor/esri-leaflet.js` dari ZIP.

## Memasukkan tiga blok sebenarnya

1. Periksa polygon, tentukan ID unik permanen, dan simpan salinan sumber GIS.
2. Ekspor batas blok dan polygon makam ke GeoJSON WGS84 EPSG:4326. Data UTM EPSG:32749 harus direproyeksi, bukan sekadar mengganti label CRS. Shapefile/GeoPackage tidak langsung diimpor pada versi ini.
3. Batas blok memiliki properti `id`, `name`. Polygon makam memiliki `id`, `block_id`. Alias `ID_Blok`, `Nama_Blok`, `ID_Makam`, `id_makam`, dan `BLOK` juga diterima. File makam milik pengguna dapat memakai `id_makam=A-015` dan `BLOK=A` tanpa mengganti nama kolom. Batas blok harus memakai ID A, B, C yang sama dengan kode BLOK pada data makam. ID pada tingkat Feature dan FID tidak dipakai sebagai ID makam.
4. Login admin, impor batas blok dahulu, lalu makam. ID yang sudah ada ditolak agar data atribut tidak tertimpa. Seluruh impor dibatalkan jika ada satu fitur tidak valid.
5. Buka makam dari peta/tabel, lalu Edit data untuk mengisi nama, tanggal, nomor, verifikasi, dan foto.

Impor geometri awal hanya memasukkan lokasi dan hubungan blok. Atribut hasil survei dimasukkan melalui formulir atau CSV. Geometri harus valid dan berada di sekitar Surabaya, dengan titik representatif makam di dalam blok yang dipilih.

## Pengisian hasil survei November

Unduh tabel saat ini melalui admin untuk memperoleh ID. Format CSV UTF-8:

```csv
id,name,death_date,row,number,verified
```

Tanggal memakai YYYY-MM-DD. `verified` memakai true/false. Kolom kosong mempertahankan data lama. Pengosongan atribut hanya melalui formulir Edit data. Unggah CSV, periksa pratinjau, kemudian Simpan perubahan. Sistem menolak ID ganda, ID tidak dikenal, tanggal tidak valid, dan data yang berubah sejak pratinjau. Maksimum 10.000 baris per impor, 20 MB per file.

Kelengkapan membutuhkan nama, tanggal wafat, blok, dan satu foto. Verifikasi terpisah dari kelengkapan. Nama dan tanggal yang belum diketahui tidak dibuat-buat. Kepadatan menggunakan jumlah makam / luas blok, ditampilkan per 1.000 m². Luas blok dihitung dengan UTM 49S. Statistik mencakup seluruh data, sementara tabel dan peta mengikuti filter.

## Foto udara ECW dan GeoTIFF, versi 3

Halaman admin menyediakan unggah raster sampai 6 GiB (6.442.450.944 byte), status pengolahan, pengaturan zoom, pemotongan cakupan, dan pemasangan hasil sebagai basemap. Batas yang ditampilkan sebagai 6 GB berlaku untuk GeoTIFF dan ECW. File TIFF 4,7 GB berada di bawah batas ini. Browser memberi waktu hingga empat jam untuk unggahan. Pemroses menghasilkan tile PNG XYZ melalui Rasterio atau GDAL Python yang dikonfigurasi dengan `RASTER_PYTHON`.

Untuk hosting, gunakan batas request 6600 MB dari `deploy/Caddyfile.example` agar file maksimum beserta multipart dapat diterima. Unggahan memakai file sementara sebelum disalin ke folder sumber. Untuk file 4,7 GiB, sediakan sekitar 9,4 GiB bagi kedua salinan, serta ruang untuk tile dan data yang sudah ada. Pada ukuran maksimum 6 GiB, dua salinan dapat memakai sekitar 12 GiB. Lokasi sementara sistem atau container juga harus memiliki ruang yang cukup.

Frontend membaca batas unggahan dari backend, sehingga tampilan dan validasi mengikuti batas server. Halaman dan JavaScript memakai kebijakan tanpa cache, dan URL JavaScript diberi versi. Untuk memasang pembaruan dan mengatasi tampilan batas lama, ikuti [UPGRADE_V7.txt](UPGRADE_V7.txt). Backend versi ini memberikan `version: "7.0.0"` dan `raster_upload.label: "6 GB"` pada `/api/config`.

Ikuti [PANDUAN_CITRA_UDARA.md](PANDUAN_CITRA_UDARA.md) untuk memperbarui proyek dan memeriksa driver ECW. Instalasi pip default mendukung GeoTIFF. ECW membutuhkan GDAL dengan driver ECW yang tersedia pada lingkungan pemroses. Browser menerima tile hasil pengolahan.

Citra yang aktif tersimpan melalui `data/imagery/current.json`. Tile berada pada `data/tiles/imagery`. Basemap sebelumnya tetap aktif hingga pekerjaan baru selesai. Seluruh folder `data` perlu dicadangkan.

URL tile manual melalui `ORTHOPHOTO_TILE_URL` tetap diterima jika belum ada hasil raster yang aktif. Basemap otomatis dari unggahan memiliki prioritas di atas konfigurasi manual.

## Menu header, Beranda, dan Tabel Infografis, versi 7

Header memiliki menu Beranda, Peta, Data makam, Statistik, serta Tentang. Tombol Tabel Infografis hanya berada pada Beranda. Statistik pada header mempertahankan ringkasan pendataan dari HTML pengguna, sementara Tabel Infografis membuka halaman grafik tersendiri.

Beranda memakai area sambutan ungu dengan tombol Peta, Tabel Infografis, serta Tentang, dan pratinjau peta di sisi kanan. Halaman ini menjadi halaman awal. Sidebar Temukan makam muncul pada Peta serta Data makam, sementara halaman lainnya memakai lebar penuh. Tombol Lihat data makam pada halaman infografis membuka daftar individual.

Infografis memakai respons `/api/statistik`: jumlah makam per blok, kelengkapan, verifikasi, distribusi tahun wafat, serta tabel ringkasan per blok. Angka, grafik, dan tabel mencakup seluruh database. Kategori tahun Belum diketahui tetap dihitung. Tidak ada data contoh yang dimasukkan pada database awal. Kondisi kosong ditampilkan jika data belum diimpor.

Ringkasan diperbarui setelah impor atau penyuntingan admin, dan dimuat ulang ketika membuka Beranda, Statistik, atau Tabel Infografis. Pratinjau peta memakai basemap aktif dan batas blok yang sudah diimpor. Ketika membuka Peta setelah Beranda, ukuran peta dihitung ulang sebelum cakupan data ditampilkan.

Untuk mengubah tampilan, edit `app/static/index.html`, `app/static/style.css`, serta `app/static/app.js`. Renderer grafik berada pada `app/static/infographics.js`. Ketiga file frontend memakai indentasi dan komentar per bagian. Teks pengguna pada HTML tetap dipertahankan. Status unggahan dinamis berada pada elemen terpisah dari pesan pribadi. Warna makam serta simbol per blok mengikuti `blockOutlines` di app.js. Footer kosong untuk informasi kontak berada setelah main pada index.html. Ikuti [UPGRADE_V7.txt](UPGRADE_V7.txt) untuk memasang pembaruan, termasuk file JavaScript baru.

## Tampilan makam, logo, dan citra satelit, versi 5

Polygon makam memiliki bagian dalam transparan dengan outline berwarna: Blok A merah, Blok B biru, dan Blok C kuning. Warna blok memakai kode ID A/B/C, sehingga tidak berubah mengikuti urutan impor. Simbol legenda juga transparan di bagian dalam. Makam yang dipilih memakai outline lebih tebal dan tetap dapat diklik dari bagian dalam polygon.

Logo UNESA dari SVG yang diberikan menjadi logo header dan favicon. Basemap **Satelit · Esri World Imagery** langsung aktif ketika belum ada foto udara yang dipasang. Pilihan ini memakai tile citra dari layanan publik World Imagery. Implementasi ini tidak membutuhkan API key. Koneksi internet diperlukan. OpenStreetMap juga tersedia di kontrol layer kanan atas.

Esri Leaflet 3.0.19 menyediakan layer citra dan atribusi penyedia yang mengikuti cakupan serta zoom peta. Library disertakan di `app/static/vendor` bersama lisensi Apache 2.0. World Imagery merupakan gabungan citra satelit dan foto udara dengan detail berbeda antarwilayah. Sumber resmi: https://www.esri.com/arcgis-blog/products/imagery/imagery/learning-more-about-the-world-imagery-basemap. Ketentuan layanan tersedia pada https://www.arcgis.com/home/item.html?id=10df2279f9684e4a9f6a7f08febac2a9. Aplikasi mengambil tile untuk tampilan online langsung dari penyedia.

Zoom peta sampai 23 memakai tile native maksimum 19 agar citra tetap tampil pada zoom dekat. Memperbesar tile tidak menambah resolusi asli. Foto udara ECW/GeoTIFF milik proyek tetap bisa diproses dan dipakai sebagai pilihan **Foto udara**, dengan citra satelit sebagai konteks di luar cakupannya. Basemap hasil unggahan otomatis aktif setelah pemrosesan selesai.

Tombol admin dengan label 0000 tetap terlihat dan dapat diklik saat website dipublikasikan. Membuka formulir login tidak memberi hak admin. Kata sandi yang benar tetap diperlukan untuk mengunggah, mengimpor, atau mengubah data.

## Database

Lokal: `data/makam.db`, foto: `data/photos`. Data tetap tersimpan setelah aplikasi ditutup. PostgreSQL: isi `DATABASE_URL` dengan driver `postgresql+psycopg`. Startup membuat tabel, extension PostGIS, kolom geometri native, indeks spasial, dan trigger sinkronisasi GeoJSON. Akun bootstrap database harus memiliki izin membuat extension. Setelah bootstrap produksi, sesuaikan hak akun jika memakai akun terpisah.

Database SQLite tidak otomatis dipindahkan saat mengganti DATABASE_URL. Pilihan sederhana adalah impor ulang sumber geometri dan atribut, kemudian salin/unggah foto dengan hubungan ID yang sama. Uji di staging sebelum perpindahan produksi. Untuk data yang sudah banyak, gunakan migrasi database terencana termasuk tabel photos dan audit.

## Deployment domain .com

Template deployment disediakan, belum dijalankan di VPS. Setelah versi lokal dan data diuji:

1. Siapkan VPS Linux, domain, Docker Compose, serta Caddy dari sumber resmi.
2. Jalankan `scripts/setup_admin.py` untuk membuat `.env`. Jangan bagikan `.env`, database, atau folder foto dalam paket kode publik.
3. Jalankan `docker compose up -d --build`. Database PostGIS berada di jaringan internal. Aplikasi hanya membuka port 8000 pada localhost server. Compose memakai volume persisten untuk database dan media.
4. Arahkan A record domain ke IPv4 VPS. Tambahkan AAAA hanya jika IPv6 server bekerja. Buka port 80 dan 443.
5. Pasang Caddy pada host, ganti domain di `deploy/Caddyfile.example`, lalu gunakan konfigurasi tersebut. Caddy mengelola HTTPS dan meneruskan permintaan ke localhost:8000. COOKIE_SECURE=true pada Compose sehingga admin membutuhkan HTTPS.
6. Uji pencarian, foto, admin, CSV, statistik, dan restart server melalui domain.

Satu proses backend digunakan pada versi awal karena sesi login dan pratinjau impor berada di memori. Restart server mengharuskan admin login ulang dan membuat ulang pratinjau. Jangan menambah beberapa worker/replica sebelum sesi dan pratinjau dipindahkan ke penyimpanan bersama. Pengguna umum tidak memerlukan login.

## Cadangan dan pembaruan

Lokal: matikan aplikasi, lalu salin folder `data` dan simpan `.env` secara terpisah dengan akses terbatas. Hosting: buat dump PostgreSQL dan cadangan volume media sebelum impor besar. Uji pemulihan ke lingkungan terpisah. Ekspor CSV bukan cadangan lengkap karena tidak mencakup geometri, foto, dan audit.

Pembaruan atribut/foto setiap 2–3 bulan dilakukan melalui admin tanpa deploy ulang. Perubahan kode memerlukan deploy ulang. Koreksi geometri yang sudah ada belum memiliki editor pada versi awal, lakukan melalui GIS dan migrasi terkontrol yang mempertahankan ID. Akun saat ini satu admin, belum mendukung banyak akun atau peran.

## Pengujian

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
node tests/test_frontend.cjs
```

Tes memakai database temporer, geometri sintetis, dan GeoTIFF uji yang tidak dimasukkan ke database aplikasi. Pengujian mencakup autentikasi, impor atomik, filter, CSV, foto, statistik, pemrosesan tile, dan penggantian basemap. Versi 7 lulus 22 tes backend serta pemeriksaan frontend untuk menu header, halaman Statistik terpisah, akses infografis dari Beranda, teks admin, visibilitas sidebar, resize peta, grafik kosong/berisi, tahun yang belum diketahui, pemuatan ulang statistik, dan urutan respons. Node.js hanya diperlukan untuk menjalankan pemeriksaan frontend, bukan untuk menjalankan WebGIS.

## Konteks proyek

Acuan proposal: Pengembangan WebGIS untuk Inventarisasi dan Analisis Spasial Makam di Taman Makam Keputih Surabaya. Perkembangan terbaru: digitasi Mask R-CNN untuk tiga blok selesai menurut pengguna. Pengumpulan identitas dan foto direncanakan November 2026. Domain .com dan hosting belum dibeli/dikonfigurasi dalam paket ini.

Chat referensi: https://chatgpt.com/s/t_6abdb4bf02548191a70b1492cc501654

Verifikasi versi 7: tes API/pemrosesan lokal, pemeriksaan sintaks JavaScript, serta pemeriksaan logika frontend dilakukan. Tampilan browser belum diverifikasi secara visual; pemeriksaan frontend menggunakan DOM simulasi. PostgreSQL/PostGIS, Docker, dan domain belum diuji pada server nyata.
