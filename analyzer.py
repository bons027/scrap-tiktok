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
import re

# Kamus Kata Sentimen Bahasa Indonesia & Daerah (Jawa/Slang Medsos)
POS_WORDS = {
    'bagus': 1.0, 'mantap': 1.2, 'keren': 1.2, 'hebat': 1.2, 'terbaik': 1.5,
    'juara': 1.0, 'setuju': 0.8, 'mendukung': 1.0, 'dukung': 1.0, 'lanjutkan': 1.2,
    'apresiasi': 1.0, 'terima kasih': 1.0, 'maturnuwun': 1.0, 'matur nuwun': 1.0,
    'alhamdulillah': 1.0, 'sukses': 1.0, 'berkah': 1.0, 'barokah': 1.0,
    'mugi': 0.8, 'sehat': 1.0, 'panjang umur': 1.2, 'amanah': 1.2, 'ramah': 1.0,
    'merakyat': 1.2, 'visioner': 1.2, 'bupatiku': 1.0, 'bupati muda': 1.0,
    'top': 1.0, 'jos': 1.2, 'josjis': 1.2, 'suka': 0.8, 'bangga': 1.2,
    'menang': 1.0, 'menawan': 1.0, 'berkembang': 0.8, 'maju': 1.0, 'semangat': 0.8,
    'menangkanklaten': 1.5, 'peduli': 1.0, 'solutif': 1.2, 'bersinar': 1.0, 'rapi': 0.8,
    'bersih': 0.8, 'apik': 1.0, 'gayeng': 0.8, 'positif': 1.0, 'senang': 1.0,
    'bantu': 0.8, 'terbantu': 1.0, 'inovasi': 1.0, 'harapan': 0.8, 'berani': 0.8,
    'responsif': 1.2, 'cepat': 0.8, 'luar biasa': 1.5, 'salut': 1.2, 'idola': 1.0,
    'semringah': 1.0, 'beres': 0.8, 'tuntas': 1.0, 'prospek': 0.8, 'pemberdayaan': 0.8,
    'inklusif': 1.0, 'berkualitas': 1.0, 'unggul': 1.2, 'apik': 1.0, 'jaya': 1.0
}

NEG_WORDS = {
    'rusak': 1.2, 'ajur': 1.5, 'mumur': 1.5, 'jeglongan': 1.2, 'lubang': 1.0, 'hancur': 1.5,
    'parah': 1.2, 'kecewa': 1.5, 'payah': 1.2, 'jelek': 1.0, 'buruk': 1.2,
    'korupsi': 2.0, 'bkk': 1.0, 'rugi': 1.2, 'uang hilang': 1.8, 'tilap': 1.5,
    'gelap': 1.0, 'mati lampu': 1.0, 'turu': 1.2, 'tidur': 1.0, 'lelet': 1.2,
    'lambat': 1.0, 'amburadul': 1.5, 'bobrok': 1.5, 'pungli': 1.8, 'sogok': 1.8,
    'zalim': 1.8, 'bohong': 1.5, 'pencitraan': 1.2, 'palsu': 1.5, 'ra cetho': 1.5,
    'ora cetho': 1.5, 'ora beres': 1.5, 'kemalingan': 1.5, 'macet': 0.8, 'banjir': 1.0,
    'ambles': 1.2, 'boros': 1.0, 'bejat': 1.8, 'sampah': 1.0, 'kumuh': 1.0,
    'bahaya': 1.0, 'sulit': 0.8, 'susah': 0.8, 'mahal': 0.8, 'merugikan': 1.2, 'marah': 1.2,
    'demo': 0.8, 'protes': 1.0, 'cuek': 1.0, 'diam saja': 1.2, 'diem saja': 1.2,
    'mengecewakan': 1.5, 'kapok': 1.2, 'mubazir': 1.0, 'semrawut': 1.2, 'keluhan': 0.8,
    'diabaikan': 1.2, 'bencana': 1.0, 'kacau': 1.2, 'batal': 0.8, 'php': 1.2, 'kurang': 0.6
}

