import sys
# Pastikan encoding output terminal mendukung karakter UTF-8 / emoji & flush instan
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

import os
import re
import csv
import time
import json
import random
import hashlib
import threading
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# Folder output default untuk menyimpan seluruh file CSV hasil scraping
def get_daily_results_dir():
    """
    Mengembalikan path folder hasil harian di dalam results/
    Format: results/{hari}-{bulan} (contoh: results/11-9 atau results/9-10)
    Folder dibuat otomatis jika belum ada.
    """
    now = datetime.now()
    daily_folder = f"{now.day}-{now.month}"
    daily_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", daily_folder)
    os.makedirs(daily_path, exist_ok=True)
    return daily_path


RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Standard CSV Headers (25 Columns for Posts / Articles, 14 Columns for Comments)
POSTS_CSV_HEADER = [
    "platform", "search_keyword", "post_id", "post_date", "profile_name",
    "profile_url", "bio", "followers_count", "following_count", "followers_list",
    "following_list", "description", "likes", "shares", "plays",
    "comments_count", "video_subtitles", "text_language", "hashtags_used", "is_ad",
    "is_pinned", "is_sponsored", "location_of_creation", "music_meta", "video_url"
]

COMMENTS_CSV_HEADER = [
    "platform", "search_keyword", "post_id", "comment_id", "comment_date",
    "profile_name", "username", "profile_url", "comment_text", "likes",
    "reply_count", "is_reply", "reply_to", "video_url"
]

# Thread-safe Locks & Global Deduplication Tracking
csv_lock = threading.Lock()
seen_lock = threading.Lock()
global_seen_urls = set()

# Default HTTP Request Headers
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
    'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Upgrade-Insecure-Requests': '1',
}

# ==========================================
# KONTROLER JEDA (PAUSE / RESUME / STOP)
# ==========================================
try:
    import msvcrt
except ImportError:
    msvcrt = None


class PauseController:
    """
    Kontroler Jeda (Pause / Resume / Stop) Interaktif & Thread-Safe.
    - Tekan 'P' atau 'Space' : Jeda (Pause) / Lanjut (Resume)
    - Tekan 'Q'             : Berhenti secara aman & simpan seluruh data ke CSV
    """
    def __init__(self):
        self.is_paused = False
        self.stop_requested = False
        self.lock = threading.Lock()
        self._listener_thread = None
        self._start_keyboard_listener()

    def _start_keyboard_listener(self):
        if msvcrt is None:
            return
        self._listener_thread = threading.Thread(target=self._listen_keyboard, daemon=True)
        self._listener_thread.start()

    def _listen_keyboard(self):
        while True:
            try:
                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    try:
                        char = ch.decode('utf-8', errors='ignore').lower()
                    except Exception:
                        char = ''

                    if char in ['p', ' ']:
                        self.toggle_pause()
                    elif char == 'q':
                        self.request_stop()
                time.sleep(0.1)
            except Exception:
                time.sleep(0.2)

    def toggle_pause(self):
        with self.lock:
            self.is_paused = not self.is_paused
            if self.is_paused:
                print("\n" + "=" * 65)
                print("  [PAUSED] SCRAPING DIJEDA / DIHENTIKAN SEMENTARA")
                print("  Status : Seluruh artikel yang sudah di-scrape tersimpan AMAN di CSV.")
                print("  -------------------------------------------------------------")
                print("  * Tekan tombol [P] atau [SPACE] di keyboard untuk MELANJUTKAN (Resume).")
                print("  * Tekan tombol [Q] di keyboard untuk BERHENTI & SIMPAN Hasil Sekarang.")
                print("=" * 65 + "\n", flush=True)
            else:
                print("\n" + "=" * 65)
                print("  [RESUMED] >> Melanjutkan proses scraping berita kembali...")
                print("=" * 65 + "\n", flush=True)

    def request_stop(self):
        with self.lock:
            self.stop_requested = True
            self.is_paused = False
            print("\n" + "=" * 65)
            print("  [STOP REQUESTED] Menghentikan scraping secara aman & menyimpan seluruh data...")
            print("=" * 65 + "\n", flush=True)

    def is_stopped(self):
        return self.stop_requested

    def check_pause(self):
        while self.is_paused and not self.stop_requested:
            time.sleep(0.2)
        return not self.stop_requested

    def sleep(self, seconds):
        steps = max(1, int(seconds / 0.1))
        for _ in range(steps):
            if self.stop_requested:
                break
            while self.is_paused and not self.stop_requested:
                time.sleep(0.2)
            time.sleep(0.1)


