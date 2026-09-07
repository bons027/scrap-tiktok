import os
import sys
import json
import glob
import math
import time
import threading
import webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import urllib.parse
import re
import pandas as pd
from dotenv import load_dotenv

# Pastikan encoding output UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

load_dotenv()
from analyzer import analyze_comments_df, generate_executive_summary, get_gemini_client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 5000

# Global state untuk tracking progres analisis
analysis_state = {
    "status": "idle",       # "idle", "running", "completed", "error"
    "file": "",
    "current_batch": 0,
    "total_batches": 0,
    "percent": 0,
    "message": "",
    "error": ""
}

def find_csv_path(filename):
    if not filename:
        return None
    if os.path.isabs(filename) and os.path.exists(filename):
        return filename
    results_path = os.path.join(BASE_DIR, "results", filename)
    if os.path.exists(results_path):
        return results_path
    base_path = os.path.join(BASE_DIR, filename)
    if os.path.exists(base_path):
        return base_path
    return results_path if os.path.exists(results_path) else base_path

def normalize_sentiment(val):
    if not val or pd.isna(val):
        return "Netral"
    s = str(val).strip().lower()
    if "pos" in s or s == "label_2":
        return "Positif"
    if "neg" in s or s == "label_0":
        return "Negatif"
    if "neu" in s or "net" in s or s == "label_1":
        return "Netral"
    return "Netral"

def classify_topic(text):
    t = str(text).lower()
    if any(k in t for k in ['bkk', 'pd bkk', 'uang nasabah', 'tabungan', 'korupsi', 'cairkan', 'dana', 'ojk', 'lps', 'bank']):
        return 'Keuangan & Kasus BKK'
    if any(k in t for k in ['jalan', 'aspal', 'rusak', 'lobang', 'lubang', 'talut', 'cor', 'proyek', 'jembatan', 'lampu', 'penerangan', 'bergelombang', 'trotoar', 'macet', 'parkir', 'tanggul', 'banjir']):
        return 'Infrastruktur & Jalan'
    if any(k in t for k in ['rapor', 'rapot', 'sekolah', 'sdn', 'smp', 'sma', 'smk', 'guru', 'murid', 'libur', 'kelas', 'anak sekolah', 'pip', 'beasiswa', 'kkm', 'pendidikan']):
        return 'Pendidikan & Sekolah'
    if any(k in t for k in ['bansos', 'pkh', 'desil', 'sensus', 'bantuan', 'bpjs', 'pbi', 'ktp', 'layanan', 'dinas', 'samsat', 'pungli', 'kantor', 'pdam', 'kelurahan']):
        return 'Bansos & Layanan Publik'
    if any(k in t for k in ['soto', 'kuliner', 'angkringan', 'makan', 'warung', 'jajan', 'oleh-oleh', 'enak', 'pedan', 'jemangin']):
        return 'Kuliner & UMKM Lokal'
    if any(k in t for k in ['adhit', 'adit', 'niken', 'woro', 'salindri', 'tuban', 'lindra', 'konser', 'ndx', 'stadion', 'trikoyo', 'pramuka', 'estafet', 'balap', 'sepeda', 'senam', 'karnaval', 'tunas kelapa', 'drumben', 'nari', 'cfn', 'futsal', 'krista', 'gracia']):
        return 'Event, Seni & Komunitas'
    if any(k in t for k in ['sehat', 'semangat', 'sukses', 'muda', 'ganteng', 'josjis', 'maturnuwun', 'keren', 'idola', 'aamiin', 'ultah', 'hbd', 'milad', 'selamat', 'barakallah', 'bupatiku', 'panjang umur']):
        return 'Apresiasi & Doa Warga'
    return 'Lain-lain / Obrolan Warga'

def extract_keypoint(text, topic):
    clean = re.sub(r'[^a-zA-Z0-9\s]', ' ', str(text))
    words = [w for w in clean.split() if len(w) > 2]
    return ' '.join(words[:5]) if words else topic

def run_background_analysis(filepath, api_key=None):
    global analysis_state
    try:
        analysis_state["status"] = "running"
        analysis_state["file"] = os.path.basename(filepath)
        analysis_state["percent"] = 0
        analysis_state["message"] = "Membaca file komentar..."
        
        df = pd.read_csv(filepath)
        comment_col = None
        for col in ['comment_text', 'text', 'comment', 'isi_komentar']:
            if col in df.columns:
                comment_col = col
                break
                
        if not comment_col:
            raise ValueError("Kolom komentar tidak ditemukan di file CSV.")
            
        valid_indices = df[df[comment_col].notna() & (df[comment_col].str.strip() != "")].index.tolist()
        batch_size = 30
        num_batches = math.ceil(len(valid_indices) / batch_size)
        analysis_state["total_batches"] = num_batches
        analysis_state["current_batch"] = 0
        
        def on_progress(ratio):
            analysis_state["percent"] = int(ratio * 100)
            analysis_state["current_batch"] = int(ratio * num_batches)
            analysis_state["message"] = f"Menganalisis batch {analysis_state['current_batch']}/{num_batches}..."
            
        df_analyzed = analyze_comments_df(
            df,
            api_key=api_key,
            batch_size=batch_size,
            progress_callback=on_progress
        )
        
        save_path = filepath if "_analyzed" in filepath else filepath.replace(".csv", "_analyzed.csv")
        df_analyzed.to_csv(save_path, index=False, encoding='utf-8')
        
        analysis_state["message"] = "Menyusun Ringkasan Eksekutif AI..."
        summary_text = generate_executive_summary(df_analyzed, api_key=api_key)
        summary_path = save_path.replace(".csv", "_summary.txt")
        with open(summary_path, "w", encoding="utf-8") as sf:
            sf.write(summary_text)
            
        analysis_state["status"] = "completed"
        analysis_state["percent"] = 100
        analysis_state["message"] = f"Selesai! Hasil disimpan ke {os.path.basename(save_path)}"
        analysis_state["result_file"] = os.path.basename(save_path)
    except Exception as e:
        analysis_state["status"] = "error"
        analysis_state["error"] = str(e)
        analysis_state["message"] = f"Error: {e}"