NEGATIONS = {'tidak', 'nggak', 'ga', 'gak', 'ora', 'mboten', 'kurang', 'belum', 'bukan', 'tanpa', 'tak'}
BOOSTERS = {'sangat', 'banget', 'tenan', 'pisan', 'sekali', 'pol', 'beneran', 'amat'}

def classify_topic(text):
    if not text:
        return 'Lain-lain / Isu Daerah'
    t = str(text).lower()
    if any(k in t for k in ['bkk', 'pd bkk', 'uang nasabah', 'tabungan', 'korupsi', 'cairkan', 'dana', 'ojk', 'lps', 'bank']):
        return 'Keuangan & Kasus BKK'
    if any(k in t for k in ['jalan', 'aspal', 'rusak', 'lobang', 'lubang', 'talut', 'cor', 'proyek', 'jembatan', 'lampu', 'penerangan', 'bergelombang', 'trotoar', 'macet', 'parkir', 'tanggul', 'banjir', 'ajur']):
        return 'Infrastruktur & Jalan'
    if any(k in t for k in ['rapor', 'rapot', 'sekolah', 'sdn', 'smp', 'sma', 'smk', 'guru', 'murid', 'libur', 'kelas', 'anak sekolah', 'pip', 'beasiswa', 'kkm', 'pendidikan', 'pelatihan']):
        return 'Pendidikan & Sekolah'
    if any(k in t for k in ['bansos', 'pkh', 'desil', 'sensus', 'bantuan', 'bpjs', 'pbi', 'ktp', 'layanan', 'dinas', 'samsat', 'pungli', 'kantor', 'pdam', 'kelurahan', 'polres', 'polisi', 'kapolres']):
        return 'Bansos & Layanan Publik'
    if any(k in t for k in ['soto', 'kuliner', 'angkringan', 'makan', 'warung', 'jajan', 'oleh-oleh', 'enak', 'pedan', 'umkm', 'pasar', 'pentol']):
        return 'Kuliner & UMKM Lokal'
    if any(k in t for k in ['adhit', 'adit', 'niken', 'woro', 'salindri', 'tuban', 'lindra', 'konser', 'ndx', 'stadion', 'trikoyo', 'pramuka', 'estafet', 'balap', 'sepeda', 'senam', 'karnaval', 'tunas kelapa', 'drumben', 'nari', 'cfn', 'futsal', 'krista', 'gracia']):
        return 'Event, Seni & Komunitas'
    if any(k in t for k in ['sehat', 'semangat', 'sukses', 'muda', 'ganteng', 'josjis', 'maturnuwun', 'keren', 'idola', 'aamiin', 'ultah', 'hbd', 'milad', 'selamat', 'barakallah', 'bupatiku', 'panjang umur', 'menangkan', 'pdi', 'wong enom', 'harapan']):
        return 'Apresiasi & Doa Warga'
    return 'Lain-lain / Isu Daerah'

def extract_keypoint(text, topic):
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(text))
    words = [w for w in clean.split() if len(w) > 2]
    return ' '.join(words[:5]) if words else topic