pause_ctrl = PauseController()


# ==========================================
# FUNGSI HELPER TEXT & DATE
# ==========================================
def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\r\n\t]+', ' ', str(text))
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def standardize_date(raw_date):
    """
    Mengubah format tanggal berita dari berbagai portal ke format standar: YYYY-MM-DD HH:MM:SS
    """
    if not raw_date:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    raw_date = str(raw_date).strip()

    # ISO Format: 2026-09-05T06:30:22+00:00 atau 2026-08-28T08-29-19Z
    iso_match = re.search(r'(\d{4})-(\d{2})-(\d{2})[T\s](\d{2})[:\-](\d{2})[:\-](\d{2})', raw_date)
    if iso_match:
        y, m, d, hh, mm, ss = iso_match.groups()
        return f"{y}-{m}-{d} {hh}:{mm}:{ss}"

    # Format YYYY-MM-DD
    simple_iso = re.search(r'(\d{4})-(\d{2})-(\d{2})', raw_date)
    if simple_iso:
        y, m, d = simple_iso.groups()
        return f"{y}-{m}-{d} 00:00:00"

    # Indonesian Month Names mapping
    months_id = {
        'januari': '01', 'jan': '01',
        'februari': '02', 'feb': '02',
        'maret': '03', 'mar': '03',
        'april': '04', 'apr': '04',
        'mei': '05', 'may': '05',
        'juni': '06', 'jun': '06',
        'juli': '07', 'jul': '07',
        'agustus': '08', 'agu': '08', 'agt': '08',
        'september': '09', 'sep': '09',
        'oktober': '10', 'okt': '10', 'oct': '10',
        'november': '11', 'nov': '11',
        'desember': '12', 'des': '12', 'dec': '12'
    }

    # Format: "Jumat, 20 Februari 2026 13:24 WIB" atau "20 Feb 2026, 13:24"
    date_pat = re.search(r'(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})(?:\s+(\d{1,2})[:\.](\d{2}))?', raw_date, re.IGNORECASE)
    if date_pat:
        d = int(date_pat.group(1))
        m_str = date_pat.group(2).lower()
        y = date_pat.group(3)
        hh = date_pat.group(4) if date_pat.group(4) else "00"
        mm = date_pat.group(5) if date_pat.group(5) else "00"
        m = months_id.get(m_str, "01")
        return f"{y}-{m}-{d:02d} {int(hh):02d}:{int(mm):02d}:00"

    # Format relatif: "5 jam yang lalu", "10 menit lalu", "2 hari yang lalu"
    rel_match = re.search(r'(\d+)\s*(jam|menit|hari|detik)\s*(yang)?\s*lalu', raw_date, re.IGNORECASE)
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2).lower()
        now = datetime.now()
        if 'menit' in unit:
            return (now - datetime.timedelta(minutes=val)).strftime("%Y-%m-%d %H:%M:%S")
        elif 'jam' in unit:
            return (now - datetime.timedelta(hours=val)).strftime("%Y-%m-%d %H:%M:%S")
        elif 'hari' in unit:
            return (now - datetime.timedelta(days=val)).strftime("%Y-%m-%d %H:%M:%S")

    return raw_date


