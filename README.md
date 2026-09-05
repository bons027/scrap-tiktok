# Social Media Intelligence Platform (TikTok & Facebook Scraper + AI Analyzer)

Platform monitoring dan intelligence media sosial berbasis **Python, Selenium (`undetected-chromedriver`), XHR/GraphQL Network Interception, dan AI (Google Gemini & IndoBERT)** untuk monitoring opini publik, aduan warga, dan isu daerah (Humas Pemda / Bupati).

---

## 🚀 Fitur Utama

### 1. TikTok Scraper (`key_scrap.py`)
- **XHR / Fetch Interception**: Menangkap data video & komentar langsung dari API internal TikTok.
- **Login QR Code / Guest Mode**: Opsi login tersimpan atau tanpa login dengan bypass pop-up otomatis.
- **Pagination Komentar Tak Terbatas**: Mengambil seluruh komentar hingga akhir.

### 2. Facebook Regional Intelligence Scraper (`fb_scrap.py`)
- **GraphQL & XHR Network Interceptor**: Menangkap payload komentar Facebook secara *real-time* via Chrome DevTools Protocol (CDP).
- **Persistent Profile (`facebook_chrome_profile`)**: Cukup login sekali, sesi tersimpan selamanya.
- **Pencarian Isu Daerah (Global Search)**: Memindai isu daerah berdasarkan `keywords.txt`.
- **Monitoring Grup Warga (`groups.txt`)**: Mencari keluhan spesifik atau memantau feed terbaru di grup komunitas/warga.
- **4-Langkah Otomatisasi Komentar**: Otomatis klik postingan -> ubah filter ke *"Semua komentar"* -> scroll sampai habis -> simpan ke CSV.
- **Live Interceptor Mode**: Bebas scroll/klik di browser secara manual, script otomatis menyedot seluruh komentar ke CSV.

### 3. AI Sentiment & Topic Analyzer (`analyzer.py` & `app.py`)
- **Klasifikasi Topik Otomatis**: Infrastruktur, Pelayanan Publik, Pendidikan, Bansos, UMKM, dll.
- **Analisis Sentimen**: Positif, Netral, Negatif menggunakan IndoBERT / Gemini AI.
- **Ringkasan Eksekutif AI**: Membuat laporan ringkas rekomendasi kebijakan untuk Bupati/Pimpinan.
- **Web Dashboard Interaktif**: Dashboard visualisasi grafik, tabel aduan, dan ringkasan eksekutif (`http://localhost:5000`).

---

## 📦 Instalasi

1. **Clone Repository**:
   ```bash
   git clone https://github.com/bons027/scrap-tiktok.git
   cd scrap-tiktok
   ```

2. **Install Dependensi Python**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Siapkan Konfigurasi API (Opsional untuk AI Gemini)**:
   Salin file `.env.example` menjadi `.env`:
   ```bash
   copy .env.example .env
   ```
   Isi `GEMINI_API_KEY=your_gemini_api_key_here` jika ingin menggunakan ringkasan AI otomatis.

4. **Chrome & ChromeDriver (Chrome for Testing)**:
   Letakkan folder `chrome-win64` dan `chromedriver-win64` di dalam folder project ini.

---

## 🛠️ Cara Penggunaan

### 1. Uji Koneksi Web Driver
```bash
python tes-koneksi.py
```

### 2. Jalankan Facebook Scraper
```bash
python fb_scrap.py
```
*Pilihan Menu:*
- **0**: Setup login Facebook (login sekali di awal).
- **1**: Pencarian otomatis kata kunci isu daerah (`keywords.txt`).
- **2**: Monitoring otomatis grup Facebook warga (`groups.txt`).
- **3**: Mode Live Interceptor (bebas klik/scroll, script otomatis sedot komentar).

### 3. Jalankan TikTok Scraper
```bash
python key_scrap.py
```

### 4. Buka Dashboard Web & Analisis AI
```bash
python app.py
```
Buka browser ke `http://localhost:5000`, pilih file komentar CSV hasil scraping, dan klik **"Mulai Analisis AI"**.

### 5. Pintasan Cepat Browser
- `buka_facebook.bat`: Membuka browser Chrome langsung dengan cookies Facebook scraper.
- `buka_tiktok.bat`: Membuka browser Chrome langsung dengan cookies TikTok scraper.

---

## 📄 Lisensi
MIT License