def analyze_sentiment_fast(text):
    """
    Analisis sentimen instan (Positif, Negatif, Netral) berbasis kamus bahasa Indonesia,
    bahasa Jawa, dan slang media sosial. Cepat, akurat, dan tidak membutuhkan kuota API.
    """
    if not text or not isinstance(text, str) or len(text.strip()) < 2:
        return "Netral", 0.0, "Lain-lain / Isu Daerah", "Umum"
        
    t_clean = text.lower()
    words = re.findall(r'\b[a-z0-9_#]+\b', t_clean)
    pos_score = 0.0
    neg_score = 0.0
    
    # Deteksi multi-word phrases terlebih dahulu (positif > 0, negatif < 0)
    phrases = [
        ('matur nuwun', 1.0), ('panjang umur', 1.2), ('bupati muda', 1.0), ('wong enom', 1.0),
        ('terima kasih', 1.0), ('luar biasa', 1.5), ('tunas kelapa', 0.8), ('harapan baru', 1.2),
        ('uang hilang', -1.8), ('mati lampu', -1.0), ('ra cetho', -1.5), ('ora cetho', -1.5),
        ('ra ceto', -1.5), ('ora ceto', -1.5), ('ora beres', -1.5), ('diam saja', -1.2),
        ('diem saja', -1.2), ('tidak bagus', -1.2), ('kurang bagus', -0.8), ('ajur mumur', -1.8),
        ('jeglongan sewu', -1.5), ('jalan rusak', -1.5), ('uang nasabah', -1.5)
    ]
    for phrase, weight in phrases:
        if phrase in t_clean:
            if weight > 0:
                pos_score += weight
            else:
                neg_score += abs(weight)

    for i, w in enumerate(words):
        has_negation = False
        if i > 0 and words[i-1] in NEGATIONS:
            has_negation = True
        elif i > 1 and words[i-2] in NEGATIONS:
            has_negation = True
            
        is_boosted = False
        if (i > 0 and words[i-1] in BOOSTERS) or (i < len(words)-1 and words[i+1] in BOOSTERS):
            is_boosted = True
            
        mult = 1.5 if is_boosted else 1.0
        
        if w in POS_WORDS:
            val = POS_WORDS[w] * mult
            if has_negation:
                neg_score += val
            else:
                pos_score += val
        elif w in NEG_WORDS:
            val = NEG_WORDS[w] * mult
            if has_negation:
                pos_score += val
            else:
                neg_score += val

    diff = pos_score - neg_score
    if diff > 0.4:
        sentiment = "Positif"
        score = min(1.0, round(diff / (pos_score + neg_score + 1.0) * 1.5, 2))
    elif diff < -0.4:
        sentiment = "Negatif"
        score = max(-1.0, round(diff / (pos_score + neg_score + 1.0) * 1.5, 2))
    else:
        sentiment = "Netral"
        score = 0.0

    topic = classify_topic(text)
    key_point = extract_keypoint(text, topic)
    return sentiment, score, topic, key_point

def enrich_csv_with_sentiment(filepath):
    """
    Menambahkan kolom sentimen (Positif, Netral, Negatif), sentiment_score,
    topic, dan key_point ke file CSV (Facebook atau TikTok).
    """
    if not os.path.exists(filepath):
        return False
    try:
        df = pd.read_csv(filepath)
        if len(df) == 0:
            return False
            
        text_col = None
        for col in ['comment_text', 'post_text', 'text', 'comment', 'description', 'isi_komentar']:
            if col in df.columns:
                text_col = col
                break
        if not text_col:
            return False
            
        results = [analyze_sentiment_fast(t) for t in df[text_col].fillna('')]
        df['sentiment'] = [r[0] for r in results]
        df['sentiment_score'] = [r[1] for r in results]
        df['topic'] = [r[2] for r in results]
        df['key_point'] = [r[3] for r in results]
        
        df.to_csv(filepath, index=False, encoding='utf-8')
        return True
    except Exception as e:
        print(f"[!] Gagal enrich sentiment pada {filepath}: {e}")
        return False

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
    
    # Pastikan ada kolom komentar
    comment_col = None
    for col in ['comment_text', 'text', 'comment', 'isi_komentar']:
        if col in df.columns:
            comment_col = col
            break
            
    if not comment_col:
        raise ValueError(f"Kolom teks komentar tidak ditemukan dalam DataFrame! Kolom yang ada: {list(df.columns)}")
        
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
    
    # Ambil sampel keluhan negatif utama
    neg_samples = df[df['sentiment'] == 'Negatif']['comment_text'].dropna().head(8).tolist()
    # Ambil sampel apresiasi positif utama
    pos_samples = df[df['sentiment'] == 'Positif']['comment_text'].dropna().head(5).tolist()
    
    summary_prompt = f"""
Berikut adalah rangkuman data opini publik dari {total} komentar TikTok warga mengenai pimpinan/pemerintah daerah:

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