def detect_platform(url):
    """
    Mendeteksi nama portal media dari domain URL artikel.
    """
    url_lower = url.lower()
    if 'detik.com' in url_lower: return 'Detik.com'
    if 'kompas.com' in url_lower: return 'Kompas.com'
    if 'tribunnews.com' in url_lower or 'tribun' in url_lower: return 'Tribunnews.com'
    if 'solopos' in url_lower or 'espos.id' in url_lower: return 'Solopos.com'
    if 'antaranews.com' in url_lower: return 'AntaraNews.com'
    if 'tempo.co' in url_lower: return 'Tempo.co'
    if 'liputan6.com' in url_lower: return 'Liputan6.com'
    if 'cnnindonesia.com' in url_lower: return 'CNN Indonesia'
    if 'cnbcindonesia.com' in url_lower: return 'CNBC Indonesia'
    if 'sindonews.com' in url_lower: return 'Sindonews.com'
    if 'merdeka.com' in url_lower: return 'Merdeka.com'
    if 'kumparan.com' in url_lower: return 'Kumparan'
    if 'idntimes.com' in url_lower: return 'IDN Times'
    if 'jawapos.com' in url_lower or 'radarsolo' in url_lower: return 'Jawa Pos'
    if 'rri.co.id' in url_lower: return 'RRI'
    if 'suara.com' in url_lower: return 'Suara.com'
    if 'inews.id' in url_lower: return 'iNews.id'
    if 'viva.co.id' in url_lower: return 'VIVA.co.id'
    
    # Fallback to domain name
    domain_match = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if domain_match:
        return domain_match.group(1).capitalize()
    return "Media Online"


def extract_location(text, title=""):
    """
    Mendeteksi kota / lokasi pembuatan berita (Dateline / Location of Creation).
    """
    combined = f"{title} {text[:300]}"
    cities = [
        ("Klaten", ["klaten", "pemkab klaten"]),
        ("Solo", ["solo", "surakarta"]),
        ("Yogyakarta", ["jogja", "yogyakarta", "diy"]),
        ("Boyolali", ["boyolali"]),
        ("Sukoharjo", ["sukoharjo"]),
        ("Karanganyar", ["karanganyar"]),
        ("Wonogiri", ["wonogiri"]),
        ("Sragen", ["sragen"]),
        ("Semarang", ["semarang"]),
        ("Magelang", ["magelang"]),
        ("Jakarta", ["jakarta"]),
        ("Surabaya", ["surabaya"]),
        ("Bandung", ["bandung"]),
        ("Medan", ["medan"]),
        ("Makassar", ["makassar"]),
        ("Bali", ["denpasar", "bali"]),
        ("Banyumas", ["purwokerto", "banyumas"])
    ]

    # Cek pola dateline di awal berita e.g. "KLATEN —", "SOLO, KOMPAS.com —"
    loc_match = re.match(r'^([A-Z\s]{3,20})\s*([,—\-–])', text.strip())
    if loc_match:
        lead = loc_match.group(1).strip().lower()
        for city_name, aliases in cities:
            if any(alias in lead for alias in aliases):
                return city_name

    for city_name, aliases in cities:
        if any(alias in combined.lower() for alias in aliases):
            return city_name

    return ""


