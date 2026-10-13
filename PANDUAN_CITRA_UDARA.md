# Basemap Foto Udara ECW dan GeoTIFF, Versi 7

## Fitur yang ditambahkan

- Unggah ECW dan GeoTIFF melalui halaman admin, maksimum 6 GiB (6.442.450.944 byte), ditampilkan sebagai 6 GB. TIFF berukuran 4,7 GB berada di bawah batas ini.
- Waktu unggah pada browser hingga empat jam, kemudian pengolahan tile berjalan di latar belakang.
- Batas ukuran dan timeout berasal dari backend. Frontend mendeteksi server lama yang belum memiliki konfigurasi unggahan baru.
- Halaman dan JavaScript menggunakan kebijakan tanpa cache. URL JavaScript memiliki versi untuk memuat kode terbaru setelah pembaruan.
- Progres unggahan, pengolahan tile, dan hasil pekerjaan.
- Pengolahan berjalan pada proses terpisah. Pencarian dan peta tetap dapat digunakan.
- Pemeriksaan ketersediaan driver sebelum mengunggah ECW yang besar.
- Pemotongan cakupan ke batas tiga blok dengan konteks sekitar 100 meter, atau pilihan seluruh citra.
- Tile PNG transparan dengan indeks XYZ dan koordinat EPSG:3857.
- Zoom akhir dibatasi oleh resolusi asli citra dan maksimum 20.000 tile per pekerjaan.
- Foto udara otomatis menjadi basemap setelah seluruh tile selesai. Peta dasar umum tersedia pada kontrol layer dan sebagai konteks di luar cakupan foto.
- Basemap lama tetap digunakan selama proses baru berjalan. Kegagalan konversi tidak menghapus tile basemap lama.
- Metadata basemap serta status pekerjaan tersimpan di disk dan dapat dibaca setelah aplikasi dibuka kembali.

## 1. Memperbarui proyek lama

1. Hentikan server dengan **Ctrl+C**.
2. Ekstrak `WebGIS_Header_Rapi_v7.zip`. Salin isi folder `webgis-makam` ke folder proyek lama yang digunakan untuk menjalankan server dan setujui penggantian file kode. Folder tujuan harus memiliki `app/main.py` dan `scripts/run.py` langsung di dalamnya.
3. Pertahankan `.env`, folder `.venv`, dan folder `data` yang sudah ada. ZIP tidak berisi kata sandi atau database sehingga tidak mengganti ketiganya.
4. Pada terminal di folder proyek, jalankan:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe scripts\check_raster.py
.venv\Scripts\python.exe scripts\run.py
```

5. Pastikan terminal menunjukkan **WebGIS v7.0.0. Batas unggahan raster: 6 GB.** serta folder proyek yang benar.
6. Buka `http://127.0.0.1:8000/?v=7-nav` dan tekan **Ctrl+F5** agar JavaScript dan tampilan baru dimuat.
7. Buka `http://127.0.0.1:8000/api/config`. Nilai `version` harus `7.0.0` dan `raster_upload.label` harus `6 GB`. Jika field ini tidak ada, server masih menjalankan kode lama. Hentikan server, periksa folder pada terminal, dan jalankan ulang dari folder yang sudah diperbarui.
8. Klik tombol 0000, login dengan kata sandi admin, dan buka bagian **Basemap foto udara**. Tampilan harus menunjukkan batas 6 GB. Jika konfigurasi API sudah benar tetapi tampilan masih lama, muat URL baru pada langkah 6.

Untuk pemasangan pertama kali, ikuti pembuatan `.venv` dan konfigurasi admin pada README. Jangan menjalankan konfigurasi kata sandi kembali hanya untuk memasang pembaruan ini.

## 2. Pembaca ECW

ECW memerlukan driver ECW pada GDAL. Instalasi Rasterio dari pip menyediakan pembaca GeoTIFF, tetapi tidak menjamin tersedianya driver ECW.

Aplikasi mendukung dua lingkungan pembaca:

| Lingkungan | Cara penggunaan |
|---|---|
| Python aplikasi dengan Rasterio | Default. GeoTIFF langsung dapat diproses setelah requirements terpasang |
| Python terpisah dengan `osgeo.gdal` dan driver ECW | Diatur melalui `RASTER_PYTHON`, digunakan untuk membaca ECW dan menghasilkan tile |

Jika sudah memiliki lingkungan GDAL yang dapat membaca ECW, isi `.env` dengan lokasi Python lingkungan tersebut. Contoh berikut hanya menunjukkan format lokasi, bukan jaminan bahwa instalasi itu memiliki driver ECW:

