import os
import sys
import json
import time
import math
import pandas as pd
from dotenv import load_dotenv

# Pastikan encoding UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

load_dotenv()

def get_gemini_client(api_key=None):
    """
    Inisialisasi client Google GenAI menggunakan API key dari parameter atau environment variable.
    """
    key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key:
        raise ValueError("GEMINI_API_KEY belum disetel! Masukkan API key di form dashboard atau file .env")
    
    from google import genai
    return genai.Client(api_key=key)

SYSTEM_PROMPT = """
Kamu adalah analis sentimen dan intelijen opini publik spesialis media sosial Indonesia (termasuk bahasa daerah seperti bahasa Jawa dan slang TikTok).
Tugasmu adalah menganalisis sekumpulan komentar TikTok warga terhadap tokoh/pejabat daerah.

Untuk setiap komentar dalam daftar yang diberikan, berikan analisis terstruktur dalam format JSON:
1. sentiment: HANYA pilih salah satu dari ["Positif", "Netral", "Negatif"]
2. sentiment_score: angka float antara -1.0 (sangat negatif/kritik tajam/marah) hingga 1.0 (sangat positif/pujian/doa), dan 0.0 jika netral/pertanyaan santai.
3. topic: pilih atau standarkan ke salah satu kategori topik berikut:
   - "Infrastruktur & Jalan" (jalan rusak, talut, penerangan jalan, fasilitas umum)
   - "Keuangan & Kasus BKK" (krisis PD BKK Klaten, tabungan nasabah, transparansi keuangan)
   - "Pendidikan & Anak" (ambil rapor, hari sekolah, fasilitas sekolah, prestasi)
   - "Apresiasi & Doa Personal" (pujian bupati muda, ucapan selamat, doa kesehatan)
   - "Event, Seni & Budaya" (konser NDX, karnaval, estafet pramuka, sepeda santai)
   - "Pelayanan Publik & Birokrasi" (layanan dinas, perizinan, mutasi jabatan)
   - "Pertanian & Wisata" (potensi lokal, investor, pertanian)
   - "Lain-lain" (jika tidak masuk kategori di atas)
4. key_point: ringkasan 3-7 kata mengenai inti pesan/keluhan warga.

WAJIB mengembalikan output HANYA berupa JSON Array valid dengan skema:
[
  {
    "index": 0,
    "sentiment": "Positif",
    "sentiment_score": 0.8,
    "topic": "Apresiasi & Doa Personal",
    "key_point": "Mendoakan bupati sehat dan sukses"
  }
]
"""

def analyze_batch_with_gemini(client, batch_items, model_name="gemini-3.6-flash"):
    """
    Mengirim batch komentar (misal 25-35 komentar) ke Gemini API.
    """
    from google.genai import types
    
    prompt_content = "Berikut adalah daftar komentar yang harus kamu analisis:\n" + json.dumps(batch_items, ensure_ascii=False, indent=2)
    
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT,
        temperature=0.2,
        response_mime_type="application/json"
    )
    
    # Coba model utama, jika gagal coba fallback
    models_to_try = [model_name, "gemini-2.5-flash-lite", "gemini-flash-latest"]
    last_error = None
    
    for m in models_to_try:
        try:
            response = client.models.generate_content(
                model=m,
                contents=prompt_content,
                config=config
            )
            raw_text = response.text.strip()
            # Bersihkan markdown formatting jika ada
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]
                
            parsed = json.loads(raw_text.strip())
            if isinstance(parsed, list):
                return parsed
        except Exception as e:
            last_error = e
            time.sleep(2)
            continue
            
    raise RuntimeError(f"Gagal memproses batch komentar: {last_error}")

def analyze_comments_df(df, api_key=None, batch_size=30, progress_callback=None):
    """
    Menganalisis DataFrame komentar TikTok secara batch menggunakan Gemini API.
    Mendukung progress callback untuk progress bar di Streamlit.
    """
    client = get_gemini_client(api_key=api_key)
    
    # Pastikan ada kolom komentar / teks postingan
    comment_col = None
    for col in ['comment_text', 'description', 'post_text', 'text', 'comment', 'isi_komentar']:
        if col in df.columns:
            comment_col = col
            break
            
    if not comment_col:
        raise ValueError(f"Kolom teks (comment_text/description) tidak ditemukan dalam DataFrame! Kolom yang ada: {list(df.columns)}")
        
    total_rows = len(df)
    results = {}
    
    # Filter komentar yang tidak kosong
    valid_indices = df[df[comment_col].notna() & (df[comment_col].str.strip() != "")].index.tolist()
    total_valid = len(valid_indices)
    
    num_batches = math.ceil(total_valid / batch_size)
    print(f"[*] Memulai analisis {total_valid} komentar dalam {num_batches} batch (batch size: {batch_size})...")
    
    for b_idx in range(num_batches):
        batch_ids = valid_indices[b_idx * batch_size : (b_idx + 1) * batch_size]
        batch_payload = [
            {"index": idx, "text": str(df.at[idx, comment_col])[:300]}
            for idx in batch_ids
        ]
        
        # Kirim ke Gemini dengan retry
        max_retries = 3
        batch_result = []
        for attempt in range(max_retries):
            try:
                batch_result = analyze_batch_with_gemini(client, batch_payload)
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"[!] Gagal batch {b_idx + 1} setelah {max_retries} percobaan: {e}")
                    # Berikan fallback Netral jika batch gagal total
                    batch_result = [
                        {"index": item["index"], "sentiment": "Netral", "sentiment_score": 0.0, "topic": "Lain-lain", "key_point": "Gagal analisis"}
                        for item in batch_payload
                    ]
                else:
                    time.sleep(3 * (attempt + 1))
                    
        for res in batch_result:
            idx = res.get("index")
            if idx is not None:
                results[idx] = {
                    "sentiment": res.get("sentiment", "Netral"),
                    "sentiment_score": float(res.get("sentiment_score", 0.0)),
                    "topic": res.get("topic", "Lain-lain"),
                    "key_point": res.get("key_point", "")
                }
                
        if progress_callback:
            progress_callback((b_idx + 1) / num_batches)
            
        print(f"  [+] Selesai batch {b_idx + 1}/{num_batches} (min({(b_idx + 1) * batch_size}, {total_valid}) komentar)", flush=True)
        time.sleep(0.5)  # Rate limiting prevention
        
    # Gabungkan hasil ke DataFrame
    df['sentiment'] = df.index.map(lambda i: results.get(i, {}).get("sentiment", "Netral"))
    df['sentiment_score'] = df.index.map(lambda i: results.get(i, {}).get("sentiment_score", 0.0))
    df['topic'] = df.index.map(lambda i: results.get(i, {}).get("topic", "Lain-lain"))
    df['key_point'] = df.index.map(lambda i: results.get(i, {}).get("key_point", ""))
    
    return df