# ==========================================
# PARSER KONTEN ARTIKEL DETAIL
# ==========================================
def parse_article_detail(url, session=None):
    """
    Membuka dan mengekstrak konten lengkap, metadata jurnalis, tanggal, tags, dan rubrik artikel berita.
    """
    req_session = session or requests.Session()
    try:
        resp = req_session.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code != 200:
            return None
        
        # Deteksi encoding
        if resp.encoding is None or resp.encoding == 'ISO-8859-1':
            resp.encoding = resp.apparent_encoding or 'utf-8'

        soup = BeautifulSoup(resp.text, 'html.parser')

        # 1. Platform
        platform = detect_platform(url)

        # 2. Judul Berita (Headline)
        title = ""
        og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
        if og_title and og_title.get('content'):
            title = og_title['content']
        elif soup.find('h1'):
            title = soup.find('h1').get_text()
        
        title = clean_text(title)
        # Bersihkan akhiran portal di title (contoh: " - detikcom", " - Kompas.com")
        title = re.sub(r'\s*[-|–]\s*(detikcom|kompas\.com|solopos\.com|tribunnews\.com|tempo\.co|antara|liputan6\.com|cnn indonesia|sindonews|merdeka\.com|idntimes).*$', '', title, flags=re.IGNORECASE).strip()

        if not title or len(title) < 5:
            return None

        # 3. Penulis / Jurnalis / Redaksi (Profile Name)
        author = ""
        auth_meta = (
            soup.find('meta', attrs={'name': 'author'}) or
            soup.find('meta', property='article:author') or
            soup.find('meta', property='dable:author') or
            soup.find('meta', attrs={'name': 'reporter'})
        )
        if auth_meta and auth_meta.get('content'):
            author = clean_text(auth_meta['content'])
        else:
            auth_el = soup.select_one('.author, .penulis, .read__author, .detail__author, .media-author, .side-article-author, .credit, .article__author')
            if auth_el:
                author = clean_text(auth_el.get_text())
                author = re.sub(r'^(Penulis|Reporter|Editor|Oleh|Author|Jurnalis)\s*:\s*', '', author, flags=re.IGNORECASE).strip()

        if not author:
            author = f"Redaksi {platform}"

        # 4. Tanggal Publikasi (Post Date)
        date_str = ""
        pub_meta = (
            soup.find('meta', property='article:published_time') or
            soup.find('meta', attrs={'name': 'pubdate'}) or
            soup.find('meta', property='og:updated_time') or
            soup.find('meta', attrs={'name': 'publishdate'})
        )
        if pub_meta and pub_meta.get('content'):
            date_str = standardize_date(pub_meta['content'])
        else:
            date_el = soup.select_one('.date, .read__time, .detail__date, .media-date, time, .side-article-time, .article__date')
            if date_el:
                date_str = standardize_date(date_el.get_text())
            else:
                date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 5. Tags / Hashtags Digunakan
        tags = []
        kw_meta = soup.find('meta', attrs={'name': 'keywords'}) or soup.find('meta', property='article:tag')
        if kw_meta and kw_meta.get('content'):
            raw_tags = kw_meta['content'].split(',')
            for t in raw_tags:
                tc = clean_text(t)
                if tc and len(tc) > 2 and tc.lower() not in ['berita', 'terkini', 'hari ini', 'indonesia']:
                    tags.append(tc)
        else:
            for tag_el in soup.select('.tag a, .tags a, .topic a, .detail__tags a, .tag-cloud a, .article-tags a'):
                tc = clean_text(tag_el.get_text())
                if tc and len(tc) > 2:
                    tags.append(tc)

        # Format hashtags with #
        formatted_tags = []
        for t in tags[:12]:
            t_tag = re.sub(r'[^\w\s]', '', t).strip().replace(' ', '_')
            if t_tag:
                formatted_tags.append(f"#{t_tag}")
        hashtags_used = ", ".join(formatted_tags)

        # 6. Kategori / Rubrik (Music Meta / Category)
        category = ""
        sec_meta = soup.find('meta', property='article:section')
        if sec_meta and sec_meta.get('content'):
            category = f"Rubrik: {clean_text(sec_meta['content'])}"
        else:
            bread = soup.select('.breadcrumb a, .breadcrumb-item a')
            if len(bread) > 1:
                category = f"Rubrik: {clean_text(bread[1].get_text())}"

        # 7. Isi Berita (Body Paragraphs)
        body_parts = []
        body_selectors = [
            '.post-body', '.single-content', '.read__content', '.detail__body-text',
            '.entry-content', '.article-content', '.post-content', '#article-body',
            '.content-text', '.side-article-txt', '.txt-article', '.detail_text',
            '.article__body', '.news-text'
        ]
        container = None
        for sel in body_selectors:
            found = soup.select_one(sel)
            if found and len(found.find_all('p')) >= 2:
                container = found
                break

        if container:
            # Hapus iklan, widget baca juga, video terkait
            for unwanted in container.select('script, style, iframe, .ads, .baca-juga, .related, .link-terkait, .video-container, .dable-widget'):
                unwanted.decompose()
            for p in container.find_all('p'):
                txt = clean_text(p.get_text())
                if txt and len(txt) > 20 and not re.match(r'^(Baca juga|Simak Video|Pilihan Editor|Video Terkait|Tonton juga)', txt, re.I):
                    body_parts.append(txt)
        else:
            for p in soup.find_all('p'):
                txt = clean_text(p.get_text())
                if len(txt) > 40 and not re.match(r'^(Baca juga|Simak Video|Pilihan Editor|Copyright|All rights reserved)', txt, re.I):
                    body_parts.append(txt)

        full_body = "\n\n".join(body_parts)

        # 8. Ringkasan / Snippet (Video Subtitles)
        snippet = ""
        desc_meta = soup.find('meta', attrs={'name': 'description'}) or soup.find('meta', property='og:description')
        if desc_meta and desc_meta.get('content'):
            snippet = clean_text(desc_meta['content'])
        elif body_parts:
            snippet = body_parts[0][:200]

        # 9. Format Deskripsi Lengkap: [JUDUL] ... \n\n [BERITA] ...
        if full_body:
            description = f"[JUDUL] {title}\n\n[BERITA]\n{full_body}"
        else:
            description = f"[JUDUL] {title}\n\n{snippet}"

        # 10. Lokasi Pembuatan (Dateline / Location)
        location = extract_location(full_body, title)

        # 11. Post ID (ID artikel atau hash URL)
        id_match = re.search(r'[/-](\d{5,15})(?:\.html|/|$)', url)
        if id_match:
            post_id = f"{platform.split('.')[0].lower()}_{id_match.group(1)}"
        else:
            post_id = f"{platform.split('.')[0].lower()}_{hashlib.md5(url.encode()).hexdigest()[:12]}"

        # 12. Profil URL & Bio
        domain_match = re.search(r'^(https?://[^/]+)', url)
        profile_url = domain_match.group(1) if domain_match else f"https://www.{platform.lower()}"
        bio = f"Portal Berita Online - {platform} ({category if category else 'Nasional & Daerah'})"

        return {
            "platform": platform,
            "search_keyword": "",  # Diisi di caller
            "post_id": post_id,
            "post_date": date_str,
            "profile_name": author,
            "profile_url": profile_url,
            "bio": bio,
            "followers_count": 0,
            "following_count": 0,
            "followers_list": "",
            "following_list": "",
            "description": description,
            "likes": 0,
            "shares": 0,
            "plays": 0,
            "comments_count": 0,
            "video_subtitles": snippet,
            "text_language": "id",
            "hashtags_used": hashtags_used,
            "is_ad": "No",
            "is_pinned": "No",
            "is_sponsored": "No",
            "location_of_creation": location,
            "music_meta": category,
            "video_url": url
        }
    except Exception as e:
        return None