```env
RASTER_PYTHON=C:\OSGeo4W\bin\python3.exe
```

Lalu jalankan ulang:

```powershell
.venv\Scripts\python.exe scripts\check_raster.py
```

Hasil yang diperlukan untuk ECW adalah **ECW: siap**. Jika program memerlukan pengaturan PATH/DLL dari distribusi GDAL, jalankan server melalui shell distribusi tersebut dan ulangi pemeriksaan. Menunjuk lokasi Python saja tidak memasang driver ECW.

Jika ECW belum siap, ada dua cara melanjutkan:

1. Lengkapi lingkungan GDAL yang memiliki driver ECW, lalu periksa kembali.
2. Buka ECW pada GIS yang sudah bisa membacanya, ekspor ke GeoTIFF RGB 8-bit dengan georeferensi, kemudian unggah GeoTIFF tersebut. Potong ke tiga blok agar hasil ekspor berada di bawah batas unggahan.

Gunakan sistem koordinat dan georeferensi asli yang benar pada raster. Pemroses mengubahnya ke EPSG:3857 secara otomatis. Ketentuan EPSG:4326 untuk importer GeoJSON tidak berarti raster wajib diekspor ke EPSG:4326.

## 3. Mengunggah citra

1. Login admin.
2. Pilih `.ecw`, `.tif`, atau `.tiff`.
3. Untuk awal, gunakan zoom 14–21. Pemroses menurunkan zoom akhir bila resolusi asli lebih rendah. Zoom 23 bukan jaminan citra lebih detail.
4. Pilih **Tiga blok dan area sekitar** jika batas blok sudah diimpor. Jika belum, impor batas terlebih dahulu atau pilih **Seluruh citra**.
5. Klik **Unggah dan jadikan basemap**.
6. Progres unggahan akan mencapai 100%, kemudian progres pengolahan dimulai. Keduanya adalah tahap berbeda.
7. Tunggu pesan **Foto udara siap dan sudah menjadi basemap**.
8. Buka Peta. Foto udara otomatis aktif, sedangkan polygon makam tetap berada di atasnya.

File kosong, format yang tidak dapat dibaca, raster tanpa CRS, citra yang tidak beririsan dengan cakupan blok, dan pekerjaan di atas 20.000 tile ditolak. Geotag foto biasa tidak cukup menggantikan georeferensi raster.

Data tampilan yang diterima adalah raster Byte/8-bit grayscale, RGB, atau RGB dengan alpha, dengan 1, 3, atau 4 band. Untuk raster multispektral/16-bit, buat komposit RGB 8-bit terlebih dahulu di GIS.

Satu citra diproses pada satu waktu. Selama pemrosesan, basemap lama tetap aktif. Pengunjung umum memperoleh basemap baru ketika memuat ulang halaman. Halaman admin memeriksa status dan mengaktifkan hasil baru tanpa harus restart server.

## 4. Penyimpanan

| Lokasi | Isi |
|---|---|
| `data/imagery/jobs/<id>/source.ecw` atau `source.tif` | File raster sumber, tidak disajikan ke pengunjung |
| `data/imagery/jobs/<id>/job.json` | Status dan konfigurasi pekerjaan |
| `data/imagery/jobs/<id>/worker.log` | Detail kesalahan pemroses |
| `data/imagery/current.json` | Metadata basemap yang aktif |
| `data/tiles/imagery/<id>/<z>/<x>/<y>.png` | Tile yang dilihat browser |

Unggahan besar disimpan sementara oleh parser HTTP, lalu disalin ke folder sumber secara bertahap per 1 MiB. Untuk file 4,7 GiB, ruang sementara dan sumber dapat memakai hingga sekitar 9,4 GiB secara bersamaan. Pada batas file 6 GiB, sediakan sekitar 12 GiB bagi kedua salinan. Pastikan lokasi sementara sistem atau container dan lokasi `data` memiliki ruang yang cukup. Angka ini belum mencakup tile, database, foto, atau versi citra lama.

Ukuran tile dapat melebihi ukuran ECW. Pemroses memperkirakan kebutuhan ruang sebelum membuat tile. Sumber dan versi tile sebelumnya dipertahankan, sehingga kebutuhan ruang bertambah jika citra diperbarui berkali-kali. Buat cadangan sebelum membersihkan versi lama dan jangan menghapus folder tile yang dirujuk `current.json`.

## 5. Deployment

