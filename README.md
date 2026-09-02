# TikTok Scraper (Video & Comments) - Local Selenium

Tool scraping TikTok berbasis Python, Selenium, dan `undetected-chromedriver` dengan teknik XHR/Fetch API Interception untuk mengekstraksi metadata video dan komentar secara lengkap, baik dalam mode login (QR Code) maupun tanpa login (Guest Mode).

## 🚀 Fitur Utama

- **Otomatis Deteksi Chrome & ChromeDriver**: Mencari binary Chrome & ChromeDriver lokal di folder project atau direktori di atasnya.
- **XHR / Fetch Interception**: Mengambil data langsung dari respons API internal TikTok (bebas batasan rendering DOM).
- **Pilihan Metode Login**:
  - **Login via QR Code**: Scan melalui aplikasi TikTok HP untuk scraping data lebih banyak.
  - **Tanpa Login (Guest Mode)**: Langsung scraping tanpa autentikasi dengan auto-dismiss popup login.
- **3 Mode Scraping**:
  1. **Scrap Video Saja**: Mengumpulkan data video berdasarkan kata kunci di `keywords.txt`.
  2. **Scrap Video + Komentar**: Mencari video sekaligus mengambil komentar dari tiap video.
  3. **Scrap Komentar dari CSV yang Ada**: Mengambil komentar dari file CSV hasil scraping sebelumnya tanpa search ulang.
- **Struktur Data Lengkap**:
  - Video: `search_keyword`, `video_id`, `upload_date`, `username`, `description`, `play_count`, `digg_count`, `comment_count`, `video_url`.
  - Komentar: `video_id`, `search_keyword`, `comment_id`, `comment_date`, `username`, `nickname`, `comment_text`, `likes`, `reply_count`, `video_url`.

## 📦 Instalasi

1. **Clone Repository**:
   ```bash
   git clone <URL_REPO_GITHUB_ANDA>
   cd scrap-tiktok
   ```

2. **Install Dependensi Python**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Siapkan Chrome & ChromeDriver (Chrome for Testing)**:
   - Letakkan folder `chrome-win64` dan `chromedriver-win64` di dalam folder project ini.

## 🛠️ Penggunaan

### 1. Uji Koneksi Web Driver
```bash
python tes-koneksi.py
```

### 2. Jalankan Scraper
1. Masukkan kata kunci pencarian ke file `keywords.txt` (1 keyword per baris):
   ```text
   Hamenang
   resep masakan
   ```
2. Jalankan script:
   ```bash
   python key_scrap.py
   ```
3. Ikuti petunjuk interaktif di terminal untuk memilih mode dan metode login.

## 📄 Lisensi
MIT License