# ==========================================
# SEARCH ENGINES & PORTAL ADAPTERS
# ==========================================
def search_duckduckgo(keyword, max_results=30, session=None):
    """
    Search Engine Multi-Portal Aggregator via DuckDuckGo HTML.
    Mencakup Detik, Kompas, Tribunnews, Solopos, Antaranews, Tempo, Liputan6, CNN Indonesia, Sindonews, dll.
    """
    req_session = session or requests.Session()
    domains = [
        "detik.com", "kompas.com", "tribunnews.com", "solopos.espos.id",
        "antaranews.com", "tempo.co", "liputan6.com", "cnnindonesia.com",
        "sindonews.com", "merdeka.com", "kumparan.com", "radarsolo.jawapos.com",
        "suara.com", "rri.co.id"
    ]
    query = f"{keyword} (" + " OR ".join([f"site:{d}" for d in domains]) + ")"
    url = "https://html.duckduckgo.com/html/"
    
    results = []
    try:
        resp = req_session.post(url, data={"q": query}, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for el in soup.select('.result'):
                title_el = el.select_one('.result__title a')
                if not title_el:
                    continue
                href = title_el.get('href', '')
                if 'uddg=' in href:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    if 'uddg' in qs:
                        href = qs['uddg'][0]
                
                # Filter out tag and search index pages
                if href and href.startswith('http') and not any(x in href for x in ['/tag/', '/tags/', '/search', '/indeks', '/topik/']):
                    results.append(href)
                if len(results) >= max_results:
                    break
    except Exception as e:
        print(f"  [!] Gagal mencari di DuckDuckGo: {e}")

    return results


def search_detik(keyword, max_results=30, session=None):
    """
    Search Engine Khusus Detik.com
    """
    req_session = session or requests.Session()
    results = []
    page = 1
    while len(results) < max_results and page <= 5:
        url = f"https://www.detik.com/search/searchall?query={urllib.parse.quote(keyword)}&sortby=time&page={page}"
        try:
            resp = req_session.get(url, headers=DEFAULT_HEADERS, timeout=12)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, 'html.parser')
            articles = soup.select('article')
            if not articles:
                break
            for art in articles:
                a = art.select_one('a')
                if a and a.get('href') and 'detik.com' in a['href']:
                    href = a['href']
                    if not any(x in href for x in ['/tag/', '/search', '/foto/']):
                        results.append(href)
                if len(results) >= max_results:
                    break
            page += 1
        except Exception:
            break
    return results