- Caddyfile pembaruan kapasitas memakai batas request 6600 MB untuk menampung file sampai 6 GiB beserta multipart. Ganti konfigurasi Caddy yang aktif dengan nilai baru dan muat ulang konfigurasi tersebut.
- Sesuaikan batas request, timeout, dan disk pada setiap proxy/hosting yang dipakai. Batas di aplikasi tidak menggantikan batas layanan hosting. Browser menunggu hingga empat jam untuk unggahan, sehingga proxy tidak boleh menghentikan unggahan lebih awal.
- Dockerfile perlu dibangun ulang karena requirements menambahkan Rasterio.
- Image Docker default mendukung jalur GeoTIFF melalui Rasterio. Driver ECW belum disertakan otomatis dalam image.
- Pilihan praktis adalah mengolah ECW di laptop yang memiliki pembacanya, lalu menyalin `data/imagery/current.json` dan folder tile yang dirujuknya ke volume media server. ECW sumber tidak perlu dibaca kembali oleh server untuk menampilkan basemap.
- Pemrosesan langsung ECW di server memerlukan lingkungan pembaca ECW yang sesuai pada server tersebut.
- Pertahankan konfigurasi satu proses backend pada versi ini.

## 6. Endpoint baru

| Endpoint | Fungsi |
|---|---|
| `POST /api/admin/imagery/upload` | Menerima raster dan memulai pekerjaan |
| `GET /api/admin/imagery/status` | Memeriksa pembaca, progres, dan basemap aktif |
| `GET /api/config` | Memberikan URL tile dan metadata basemap untuk frontend |
| `GET /tiles/imagery/<id>/<z>/<x>/<y>.png` | Menyediakan satu tile PNG |

Unggah membutuhkan sesi admin dan token CSRF. Halaman publik tidak memiliki akses unggah.

## 7. Pengujian yang sudah dilakukan

Pada versi 7, 22 tes backend/pemrosesan dan pemeriksaan logika frontend lulus. Cakupan backend meliputi konversi raster GeoTIFF nyata menjadi PNG XYZ, transparansi tepi, status persisten, proses terpisah, penyajian tile melalui HTTP, autentikasi, batas unggahan, konfigurasi batas dari backend, kebijakan tanpa cache, dan penggantian basemap yang gagal. Pemeriksaan frontend mencakup navigasi Beranda, sidebar, resize peta, grafik dan tabel dari statistik, serta pemuatan ulang data.

Pembaruan kapasitas memeriksa preflight request berukuran besar melalui header, penerimaan batas file yang tepat, penolakan file di atas batas, serta pembersihan sumber parsial. Pemeriksaan frontend memverifikasi file berukuran 4,7 GiB dan 6 GiB diteruskan ke unggahan, 6 GiB + 1 byte ditolak, dan timeout empat jam digunakan. Frontend juga mendeteksi backend lama yang belum menyediakan konfigurasi batas. Uji rutin ini memakai ukuran/header simulasi dan badan file kecil.

Uji HTTP penuh terpisah berhasil mengirim BigTIFF sintetis berukuran 4,7 GiB (5.046.586.573 byte) ke server Uvicorn lokal. Server mengembalikan HTTP 202, menyimpan seluruh byte dengan ukuran yang cocok, menyelesaikan pengolahan menjadi basemap, dan menyajikan tile PNG melalui HTTP 200. Transfer dan penyalinan sumber selesai dalam sekitar 15,2 detik pada lingkungan pengujian ini. File tersebut memiliki raster RGB kecil dengan padding nol, sehingga uji ini memeriksa transfer file besar dan jalur BigTIFF. Uji ini tidak mengukur waktu pengolahan raster asli 4,7 GB milik pengguna. Caddy dan hosting produksi belum diuji.

File ECW sekitar 400 MB milik pengguna belum diuji karena belum tersedia di proyek. Lingkungan pengujian memiliki Rasterio dengan dukungan GeoTIFF, tanpa driver ECW. Jalur `osgeo.gdal` dengan driver ECW perlu diuji pada komputer yang memiliki pembaca tersebut. Tampilan browser dan deployment VPS belum diverifikasi pada versi ini.

## Dokumentasi resmi

- [GDAL ECW](https://gdal.org/en/stable/drivers/raster/ecw.html)
- [Rasterio WarpedVRT](https://rasterio.readthedocs.io/en/stable/topics/virtual-warping.html)
- [Leaflet TileLayer](https://leafletjs.com/reference.html#tilelayer)
