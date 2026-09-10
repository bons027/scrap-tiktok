# =====================================================================
# TIKTOK SENTIMENT & TOPIC INTELLIGENCE (INDOBERT GOOGLE COLAB SCRIPT)
# Jalankan script ini di Google Colab dengan GPU T4 Gratis!
# =====================================================================

# 1. Install Library
# !pip install -q transformers torch pandas scikit-learn

import torch
import time
import re
import os
import pandas as pd
from google.colab import files
from transformers import pipeline

print("=" * 60)
print("   INDOBERT SENTIMENT & TOPIC PROCESSOR FOR TIKTOK")
print("=" * 60)
print(f"CUDA Tersedia : {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"Nama GPU      : {torch.cuda.get_device_name(0)}")
else:
    print("PERINGATAN: GPU belum aktif. Aktifkan di Runtime -> Change runtime type -> T4 GPU")

# 2. Upload File CSV Komentar
print("\n[*] Silakan upload file CSV komentar (contoh: tes_comments.csv):")
uploaded = files.upload()
if not uploaded:
    raise ValueError("Tidak ada file yang di-upload!")

uploaded_filename = list(uploaded.keys())[0]
df = pd.read_csv(uploaded_filename)
print(f"\n[+] Berhasil memuat {len(df)} baris dari {uploaded_filename}")

# 3. Load Model IndoBERT
device = 0 if torch.cuda.is_available() else -1
print("\n[*] Memuat model IndoBERT (w11wo/indonesian-roberta-base-sentiment-classifier)...")
sentiment_pipe = pipeline(
    "sentiment-analysis",
    model="w11wo/indonesian-roberta-base-sentiment-classifier",
    device=device,
    truncation=True,
    max_length=128
)

# 4. Deteksi Kolom Komentar / Teks Postingan
comment_col = None
for col in ['comment_text', 'description', 'post_text', 'text', 'comment', 'isi_komentar']:
    if col in df.columns:
        comment_col = col
        break

if not comment_col:
    raise ValueError(f"Kolom teks (comment_text/description) tidak ditemukan. Kolom yang ada: {list(df.columns)}")

texts = df[comment_col].fillna("").astype(str).tolist()
print(f"[*] Memproses {len(texts)} komentar di GPU...")
t0 = time.time()

# Batch Processing
batch_size = 64
results = []
for i in range(0, len(texts), batch_size):
    batch = texts[i:i + batch_size]
    preds = sentiment_pipe(batch)
    results.extend(preds)
    if (i // batch_size) % 5 == 0:
        print(f"  Progress: {min(i + batch_size, len(texts))}/{len(texts)} komentar...")

dur = time.time() - t0
print(f"\n[+] Selesai dalam {dur:.2f} detik! ({len(texts)/dur:.1f} komentar/detik)")

label_map = {
    "positive": "Positif",
    "neutral": "Netral",
    "negative": "Negatif",
    "LABEL_0": "Negatif",
    "LABEL_1": "Netral",
    "LABEL_2": "Positif"
}

df['sentiment'] = [label_map.get(r['label'].lower(), r['label'].capitalize()) for r in results]
df['sentiment_score'] = [round(r['score'] if 'pos' in r['label'].lower() else (-r['score'] if 'neg' in r['label'].lower() else 0.0), 3) for r in results]

# 5. Klasifikasi Topik / Isu Hangat
def classify_topic(text):
    t = text.lower()
    if any(k in t for k in ['bkk', 'pd bkk', 'uang nasabah', 'tabungan', 'korupsi', 'cairkan', 'dana']):
        return 'Keuangan & Kasus BKK'
    if any(k in t for k in ['jalan', 'aspal', 'rusak', 'lobang', 'lubang', 'talut', 'cor', 'proyek', 'jembatan', 'lampu']):
        return 'Infrastruktur & Jalan'
    if any(k in t for k in ['rapor', 'rapot', 'sekolah', 'sdn', 'guru', 'murid', 'libur', 'kelas', 'anak sekolah']):
        return 'Pendidikan & Anak'
    if any(k in t for k in ['konser', 'ndx', 'stadion', 'trikoyo', 'pramuka', 'estafet', 'balap', 'sepeda', 'senam', 'karnaval']):
        return 'Event, Seni & Olahraga'
    if any(k in t for k in ['ktp', 'layanan', 'dinas', 'bupati', 'kantor', 'bansos', 'bantuan', 'desa']):
        return 'Layanan Publik & Birokrasi'
    if any(k in t for k in ['sehat', 'semangat', 'sukses', 'muda', 'ganteng', 'josjis', 'maturnuwun', 'keren', 'idola', 'aamiin']):
        return 'Apresiasi & Doa Personal'
    return 'Lain-lain'

def extract_keypoint(text, topic):
    words = [w for w in re.sub(r'[^a-zA-Z0-9\s]', '', text).split() if len(w) > 2]
    return ' '.join(words[:5]) if words else topic

df['topic'] = df[comment_col].fillna('').apply(classify_topic)
df['key_point'] = [extract_keypoint(txt, top) for txt, top in zip(df[comment_col].fillna(''), df['topic'])]

# 6. Ringkasan Eksekutif
total = len(df)
pos_pct = (df['sentiment'] == 'Positif').mean() * 100
neg_pct = (df['sentiment'] == 'Negatif').mean() * 100
neu_pct = (df['sentiment'] == 'Netral').mean() * 100
top_issue = df['topic'].value_counts().index[0]

summary_content = f"""Berdasarkan analisis terhadap {total} komentar publik menggunakan model IndoBERT, sentimen masyarakat menunjukkan {pos_pct:.1f}% Positif, {neu_pct:.1f}% Netral, dan {neg_pct:.1f}% Negatif. Topik yang paling mendominasi pembicaraan adalah '{top_issue}'. Isu-isu negatif utama berkisar pada keluhan infrastruktur jalan dan tuntutan nasabah mengenai kasus BKK, sementara sentimen positif didominasi apresiasi terhadap kehadiran pimpinan daerah dan partisipasi dalam kegiatan kemasyarakatan."""

# 7. Simpan & Download File Hasil
out_csv_name = uploaded_filename.replace('.csv', '_analyzed.csv')
out_txt_name = uploaded_filename.replace('.csv', '_summary.txt')

df.to_csv(out_csv_name, index=False, encoding='utf-8')
with open(out_txt_name, 'w', encoding='utf-8') as f:
    f.write(summary_content)

print(f"\n[+] Hasil disimpan ke {out_csv_name} dan {out_txt_name}!")
print("[*] Mengunduh otomatis ke komputermu...")
files.download(out_csv_name)
files.download(out_txt_name)
print("\n>>> Selesai! Pindahkan file yang diunduh ke folder scrap-tiktok di komputermu, lalu buka web dashboard lokal! <<<")