def search_kompas(keyword, max_results=30, session=None):
    """
    Search Engine Khusus Kompas.com
    """
    req_session = session or requests.Session()
    results = []
    page = 1
    while len(results) < max_results and page <= 4:
        url = f"https://search.kompas.com/search?q={urllib.parse.quote(keyword)}&sort=latest&page={page}"
        try:
            resp = req_session.get(url, headers=DEFAULT_HEADERS, timeout=12)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, 'html.parser')
            items = soup.select('.article__list, .articleItem, .search__item, .gsc-webResult')
            if not items:
                break
            for it in items:
                a = it.select_one('a')
                if a and a.get('href') and 'kompas.com' in a['href']:
                    href = a['href']
                    if '/read/' in href:
                        results.append(href)
                if len(results) >= max_results:
                    break
            page += 1
        except Exception:
            break
    return results


def search_solopos(keyword, max_results=30, session=None):
    """
    Search Engine Khusus Solopos.com / Espos.id (Portal Utama Wilayah Solo Raya & Klaten)
    """
    req_session = session or requests.Session()
    results = []
    url = f"https://solopos.espos.id/?s={urllib.parse.quote(keyword)}"
    try:
        resp = req_session.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for art in soup.select('article, .post-item, .card, .elementor-post'):
                a = art.select_one('a')
                if a and a.get('href'):
                    href = a['href']
                    if ('solopos' in href or 'espos.id' in href) and re.search(r'-\d{5,10}', href):
                        results.append(href)
                if len(results) >= max_results:
                    break
    except Exception:
        pass
    return results