def generate_executive_summary(df, api_key=None):
    """
    Menghasilkan Ringkasan Eksekutif Opini Publik menggunakan Gemini AI
    berdasarkan statistik agregat dan sampel keluhan/pujian masyarakat.
    """
    client = get_gemini_client(api_key=api_key)
    from google.genai import types
    
    total = len(df)
    if total == 0:
        return "Tidak ada data komentar untuk dianalisis."
        
    sentiment_counts = df['sentiment'].value_counts().to_dict()
    topic_counts = df['topic'].value_counts().head(6).to_dict()
    
    # Deteksi kolom teks
    text_col = None
    for col in ['comment_text', 'description', 'post_text', 'text', 'comment', 'isi_komentar']:
        if col in df.columns:
            text_col = col
            break
    text_col = text_col or 'comment_text'

    # Ambil sampel keluhan negatif utama
    neg_samples = df[df['sentiment'] == 'Negatif'][text_col].dropna().head(8).tolist() if text_col in df.columns else []
    # Ambil sampel apresiasi positif utama
    pos_samples = df[df['sentiment'] == 'Positif'][text_col].dropna().head(5).tolist() if text_col in df.columns else []
    
    summary_prompt = f"""
Berikut adalah rangkuman data opini publik dari {total} data/komentar media sosial warga mengenai pimpinan/pemerintah daerah:

STATISTIK SENTIMEN:
{json.dumps(sentiment_counts, indent=2)}

TOPIK/ISU PALING BANYAK DIBICARAKAN:
{json.dumps(topic_counts, indent=2)}

SAMPEL KELUHAN / KRITIK WARGA (SENTIMEN NEGATIF):
{chr(10).join(f"- {s}" for s in neg_samples)}

SAMPEL APRESIASI / DUKUNGAN WARGA (SENTIMEN POSITIF):
{chr(10).join(f"- {s}" for s in pos_samples)}

TUGAS:
Buatkan Ringkasan Eksekutif (Executive Briefing) resmi, padat, dan profesional (2-3 paragraf) untuk konsumsi Bupati / Pejabat Pemda / Tim Humas.
Isi harus memuat:
1. Gambaran umum persepsi dan sentimen publik (apakah mayoritas mendukung, netral, atau kritis).
2. Isu paling kritis/sensitif yang paling banyak dituntut oleh warga dan butuh solusi cepat dari pemerintah.
3. Rekomendasi langkah taktis atau respons komunikasi publik yang disarankan.
Gunakan gaya bahasa laporan intelijen media yang tajam dan berbobot.
"""
    
    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=summary_prompt,
            config=types.GenerateContentConfig(temperature=0.3)
        )
        return response.text.strip()
    except Exception as e:
        return f"Gagal membuat ringkasan eksekutif: {e}"

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Penggunaan: python analyzer.py <file_komentar.csv>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    if not os.path.exists(filepath):
        print(f"[ERROR] File {filepath} tidak ditemukan!")
        sys.exit(1)
        
    print(f"[*] Membaca {filepath}...")
    df = pd.read_csv(filepath)
    df_analyzed = analyze_comments_df(df)
    
    output_path = filepath.replace(".csv", "_analyzed.csv")
    df_analyzed.to_csv(output_path, index=False, encoding='utf-8')
    print(f"\n[SELESAI] Hasil analisis disimpan ke: {output_path}")
    
    print("\n[*] Menghasilkan Ringkasan Eksekutif AI...")
    summary = generate_executive_summary(df_analyzed)
    print("\n" + "=" * 60)
    print("        RINGKASAN EKSEKUTIF OPINI PUBLIK (AI BRIEF)")
    print("=" * 60)
    print(summary)
    print("=" * 60)
