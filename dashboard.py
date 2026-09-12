import os
import glob
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

# Import mesin analisis
from analyzer import analyze_comments_df, generate_executive_summary

load_dotenv()

# ==========================================
# 1. KONFIGURASI HALAMAN & TEMA
# ==========================================
st.set_page_config(
    page_title="TikTok Opinion & Sentiment AI Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS untuk estetika modern & premium
st.markdown("""
<style>
    /* Gradient Header & Metric Cards */
    .metric-card {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        padding: 16px 20px;
        text-align: center;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
        transition: transform 0.2s ease;
    }
    .metric-card:hover {
        transform: translateY(-2px);
    }
    .metric-title {
        font-size: 0.85rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 6px;
    }
    .metric-val {
        font-size: 1.8rem;
        font-weight: 700;
        margin: 0;
    }
    .val-pos { color: #10b981; }
    .val-neu { color: #f59e0b; }
    .val-neg { color: #ef4444; }
    .val-net { color: #3b82f6; }

    /* AI Executive Card */
    .ai-box {
        background: linear-gradient(135deg, rgba(30, 41, 59, 0.8) 0%, rgba(15, 23, 42, 0.9) 100%);
        border-left: 4px solid #3b82f6;
        border-radius: 10px;
        padding: 20px 24px;
        margin-bottom: 25px;
        box-shadow: 0 4px 15px rgba(0, 0, 0, 0.2);
    }
    .ai-header {
        display: flex;
        align-items: center;
        gap: 10px;
        font-size: 1.1rem;
        font-weight: 600;
        color: #60a5fa;
        margin-bottom: 12px;
    }
    .ai-content {
        font-size: 0.95rem;
        line-height: 1.6;
        color: #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# Palet warna sentimen yang harmonis
COLOR_MAP = {
    "Positif": "#10b981",  # Emerald
    "Netral": "#f59e0b",   # Amber
    "Negatif": "#ef4444"   # Rose
}

# ==========================================
# 2. SIDEBAR KONTROL & INPUT
# ==========================================
st.sidebar.title("⚙️ Kontrol & Data")

# Deteksi file CSV yang ada di direktori root dan seluruh subfolder results/
csv_files = (
    glob.glob("*.csv") +
    glob.glob("results/*.csv") +
    glob.glob("results/*/*.csv") +
    glob.glob("results/**/*.csv", recursive=True)
)
# Urutkan berdasarkan waktu modifikasi terbaru
csv_files = sorted(list(set(csv_files)), key=lambda x: os.path.getmtime(x) if os.path.exists(x) else 0, reverse=True)
available_files = [f for f in csv_files if os.path.isfile(f)]

def format_file_label(fpath):
    parts = fpath.replace("\\", "/").split("/")
    fname = os.path.basename(fpath)
    if len(parts) >= 3 and parts[0] == "results":
        return f"[{parts[1]}] {fname}"
    elif len(parts) == 2 and parts[0] == "results":
        return f"[results] {fname}"
    return fname

if not available_files:
    st.sidebar.warning("Tidak ditemukan file CSV di folder ini. Silakan jalankan scraper terlebih dahulu.")
    selected_file = None
else:
    # Prioritaskan file _analyzed jika ada
    default_idx = 0
    for i, f in enumerate(available_files):
        if "_analyzed" in f:
            default_idx = i
            break
    selected_file = st.sidebar.selectbox("Pilih File Komentar CSV:", available_files, index=default_idx, format_func=format_file_label)

# Input Gemini API Key
env_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
api_key = st.sidebar.text_input(
    "Google Gemini API Key:",
    value=env_key,
    type="password",
    help="Dapatkan key gratis di https://aistudio.google.com/"
)

# Tombol Analisis AI jika file belum dianalisis atau ingin analisis ulang
is_analyzed = selected_file and "_analyzed" in selected_file
st.sidebar.markdown("---")

if selected_file:
    df_raw = pd.read_csv(selected_file)
    has_sentiment_col = 'sentiment' in df_raw.columns and 'topic' in df_raw.columns

    btn_label = "🔄 Analisis Ulang dengan Gemini AI" if has_sentiment_col else "🚀 Mulai Analisis AI (Gemini Flash)"
    if st.sidebar.button(btn_label, use_container_width=True):
        if not api_key:
            st.sidebar.error("Masukkan Gemini API Key terlebih dahulu!")
        else:
            with st.spinner("Sedang menganalisis komentar secara cerdas menggunakan Gemini AI..."):
                progress_bar = st.sidebar.progress(0.0)
                status_txt = st.sidebar.empty()
                
                def update_prog(ratio):
                    progress_bar.progress(ratio)
                    status_txt.text(f"Menganalisis... {int(ratio * 100)}%")

                try:
                    df_res = analyze_comments_df(
                        df_raw.copy(),
                        api_key=api_key,
                        batch_size=30,
                        progress_callback=update_prog
                    )
                    
                    # Simpan hasil analisis
                    save_name = selected_file if "_analyzed" in selected_file else selected_file.replace(".csv", "_analyzed.csv")
                    df_res.to_csv(save_name, index=False, encoding='utf-8')
                    
                    # Buat Executive Summary jika belum ada
                    exec_summary = generate_executive_summary(df_res, api_key=api_key)
                    summary_file = save_name.replace(".csv", "_summary.txt")
                    with open(summary_file, "w", encoding="utf-8") as sf:
                        sf.write(exec_summary)

                    st.sidebar.success(f"Analisis Selesai! Data disimpan ke {save_name}")
                    st.rerun()
                except Exception as e:
                    st.sidebar.error(f"Gagal analisis: {e}")

# ==========================================
# 3. KONTEN UTAMA DASHBOARD
# ==========================================
st.title("📊 TikTok Public Opinion & Sentiment Intelligence")
st.caption("Dashboard Pemantauan Sentimen Publik dan Isu Hangat Berbasis Google Gemini LLM")

if not selected_file or df_raw is None or len(df_raw) == 0:
    st.info("👋 Silakan pilih file CSV komentar di sidebar sebelah kiri untuk mulai mengeksplorasi data.")
    st.stop()

# Cek apakah file sudah memiliki kolom sentimen
if not ('sentiment' in df_raw.columns and 'topic' in df_raw.columns):
    st.warning(f"File **{selected_file}** belum memiliki hasil klasifikasi sentimen & topik.")
    st.info("👉 Masukkan Gemini API Key di sidebar sebelah kiri, lalu klik tombol **'Mulai Analisis AI (Gemini Flash)'** untuk menganalisis komentar ini secara otomatis!")
    
    # Preview data mentah
    st.subheader("Preview Data Mentah:")
    preview_cols = [c for c in ['platform', 'post_author', 'profile_name', 'username', 'comment_text', 'post_description', 'description', 'likes', 'video_url', 'post_url'] if c in df_raw.columns]
    if not preview_cols:
        preview_cols = df_raw.columns[:6].tolist()
    st.dataframe(df_raw[preview_cols].head(10), use_container_width=True)
    st.stop()

df = df_raw.copy()

# ==========================================
# 4. EXECUTIVE AI BRIEF CARD
# ==========================================
summary_file = selected_file.replace(".csv", "_summary.txt")
exec_text = ""
if os.path.exists(summary_file):
    with open(summary_file, "r", encoding="utf-8") as sf:
        exec_text = sf.read()

if exec_text:
    st.markdown(f"""
    <div class="ai-box">
        <div class="ai-header">
            <span>✨</span> Ringkasan Eksekutif Opini Publik (AI Intel Brief)
        </div>
        <div class="ai-content">
            {exec_text.replace(chr(10), '<br>')}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ==========================================
# 5. METRIC KPI CARDS
# ==========================================
total_comms = len(df)
pos_count = (df['sentiment'] == 'Positif').sum()
neu_count = (df['sentiment'] == 'Netral').sum()
neg_count = (df['sentiment'] == 'Negatif').sum()

pos_pct = (pos_count / total_comms * 100) if total_comms > 0 else 0
neu_pct = (neu_count / total_comms * 100) if total_comms > 0 else 0
neg_pct = (neg_count / total_comms * 100) if total_comms > 0 else 0
net_sentiment = pos_pct - neg_pct

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Total Komentar/Data</div>
        <div class="metric-val">{total_comms:,}</div>
    </div>
    """, unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Sentimen Positif</div>
        <div class="metric-val val-pos">{pos_pct:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Sentimen Netral</div>
        <div class="metric-val val-neu">{neu_pct:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with c4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Sentimen Negatif</div>
        <div class="metric-val val-neg">{neg_pct:.1f}%</div>
    </div>
    """, unsafe_allow_html=True)
with c5:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-title">Net Sentiment (NPS)</div>
        <div class="metric-val val-net">{net_sentiment:+.1f}</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# ==========================================
# 6. FILTER DINAMIS
# ==========================================
with st.expander("🔍 Filter & Eksplorasi Data", expanded=False):
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        selected_sentiments = st.multiselect(
            "Filter Sentimen:",
            options=["Positif", "Netral", "Negatif"],
            default=["Positif", "Netral", "Negatif"]
        )
    with f_col2:
        all_topics = sorted(df['topic'].dropna().unique().tolist())
        selected_topics = st.multiselect(
            "Filter Isu/Topik:",
            options=all_topics,
            default=all_topics
        )
    with f_col3:
        search_kw = st.text_input("Cari Kata Kunci:", placeholder="misal: bkk, jalan, sekolah, nama warga...")

# Aplikasikan Filter
filtered_df = df[
    (df['sentiment'].isin(selected_sentiments)) &
    (df['topic'].isin(selected_topics))
]
if search_kw.strip():
    kw = search_kw.strip().lower()
    search_mask = pd.Series(False, index=filtered_df.index)
    for col_k in ['comment_text', 'description', 'post_text', 'key_point', 'profile_name', 'username', 'author_name']:
        if col_k in filtered_df.columns:
            search_mask = search_mask | filtered_df[col_k].fillna('').astype(str).str.lower().str.contains(kw)
    filtered_df = filtered_df[search_mask]

# ==========================================
# 7. GRAFIK & VISUALISASI DATA (PLOTLY)
# ==========================================
g_row1_col1, g_row1_col2 = st.columns([1, 1.4])

with g_row1_col1:
    st.subheader("Distribusi Sentimen")
    sent_dist = filtered_df['sentiment'].value_counts().reset_index()
    sent_dist.columns = ['Sentimen', 'Jumlah']
    
    fig_donut = px.pie(
        sent_dist,
        names='Sentimen',
        values='Jumlah',
        color='Sentimen',
        color_discrete_map=COLOR_MAP,
        hole=0.55
    )
    fig_donut.update_traces(textinfo='percent+label', hoverinfo='label+value+percent')
    fig_donut.update_layout(
        showlegend=False,
        margin=dict(t=20, b=20, l=20, r=20),
        height=320
    )
    st.plotly_chart(fig_donut, use_container_width=True)

with g_row1_col2:
    st.subheader("Topik & Isu Hangat yang Paling Dibicarakan")
    topic_counts = filtered_df['topic'].value_counts().head(8).reset_index()
    topic_counts.columns = ['Topik', 'Jumlah Data']
    
    fig_bar = px.bar(
        topic_counts,
        x='Jumlah Data',
        y='Topik',
        orientation='h',
        color='Jumlah Data',
        color_continuous_scale='Blues'
    )
    fig_bar.update_layout(
        yaxis={'categoryorder': 'total ascending'},
        margin=dict(t=20, b=20, l=20, r=20),
        height=320,
        showlegend=False
    )
    st.plotly_chart(fig_bar, use_container_width=True)

# Baris Grafik 2: Cross Tabulation (Sentimen per Isu)
st.subheader("Analisis Silang: Sentimen Warga untuk Tiap Isu")
topic_sent = filtered_df.groupby(['topic', 'sentiment']).size().reset_index(name='count')
top_order = filtered_df['topic'].value_counts().head(7).index.tolist()
topic_sent_filtered = topic_sent[topic_sent['topic'].isin(top_order)]

fig_stacked = px.bar(
    topic_sent_filtered,
    x='topic',
    y='count',
    color='sentiment',
    color_discrete_map=COLOR_MAP,
    barmode='stack',
    labels={'topic': 'Kategori Isu', 'count': 'Jumlah Data', 'sentiment': 'Sentimen'}
)
fig_stacked.update_layout(
    margin=dict(t=20, b=20, l=20, r=20),
    height=340,
    xaxis_tickangle=-20
)
st.plotly_chart(fig_stacked, use_container_width=True)

# ==========================================
# 8. TABEL EKSPLORASI KOMENTAR & EXPORT
# ==========================================
st.subheader("📋 Eksplorasi Detail Data & Komentar")
st.caption(f"Menampilkan {len(filtered_df):,} dari {len(df):,} baris sesuai filter.")

cols_to_show = ['sentiment', 'topic', 'key_point', 'comment_text', 'post_description', 'description', 'likes', 'shares', 'plays', 'post_author', 'profile_name', 'username', 'platform', 'comment_date', 'post_date', 'video_url']
available_cols = [c for c in cols_to_show if c in filtered_df.columns]

# Format styling badge sentimen
def highlight_sentiment(val):
    if val == "Positif":
        return "background-color: rgba(16, 185, 129, 0.2); color: #10b981; font-weight: bold;"
    elif val == "Negatif":
        return "background-color: rgba(239, 68, 68, 0.2); color: #ef4444; font-weight: bold;"
    return "background-color: rgba(245, 158, 11, 0.2); color: #f59e0b;"

styler = filtered_df[available_cols].style
subset_col = ['sentiment'] if 'sentiment' in available_cols else []
if hasattr(styler, 'map'):
    styled_df = styler.map(highlight_sentiment, subset=subset_col)
else:
    styled_df = styler.applymap(highlight_sentiment, subset=subset_col)

st.dataframe(
    styled_df,
    use_container_width=True,
    height=380
)

# Tombol Download
csv_data = filtered_df.to_csv(index=False).encode('utf-8')
st.download_button(
    label="📥 Unduh Data Hasil Filter (CSV)",
    data=csv_data,
    file_name=f"hasil_analisis_{selected_file}",
    mime="text/csv"
)