def search_antara(keyword, max_results=30, session=None):
    """
    Search Engine Khusus LKBN Antara News
    """
    req_session = session or requests.Session()
    results = []
    url = f"https://www.antaranews.com/search/{urllib.parse.quote(keyword)}"
    try:
        resp = req_session.get(url, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for art in soup.select('article, .simple-post, .card'):
                a = art.select_one('a')
                if a and a.get('href') and 'antaranews.com' in a['href']:
                    href = a['href']
                    if '/berita/' in href:
                        results.append(href)
                if len(results) >= max_results:
                    break
    except Exception:
        pass
    return results


def search_tribun(keyword, max_results=30, session=None):
    """
    Search Engine Khusus Tribun Network
    """
    req_session = session or requests.Session()
    query = f"{keyword} site:tribunnews.com"
    url = "https://html.duckduckgo.com/html/"
    results = []
    try:
        resp = req_session.post(url, data={"q": query}, headers=DEFAULT_HEADERS, timeout=12)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            for el in soup.select('.result'):
                title_el = el.select_one('.result__title a')
                if not title_el:
                    continue
                href = title_el.get('href', '')
                if 'uddg=' in href:
                    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    if 'uddg' in qs:
                        href = qs['uddg'][0]
                if href and 'tribunnews.com' in href and not any(x in href for x in ['/tag/', '/topic/']):
                    results.append(href)
                if len(results) >= max_results:
                    break
    except Exception:
        pass
    return results


# ==========================================
# MULTI-SOURCE SEARCH DISPATCHER
# ==========================================
def fetch_article_urls_for_keyword(keyword, source_mode="all", max_articles=30):
    """
    Mencari daftar URL artikel berita berdasarkan keyword & pilihan mesin pencari.
    """
    session = requests.Session()
    urls = []

    print(f"  🔍 Menghubungi Search Engine untuk keyword: '{keyword}'...")

    if source_mode == "all":
        # Multi-engine aggregator: DDG + Detik + Kompas + Solopos + Antara
        target_per_source = max(5, max_articles // 3)
        ddg_urls = search_duckduckgo(keyword, max_results=max_articles, session=session)
        detik_urls = search_detik(keyword, max_results=target_per_source, session=session)
        kompas_urls = search_kompas(keyword, max_results=target_per_source, session=session)
        solopos_urls = search_solopos(keyword, max_results=target_per_source, session=session)
        antara_urls = search_antara(keyword, max_results=target_per_source, session=session)

        # Merge & deduplicate preserving order
        for u_list in [ddg_urls, detik_urls, kompas_urls, solopos_urls, antara_urls]:
            for u in u_list:
                if u not in urls:
                    urls.append(u)
    elif source_mode == "ddg":
        urls = search_duckduckgo(keyword, max_results=max_articles, session=session)
    elif source_mode == "detik":
        urls = search_detik(keyword, max_results=max_articles, session=session)
    elif source_mode == "kompas":
        urls = search_kompas(keyword, max_results=max_articles, session=session)
    elif source_mode == "solopos":
        urls = search_solopos(keyword, max_results=max_articles, session=session)
    elif source_mode == "antara":
        urls = search_antara(keyword, max_results=max_articles, session=session)
    elif source_mode == "tribun":
        urls = search_tribun(keyword, max_results=max_articles, session=session)

    return urls[:max_articles]


# ==========================================
# PIPELINE EKSEKUSI SCRAPING BERITA
# ==========================================
def save_article_to_csv(article_data, posts_csv_path):
    """
    Menyimpan satu baris data artikel secara inkremental ke file CSV dengan thread-lock.
    """
    with csv_lock:
        file_exists = os.path.exists(posts_csv_path) and os.path.getsize(posts_csv_path) > 0
        with open(posts_csv_path, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=POSTS_CSV_HEADER)
            if not file_exists:
                writer.writeheader()
            writer.writerow(article_data)


def init_comments_csv(comments_csv_path):
    """
    Membuat file CSV komentar pasangan agar format 100% konsisten dengan TikTok & Facebook.
    """
    with csv_lock:
        if not os.path.exists(comments_csv_path) or os.path.getsize(comments_csv_path) == 0:
            with open(comments_csv_path, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(COMMENTS_CSV_HEADER)


def run_news_scraper(keywords, output_name, source_mode="all", max_articles_per_keyword=30, delay=1.0):
    """
    Menjalankan alur scraping portal berita online untuk daftar keyword yang ditentukan.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_output_name = re.sub(r'[\\/*?:"<>| ]', '_', output_name.strip())
    
    daily_dir = get_daily_results_dir()
    posts_csv_path = os.path.join(daily_dir, f"{safe_output_name}_{timestamp}_posts.csv")
    comments_csv_path = os.path.join(daily_dir, f"{safe_output_name}_{timestamp}_comments.csv")

    # Inisialisasi CSV Komentar
    init_comments_csv(comments_csv_path)

    total_scraped = 0
    start_time = time.time()
    session = requests.Session()

    print("\n" + "=" * 65)
    print("  🚀 MEMULAI SCRAPING MEDIA ONLINE")
    print(f"  📁 File Output Posts : results/{os.path.basename(posts_csv_path)}")
    print(f"  📁 File Output Komen : results/{os.path.basename(comments_csv_path)}")
    print(f"  🔑 Jumlah Kata Kunci : {len(keywords)}")
    print(f"  🎯 Target per Keyword: {max_articles_per_keyword} artikel")
    print(f"  🌐 Mode Search Engine: {source_mode.upper()}")
    print("  ⌨️  Kontrol Keyboard   : Tekan [P] untuk Jeda, [Q] untuk Berhenti")
    print("=" * 65 + "\n")

    for kw_idx, kw in enumerate(keywords, 1):
        if pause_ctrl.is_stopped():
            break

        print(f"\n[{kw_idx}/{len(keywords)}] Memproses Kata Kunci: '{kw}'")
        article_urls = fetch_article_urls_for_keyword(kw, source_mode=source_mode, max_articles=max_articles_per_keyword)
        
        print(f"  📋 Ditemukan {len(article_urls)} tautan artikel berita.")

        kw_scraped = 0
        for url_idx, url in enumerate(article_urls, 1):
            if not pause_ctrl.check_pause():
                break

            # Cek duplikasi URL global
            with seen_lock:
                if url in global_seen_urls:
                    continue
                global_seen_urls.add(url)

            # Ekstrak data artikel
            article_data = parse_article_detail(url, session=session)
            if not article_data:
                continue

            article_data["search_keyword"] = kw
            save_article_to_csv(article_data, posts_csv_path)
            
            total_scraped += 1
            kw_scraped += 1

            headline_preview = article_data['description'].split('\n')[0].replace('[JUDUL] ', '')
            if len(headline_preview) > 55:
                headline_preview = headline_preview[:52] + "..."

            print(f"  [{kw_scraped}/{len(article_urls)}] ✅ [{article_data['platform']}] {headline_preview} ({article_data['post_date'][:10]})")

            # Jeda sopan antar request
            pause_ctrl.sleep(random.uniform(delay * 0.8, delay * 1.3))

            if kw_scraped >= max_articles_per_keyword:
                break

    elapsed = time.time() - start_time
    print("\n" + "=" * 65)
    print("  🎉 SCRAPING MEDIA ONLINE SELESAI!")
    print(f"  📊 Total Artikel Terkumpul : {total_scraped} artikel")
    print(f"  ⏱️  Waktu Eksekusi         : {elapsed:.1f} detik")
    print(f"  💾 Lokasi Hasil Posts     : {posts_csv_path}")
    print(f"  💾 Lokasi Hasil Komen     : {comments_csv_path}")
    print("=" * 65 + "\n")

    return posts_csv_path, comments_csv_path


# ==========================================
# MENU INTERAKTIF TERMINAL
# ==========================================
def main_menu():
    print("""
===================================================================
📰  ONLINE MEDIA & NEWS SCRAPER (PORTAL BERITA INDONESIA)
    Format Standar 25 Kolom (Sama dengan TikTok & Facebook Scraper)
===================================================================
""")

    # 1. Pilih Sumber Kata Kunci
    print("Pilih Sumber Keyword:")
    print("  [1] Input Keyword Manual (satu atau beberapa dipisah koma)")
    print("  [2] Baca Otomatis dari file 'keywords.txt'")
    
    choice_kw = input("Pilihan (1/2) [Default: 2]: ").strip()
    keywords = []

    if choice_kw == "1":
        raw_kw = input("\nMasukkan Keyword (contoh: Bupati Klaten, Jalan Rusak Klaten): ").strip()
        if raw_kw:
            keywords = [k.strip() for k in raw_kw.split(',') if k.strip()]
    else:
        kw_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "keywords.txt")
        if os.path.exists(kw_file):
            with open(kw_file, 'r', encoding='utf-8') as f:
                keywords = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            print(f"  -> Berhasil memuat {len(keywords)} kata kunci dari 'keywords.txt'")
        else:
            print("  [!] File 'keywords.txt' tidak ditemukan. Menggunakan keyword default.")
            keywords = ["Bupati Klaten"]

    if not keywords:
        keywords = ["Bupati Klaten"]

    # 2. Pilih Mesin Pencari / Sumber Media
    print("\nPilih Sumber / Mesin Pencari Media:")
    print("  [1] Semua Portal Media (Aggregator: Detik, Kompas, Solopos, Antara, Tribun, Tempo, dll.) - [DIREKOMENDASIKAN]")
    print("  [2] Detik.com")
    print("  [3] Kompas.com")
    print("  [4] Solopos.com / Espos.id (Solo Raya & Klaten)")
    print("  [5] LKBN Antara News")
    print("  [6] Tribunnews Network")
    print("  [7] DuckDuckGo Search Engine")

    choice_src = input("Pilihan (1-7) [Default: 1]: ").strip()
    source_map = {
        "1": "all",
        "2": "detik",
        "3": "kompas",
        "4": "solopos",
        "5": "antara",
        "6": "tribun",
        "7": "ddg"
    }
    selected_source = source_map.get(choice_src, "all")

    # 3. Jumlah Target Artikel
    target_inp = input("\nTarget Maksimal Artikel per Keyword [Default: 25]: ").strip()
    try:
        max_articles = int(target_inp) if target_inp else 25
    except ValueError:
        max_articles = 25

    # 4. Nama File Output
    default_name = f"media_{keywords[0].replace(' ', '_').lower()}" if keywords else "media_news"
    name_inp = input(f"Nama File Output CSV [Default: {default_name}]: ").strip()
    output_name = name_inp if name_inp else default_name

    # Jalankan Scraper
    run_news_scraper(
        keywords=keywords,
        output_name=output_name,
        source_mode=selected_source,
        max_articles_per_keyword=max_articles,
        delay=1.0
    )


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n[!] Scraping dibatalkan oleh pengguna (Ctrl+C). Seluruh data tersimpan aman.")