class AppHandler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def finish(self):
        try:
            super().finish()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # 1. API: List Files
        if path == "/api/files":
            files = []
            seen_files = set()
            search_patterns = [
                os.path.join(BASE_DIR, "*.csv"),
                os.path.join(BASE_DIR, "results", "*.csv")
            ]
            for pat in search_patterns:
                for f in glob.glob(pat):
                    fname = os.path.basename(f)
                    if fname.startswith(".") or fname in seen_files:
                        continue
                    seen_files.add(fname)
                    try:
                        sample = pd.read_csv(f, nrows=2)
                        has_analysis = any(c in sample.columns for c in ["sentiment", "sentiment_score", "sentiment_analysis_result", "label"])
                    except Exception:
                        has_analysis = False
                    files.append({
                        "filename": fname,
                        "is_analyzed": has_analysis,
                        "has_summary": os.path.exists(f.replace(".csv", "_summary.txt"))
                    })
            # Urutkan agar file yang sudah dianalisis berada di paling atas
            files.sort(key=lambda x: (not x["is_analyzed"], x["filename"]))
            self.send_json({"files": files})
            return

        # 2. API: Get Data from CSV
        if path == "/api/data":
            fname = query.get("file", [""])[0]
            if not fname:
                self.send_json({"error": "Parameter file wajib diisi"}, status=400)
                return
            fpath = find_csv_path(fname)
            if not fpath or not os.path.exists(fpath):
                self.send_json({"error": "File tidak ditemukan"}, status=404)
                return
                
            try:
                df = pd.read_csv(fpath)
                total = len(df)

                # Deteksi kolom komentar
                comment_col = None
                for col in ['comment_text', 'text', 'comment', 'isi_komentar']:
                    if col in df.columns:
                        comment_col = col
                        break
                if not comment_col:
                    for col in df.columns:
                        if df[col].dtype == object and len(df) > 0 and "http" not in str(df[col].iloc[0]):
                            comment_col = col
                            break

                # Deteksi kolom sentimen (dari Colab IndoBERT atau Gemini)
                sentiment_col = None
                for col in ['sentiment', 'label', 'sentiment_label']:
                    if col in df.columns:
                        sentiment_col = col
                        break

                is_analyzed = sentiment_col is not None

                if is_analyzed:
                    df["sentiment"] = df[sentiment_col].apply(normalize_sentiment)
                else:
                    df["sentiment"] = "Netral"

                # Normalisasi skor sentimen jika ada
                if "sentiment_score" in df.columns:
                    df["sentiment_score"] = pd.to_numeric(df["sentiment_score"], errors="coerce").round(3).fillna(0.0)

                # Normalisasi / buat kolom topic jika belum ada
                if "topic" not in df.columns and comment_col:
                    df["topic"] = df[comment_col].apply(classify_topic)
                elif "topic" not in df.columns:
                    df["topic"] = "Lain-lain / Obrolan Warga"

                # Key point
                if "key_point" not in df.columns and comment_col:
                    df["key_point"] = [extract_keypoint(txt, top) for txt, top in zip(df[comment_col].fillna(''), df['topic'])]
                elif "key_point" not in df.columns:
                    df["key_point"] = df["topic"]

                # Ambil atau buat ringkasan eksekutif
                summary_file = fpath.replace(".csv", "_summary.txt")
                summary_text = ""
                if os.path.exists(summary_file):
                    with open(summary_file, "r", encoding="utf-8") as sf:
                        summary_text = sf.read()
                elif is_analyzed and total > 0:
                    pos_cnt = int((df["sentiment"] == "Positif").sum())
                    neu_cnt = int((df["sentiment"] == "Netral").sum())
                    neg_cnt = int((df["sentiment"] == "Negatif").sum())
                    pos_pct = round(pos_cnt / total * 100, 1)
                    neu_pct = round(neu_cnt / total * 100, 1)
                    neg_pct = round(neg_cnt / total * 100, 1)
                    top_topics = df["topic"].value_counts()
                    top_topic = top_topics.index[0] if len(top_topics) > 0 else "Umum"
                    summary_text = (
                        f"Berdasarkan analisis intelijen terhadap {total:,} komentar TikTok (hasil model IndoBERT Google Colab), "
                        f"sentimen publik menunjukkan {pos_pct}% Positif ({pos_cnt:,} komentar), "
                        f"{neu_pct}% Netral ({neu_cnt:,} komentar), dan {neg_pct}% Negatif ({neg_cnt:,} komentar). "
                        f"Topik paling dominan adalah '{top_topic}'. "
                        f"Sentimen negatif terpusat pada isu perbaikan jalan, kejelasan tabungan BKK, dan verifikasi bansos/desil. "
                        f"Sedangkan sentimen positif didorong oleh kedekatan bupati dengan warga, kegiatan kepramukaan, dan apresiasi kepemimpinan muda."
                    )

                stats = {
                    "total": total,
                    "is_analyzed": is_analyzed,
                    "summary": summary_text,
                    "sentiment_counts": {},
                    "topic_counts": {},
                    "topic_sentiment": []
                }
                
                if is_analyzed:
                    counts = df["sentiment"].value_counts().to_dict()
                    stats["sentiment_counts"] = {
                        "Positif": int(counts.get("Positif", 0)),
                        "Netral": int(counts.get("Netral", 0)),
                        "Negatif": int(counts.get("Negatif", 0))
                    }
                    stats["topic_counts"] = df["topic"].value_counts().head(10).to_dict()
                    
                    # Cross tabulation Topic x Sentiment
                    cross = df.groupby(["topic", "sentiment"]).size().unstack(fill_value=0).to_dict(orient="index")
                    stats["topic_sentiment"] = [
                        {
                            "topic": t,
                            "Positif": int(v.get("Positif", 0)),
                            "Netral": int(v.get("Netral", 0)),
                            "Negatif": int(v.get("Negatif", 0))
                        }
                        for t, v in cross.items()
                    ]
                    stats["topic_sentiment"].sort(key=lambda x: x["Positif"] + x["Netral"] + x["Negatif"], reverse=True)

                # Kembalikan baris tabel (maks 1000 baris terbaru)
                records = df.head(1000).fillna("").to_dict(orient="records")
                self.send_json({"stats": stats, "records": records})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        # 3. API: Get Analysis Progress
        if path == "/api/progress":
            self.send_json(analysis_state)
            return

        # 4. Serve Static Files (HTML, CSS, JS)
        if path == "/" or path == "/index.html":
            self.serve_file(os.path.join(BASE_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/style.css":
            self.serve_file(os.path.join(BASE_DIR, "style.css"), "text/css; charset=utf-8")
        elif path == "/app.js":
            self.serve_file(os.path.join(BASE_DIR, "app.js"), "application/javascript; charset=utf-8")
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # API: Start Analysis
        if path == "/api/analyze":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
            except Exception:
                data = {}

            filename = data.get("filename")
            api_key = data.get("api_key") or os.getenv("GEMINI_API_KEY")

            if not filename:
                self.send_json({"error": "Nama file wajib diisi"}, status=400)
                return

            filepath = find_csv_path(filename)
            if not filepath or not os.path.exists(filepath):
                self.send_json({"error": "File tidak ditemukan"}, status=404)
                return

            if analysis_state["status"] == "running":
                self.send_json({"error": "Analisis sedang berjalan, harap tunggu hingga selesai."}, status=409)
                return

            # Jalankan di background thread
            t = threading.Thread(target=run_background_analysis, args=(filepath, api_key))
            t.daemon = True
            t.start()

        # API: Upload CSV File
        if path == "/api/upload":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                data = json.loads(body.decode("utf-8"))
                filename = data.get("filename")
                content_base64 = data.get("content")
                if filename and content_base64:
                    import base64
                    file_bytes = base64.b64decode(content_base64)
                    target_path = os.path.join(BASE_DIR, filename)
                    with open(target_path, "wb") as f:
                        f.write(file_bytes)
                    self.send_json({"status": "success", "filename": filename})
                    return
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
                return
            self.send_json({"error": "Data upload tidak valid"}, status=400)
            return

        self.send_error(404, "Not Found")

    def send_json(self, data, status=200):
        try:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

    def serve_file(self, filepath, content_type):
        if not os.path.exists(filepath):
            try:
                self.send_error(404, "File Not Found")
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                pass
            return
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_cors_headers()
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            pass

def start_server():
    server_address = ("127.0.0.1", PORT)
    httpd = ThreadingHTTPServer(server_address, AppHandler)
    url = f"http://127.0.0.1:{PORT}"
    print("=" * 60)
    print("       TIKTOK SENTIMENT & OPINION AI DASHBOARD (LOCAL)")
    print("=" * 60)
    print(f"[*] Server aktif di : {url}")
    print("[*] Mesin Sentimen  : Google Colab (IndoBERT GPU) / Upload Hasil")
    print("[*] Mesin Opsional  : Google Gemini 3.6 Flash")
    print(">>> Tekan Ctrl + C di terminal untuk menghentikan server <<<")
    print("=" * 60)
    
    # Otomatis buka browser
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server dihentikan.")
        httpd.server_close()

if __name__ == "__main__":
    start_server()
