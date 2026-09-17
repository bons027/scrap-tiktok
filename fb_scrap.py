import sys
# Pastikan encoding output terminal mendukung karakter UTF-8 / emoji & flush instan
try:
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
except Exception:
    pass

import time
import json
import csv
import os
import random
import re
import base64
import subprocess
import urllib.parse
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Patch untuk mencegah bug WinError 6 pada Windows saat shutdown undetected-chromedriver
uc.Chrome.__del__ = lambda self: None

# Blacklist teks UI / Notifikasi Facebook agar tidak tercampur ke data komentar
NOTIFICATION_BLACKLIST = [
    'menerima permintaan pertemanan',
    'permintaan pertemanan',
    'menyukai postingan',
    'membagikan postingan',
    'mengomentari postingan',
    'mengikuti anda',
    'kirim pesan',
    'tulis komentar',
    'lihat komentar sebelumnya',
    'lihat komentar lainnya',
    'lihat balasan lainnya',
    'view more comments',
    'previous comments',
    'aktif sekarang',
    'tulis balasan',
    'jawab kuis'
]

# Filter BARU untuk "Postingan Terbaru" (recent_posts) - endpoint /search/top/
# JSON Asli: {"recent_posts:0":"{\"name\":\"recent_posts\",\"args\":\"\"}"}
FB_RECENT_POSTS_FILTER = "eyJyZWNlbnRfcG9zdHM6MCI6IntcIm5hbWVcIjpcInJlY2VudF9wb3N0c1wiLFwiYXJnc1wiOlwiXCJ9In0%3D"

# Filter LAMA (chronosort) - tetap disimpan sebagai fallback
# JSON Asli: {"rp_chrono_sort:0":"{\"name\":\"chronosort\",\"args\":\"\"}"}
FB_CHRONOSORT_FILTER = "eyJycF9jaHJvbm9fc29ydDowIjoie1wibmFtZVwiOlwiY2hyb25vc29ydFwiLFwiYXJnc1wiOlwiXCJ9In0%3D"

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
    Mendengarkan penekanan tombol keyboard secara non-blocking di terminal Windows.
    - Tekan 'P' atau 'Space' : Jeda (Pause) / Lanjut (Resume)
    - Tekan 'Q'             : Berhenti secara aman & simpan seluruh data ke CSV
    """
    def __init__(self):
        import threading
        self.is_paused = False
        self.stop_requested = False
        self.lock = threading.Lock()
        self._listener_thread = None
        self._start_keyboard_listener()

    def start_listener(self):
        if not self._listener_thread or not self._listener_thread.is_alive():
            self._start_keyboard_listener()

    def _start_keyboard_listener(self):
        if not msvcrt:
            return

        import threading
        def _worker():
            while not self.stop_requested:
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
                except Exception:
                    pass
                time.sleep(0.08)

        self._listener_thread = threading.Thread(target=_worker, daemon=True)
        self._listener_thread.start()

    def toggle_pause(self):
        with self.lock:
            self.is_paused = not self.is_paused
            if self.is_paused:
                print("\n" + "=" * 65)
                print("  [PAUSED] SCRAPING DIJEDA / DIHENTIKAN SEMENTARA")
                print("  Status : Seluruh data yang sudah di-scrape tersimpan AMAN di CSV.")
                print("  -------------------------------------------------------------")
                print("  * Tekan tombol [P] atau [SPACE] di keyboard untuk MELANJUTKAN (Resume).")
                print("  * Tekan tombol [Q] di keyboard untuk BERHENTI & SIMPAN Hasil Sekarang.")
                print("=" * 65 + "\n", flush=True)
            else:
                print("\n" + "=" * 65)
                print("  [RESUMED] >> Melanjutkan proses scraping kembali...")
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
        """
        Tahan eksekusi selama status is_paused = True.
        Mengembalikan True jika boleh lanjut, False jika user meminta stop.
        """
        while self.is_paused and not self.stop_requested:
            time.sleep(0.2)
        return not self.stop_requested

    def sleep(self, seconds):
        """
        Pengganti time.sleep() yang responsif terhadap jeda (pause) & stop.
        """
        steps = max(1, int(seconds / 0.1))
        for _ in range(steps):
            if self.stop_requested:
                break
            while self.is_paused and not self.stop_requested:
                time.sleep(0.2)
            time.sleep(0.1)


# Inisialisasi Kontroler Jeda Global
pause_ctrl = PauseController()


# ==========================================
# 1. CDP SCRIPT: STEALTH ANTI-BOT & GRAPHQL INTERCEPTOR
# ==========================================
CDP_STEALTH_AND_INTERCEPTOR = """
// ----------------------------------------------------
// A. ANTI-BOT & FINGERPRINT EVASION (STEALTH SHIELD)
// ----------------------------------------------------
try {
    // 1. Webdriver Detection Elimination
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    delete navigator.__proto__.webdriver;

    // 2. Mock Chrome Runtime & Internal APIs
    window.chrome = {
        runtime: {
            OnInstalledReason: { INSTALL: 'install', UPDATE: 'update', CHROME_UPDATE: 'chrome_update', SHARED_MODULE_UPDATE: 'shared_module_update' },
            OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
            PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
            PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
            RequestUpdateCheckStatus: { THROTTLED: 'throttled', NO_UPDATE: 'no_update', UPDATE_AVAILABLE: 'update_available' }
        },
        app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
        csi: function() {},
        loadTimes: function() {}
    };

    // 3. Realistic Browser Attributes
    Object.defineProperty(navigator, 'languages', { get: () => ['id-ID', 'id', 'en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });

    // 4. Permissions API Spoof
    const origPermissions = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            origPermissions(parameters)
    );

    // 5. Hardware / WebGL GPU Mock
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(parameter) {
        if (parameter === 37445) return 'Google Inc. (NVIDIA)';
        if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameter.apply(this, [parameter]);
    };
    if (typeof WebGL2RenderingContext !== 'undefined') {
        const getParameter2 = WebGL2RenderingContext.prototype.getParameter;
        WebGL2RenderingContext.prototype.getParameter = function(parameter) {
            if (parameter === 37445) return 'Google Inc. (NVIDIA)';
            if (parameter === 37446) return 'ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)';
            return getParameter2.apply(this, [parameter]);
        };
    }
} catch(e) {}

// ----------------------------------------------------
// B. GRAPHQL & XHR IN-MEMORY NETWORK INTERCEPTOR
// ----------------------------------------------------
window._scraped_data = [];
function pushData(type, payload) {
    if (window._scraped_data.length > 1000) {
        window._scraped_data.shift();
    }
    window._scraped_data.push({ type: type, timestamp: Date.now(), payload: payload });
}

// Intercept Fetch API (Facebook GraphQL)
const origFetch = window.fetch;
window.fetch = new Proxy(origFetch, {
    apply: async function(target, thisArg, argumentsList) {
        const [input, init] = argumentsList;
        const response = await target.apply(thisArg, argumentsList);
        try {
            const url = typeof input === 'string' ? input : (input?.url || '');
            if (url.includes('graphql') || url.includes('/api/') || url.includes('comment') || url.includes('feedback')) {
                const clone = response.clone();
                const text = await clone.text();
                pushData('INTERCEPTED_FETCH', { url: url, text: text });
            }
        } catch(e) {}
        return response;
    }
});

// Intercept XMLHttpRequest
const OrigXHR = window.XMLHttpRequest;
window.XMLHttpRequest = new Proxy(OrigXHR, {
    construct: function(target, args) {
        const xhr = new target(...args);
        xhr.addEventListener('load', () => {
            try {
                if (xhr.responseURL && (xhr.responseURL.includes('graphql') || xhr.responseURL.includes('/api/') || xhr.responseURL.includes('comment'))) {
                    pushData('INTERCEPTED_XHR', { url: xhr.responseURL, text: xhr.responseText });
                }
            } catch(e) {}
        });
        return xhr;
    }
});
"""


# ==========================================
# 2. PARSER JSON GRAPHQL FACEBOOK REKURSIF
# ==========================================
def parse_facebook_raw_response(raw_text):
    if not raw_text or not isinstance(raw_text, str):
        return []

    clean_text = raw_text.strip()
    if clean_text.startswith("for (;;);"):
        clean_text = clean_text[9:].strip()

    try:
        data = json.loads(clean_text)
        return [data] if isinstance(data, dict) else []
    except Exception:
        pass

    results = []
    for line in clean_text.splitlines():
        line = line.strip()
        if line.startswith("for (;;);"):
            line = line[9:].strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                data = json.loads(line)
                if isinstance(data, dict):
                    results.append(data)
            except Exception:
                pass
    return results


def is_valid_comment_text(text):
    if not text or len(text) < 2:
        return False
    t_lower = text.lower()
    for b in NOTIFICATION_BLACKLIST:
        if b in t_lower:
            return False
    return True


def is_outdated_post(date_str, min_year=2025):
    """
    Mengecek apakah tanggal postingan lebih tua dari min_year (contoh: 2024, 2023, 2022).
    - Jika min_year <= 0 atau None -> Tidak membatasi tahun (selalu False).
    - Menolak tahun < min_year (misal 2024, 2023 jika min_year=2025).
    - Menerima tahun >= min_year (misal 2025, 2026) dan tanggal relatif terkini.
    """
    if not date_str or not min_year or min_year <= 0:
        return False
    d = str(date_str).strip()
    
    # 1. Cek tahun 4 digit eksplisit (1990 - 2099)
    raw_years = re.findall(r'\b(19\d{2}|20\d{2})\b', d)
    years = [int(y) for y in raw_years if 1990 <= int(y) <= 2099]
    if years:
        # Jika ada tahun yang >= min_year (misal 2025 atau 2026), postingan diterima!
        if any(y >= min_year for y in years):
            return False
        # Jika semua tahun yang terdeteksi < min_year (misal 2024, 2023), tolak sebagai usang!
        if all(y < min_year for y in years):
            return True

    # 2. Cek format relatif dalam hitungan tahun (contoh: "2 thn lalu", "3 tahun yang lalu", "2 yrs ago", "1 thn")
    rel_match = re.search(r'(\d+)\s*(?:thn|th|tahun|yr|yrs|year|years)\b', d, re.IGNORECASE)
    if rel_match:
        try:
            n_years = int(rel_match.group(1))
            current_year = datetime.now().year
            est_year = current_year - n_years
            if est_year < min_year:
                return True
            else:
                return False
        except Exception:
            pass

    # 3. Cek format relatif dalam hitungan bulan (contoh: "18 bln lalu", "24 bulan yang lalu", "20 mo ago")
    rel_month_match = re.search(r'(\d+)\s*(?:bln|bulan|mo|months?)\b', d, re.IGNORECASE)
    if rel_month_match:
        try:
            n_months = int(rel_month_match.group(1))
            current_date = datetime.now()
            from datetime import timedelta
            est_date = current_date - timedelta(days=n_months * 30.5)
            if est_date.year < min_year:
                return True
        except Exception:
            pass

    # 4. Cek format relatif dalam hitungan minggu (contoh: "70 mgg lalu", "90 minggu", "100 weeks ago")
    rel_week_match = re.search(r'(\d+)\s*(?:mgg|minggu|wk|weeks?)\b', d, re.IGNORECASE)
    if rel_week_match:
        try:
            n_weeks = int(rel_week_match.group(1))
            current_date = datetime.now()
            from datetime import timedelta
            est_date = current_date - timedelta(weeks=n_weeks)
            if est_date.year < min_year:
                return True
        except Exception:
            pass

    return False



def is_specific_post_url(url):
    """
    Memastikan URL adalah permalink postingan/video langsung, bukan URL grup umum,
    halaman profil umum, atau halaman pencarian.
    Mendukung format post, permalink, story_fbid, video, reel, watch, share, dan photo.
    """
    if not url:
        return False
    u = str(url).lower()
    if '/search/' in u or '/search?' in u or '/search' == u.rstrip('/'):
        return False

    markers = [
        '/posts/', '/permalink/', 'story_fbid', '/videos/', '/reel/', '/reels/',
        '/watch', 'fbid=', 'multi_permalinks', 'set=gm.', 'set=pcb.', '/share/v/', '/share/r/', '/share/p/',
        '/photo/', '/photos/', 'photo.php'
    ]
    has_marker = any(marker in u for marker in markers)
    if has_marker:
        # Jika memuat /watch, pastikan ada parameter video id (v=)
        if '/watch' in u and not ('v=' in u):
            return False
        return True

    return False


def is_keyword_relevant(post_text, author="", keyword="", group_name=None, card_full_text=""):
    """
    Validasi kata kunci (Keyword Relevance):
    - Jika keyword == "Feed Terbaru" atau kosong -> True (mode feed umum).
    - Jika keyword diapit tanda kutip ("kata kunci" atau 'kata kunci') -> Wajib frasa persis (Exact Phrase).
    - Memeriksa kemunculan keyword pada:
      1. Teks utama postingan (post_text)
      2. Nama pembuat postingan (author)
      3. Seluruh teks kartu postingan (card_full_text, mencakup shared post, link preview, badge, alt gambar)
      4. Nama grup target (group_name) untuk konteks wilayah.
    """
    if not keyword or keyword.strip() == "" or keyword.strip().lower() == "feed terbaru":
        return True

    kw = keyword.strip()
    txt = (post_text or "").lower()
    auth = (author or "").lower()
    card_txt = (card_full_text or "").lower()
    grp = (group_name or "").lower().replace("-", " ").replace("_", " ")

    # Gabungan seluruh konten teks yang terlihat pada kartu postingan
    post_content = f"{auth} {txt} {card_txt}".strip()
    full_context = f"{post_content} {grp}".strip()

    # 1. Cek mode Frasa Persis jika diapit tanda kutip: "contoh frasa"
    if (kw.startswith('"') and kw.endswith('"')) or (kw.startswith("'") and kw.endswith("'")):
        exact_phrase = kw[1:-1].strip().lower()
        if not exact_phrase:
            return True
        return exact_phrase in post_content

    # 2. Cek apakah seluruh keyword muncul sebagai satu kesatuan frase
    kw_lower = kw.lower()
    if kw_lower in post_content:
        return True

    # 3. Multi-kata: Pecah menjadi kata-kata unik (minimal 2 huruf)
    raw_tokens = re.findall(r'\b\w+\b', kw_lower)
    words = list(dict.fromkeys(raw_tokens))
    if not words:
        return True

    # Jika hanya 1 kata (misal: "Hamenang"), wajib ada di teks/author/kartu
    if len(words) == 1:
        return words[0] in post_content

    # Jika multi-kata (misal: "Jalan Rusak Klaten"):
    # Semua kata wajib ada di full_context (gabungan teks, author, nama grup, dan kartu)
    all_in_context = all(w in full_context for w in words)
    if not all_in_context:
        return False

    # Minimal ada setidaknya 1 kata inti keyword yang benar-benar ada di post_content
    core_words_in_post = any(w in post_content for w in words)
    return core_words_in_post


def is_page_or_group_broken(driver, expected_url=""):
    """
    Mendeteksi apakah halaman atau grup Facebook rusak, dihapus, tidak tersedia,
    atau terlempar ke beranda utama / login.
    Mengembalikan (True, alasan) jika rusak, (False, "") jika normal.
    """
    try:
        curr_url = driver.current_url.lower()

        # 1. Cek pengalihan URL (Redirect ke Login / Checkpoint / Help)
        if any(bad in curr_url for bad in ['/login/', '/checkpoint/', '/recover/', 'facebook.com/help']):
            return True, "Terlempar ke halaman Login/Checkpoint"

        # Jika URL target adalah grup/pencarian, tapi terlempar ke beranda utama facebook
        clean_curr = curr_url.split('?')[0].rstrip('/')
        if clean_curr in ['https://www.facebook.com', 'https://web.facebook.com', 'https://m.facebook.com']:
            return True, "Grup tidak ditemukan / dialihkan ke beranda utama"

        # JIKA ADA FEED ATAU KONTEN POSTINGAN AKTIF, HALAMAN PASTI NORMAL (BUKAN RUSAK)!
        has_active_feed = driver.execute_script("""
            let feed = document.querySelector('div[role="feed"], div[role="main"]');
            let articles = document.querySelectorAll('div[role="article"], div[data-ad-preview="message"]');
            return !!feed && articles.length > 0;
        """)
        if has_active_feed:
            return False, ""

        # 2. Cek teks error khas Facebook HANYA pada judul halaman atau banner error khusus Facebook
        # (JANGAN membaca document.body.innerText karena teks postingan/komentar warga bisa memuat kata error tersebut!)
        error_check = driver.execute_script("""
            let titleText = (document.title || '').toLowerCase();

            let brokenTitlePhrases = [
                'konten tidak ditemukan',
                'halaman tidak ditemukan',
                'halaman tidak tersedia',
                'grup ini tidak tersedia',
                'grup ini telah ditutup',
                'page not found',
                'content not found',
                'this page isn\\'t available',
                'this group is unavailable'
            ];

            for (let phrase of brokenTitlePhrases) {
                if (titleText.includes(phrase)) {
                    return { is_broken: true, reason: phrase };
                }
            }

            // Cek elemen banner error khusus Facebook
            let errorEl = document.querySelector('div[data-testid="error_box"]');
            if (errorEl && errorEl.offsetHeight > 50) {
                return { is_broken: true, reason: (errorEl.innerText || '').trim() || 'Banner error Facebook' };
            }

            return { is_broken: false, reason: '' };
        """)

        if error_check and error_check.get('is_broken'):
            return True, f"Pesan Facebook: '{error_check.get('reason')}'"

    except Exception:
        pass

    return False, ""


def decode_facebook_uzpf(token_str):
    """
    Mendekode token Uzpf Facebook untuk mengekstrak Post ID asli dari grup / cerita / search result.
    Contoh: UzpfSVNDOjQ0NDkzODkzNzUzODI0MTQ= -> 4449389375382414
    Contoh: UzpfSTEwMDAxMDgyNjczNDYyMjpWSzo0NTU3MzI2MTU3OTIyMDY4 -> 4557326157922068
    Contoh: UzpfSTEwMDAwNTcyMDk3Mjg2ODpWSzo0NTUwMTA3NzQ1MzEwNTc2 -> 4550107745310576
    """
    if not token_str:
        return ""
    token_str = str(token_str)
    m = re.search(r'Uzpf([a-zA-Z0-9_-]+={0,2})', token_str)
    if m:
        b64_part = m.group(1).replace('-', '+').replace('_', '/')
        padding = 4 - (len(b64_part) % 4)
        if padding and padding < 4:
            b64_part += '=' * padding
        try:
            decoded = base64.b64decode(b64_part).decode('utf-8', errors='ignore')
            m_id = re.search(r'(?:ISC|VK|story|fbid):([0-9]{8,25})', decoded)
            if m_id:
                return m_id.group(1)
            m_digits = re.findall(r'([0-9]{10,25})', decoded)
            if m_digits:
                return m_digits[-1]
        except Exception:
            pass
    return ""


def extract_comments_from_json_tree(obj, results=None, parent_author=None, is_reply=False, inside_comment_node=False):
    """
    Mengekstrak komentar dan deep replies dari struktur pohon GraphQL secara rekursif.
    HANYA mengekstrak node bertipe 'Comment' / 'FeedbackComment',
    menjamin TIDAK ADA caption postingan lain (Story/FeedUnit) yang bocor sebagai komentar.
    """
    if results is None:
        results = []

    if isinstance(obj, dict):
        typename = str(obj.get('__typename', ''))
        
        # JANGAN pernah ekstrak dari Story / FeedUnit / Search Result Card
        if typename in ['Story', 'FeedUnit', 'SearchFeedUnit', 'GroupPost', 'FeedEdge', 'Viewer', 'Group', 'Page', 'CometFeedUnit', 'SearchResultsFeed']:
            inside_comment_node = False

        # Node HANYA valid jika benar-benar merupakan Comment/FeedbackComment atau node di dalam comment tree
        is_comment_obj = (
            typename in ['Comment', 'FeedbackComment'] or 
            (inside_comment_node and typename in ['', 'Comment', 'FeedbackComment'] and 'comment_parent' in obj)
        )

        if is_comment_obj and typename not in ['Story', 'FeedUnit', 'SearchFeedUnit', 'GroupPost', 'FeedEdge']:
            text = ""
            if 'preferred_body' in obj and isinstance(obj['preferred_body'], dict):
                text = str(obj['preferred_body'].get('text', '')).strip()
            elif 'body' in obj and isinstance(obj['body'], dict):
                text = str(obj['body'].get('text', '')).strip()
            elif 'comment_text' in obj and isinstance(obj['comment_text'], dict):
                text = str(obj['comment_text'].get('text', '')).strip()
            elif 'translation' in obj and isinstance(obj['translation'], dict):
                text = str(obj['translation'].get('text', '')).strip()
            elif typename == 'Comment' and 'text' in obj and isinstance(obj['text'], str):
                text = str(obj.get('text', '')).strip()
            elif typename == 'Comment' and 'message' in obj and isinstance(obj['message'], dict):
                text = str(obj['message'].get('text', '')).strip()

            cid = str(obj.get('id', obj.get('legacy_fbid', obj.get('legacy_token', ''))))

            if text and is_valid_comment_text(text) and not text.startswith("http") and len(text) < 2500:
                # Filter notifikasi ID & noise
                if not cid.startswith('bm90aWZpY2F0aW9u') and 'notification' not in cid.lower():
                    author = 'Warga'
                    author_url = ''
                    uname = 'Warga'
                    if 'author' in obj and isinstance(obj['author'], dict):
                        author = obj['author'].get('name', 'Warga')
                        author_url = obj['author'].get('url', '')
                        uname = obj['author'].get('id') or author
                    elif 'comment_parent' in obj and isinstance(obj.get('comment_parent'), dict):
                        author = obj['comment_parent'].get('author', {}).get('name', 'Warga')

                    c_time = obj.get('created_time')
                    c_date = 'Terkini'
                    if c_time:
                        try:
                            c_date = datetime.fromtimestamp(int(c_time)).strftime('%Y-%m-%d %H:%M:%S')
                        except Exception:
                            c_date = str(c_time)

                    # Likes & Reaksi
                    likes = 0
                    feedback = obj.get('feedback', {})
                    reply_count = 0
                    if isinstance(feedback, dict):
                        react_cnt = feedback.get('reaction_count', {})
                        if isinstance(react_cnt, dict):
                            likes = react_cnt.get('count', 0)
                        elif isinstance(feedback.get('feedback_reaction_count'), int):
                            likes = feedback.get('feedback_reaction_count', 0)
                        elif isinstance(feedback.get('reactors', {}), dict):
                            likes = feedback['reactors'].get('count', 0)

                        # Deteksi reply count
                        if 'replies' in feedback and isinstance(feedback['replies'], dict):
                            reply_count = feedback['replies'].get('count', 0)
                        elif 'comment_replies' in feedback and isinstance(feedback['comment_replies'], dict):
                            reply_count = feedback['comment_replies'].get('count', 0)
                        elif 'total_comment_count' in feedback:
                            reply_count = feedback.get('total_comment_count', 0)

                    # Cek apakah objek ini adalah balasan (reply)
                    has_parent = 'comment_parent' in obj or is_reply
                    reply_to_target = parent_author or ''
                    if 'comment_parent' in obj and isinstance(obj['comment_parent'], dict):
                        has_parent = True
                        p_name = obj['comment_parent'].get('author', {}).get('name')
                        if p_name:
                            reply_to_target = p_name

                    results.append({
                        'comment_id': cid or f"fb_c_{abs(hash(text))}",
                        'author': author,
                        'username': uname,
                        'profile_url': author_url,
                        'comment_date': c_date,
                        'comment_text': text,
                        'likes': likes,
                        'reply_count': reply_count,
                        'is_reply': 'YA' if has_parent else 'TIDAK',
                        'reply_to': reply_to_target
                    })

                    # Jika komentar ini memiliki node balasan di dalamnya, traverse dengan menandai is_reply=True
                    if 'feedback' in obj and isinstance(obj['feedback'], dict):
                        sub_replies = obj['feedback'].get('replies', {}) or obj['feedback'].get('comment_rendering_instance', {})
                        if isinstance(sub_replies, (dict, list)):
                            extract_comments_from_json_tree(sub_replies, results, parent_author=author, is_reply=True, inside_comment_node=True)

        for k, v in obj.items():
            if k not in ['feedback', 'comment_parent']:
                is_comment_sub = inside_comment_node or (k in ['comments', 'comment_rendering_instance', 'replies', 'comment_replies', 'display_comments'])
                extract_comments_from_json_tree(v, results, parent_author=parent_author, is_reply=is_reply, inside_comment_node=is_comment_sub)

    elif isinstance(obj, list):
        for item in obj:
            extract_comments_from_json_tree(item, results, parent_author=parent_author, is_reply=is_reply, inside_comment_node=inside_comment_node)

    return results


# ==========================================
# 3. FUNGSI BANTUAN BINARY, PROFIL & CSV
# ==========================================
def find_binary(filenames, subdirs):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(base_dir)
    
    search_dirs = [base_dir, parent_dir]
    for d in search_dirs:
        for subdir in subdirs:
            for fname in filenames:
                candidate = os.path.join(d, subdir, fname) if subdir else os.path.join(d, fname)
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)
    return None


def get_chrome_major_version(chrome_path):
    """
    Mendeteksi versi utama (major version) dari file executable Chrome.
    Contoh: '152.0.7977.75' -> 152
    """
    if not chrome_path or not os.path.exists(chrome_path):
        return None
    try:
        cmd = f'(Get-Item "{chrome_path}").VersionInfo.ProductVersion'
        res = subprocess.check_output(['powershell', '-NoProfile', '-Command', cmd], text=True).strip()
        if res:
            m = re.search(r'^(\d+)', res)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


def get_driver():
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    driver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    version_main = get_chrome_major_version(chrome_path)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, "facebook_chrome_profile")
    os.makedirs(profile_dir, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-notifications")

    driver_kwargs = {
        "options": options,
        "user_data_dir": profile_dir
    }
    if chrome_path:
        driver_kwargs["browser_executable_path"] = chrome_path
    if driver_path:
        driver_kwargs["driver_executable_path"] = driver_path
    if version_main:
        driver_kwargs["version_main"] = version_main

    # Bersihkan file lock Chrome yang tertinggal agar tidak memicu error 'profile in use'
    for lock_name in ["SingletonLock", "SingletonSocket", "SingletonCookie"]:
        lock_path = os.path.join(profile_dir, lock_name)
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except Exception:
                pass

    driver = uc.Chrome(**driver_kwargs)

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": CDP_STEALTH_AND_INTERCEPTOR})
    except Exception:
        pass

    return driver, profile_dir


def ensure_driver_alive(driver):
    """Memeriksa apakah driver browser masih aktif. Jika crash/ditutup, buka kembali."""
    is_alive = False
    try:
        if driver is not None:
            _ = driver.current_url
            is_alive = True
    except Exception:
        is_alive = False

    if not is_alive:
        print("\n[!] Sesi browser terputus atau tertutup. Membuka kembali browser Facebook...")
        try:
            if driver is not None:
                driver.quit()
        except Exception:
            pass
        try:
            driver, _ = get_driver()
            driver.get("https://www.facebook.com")
            pause_ctrl.sleep(3.0)
            print("[*] Browser berhasil dibuka kembali.")
        except Exception as e:
            print(f"[ERROR] Gagal membuka kembali browser: {e}")
    return driver


def load_keywords(filepath="keywords.txt", prompt_fallback=True):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        if os.path.basename(full_path).lower() == "keywords.txt":
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write("# Masukkan 1 keyword per baris\njalan rusak Klaten\nBupati Klaten\n")
        else:
            return []
            
    with open(full_path, 'r', encoding='utf-8') as f:
        keywords = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
        
    if not keywords and prompt_fallback:
        manual_kw = input("Keyword: ").strip()
        if manual_kw:
            keywords = [manual_kw]
            
    return keywords


def load_groups(filepath="groups.txt", prompt_fallback=True):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        if os.path.basename(full_path).lower() == "groups.txt":
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write("# Masukkan 1 link grup Facebook per baris\n# https://www.facebook.com/groups/namagrup\n")
        else:
            return []
            
    with open(full_path, 'r', encoding='utf-8') as f:
        groups = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
        
    return groups


def select_keywords_source(base_dir=None, default_file="keywords.txt"):
    """
    Menampilkan menu interaktif pemilihan sumber kata kunci (file keywords*.txt,
    file manual, atau input kata kunci / link postingan langsung).
    Mengembalikan list kata kunci [kw1, kw2, ...].
    """
    import glob
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    candidate_files = sorted(set(glob.glob(os.path.join(base_dir, "keyword*.txt")) + glob.glob(os.path.join(base_dir, "keywords*.txt"))))
    default_path = os.path.join(base_dir, default_file)
    if not os.path.exists(default_path) and not candidate_files:
        load_keywords(default_path, prompt_fallback=False)
        candidate_files = [default_path]
    elif default_path in candidate_files:
        candidate_files.remove(default_path)
        candidate_files.insert(0, default_path)
    elif os.path.exists(default_path):
        candidate_files.insert(0, default_path)

    file_options = []
    for c_path in candidate_files:
        f_name = os.path.basename(c_path)
        try:
            c_kws = load_keywords(c_path, prompt_fallback=False)
            cnt = len(c_kws)
        except Exception:
            cnt = 0
        file_options.append((f_name, c_path, cnt))

    print("\n" + "-" * 55)
    print("PILIHAN SUMBER KATA KUNCI (KEYWORDS):")
    for i, (fn, fp, cnt) in enumerate(file_options, 1):
        label = " [Default]" if i == 1 else ""
        print(f"  {i}. {fn} ({cnt} kata kunci aktif){label}")
    print("  M. Masukkan nama file .txt lain secara manual")
    print("  T. Input kata kunci langsung / link postingan")
    print("-" * 55)

    choice = input(f"Pilih file kata kunci [1-{len(file_options)}/M/T] (default: 1): ").strip()
    keywords = []

    if not choice or choice == "1":
        chosen_path = file_options[0][1] if file_options else default_path
        keywords = load_keywords(chosen_path, prompt_fallback=False)
        print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(keywords)} kata kunci)")
    elif choice.isdigit() and 1 <= int(choice) <= len(file_options):
        chosen_path = file_options[int(choice) - 1][1]
        keywords = load_keywords(chosen_path, prompt_fallback=False)
        print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(keywords)} kata kunci)")
    elif choice.upper() == "M":
        custom_file = input("Masukkan nama file .txt (contoh: keywords_hamenang.txt): ").strip()
        if custom_file and not custom_file.endswith(".txt"):
            custom_file += ".txt"
        chosen_path = os.path.join(base_dir, custom_file) if not os.path.isabs(custom_file) else custom_file
        if not os.path.exists(chosen_path):
            print(f"[!] File '{custom_file}' tidak ditemukan di folder script.")
            keywords = []
        else:
            keywords = load_keywords(chosen_path, prompt_fallback=False)
            print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(keywords)} kata kunci)")
    elif choice.upper() == "T":
        manual_kw = input("Kata kunci (pisahkan koma jika > 1) atau link FB: ").strip()
        if manual_kw:
            if manual_kw.startswith("http://") or manual_kw.startswith("https://"):
                keywords = [manual_kw]
            elif "," in manual_kw:
                keywords = [k.strip() for k in manual_kw.split(",") if k.strip()]
            else:
                keywords = [manual_kw]
            print(f"[*] Menggunakan {len(keywords)} kata kunci/link: {', '.join(keywords)}")
    else:
        chosen_path = file_options[0][1] if file_options else default_path
        keywords = load_keywords(chosen_path, prompt_fallback=False)
        print(f"[*] Pilihan tidak dikenal, default ke '{os.path.basename(chosen_path)}' ({len(keywords)} kata kunci)")

    if not keywords:
        print("[!] Tidak ada kata kunci yang ditemukan di sumber tersebut.")
        manual_kw = input("Masukkan kata kunci langsung (atau tekan Enter untuk batal): ").strip()
        if manual_kw:
            if manual_kw.startswith("http://") or manual_kw.startswith("https://"):
                keywords = [manual_kw]
            elif "," in manual_kw:
                keywords = [k.strip() for k in manual_kw.split(",") if k.strip()]
            else:
                keywords = [manual_kw]

    return keywords


def select_groups_source(base_dir=None, default_file="groups.txt"):
    """
    Menampilkan menu interaktif pemilihan sumber daftar grup Facebook (file groups*.txt,
    file manual, atau input 1 URL grup langsung).
    Mengembalikan list grup [url1, url2, ...].
    """
    import glob
    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    candidate_files = sorted(glob.glob(os.path.join(base_dir, "groups*.txt")))
    default_path = os.path.join(base_dir, default_file)
    if not os.path.exists(default_path) and not candidate_files:
        load_groups(default_path, prompt_fallback=False)
        candidate_files = [default_path]
    elif default_path in candidate_files:
        candidate_files.remove(default_path)
        candidate_files.insert(0, default_path)
    elif os.path.exists(default_path):
        candidate_files.insert(0, default_path)

    file_options = []
    for c_path in candidate_files:
        f_name = os.path.basename(c_path)
        try:
            c_groups = load_groups(c_path, prompt_fallback=False)
            cnt = len(c_groups)
        except Exception:
            cnt = 0
        file_options.append((f_name, c_path, cnt))

    print("\n" + "-" * 55)
    print("PILIHAN SUMBER DAFTAR GRUP FACEBOOK:")
    for i, (fn, fp, cnt) in enumerate(file_options, 1):
        label = " [Default]" if i == 1 else ""
        print(f"  {i}. {fn} ({cnt} link grup aktif){label}")
    print("  M. Masukkan nama file .txt lain secara manual")
    print("  U. Input 1 link URL grup langsung")
    print("-" * 55)

    choice = input(f"Pilih file grup [1-{len(file_options)}/M/U] (default: 1): ").strip()
    groups = []

    if not choice or choice == "1":
        chosen_path = file_options[0][1] if file_options else default_path
        groups = load_groups(chosen_path, prompt_fallback=False)
        print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(groups)} link grup)")
    elif choice.isdigit() and 1 <= int(choice) <= len(file_options):
        chosen_path = file_options[int(choice) - 1][1]
        groups = load_groups(chosen_path, prompt_fallback=False)
        print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(groups)} link grup)")
    elif choice.upper() == "M":
        custom_file = input("Masukkan nama file .txt (contoh: groups_2.txt): ").strip()
        if custom_file and not custom_file.endswith(".txt"):
            custom_file += ".txt"
        chosen_path = os.path.join(base_dir, custom_file) if not os.path.isabs(custom_file) else custom_file
        if not os.path.exists(chosen_path):
            print(f"[!] File '{custom_file}' tidak ditemukan di folder script.")
            groups = []
        else:
            groups = load_groups(chosen_path, prompt_fallback=False)
            print(f"[*] Menggunakan file: '{os.path.basename(chosen_path)}' ({len(groups)} link grup)")
    elif choice.upper() == "U":
        g_input = input("URL Grup FB (contoh: https://www.facebook.com/groups/namagrup): ").strip()
        if g_input:
            groups = [g_input]
            print(f"[*] Menggunakan 1 link grup langsung: '{g_input}'")
    else:
        chosen_path = file_options[0][1] if file_options else default_path
        groups = load_groups(chosen_path, prompt_fallback=False)
        print(f"[*] Pilihan tidak dikenal, default ke '{os.path.basename(chosen_path)}' ({len(groups)} link grup)")

    if not groups:
        print("[!] Tidak ada link grup aktif yang ditemukan di sumber tersebut.")
        g_input = input("Masukkan URL Grup FB manual langsung (atau tekan Enter untuk batal): ").strip()
        if g_input:
            groups = [g_input]

    return groups


def extract_hashtags(text):
    if not text:
        return ""
    tags = re.findall(r'#[\w\u0590-\u05ff]+', str(text))
    return ", ".join(tags) if tags else ""


def detect_language(text):
    if not text:
        return "id"
    t = str(text).lower()
    jv_words = ['sing', 'nang', 'ning', 'kagem', 'panjenengan', 'lur', 'monggo', 'matur', 'nuwun', 'piye', 'niki', 'punika', 'mawon', 'mboten', 'sampun', 'menika', 'lho', 'wes', 'wis', 'nggih', 'nggon', 'rembug', 'isih', 'yoiki', 'karo', 'ora', 'iki', 'bocah', 'apik']
    en_words = ['the', 'and', 'this', 'that', 'with', 'from', 'have', 'for', 'you', 'video', 'watch', 'today', 'welcome', 'great', 'about', 'people', 'city', 'best']
    id_words = ['dan', 'yang', 'di', 'ini', 'itu', 'untuk', 'saya', 'dengan', 'ada', 'bisa', 'dari', 'tidak', 'sudah', 'akan', 'kami', 'mereka', 'kita', 'ke', 'pada', 'adalah']
    
    tokens = re.findall(r'\b\w+\b', t)
    if not tokens:
        return "id"
    
    jv_cnt = sum(1 for w in tokens if w in jv_words)
    en_cnt = sum(1 for w in tokens if w in en_words)
    id_cnt = sum(1 for w in tokens if w in id_words)
    
    if jv_cnt > 0 and jv_cnt >= en_cnt and jv_cnt >= id_cnt:
        return "jv"
    if en_cnt > id_cnt and en_cnt > jv_cnt:
        return "en"
    return "id"


def format_facebook_url(raw_url="", current_page_url="", post_id="", author="", group_name=""):
    """
    Memformat URL postingan Facebook secara standar & konsisten sesuai format canonical direct post:
    - Postingan Foto Grup dengan set=gm / set=pcb: https://www.facebook.com/groups/{group_id}/posts/{post_id}
    - Postingan Foto Standalone / Album: https://www.facebook.com/photo/?fbid={fbid} (&set={set})
    - Postingan Video Watch: https://www.facebook.com/watch/?v={video_id}
    - Postingan Reel: https://www.facebook.com/reel/{reel_id}/
    - Postingan Grup: https://www.facebook.com/groups/{group_id}/posts/{post_id}
    - Postingan User/Page: https://www.facebook.com/{author_username}/posts/{post_id}
    - Menghilangkan tracking parameters (__cft__, __tn__, rdid, dll) agar URL selalu bersih dan langsung membuka postingan saat diklik.
    """
    raw_url = (raw_url or '').strip()
    current_page_url = (current_page_url or '').strip()
    post_id = str(post_id or '').strip()

    # 1. Ekstraksi group_id / group_slug dari raw_url, current_page_url, atau group_name
    group_id = ''
    m_grp = re.search(r'facebook\.com/groups/([^/?#]+)', raw_url)
    if m_grp and m_grp.group(1).lower() not in ['search', 'feed', 'joins', 'create', 'discover']:
        group_id = m_grp.group(1)

    if not group_id and current_page_url:
        m_grp_page = re.search(r'facebook\.com/groups/([^/?#]+)', current_page_url)
        if m_grp_page and m_grp_page.group(1).lower() not in ['search', 'feed', 'joins', 'create', 'discover']:
            group_id = m_grp_page.group(1)

    if not group_id and group_name:
        group_id = str(group_name).strip()

    if not group_id:
        m_id = re.search(r'[?&]id=([0-9]+)', raw_url) or re.search(r'[?&]id=([0-9]+)', current_page_url)
        if m_id:
            group_id = m_id.group(1)

    # 2. PHOTO LINKS: Jika raw_url adalah tautan foto (/photo/, photo.php, /photos/)
    if '/photo' in raw_url or 'photo.php' in raw_url:
        # Cek set=gm. atau set=pcb. (Ini adalah ID Postingan Grup Asli!)
        m_set = re.search(r'set=(?:gm|pcb)\.([0-9]{6,25})', raw_url)
        if m_set:
            p_id = m_set.group(1)
            g_id = group_id
            m_idor = re.search(r'idorvanity=([0-9]+)', raw_url)
            if m_idor:
                g_id = m_idor.group(1)
            if g_id:
                return f"https://www.facebook.com/groups/{g_id}/posts/{p_id}"
            return f"https://www.facebook.com/permalink.php?story_fbid={p_id}"

        # Jika foto standalone atau album set=a. (bukan grup post ID):
        # Buka tautan photo langsung karena mengubahnya ke /posts/{fbid} akan menghasilkan "Konten Ini Tidak Tersedia"
        m_fbid = re.search(r'[?&]fbid=([0-9]{6,25})', raw_url)
        if m_fbid:
            fbid = m_fbid.group(1)
            m_set_a = re.search(r'[?&]set=(a\.[0-9.]+)', raw_url)
            if m_set_a:
                return f"https://www.facebook.com/photo/?fbid={fbid}&set={m_set_a.group(1)}"
            return f"https://www.facebook.com/photo/?fbid={fbid}"

    # 3. VIDEO / REEL / WATCH LINKS
    # A. Watch URL
    if '/watch' in raw_url or '/watch' in current_page_url or re.search(r'[?&]v=[0-9]+', raw_url):
        m_v = re.search(r'[?&]v=([0-9]{6,25})', raw_url) or re.search(r'[?&]v=([0-9]{6,25})', current_page_url)
        v_id = m_v.group(1) if m_v else post_id
        if v_id and v_id != group_id:
            return f"https://www.facebook.com/watch/?v={v_id}"

    # B. Reel URL
    if '/reel/' in raw_url or '/reels/' in raw_url:
        m_r = re.search(r'/(?:reel|reels)/([0-9]{6,25})', raw_url)
        if m_r:
            return f"https://www.facebook.com/reel/{m_r.group(1)}/"

    # C. Group / User Videos
    if '/videos/' in raw_url or '/videos/' in current_page_url:
        m_vid = re.search(r'/videos/([0-9]{6,25})', raw_url) or re.search(r'/videos/([0-9]{6,25})', current_page_url)
        v_id = m_vid.group(1) if m_vid else post_id
        if v_id and v_id != group_id:
            return f"https://www.facebook.com/watch/?v={v_id}"

    # D. Share Links
    m_share = re.search(r'facebook\.com/share/([vrp])/([a-zA-Z0-9_-]+)', raw_url)
    if m_share:
        return f"https://www.facebook.com/share/{m_share.group(1)}/{m_share.group(2)}/"

    # 4. GROUP POST LINKS
    # A. set=gm. atau set=pcb. di luar URL foto
    m_set_any = re.search(r'set=(?:gm|pcb)\.([0-9]{6,25})', raw_url)
    if m_set_any:
        p_id = m_set_any.group(1)
        if group_id:
            return f"https://www.facebook.com/groups/{group_id}/posts/{p_id}"
        return f"https://www.facebook.com/permalink.php?story_fbid={p_id}"

    # B. /groups/{id}/posts/{postId} atau /groups/{id}/permalink/{postId}
    m_grp_post = re.search(r'/groups/[^/?#]+/(?:user/[^/?#]+/)?(?:posts|permalink)/([0-9]{6,25})', raw_url)
    if m_grp_post:
        p_id = m_grp_post.group(1)
        if group_id and p_id != group_id:
            return f"https://www.facebook.com/groups/{group_id}/posts/{p_id}"

    # C. multi_permalinks
    m_multi = re.search(r'[?&]multi_permalinks=([0-9]{6,25})', raw_url)
    if m_multi:
        p_id = m_multi.group(1)
        if group_id and p_id != group_id:
            return f"https://www.facebook.com/groups/{group_id}/posts/{p_id}"

    # D. story_fbid
    m_story = re.search(r'[?&]story_fbid=([0-9]{6,25})', raw_url)
    if m_story:
        p_id = m_story.group(1)
        if group_id and p_id != group_id:
            return f"https://www.facebook.com/permalink.php?story_fbid={p_id}&id={group_id}"
        return f"https://www.facebook.com/permalink.php?story_fbid={p_id}"

    # 5. USER / PAGE POST
    m_user_post = re.search(r'facebook\.com/([^/?#]+)/posts/([0-9]{6,25})', raw_url)
    if m_user_post and m_user_post.group(1).lower() not in ['groups', 'permalink.php', 'story.php']:
        return f"https://www.facebook.com/{m_user_post.group(1)}/posts/{m_user_post.group(2)}"

    # 6. Fallback jika ada group_id dan post_id yang valid
    if group_id and post_id and post_id != group_id and re.match(r'^[0-9]{6,25}$', post_id):
        return f"https://www.facebook.com/groups/{group_id}/posts/{post_id}"

    # 7. Fallback post_id saja
    if post_id and re.match(r'^[0-9]{6,25}$', post_id):
        return f"https://www.facebook.com/permalink.php?story_fbid={post_id}"

    # 8. Jika URL bersih sudah spesifik
    if raw_url and not raw_url.startswith('https://www.facebook.com/search/'):
        parsed = urllib.parse.urlparse(raw_url)
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip('/')
        if is_specific_post_url(clean):
            return clean

    if group_id:
        return f"https://www.facebook.com/groups/{group_id}"

    return raw_url or current_page_url or "https://www.facebook.com"


def init_posts_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'platform', 'search_keyword', 'post_id', 'post_date', 'profile_name',
                'profile_url', 'bio', 'followers_count', 'following_count', 'followers_list',
                'following_list', 'description', 'likes', 'shares', 'plays',
                'comments_count', 'video_subtitles', 'text_language', 'hashtags_used',
                'is_ad', 'is_pinned', 'is_sponsored', 'location_of_creation', 'music_meta', 'video_url'
            ])


def init_comments_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'platform', 'search_keyword', 'post_id', 'post_date', 'post_author',
                'post_profile_url', 'post_description', 'post_likes', 'post_shares', 'post_plays',
                'post_comments_count', 'comment_id', 'comment_date', 'profile_name', 'username',
                'profile_url', 'comment_text', 'likes', 'reply_count', 'is_reply',
                'reply_to', 'text_language', 'hashtags_used', 'location_of_creation', 'video_url'
            ])


def save_to_csv(filename, data_row):
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(data_row)


def load_all_existing_sheet_data(current_post_csv, current_comment_csv):
    """
    Memuat seluruh signature postingan, ID postingan, URL postingan, dan teks komentar
    hanya dari file CSV sesi aktif saat ini agar data yang sudah tersimpan pada sesi ini
    tidak diambil ganda, tanpa memblokir data dari sesi/file lain.
    """
    seen_post_signatures = set()
    seen_post_ids = set()
    seen_post_urls = set()
    seen_comment_keys = set()

    files_to_check = set()
    if current_post_csv and os.path.exists(current_post_csv):
        files_to_check.add(os.path.abspath(current_post_csv))
    if current_comment_csv and os.path.exists(current_comment_csv):
        files_to_check.add(os.path.abspath(current_comment_csv))

    for fpath in files_to_check:
        try:
            with open(fpath, mode='r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    continue
                fieldnames = [fn.lower().strip() for fn in reader.fieldnames]
                
                is_post_file = any('post_text' in fn or 'description' in fn or 'reactions_count' in fn for fn in fieldnames)
                is_comment_file = any('comment_text' in fn or 'reply_to' in fn for fn in fieldnames)

                for row in reader:
                    row_lower = {k.lower().strip(): v for k, v in row.items() if k and v}
                    
                    # Track post
                    if is_post_file or 'post_text' in row_lower or 'description' in row_lower:
                        auth = (row_lower.get('profile_name') or row_lower.get('author_name') or row_lower.get('author') or '').strip()
                        txt = (row_lower.get('description') or row_lower.get('post_text') or '').strip()
                        pid = (row_lower.get('post_id') or row_lower.get('video_id') or '').strip()
                        purl = (row_lower.get('video_url') or row_lower.get('post_url') or '').strip()

                        if auth or txt:
                            seen_post_signatures.add(f"{auth}:::{txt[:45]}")
                        if pid and pid not in ['post_id', 'video_id']:
                            seen_post_ids.add(pid)
                        if purl:
                            clean_u = purl.split('?')[0].rstrip('/')
                            if is_specific_post_url(clean_u):
                                seen_post_urls.add(clean_u)

                    # Track comment
                    if is_comment_file or 'comment_text' in row_lower:
                        cid = (row_lower.get('comment_id') or '').strip()
                        c_txt = (row_lower.get('comment_text') or '').strip()
                        c_auth = (row_lower.get('profile_name') or row_lower.get('author_name') or row_lower.get('author') or '').strip()
                        if cid and cid not in ['comment_id'] and not cid.startswith('no_comment_'):
                            seen_comment_keys.add(cid)
                        if c_txt and c_txt != '[Tidak ada komentar]':
                            seen_comment_keys.add(f"{c_auth}:::{c_txt[:50]}")
        except Exception:
            pass

    return seen_post_signatures, seen_post_ids, seen_post_urls, seen_comment_keys


def perform_feed_scroll(driver, distance=800):
    """
    Scroll feed dengan ritme responsif dan efektif memicu lazy load postingan baru
    pada berbagai container scroll Facebook (window, html, body, role=main, role=feed).
    """
    try:
        ActionChains(driver).scroll_by_amount(0, int(distance)).perform()
    except Exception:
        pass
    try:
        driver.execute_script("""
            const dist = arguments[0];
            window.scrollBy(0, dist);
            if (document.documentElement) document.documentElement.scrollTop += dist;
            if (document.body) document.body.scrollTop += dist;

            let scrollables = document.querySelectorAll('div[role="feed"], div[role="main"], div[data-pagelet*="Feed"], div[data-pagelet*="Search"]');
            for (let el of scrollables) {
                el.scrollTop += dist;
            }

            let allDivs = document.querySelectorAll('div');
            for (let d of allDivs) {
                if (d.scrollHeight > d.clientHeight && d.clientHeight > 300) {
                    let s = window.getComputedStyle(d);
                    if (s.overflowY === 'auto' || s.overflowY === 'scroll') {
                        d.scrollTop += dist;
                    }
                }
            }
        """, distance)
    except Exception:
        pass
    time.sleep(0.05)


# ==========================================
# HELPER KHUSUS SEARCH MODE (MODE 1)
# Tidak dipakai oleh Mode 2 (Group Scraping)
# ==========================================

DEBUG_SEARCH = False


def build_search_url(keyword, use_filter=True, filter_version="recent"):
    """
    Membangun URL pencarian Facebook global (Mode 1).
    - filter_version="recent"  -> Filter BARU (recent_posts) + endpoint /search/top/
    - filter_version="chrono"  -> Filter LAMA (chronosort) + endpoint /search/posts/
    - filter_version="none"    -> Tanpa filter (fallback terakhir)
    
    Fungsi ini HANYA dipanggil oleh Mode 1.
    """
    q = urllib.parse.quote(keyword)
    
    if not use_filter:
        return f"https://www.facebook.com/search/top/?q={q}"
    
    if filter_version == "recent":
        return f"https://www.facebook.com/search/top/?q={q}&filters={FB_RECENT_POSTS_FILTER}"
    elif filter_version == "chrono":
        return f"https://www.facebook.com/search/posts/?q={q}&filters={FB_CHRONOSORT_FILTER}"
    else:
        return f"https://www.facebook.com/search/top/?q={q}"


def perform_search_feed_scroll(driver, distance=800):
    """
    Scroll khusus halaman /search/top/ Facebook.
    Mencari container scrollable TERBESAR (bukan sidebar filter).
    """
    try:
        ActionChains(driver).scroll_by_amount(0, int(distance)).perform()
    except Exception:
        pass
    try:
        driver.execute_script("""
            const dist = arguments[0];
            window.scrollBy(0, dist);

            // Cari container scrollable terbesar (menghindari sidebar kecil)
            let allDivs = document.querySelectorAll('div');
            let biggest = null, biggestArea = 0;
            for (let d of allDivs) {
                const s = window.getComputedStyle(d);
                if ((s.overflowY === 'auto' || s.overflowY === 'scroll')
                    && d.scrollHeight > d.clientHeight + 50) {
                    let area = d.clientHeight * d.clientWidth;
                    if (area > biggestArea) {
                        biggestArea = area;
                        biggest = d;
                    }
                }
            }
            if (biggest) {
                biggest.scrollTop += dist;
                biggest.dispatchEvent(new WheelEvent('wheel', {
                    deltaY: dist, bubbles: true
                }));
            }
        """, distance)
    except Exception:
        pass
    time.sleep(0.05)


def close_search_dialog(driver, search_url=None):
    """
    Tutup dialog di halaman search TANPA reload agresif.
    Hanya reload jika URL benar-benar keluar dari /search/.
    """
    # 1. Tutup dialog komentar jika ada
    try:
        driver.execute_script("""
            let dialogs = document.querySelectorAll(
                'div[role="dialog"][aria-modal="true"], div[data-pagelet*="Tahoe"]'
            );
            for (let d of dialogs) {
                let closeBtn = d.querySelector(
                    'div[aria-label="Tutup"], div[aria-label="Close"], '
                    + 'div[role="button"][aria-label*="Tutup"]'
                );
                if (closeBtn) {
                    (closeBtn.closest('div[role="button"]') || closeBtn).click();
                }
            }
        """)
        time.sleep(0.2)
    except Exception:
        pass

    # 2. Tekan ESC jika masih ada dialog
    try:
        has_dialog = driver.execute_script("""
            let dialogs = document.querySelectorAll(
                'div[role="dialog"][aria-modal="true"], div[data-pagelet*="Tahoe"]'
            );
            for (let d of dialogs) {
                if (d.querySelector('[aria-label*="Komentar"], [aria-label*="Comment"]')) {
                    return true;
                }
            }
            return false;
        """)
        if has_dialog:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.2)
    except Exception:
        pass

    # 3. Hanya reload jika URL keluar dari /search/
    if search_url:
        try:
            curr = driver.current_url.lower()
            if '/search/' not in curr:
                driver.get(search_url)
                time.sleep(2.0)
        except Exception:
            pass


def scroll_comment_container_center(driver, distance=550):
    """
    Melakukan scroll roda mouse KHUSUS di bagian tengah dialog komentar,
    memicu lazy loading komentar Facebook tanpa menggeser feed halaman luar.
    Menggunakan humanized step wheel events.
    """
    try:
        dialog = driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"], div[aria-modal="true"], div[data-pagelet*="Tahoe"], div[data-pagelet*="Watch"], div[role="complementary"]')
        ActionChains(driver).move_to_element(dialog).scroll_by_amount(0, distance).perform()
    except Exception:
        pass

    try:
        driver.execute_script("""
            const distance = arguments[0];
            const dialog = document.querySelector('div[role="dialog"], div[aria-modal="true"], div[data-pagelet*="Tahoe"], div[data-pagelet*="Watch"], div[role="complementary"]');
            let target = null;

            if (dialog) {
                // Cari container internal di dalam dialog yang memiliki overflow scroll
                const allDivs = Array.from(dialog.querySelectorAll('div, form, ul, section'));
                for (let d of allDivs) {
                    const style = window.getComputedStyle(d);
                    if ((style.overflowY === 'auto' || style.overflowY === 'scroll') && d.scrollHeight > d.clientHeight + 30) {
                        target = d;
                        break;
                    }
                }
                if (!target) target = dialog;
            }

            if (target) {
                target.scrollTop += distance;
                target.dispatchEvent(new WheelEvent('wheel', { 
                    deltaY: distance, 
                    bubbles: true, 
                    clientX: window.innerWidth / 2 + (Math.random() * 20 - 10), 
                    clientY: window.innerHeight / 2 + (Math.random() * 20 - 10) 
                }));
                target.dispatchEvent(new Event('scroll', { bubbles: true }));
            }
        """, distance)
    except Exception:
        pass


def check_facebook_login(driver):
    try:
        cookies = driver.get_cookies()
        if any(c.get('name') == 'c_user' for c in cookies):
            return True
        is_logged = driver.execute_script("""
            return !!(
                document.querySelector('[aria-label*="Akun Anda"], [aria-label*="Your profile"], [aria-label*="Menu"], [role="navigation"]') ||
                document.querySelector('a[href*="/me/"], a[href*="/profile.php"]') ||
                document.querySelector('svg[aria-label*="Facebook"]')
            );
        """)
        return bool(is_logged)
    except Exception:
        return False


def setup_facebook_session():
    print("\n" + "=" * 65)
    print("         SETUP & SIMPAN SESI LOGIN FACEBOOK")
    print("=" * 65)
    print("[*] Membuka browser Chrome dengan profil lokal...")
    
    try:
        driver, profile_dir = get_driver()
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        driver.get("https://www.facebook.com")
        time.sleep(3)

        if check_facebook_login(driver):
            print("\n  [INFO] AKUN ANDA SUDAH DALAM KEADAAN LOGIN! (Sesi Aktif)")
            input("\nTekan [ENTER] untuk menutup browser dan kembali ke Menu...")
            return

        print("\n  >>> SILAKAN LOGIN DI JENDELA BROWSER CHROME SEKARANG <<<")
        print("  1. Masukkan Email/No HP dan Password akun Facebook Anda.")
        print("  2. Selesaikan kode 2FA / OTP (jika ada).")
        print("  3. Setelah berhasil masuk ke Beranda Facebook:")
        print("     KEMBALI KE TERMINAL INI lalu TEKAN [ENTER].")
        print("=" * 65)

        input("\n>>> Tekan [ENTER] di sini JIKA SUDAH BERHASIL LOGIN di browser... <<< ")
        time.sleep(2)
        print("\n  [BERHASIL] Sesi login Facebook Anda berhasil disimpan!")

    except Exception as e:
        print(f"[ERROR] Terjadi kendala saat setup login: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ==========================================
# 4. EKSTRAKSI KOMENTAR & DEEP REPLIES DARI DIALOG AKTIF
# ==========================================
def extract_comments_from_active_container(driver, current_post_text=''):
    """
    Mengekstrak komentar dan deep replies dari XHR GraphQL interceptor dan DOM dialog yang aktif.
    Mendukung resolusi SVG <use xlink:href="#Svg..."> untuk author dan teks komentar.
    Memfilter secara ketat agar caption/teks postingan (current_post_text) tidak tercampur sebagai komentar.
    """
    # 1. Dari XHR/GraphQL Network (Termasuk child replies yang ter-intercept)
    net_comments = []
    try:
        captured_data = driver.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
        if captured_data:
            for item in captured_data:
                payload = item.get('payload', {})
                raw_text = payload.get('text', '')
                if raw_text:
                    chunks = parse_facebook_raw_response(raw_text)
                    for chunk in chunks:
                        c_list = extract_comments_from_json_tree(chunk)
                        if c_list:
                            net_comments.extend(c_list)
    except Exception:
        pass

    # 2. Dari DOM dialog tengah (Mendeteksi struktur reply berjenjang & SVG obfuscation)
    dom_comments = []
    try:
        dom_comments = driver.execute_script("""
            let activePostText = (arguments[0] || '').trim();
            let results = [];
            let dialog = document.querySelector('div[role="dialog"], div[aria-modal="true"], div[data-pagelet*="Tahoe"], div[data-pagelet*="Watch"], div[role="complementary"]');
            let scope = dialog || document;
            
            // Helper untuk ekstrak teks dari elemen yang memuat SVG <use xlink:href="#Svg...">
            function resolveText(el) {
                if (!el) return '';
                let res = '';
                
                let aria = el.getAttribute('aria-label');
                if (aria) res += aria + ' ';
                
                let labelledBy = el.getAttribute('aria-labelledby');
                if (labelledBy) {
                    let ids = labelledBy.split(/\\s+/);
                    for (let id of ids) {
                        let target = document.getElementById(id);
                        if (target) {
                            res += (target.textContent || target.innerText || '') + ' ';
                        }
                    }
                }

                let uses = el.querySelectorAll('use');
                for (let u of uses) {
                    let href = u.getAttribute('xlink:href') || u.getAttribute('href') || '';
                    if (href.startsWith('#')) {
                        let ref = document.getElementById(href.substring(1));
                        if (ref) res += (ref.textContent || ref.innerText || '') + ' ';
                    }
                }
                
                let svgTexts = el.querySelectorAll('svg text, svg tspan');
                for (let st of svgTexts) {
                    res += (st.textContent || st.innerText || '') + ' ';
                }

                res += (el.innerText || el.textContent || '') + ' ';
                return res.replace(/\\s+/g, ' ').trim();
            }

            let commentElements = [];
            if (dialog) {
                commentElements = Array.from(dialog.querySelectorAll('div[aria-label*="Komentar oleh" i], div[aria-label*="Comment by" i], div[aria-label*="Balasan oleh" i], div[aria-label*="Reply by" i], ul > li div[role="article"], div[role="article"][aria-label*="Komentar" i], div[role="article"][aria-label*="Comment" i], div[role="article"][aria-label*="Balasan" i], div[role="article"][aria-label*="Reply" i]'));
            } else {
                commentElements = Array.from(document.querySelectorAll('div[aria-label*="Komentar oleh" i], div[aria-label*="Comment by" i], div[aria-label*="Balasan oleh" i], div[aria-label*="Reply by" i], ul > li div[role="article"], div[role="article"][aria-label*="Komentar" i], div[role="article"][aria-label*="Comment" i], div[role="article"][aria-label*="Balasan" i], div[role="article"][aria-label*="Reply" i]'));
            }

            commentElements.forEach((el, idx) => {
                if (el.closest('[role="navigation"]') || el.closest('[aria-label*="Notifikasi"]')) return;
                // Lewati jika elemen ini adalah kartu postingan utama atau berada di dalam area caption postingan
                if (!dialog && el.matches('div[role="feed"] > div')) return;
                if (el.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], [role="heading"], h2, h3, h4')) return;

                let authorEl = el.querySelector('a span[dir="auto"], a strong, span > strong, strong, a[role="link"]');
                let author = authorEl ? resolveText(authorEl).split('\\n')[0].replace(/·\\s*(?:Ikuti|Follow|Gabung|Join|Disponsori|Sponsored).*$/i, '').trim() : 'Warga';
                if (!author || author.toLowerCase().startsWith('hasil untuk') || author === 'Komentar' || author.toLowerCase() === 'facebook') author = 'Warga';

                let authorLink = authorEl ? (authorEl.closest('a') ? authorEl.closest('a').href : (authorEl.tagName === 'A' ? authorEl.href : '')) : '';
                let cleanAuthorUrl = authorLink ? authorLink.split('?')[0].split('&')[0] : '';
                let uname = author;
                if (cleanAuthorUrl) {
                    let mU = cleanAuthorUrl.match(/facebook\\.com\\/([^/?#]+)/);
                    if (mU && mU[1] && mU[1] !== 'profile.php' && mU[1] !== 'people') uname = mU[1];
                }

                let textEl = el.querySelector('div[dir="auto"][lang], div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
                let commentText = textEl ? resolveText(textEl) : '';

                // Jika commentText sama dengan author, cari text node berikutnya
                if (commentText === author || commentText.length < 2) {
                    let altTextEls = el.querySelectorAll('div[dir="auto"], span[dir="auto"]');
                    for (let alt of altTextEls) {
                        let aTxt = resolveText(alt);
                        if (aTxt && aTxt !== author && !['suka', 'balas', 'bagikan', 'like', 'reply', 'share', 'terkini'].includes(aTxt.toLowerCase()) && aTxt.length > 1) {
                            commentText = aTxt;
                            break;
                        }
                    }
                }

                // Filter keluar caption postingan aktif
                if (activePostText && (commentText === activePostText || (activePostText.length > 30 && activePostText.includes(commentText) && commentText.length > 30))) {
                    return;
                }

                let timeEl = el.querySelector('abbr, a[aria-label*="lalu"], a[aria-label*="ago"], span[id*="timestamp"], a[role="link"] span');
                let commentDate = timeEl ? (resolveText(timeEl) || timeEl.getAttribute('aria-label') || 'Terkini') : 'Terkini';
                if (commentDate && commentDate.length > 35) commentDate = 'Terkini';

                // Ekstraksi Likes
                let likes = 0;
                let likeEl = el.querySelector('span[aria-label*="reaksi"], span[aria-label*="like"], span[aria-label*="suka"]');
                if (likeEl) {
                    let lTxt = (likeEl.getAttribute('aria-label') || likeEl.innerText || '').replace(/[^0-9]/g, '');
                    if (lTxt) likes = parseInt(lTxt);
                }

                // Ekstraksi Reply Count pada komentar ini
                let replyCount = 0;
                let allSpans = el.querySelectorAll('span, div[role="button"]');
                for (let s of allSpans) {
                    let st = (s.innerText || '').trim();
                    let match = st.match(/(\\d+)\\s*(?:balasan|repl)/i);
                    if (match && match[1]) {
                        replyCount = parseInt(match[1]);
                        break;
                    }
                }

                // Deteksi apakah komentar ini merupakan balasan (child reply)
                let isReply = false;
                let replyTo = '';
                
                let parentArticle = el.parentElement ? el.parentElement.closest('div[role="article"], ul > li') : null;
                if (parentArticle && parentArticle !== el) {
                    isReply = true;
                    let pAuth = parentArticle.querySelector('a span[dir="auto"], strong, a[role="link"]');
                    if (pAuth) replyTo = resolveText(pAuth).split('\\n')[0].replace(/·\\s*(?:Ikuti|Follow|Gabung|Join).*$/i, '').trim();
                } else if (el.closest('ul ul') || el.getAttribute('aria-level') === '2' || commentText.startsWith('@')) {
                    isReply = true;
                    if (commentText.startsWith('@')) {
                        let m = commentText.match(/^@([^\\s,:]+)/);
                        if (m && m[1]) replyTo = m[1];
                    }
                }

                if (commentText && commentText.length > 1 && commentText !== author) {
                    results.push({
                        comment_id: 'fb_dom_' + idx + '_' + Math.floor(Math.random() * 10000),
                        author: author,
                        username: uname,
                        profile_url: cleanAuthorUrl,
                        comment_date: commentDate,
                        comment_text: commentText,
                        likes: likes,
                        reply_count: replyCount,
                        is_reply: isReply ? 'YA' : 'TIDAK',
                        reply_to: replyTo
                    });
                }
            });
            return results;
        """, current_post_text or '')
    except Exception:
        pass

    combined = []
    for c in (net_comments or []) + (dom_comments or []):
        c_txt = c.get('comment_text', '').strip()
        # Lewati jika teks komentar sama persis dengan caption postingan
        if current_post_text and (c_txt == current_post_text or (len(c_txt) > 40 and c_txt in current_post_text)):
            continue
        if is_valid_comment_text(c_txt):
            combined.append(c)

    return combined


# ==========================================
# 5. ALUR UTAMA: 4 LANGKAH EKSEKUSI PENUH
# ==========================================
def switch_filter_to_all_comments(driver):
    """
    LANGKAH 3: Klik dropdown 'Paling relevan' dan ubah ke 'Semua komentar'.
    """
    try:
        # Klik tombol dropdown 'Paling relevan'
        driver.execute_script("""
            let scope = document.querySelector('div[role="dialog"]') || document;
            let buttons = scope.querySelectorAll('div[role="button"], span');
            for (let btn of buttons) {
                let txt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                if (txt === 'paling relevan' || txt === 'top comments' || txt === 'most relevant') {
                    btn.click();
                    break;
                }
            }
        """)
        pause_ctrl.sleep(random.uniform(0.15, 0.3))

        # Klik menu 'Semua komentar'
        driver.execute_script("""
            let menuItems = document.querySelectorAll('div[role="menu"] span, div[role="menu"] div, div[role="menuitem"]');
            for (let item of menuItems) {
                let txt = (item.innerText || item.textContent || '').trim().toLowerCase();
                if (txt === 'semua komentar' || txt === 'all comments') {
                    item.click();
                    break;
                }
            }
        """)
        pause_ctrl.sleep(random.uniform(0.2, 0.4))
    except Exception:
        pass


def unfold_all_reply_threads(driver):
    """
    Mencari dan mengklik seluruh tombol balasan berjenjang (deep replies) yang terlihat di layar.
    """
    try:
        clicked_count = driver.execute_script("""
            let scope = document.querySelector('div[role="dialog"]') || document;
            let replyButtons = scope.querySelectorAll('div[role="button"], span[dir="auto"], a[role="button"], span');
            let clickCount = 0;

            for (let b of replyButtons) {
                let txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                let aria = (b.getAttribute('aria-label') || '').toLowerCase();

                let isReplyTrigger = (
                    txt.includes('lihat balasan') || txt.includes('lihat') && txt.includes('balasan') ||
                    txt.includes('balasan lainnya') || txt.includes('view replies') ||
                    txt.includes('view more replies') || txt.includes('view previous replies') ||
                    aria.includes('lihat balasan') || aria.includes('view replies')
                );

                if (isReplyTrigger) {
                    if (b.offsetParent !== null && !b.getAttribute('data-unfolded')) {
                        b.setAttribute('data-unfolded', 'true');
                        try {
                            b.click();
                            clickCount++;
                        } catch(e) {}
                    }
                }
            }
            return clickCount;
        """)
        return clicked_count or 0
    except Exception:
        return 0


def exhaustively_scroll_and_extract_comments(driver, max_idle_scrolls=3, max_total_comments_limit=150, seen_comment_keys=None, current_post_text=''):
    """
    LANGKAH 4: Scroll kontainer komentar sampai HABIS dan membongkar semua deep replies:
    - Otomatis membuka semua thread balasan (Lihat balasan, Lihat balasan lainnya, View replies)
    - Melakukan scroll pada kontainer tengah dengan ritme cepat & responsif
    - Mengumpulkan komentar utama dan balasan, serta melewatkan yang sudah ada di sheet
    - Selesai jika tidak ada komentar/balasan baru setelah beberapa putaran.
    """
    if seen_comment_keys is None:
        seen_comment_keys = set()

    seen_in_this_post = set()
    collected_for_post = []
    consecutive_no_new = 0
    total_scrolls = 0
    max_scroll_limit = 120 if max_total_comments_limit == 0 else max(10, (max_total_comments_limit // 8) + 10)

    while consecutive_no_new < max_idle_scrolls and total_scrolls < max_scroll_limit:
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        total_scrolls += 1

        # 1. Unfold semua thread balasan (deep replies) yang muncul di layar
        unfolded_replies = unfold_all_reply_threads(driver)
        if unfolded_replies > 0:
            pause_ctrl.sleep(random.uniform(0.35, 0.55))

        # 2. Klik tombol 'Lihat komentar lainnya' / 'View more comments' utama
        clicked_expand = driver.execute_script("""
            let scope = document.querySelector('div[role="dialog"]') || document;
            let buttons = scope.querySelectorAll('div[role="button"], span[dir="auto"], a[role="button"], span');
            let wasClicked = false;
            for (let b of buttons) {
                let txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                if (txt.includes('lihat komentar') || txt.includes('view more comments') || 
                    txt.includes('komentar lainnya') || txt.includes('komentar sebelumnya') ||
                    txt.includes('previous comments')) {
                    if (b.offsetParent !== null && !b.getAttribute('data-main-clicked')) {
                        b.setAttribute('data-main-clicked', 'true');
                        b.click();
                        wasClicked = true;
                        break;
                    }
                }
            }
            return wasClicked;
        """)

        # 3. Scroll kontainer tengah dialog komentar dengan cepat
        scroll_comment_container_center(driver, distance=random.randint(550, 700))
        pause_ctrl.sleep(random.uniform(0.5, 0.8))

        # 4. Ekstrak komentar & balasan yang baru masuk
        extracted = extract_comments_from_active_container(driver, current_post_text=current_post_text)
        new_found_this_step = 0

        for c in extracted:
            c_txt = c.get('comment_text', '').strip()
            c_id = c.get('comment_id', '')
            c_author = c.get('author', 'Warga')
            c_key = f"{c_author}:::{c_txt[:50]}"

            # Cek jika komentar sudah ada di sheet sebelumnya atau postingan ini
            if not c_txt or c_txt in seen_in_this_post or c_id in seen_comment_keys or c_key in seen_comment_keys:
                continue

            seen_in_this_post.add(c_txt)
            seen_comment_keys.add(c_id)
            seen_comment_keys.add(c_key)
            collected_for_post.append(c)
            new_found_this_step += 1

            c_date = c.get('comment_date', 'Terkini')
            c_likes = c.get('likes', 0)
            is_rep = c.get('is_reply', 'TIDAK')
            rep_to = c.get('reply_to', '')
            rep_cnt = c.get('reply_count', 0)

            if is_rep == 'YA':
                target_str = f" [Balasan ke @{rep_to}]" if rep_to else " [Balasan]"
                print(f"      └──{target_str} @{c_author}: \"{c_txt[:50]}...\" (likes: {c_likes})")
            else:
                rep_info = f" (balasan: {rep_cnt})" if rep_cnt > 0 else ""
                print(f"    + [{c_date}] @{c_author}: \"{c_txt[:55]}...\" (likes: {c_likes}{rep_info})")

        if new_found_this_step > 0 or clicked_expand or unfolded_replies > 0:
            consecutive_no_new = 0
        else:
            consecutive_no_new += 1

        if max_total_comments_limit > 0 and len(collected_for_post) >= max_total_comments_limit:
            break

    return collected_for_post


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


def get_group_identifier(url):
    """
    Ekstrak ID / slug unik grup dari URL Facebook.
    Contoh: https://www.facebook.com/groups/kotaklaten -> kotaklaten
            https://www.facebook.com/sorotklaten -> sorotklaten
    """
    if not url:
        return ""
    clean = url.rstrip('/')
    parts = clean.split('/')
    return parts[-1]


def get_progress_filepath(session_base_name):
    """
    Dapatkan path file *_progress.json untuk menyimpan checkpoint progres scraping.
    """
    if not session_base_name:
        return ""
    clean_name = session_base_name
    for suffix in ["_posts.csv", "_comments.csv", "_posts", "_comments", ".csv"]:
        if clean_name.endswith(suffix):
            clean_name = clean_name[:-len(suffix)]
            break

    if os.path.isabs(clean_name) or os.path.dirname(clean_name):
        return f"{clean_name}_progress.json"

    import glob
    matched = glob.glob(os.path.join(RESULTS_DIR, "**", f"{clean_name}_progress.json"), recursive=True)
    if matched and os.path.exists(matched[0]):
        return matched[0]

    return os.path.join(RESULTS_DIR, f"{clean_name}_progress.json")


def save_session_progress(session_base_name, progress_data):
    """
    Simpan checkpoint progres sesi ke format JSON secara atomik & aman.
    """
    try:
        p_path = get_progress_filepath(session_base_name)
        if not p_path:
            return
        progress_data["last_updated"] = datetime.now().isoformat()
        temp_path = f"{p_path}.tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(progress_data, f, indent=2, ensure_ascii=False)
        if os.path.exists(p_path):
            os.replace(temp_path, p_path)
        else:
            os.rename(temp_path, p_path)
    except Exception as e:
        print(f"[!] Gagal menyimpan progress checkpoint: {e}")


def load_session_progress(session_base_name, post_csv=None, comment_csv=None, all_groups=None):
    """
    Muat checkpoint progres sesi. Jika file progress.json belum ada,
    otomatis rekonstruksi dari post_csv dan daftar all_groups.
    """
    p_path = get_progress_filepath(session_base_name)
    if os.path.exists(p_path):
        try:
            with open(p_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass

    completed_groups = []
    completed_group_identifiers = set()
    total_posts = 0
    total_comments = 0

    if post_csv and os.path.exists(post_csv):
        try:
            with open(post_csv, mode='r', encoding='utf-8', errors='replace') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    total_posts += 1
                    p_url = row.get('post_url', '')
                    kw = row.get('search_keyword', '')
                    if kw.startswith('[') and ']' in kw:
                        g_slug = kw[1:kw.index(']')]
                        completed_group_identifiers.add(g_slug)
                    elif '/groups/' in p_url:
                        parts = p_url.split('/groups/')
                        if len(parts) > 1:
                            slug = parts[1].split('/')[0]
                            completed_group_identifiers.add(slug)
        except Exception:
            pass

    if comment_csv and os.path.exists(comment_csv):
        try:
            with open(comment_csv, mode='r', encoding='utf-8', errors='replace') as f:
                total_comments = max(0, sum(1 for _ in f) - 1)
        except Exception:
            pass

    if all_groups and completed_group_identifiers:
        last_matched_idx = -1
        for idx, grp in enumerate(all_groups):
            g_id = get_group_identifier(grp)
            if g_id in completed_group_identifiers:
                last_matched_idx = idx
        if last_matched_idx >= 0:
            completed_groups = all_groups[:last_matched_idx + 1]
    elif all_groups:
        for grp in all_groups:
            if get_group_identifier(grp) in completed_group_identifiers:
                completed_groups.append(grp)

    clean_id = os.path.basename(p_path).replace('_progress.json', '')
    data = {
        "session_id": clean_id,
        "completed_groups": completed_groups,
        "completed_keywords": [],
        "total_posts": total_posts,
        "total_comments": total_comments,
        "created_at": datetime.now().isoformat(),
        "last_updated": datetime.now().isoformat()
    }
    save_session_progress(session_base_name, data)
    return data


def get_recent_scrape_sessions(limit=5):
    """
    Cari daftar file sesi scraping sebelumnya di folder results/ (termasuk subfolder harian).
    """
    if not os.path.exists(RESULTS_DIR):
        return []

    import glob
    post_files = glob.glob(os.path.join(RESULTS_DIR, "*_posts.csv")) + glob.glob(os.path.join(RESULTS_DIR, "**", "*_posts.csv"), recursive=True)
    if not post_files:
        return []

    post_files = list(set(post_files))
    post_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)

    sessions = []
    for pf in post_files[:limit]:
        dir_p = os.path.dirname(pf)
        base_name = os.path.basename(pf).replace("_posts.csv", "")
        cf = os.path.join(dir_p, f"{base_name}_comments.csv")
        mtime = os.path.getmtime(pf)
        time_str = datetime.fromtimestamp(mtime).strftime("%d %b %Y %H:%M")

        posts_cnt = 0
        try:
            with open(pf, mode='r', encoding='utf-8', errors='replace') as f:
                posts_cnt = max(0, sum(1 for _ in f) - 1)
        except Exception:
            pass

        comms_cnt = 0
        if os.path.exists(cf):
            try:
                with open(cf, mode='r', encoding='utf-8', errors='replace') as f:
                    comms_cnt = max(0, sum(1 for _ in f) - 1)
            except Exception:
                pass

        p_json = os.path.join(dir_p, f"{base_name}_progress.json")
        completed_grps_count = 0
        if os.path.exists(p_json):
            try:
                with open(p_json, 'r', encoding='utf-8') as f:
                    p_data = json.load(f)
                    completed_grps_count = len(p_data.get("completed_groups", []))
            except Exception:
                pass

        sessions.append({
            "session_id": base_name,
            "post_csv": pf,
            "comment_csv": cf,
            "posts_count": posts_cnt,
            "comments_count": comms_cnt,
            "completed_groups_count": completed_grps_count,
            "time_str": time_str,
            "mtime": mtime
        })
    return sessions


def get_output_csv_paths(base_output_name, is_resume=False):
    if not base_output_name:
        base_output_name = "fb_isu_daerah"

    clean_name = base_output_name
    for suffix in ["_posts.csv", "_comments.csv", "_posts", "_comments", ".csv"]:
        if clean_name.endswith(suffix):
            clean_name = clean_name[:-len(suffix)]
            break

    if is_resume:
        if os.path.isabs(clean_name) or os.path.dirname(clean_name):
            post_csv = f"{clean_name}_posts.csv"
            comment_csv = f"{clean_name}_comments.csv"
            return post_csv, comment_csv
        else:
            import glob
            matched = glob.glob(os.path.join(RESULTS_DIR, "**", f"{clean_name}_posts.csv"), recursive=True)
            if matched and os.path.exists(matched[0]):
                dir_p = os.path.dirname(matched[0])
                return matched[0], os.path.join(dir_p, f"{clean_name}_comments.csv")
            elif os.path.exists(os.path.join(RESULTS_DIR, f"{clean_name}_posts.csv")):
                return os.path.join(RESULTS_DIR, f"{clean_name}_posts.csv"), os.path.join(RESULTS_DIR, f"{clean_name}_comments.csv")
            else:
                daily_dir = get_daily_results_dir()
                return os.path.join(daily_dir, f"{clean_name}_posts.csv"), os.path.join(daily_dir, f"{clean_name}_comments.csv")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_with_time = f"{clean_name}_{timestamp}"

    if os.path.isabs(clean_name) or os.path.dirname(clean_name):
        dir_name = os.path.dirname(clean_name)
        base_file = os.path.basename(clean_name)
        post_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_posts.csv")
        comment_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_comments.csv")
    else:
        daily_dir = get_daily_results_dir()
        post_csv = os.path.join(daily_dir, f"{base_with_time}_posts.csv")
        comment_csv = os.path.join(daily_dir, f"{base_with_time}_comments.csv")
    return post_csv, comment_csv


def close_post_dialog(driver, search_url=None):
    """
    Menutup modal dialog komentar dan memastikan browser selalu kembali ke halaman feed pencarian,
    tanpa menggunakan history browser (driver.back) yang beresiko terlempar ke beranda Facebook.
    """
    # 1. Tutup modal dialog jika ada di DOM
    try:
        driver.execute_script("""
            let dialog = document.querySelector('div[role="dialog"], div[aria-modal="true"], div[data-pagelet*="Tahoe"], div[data-pagelet*="Watch"]');
            if (dialog) {
                let closeBtn = dialog.querySelector(
                    'div[aria-label="Tutup"], div[aria-label="Close"], svg[aria-label="Tutup"], div[role="button"][aria-label*="Tutup"], div[role="button"][aria-label*="Close"]'
                );
                if (closeBtn) {
                    (closeBtn.closest('div[role="button"], span') || closeBtn).click();
                }
            }
        """)
        time.sleep(0.2)
    except Exception:
        pass

    try:
        has_dialog = driver.execute_script("return !!document.querySelector('div[role=\"dialog\"], div[aria-modal=\"true\"], div[data-pagelet*=\"Tahoe\"]');")
        if has_dialog:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.2)
    except Exception:
        pass

    # 2. Pastikan browser berada di search_url yang benar
    if search_url:
        try:
            curr = driver.current_url.lower()
            # Cek apakah URL saat ini masih di halaman pencarian atau feed kronologis
            is_on_search = ('/search' in curr or 'sorting_setting=' in curr)
            # Cek apakah modal dialog masih menutupi layar
            has_dialog_remaining = driver.execute_script("return !!document.querySelector('div[role=\"dialog\"], div[aria-modal=\"true\"], div[data-pagelet*=\"Tahoe\"]');")

            # Jika URL berpindah keluar dari pencarian (ke /posts/, /permalink/, /videos/, /reel/, /watch, beranda utama, dll)
            # atau modal dialog masih macet dan menutupi feed, navigasikan langsung ke search_url!
            if not is_on_search or has_dialog_remaining:
                print(f"  [*] Mengembalikan browser ke halaman feed pencarian: {search_url}")
                driver.get(search_url)
                time.sleep(2.5)
        except Exception:
            pass


def apply_recent_posts_filter(driver, retries=3):
    """
    Mengaktifkan filter 'Terbaru' / 'Postingan terbaru' pada feed pencarian Facebook atau grup.
    Mendukung deteksi URL parameter filters= chronosort + elemen switch presisi di DOM.
    """
    # 1. Cek apakah halaman sudah memuat parameter URL filter Postingan Terbaru
    try:
        curr_url = driver.current_url
        if "eyJycF9jaHJvbm9fc29yd" in curr_url or "chronosort" in curr_url or "CHRONOLOGICAL" in curr_url:
            print("  [*] URL sudah aktif memuat filter 'Postingan Terbaru' secara langsung.")
            return True
    except Exception:
        pass

    for attempt in range(retries):
        try:
            res = driver.execute_script("""
                // 1. Selector Presisi Sesuai DOM Facebook: <input role="switch" type="checkbox" aria-label="Terbaru">
                const exactInputs = Array.from(document.querySelectorAll(
                    'input[aria-label="Terbaru"], input[aria-label*="Terbaru" i], input[aria-label*="Recent" i], input[role="switch"]'
                ));

                for (let inp of exactInputs) {
                    let aria = (inp.getAttribute('aria-label') || '').toLowerCase();
                    if (aria.includes('terbaru') || aria.includes('recent')) {
                        let isChecked = inp.getAttribute('aria-checked') === 'true' || inp.checked === true;
                        if (isChecked) {
                            return { status: 'already_active', label: inp.getAttribute('aria-label') };
                        }
                        
                        // Scroll ke elemen dan lakukan klik
                        inp.scrollIntoView({ behavior: 'instant', block: 'center' });
                        let clickTarget = inp.closest('label') || inp.closest('div[role="switch"]') || inp.closest('div[role="button"]') || inp;
                        
                        try {
                            clickTarget.click();
                        } catch(e) {
                            try { inp.click(); } catch(e2) {}
                        }

                        // Dispatch synthetic events untuk memastikan React menangkap perubahan state
                        try {
                            inp.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                            inp.dispatchEvent(new Event('change', { bubbles: true }));
                        } catch(e3) {}

                        return { status: 'clicked', label: inp.getAttribute('aria-label') };
                    }
                }

                // 2. Fallback: Cari elemen switch / radio / container dengan teks atau aria-label 'Terbaru'
                const candidateNodes = Array.from(document.querySelectorAll(
                    'div[role="switch"], div[role="radio"], label, div[role="button"], span[dir="auto"]'
                ));

                for (let el of candidateNodes) {
                    let txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                    let aria = (el.getAttribute('aria-label') || '').toLowerCase();

                    let isRecentMatch = (
                        txt === 'terbaru' ||
                        txt === 'postingan terbaru' ||
                        txt === 'recent posts' ||
                        aria === 'terbaru' ||
                        aria.includes('postingan terbaru') ||
                        aria.includes('recent posts')
                    );

                    if (isRecentMatch) {
                        let isChecked = el.getAttribute('aria-checked') === 'true' || el.checked === true;
                        let childInput = el.querySelector('input');
                        if (childInput && (childInput.getAttribute('aria-checked') === 'true' || childInput.checked === true)) {
                            isChecked = true;
                        }

                        if (isChecked) {
                            return { status: 'already_active', label: txt || aria };
                        }

                        let target = el.closest('label, div[role="switch"], div[role="button"]') || el;
                        try {
                            target.click();
                            return { status: 'clicked', label: txt || aria };
                        } catch(e) {}
                    }
                }

                return { status: 'not_found' };
            """)

            if res and isinstance(res, dict):
                status = res.get('status')
                label = res.get('label', 'Terbaru')
                if status == 'already_active':
                    print(f"  [*] Filter '{label}' sudah dalam keadaan AKTIF.")
                    return True
                elif status == 'clicked':
                    print(f"  [*] Filter '{label}' berhasil di-KLIK (diaktifkan)!")
                    pause_ctrl.sleep(2.5)  # Tunggu feed Facebook me-refresh postingan terbaru
                    return True

        except Exception:
            pass

        if attempt < retries - 1:
            pause_ctrl.sleep(1.2)

    return False


def process_direct_post_url(driver, target_url, post_csv, comment_csv, max_comments_per_post=150):
    """
    Memproses postingan Facebook langsung dari URL tautan (Direct Post Link / Permalink).
    - Membuka URL postingan secara langsung.
    - Mengekstrak informasi postingan (author, tanggal, caption, likes, comments count).
    - Menyimpan link dan metadata postingan ke CSV.
    - Jika postingan tidak ada komentar -> link postingan tetap disimpan di post_csv dan comment_csv.
    - Jika postingan memiliki komentar -> mengambil seluruh komentar dan balasan sampai habis.
    """
    clean_url = (target_url or '').strip()
    if not clean_url:
        return

    print("\n" + "=" * 65)
    print(f"[*] MEMPROSES LINK POSTINGAN LANGSUNG: {clean_url}")
    print("=" * 65)

    try:
        driver.get(clean_url)
        pause_ctrl.sleep(3.5)
    except Exception as e:
        print(f"[!] Gagal membuka URL postingan '{clean_url}': {e}")
        return

    # Helper ekspansi teks caption jika ada "Lihat selengkapnya"
    try:
        driver.execute_script("""
            let seeMoreBtns = document.querySelectorAll('div[role="button"], span[role="button"]');
            for (let btn of seeMoreBtns) {
                let bTxt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                if (bTxt === 'lihat selengkapnya' || bTxt === 'see more' || bTxt === 'baca selengkapnya' || bTxt === 'selengkapnya') {
                    btn.click();
                }
            }
        """)
        pause_ctrl.sleep(0.3)
    except Exception:
        pass

    # Ekstrak data postingan dari halaman direct post
    post_info = driver.execute_script("""
        let curUrl = window.location.href;
        let postEl = document.querySelector('div[role="feed"] > div, div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"], div[role="main"]');
        if (!postEl) postEl = document.body;

        // Author
        let author = 'Warga / Anonim';
        let authorEl = postEl.querySelector('h2 strong, h3 strong, h4 strong, strong, h2 a, h3 a, h4 a');
        if (authorEl) {
            let aTxt = (authorEl.innerText || authorEl.textContent || '').trim();
            if (aTxt && aTxt.length < 50) author = aTxt;
        }

        // Caption / Description
        let postText = '';
        let msgSelectors = [
            'div[data-ad-preview="message"]',
            'div[data-ad-comet-preview="message"]',
            'div[data-testid="post_message"]',
            'div[dir="auto"][style*="text-align"]',
            'div.x1iorvi4'
        ];
        for (let sel of msgSelectors) {
            let mEl = postEl.querySelector(sel);
            if (mEl) {
                let t = (mEl.innerText || mEl.textContent || '').trim();
                if (t.length > postText.length) postText = t;
            }
        }

        // Tanggal
        let postDate = 'Terkini';
        const monthRegex = /\\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|agt|agu|aug|sep|okt|oct|nov|des|dec)\\b/i;
        const yearRegex = /\\b(19\\d{2}|20\\d{2})\\b/;
        const relTimeRegex = /\\b\\d+\\s*(?:thn|th|tahun|yr|yrs|year|years|mgg|minggu|wk|week|weeks|hr|hari|day|days|jam|jm|hour|hours|mnt|menit|min|mins|lalu|ago)\\b/i;

        let timeCands = [];
        let tLinks = postEl.querySelectorAll('abbr, a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], a[role="link"], [aria-label], span[dir="auto"]');
        for (let tl of tLinks) {
            if (tl.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"], form')) continue;
            let aria = (tl.getAttribute('aria-label') || '').trim();
            let txt = (tl.innerText || tl.textContent || '').trim();
            if (aria) timeCands.push(aria);
            if (txt) timeCands.push(txt);
        }
        for (let rawCand of timeCands) {
            if (!rawCand) continue;
            let cand = rawCand.split('·')[0].split('\\u00b7')[0].trim();
            if (cand.length < 2 || cand.length > 70) continue;
            let cLower = cand.toLowerCase();
            if (cLower.includes('komentar') || cLower.includes('reaksi') || cLower.includes('suka') || cLower.includes('bagikan') || cLower.includes('ikuti')) continue;
            if (yearRegex.test(cand) || (monthRegex.test(cand) && /\\d/.test(cand)) || relTimeRegex.test(cand) || cLower.includes('kemarin') || cLower.includes('baru saja') || cLower.endsWith(' yang lalu') || cLower.endsWith(' lalu') || cLower.endsWith(' ago')) {
                if (yearRegex.test(cand)) {
                    postDate = cand;
                    break;
                } else if (postDate === 'Terkini') {
                    postDate = cand;
                }
            }
        }

        // Stats
        let commentsCount = 0;
        let reactionsCount = 0;
        let allBtns = postEl.querySelectorAll('div[role="button"], span[dir="auto"], span, a');
        for (let s of allBtns) {
            let t = (s.innerText || s.textContent || '').toLowerCase();
            let aria = (s.getAttribute('aria-label') || '').toLowerCase();
            let mCom = t.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?)\\s*(?:komentar|comment)/i) ||
                       aria.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?)\\s*(?:komentar|comment)/i);
            if (mCom) {
                let numStr = mCom[1].replace(/\\s/g, '').replace(',', '.');
                if (numStr.endsWith('rb') || numStr.endsWith('k')) commentsCount = Math.round(parseFloat(numStr) * 1000);
                else if (numStr.endsWith('jt') || numStr.endsWith('m')) commentsCount = Math.round(parseFloat(numStr) * 1000000);
                else commentsCount = parseInt(numStr.replace(/[^0-9]/g, '')) || 0;
                break;
            }
        }

        return {
            author: author,
            post_text: postText,
            post_date: postDate,
            comments_count: commentsCount,
            reactions_count: reactionsCount
        };
    """)

    p_author = post_info.get('author', 'Warga') if post_info else 'Warga'
    p_text = post_info.get('post_text', '') if post_info else ''
    p_date = post_info.get('post_date', 'Terkini') if post_info else 'Terkini'
    p_comments_count = post_info.get('comments_count', 0) if post_info else 0
    p_reactions_count = post_info.get('reactions_count', 0) if post_info else 0

    p_url = format_facebook_url(raw_url=clean_url, current_page_url=driver.current_url, author=p_author)
    if not p_url or p_url.startswith('https://www.facebook.com/search/'):
        p_url = clean_url

    # Ekstrak ID dari URL
    p_id = ''
    m_id = (
        re.search(r'/(?:posts|permalink|videos|reel|reels)/([0-9]+)', p_url) or
        re.search(r'[?&](?:story_fbid|multi_permalinks|fbid|v)=([0-9]+)', p_url)
    )
    if m_id:
        p_id = m_id.group(1)
    else:
        p_id = str(abs(hash(p_url)) % 1000000000)

    p_hashtags = extract_hashtags(p_text)
    p_lang = detect_language(p_text)
    csv_label = "[Direct Link] " + p_url
    is_vid_direct = any(vm in p_url.lower() for vm in ['/watch', '/reel/', '/reels/', '/videos/', '/share/v/', '/share/r/'])
    p_sub = "[Video]" if is_vid_direct else ""

    print(f"[*] Data Postingan: @{p_author} ({p_date})")
    print(f"  * Link: {p_url}")
    print(f"  * Teks: \"{(p_text or '')[:70]}...\"")
    print(f"  * Estimasi Komentar: {p_comments_count}")

    # 1. Simpan metadata postingan ke post_csv
    save_to_csv(post_csv, [
        "Facebook", csv_label, p_id, p_date, p_author,
        "", "", 0, 0, "",
        "", p_text, p_reactions_count, 0, 0,
        p_comments_count, p_sub, p_lang, p_hashtags,
        "No", "No", "No", "", "", p_url
    ])

    # 2. Ambil komentar postingan ini
    print("  [*] Memeriksa & mengambil komentar postingan...")
    switch_filter_to_all_comments(driver)
    post_comments = exhaustively_scroll_and_extract_comments(
        driver, max_idle_scrolls=4, max_total_comments_limit=max_comments_per_post, current_post_text=p_text
    )
    if post_comments:
        p_comments_count = max(p_comments_count, len(post_comments))

    if post_comments:
        for c in post_comments:
            c_prof_url = c.get('profile_url', '')
            c_username = c.get('username') or c.get('author', 'Warga')
            c_author = c.get('author', 'Warga')
            c_text = c.get('comment_text', '')
            c_lang = detect_language(c_text)
            c_is_rep = "Yes" if str(c.get('is_reply', '')).upper() in ['YA', 'YES', 'TRUE', '1'] else "No"
            save_to_csv(comment_csv, [
                "Facebook", csv_label, p_id, p_date, p_author,
                "", p_text, p_reactions_count, 0, 0,
                p_comments_count, c.get('comment_id'), c.get('comment_date'), c_author, c_username,
                c_prof_url, c_text, c.get('likes', 0), c.get('reply_count', 0), c_is_rep,
                c.get('reply_to', ''), c_lang, p_hashtags, "", p_url
            ])
        print(f"  [+] Berhasil menyimpan link postingan DAN {len(post_comments)} komentar ke CSV!")
    else:
        # Jika postingan tidak memiliki komentar, link postingan tetap dicatat di comment_csv
        save_to_csv(comment_csv, [
            "Facebook", csv_label, p_id, p_date, p_author,
            "", p_text, p_reactions_count, 0, 0,
            0, f"no_comment_{p_id}", p_date, "-", "-",
            "", "[Tidak ada komentar]", 0, 0, "No",
            "", p_lang, p_hashtags, "", p_url
        ])
        print(f"  [i] Postingan tidak memiliki komentar. Link postingan ({p_url}) berhasil disimpan ke file CSV!")


def process_search_workflow(driver, keyword, post_csv, comment_csv, max_posts=20, max_comments_per_post=150, custom_search_url=None, group_name=None, min_year=2025, is_search_mode=False):
    """
    Workflow 4 Langkah Berurutan (Post per Post) dengan Kecepatan Tinggi & Deduplikasi Sheet Otomatis:
    1. Buka Keyword di Facebook Search Feed / Group Search.
    2. Aktifkan Filter 'Postingan Terbaru'.
    3. Ambil postingan berikutnya di feed -> Cek Tahun (Skip jika < 2025) -> Cek Sheet (Skip jika sudah ada).
    4. Klik Toggle Komentar -> Ubah filter menjadi 'Semua Komentar'.
    5. Scroll kontainer komentar & bongkar balasan sampai HABIS -> Simpan CSV -> Lanjut Post Berikutnya!
    """
    # Memuat seluruh database postingan & komentar yang sudah pernah tersimpan di seluruh sheet/CSV
    seen_signatures, seen_post_ids, seen_post_urls, seen_comment_keys = load_all_existing_sheet_data(post_csv, comment_csv)

    total_posts_saved = 0
    total_comments_saved = 0
    empty_scrolls = 0
    filter_fallback_done = False
    filter_version_used = "recent" if is_search_mode else "chrono"

    if custom_search_url:
        search_url = custom_search_url
    elif is_search_mode:
        search_url = build_search_url(keyword, use_filter=True, filter_version="recent")
    else:
        search_url = f"https://www.facebook.com/search/posts/?q={urllib.parse.quote(keyword)}&filters={FB_CHRONOSORT_FILTER}"

    title_info = f"Grup '{group_name}' | Kata Kunci: '{keyword}'" if group_name else f"Kata Kunci: '{keyword}'"
    max_label = f"{max_posts} Postingan" if max_posts > 0 else "Tanpa Batas (Ambil Semua)"
    com_label = f"{max_comments_per_post} Komentar / Post" if max_comments_per_post > 0 else "Tanpa Batas (Ambil Semua)"
    print(f"\n" + "=" * 65)
    print(f"[*] LANGKAH 1: Memproses {title_info}")
    print(f"[*] Target Batas Postingan   : {max_label}")
    print(f"[*] Target Batas Komentar    : {com_label}")
    print(f"[*] Filter Periode Postingan : Minimal Tahun {min_year} ke atas (Postingan <= {min_year-1} dilewati otomatis)")
    if seen_signatures or seen_post_ids:
        print(f"[*] [DEDUPLIKASI SHEET AKTIF] Terdeteksi {len(seen_signatures)} postingan & {len(seen_comment_keys)} komentar sudah ada di sheet (akan otomatis di-SKIP).")
    print(f"[*] Lokasi Penyimpanan Hasil:")
    print(f"    - Postingan: {post_csv}")
    print(f"    - Komentar : {comment_csv}")
    print("=" * 65)

    # Periksa apakah halaman pencarian / grup rusak atau dialihkan
    is_broken, broken_reason = is_page_or_group_broken(driver, expected_url=search_url)
    if is_broken:
        print(f"  [!] Halaman grup/pencarian rusak atau tidak dapat diakses ({broken_reason}).")
        return "BROKEN"

    # Coba aktifkan filter 'Postingan Terbaru' jika tombol tersedia
    apply_recent_posts_filter(driver)

    while (max_posts == 0 or total_posts_saved < max_posts) and empty_scrolls < 12:
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        # Pastikan modal dialog tertutup dan tetap di halaman pencarian
        if is_search_mode:
            close_search_dialog(driver, search_url=search_url)
        else:
            close_post_dialog(driver, search_url=search_url)

        if is_search_mode and DEBUG_SEARCH:
            try:
                info = driver.execute_script("""
                    return {
                        url: location.href,
                        feed: document.querySelectorAll('div[role="feed"] > div').length,
                        article: document.querySelectorAll('div[role="article"]').length,
                        bodyH: document.body.scrollHeight,
                        scrollY: window.scrollY
                    };
                """)
                print(f"  [DEBUG-SEARCH] {info}")
            except Exception:
                pass

        # Cari postingan berikutnya yang belum diproses dari feed
        next_post = driver.execute_script("""
            let seenSignatures = arguments[0];
            let seenPostIds = arguments[1];
            let seenPostUrls = arguments[2];
            let isSearchMode = arguments[4] === true;

            function decodeUzpf(tokenStr) {
                if (!tokenStr) return '';
                let m = tokenStr.match(/Uzpf([a-zA-Z0-9_-]+={0,2})/);
                if (!m) return '';
                let b64Part = m[1].replace(/-/g, '+').replace(/_/g, '/');
                let pad = 4 - (b64Part.length % 4);
                if (pad > 0 && pad < 4) b64Part += '='.repeat(pad);
                try {
                    let dec = atob(b64Part);
                    let mId = dec.match(/(?:ISC|VK|story|fbid):([0-9]{8,25})/);
                    if (mId) return mId[1];
                    let digits = dec.match(/([0-9]{10,25})/g);
                    if (digits && digits.length > 0) return digits[digits.length - 1];
                } catch(e) {}
                return '';
            }

            // Dapatkan HANYA kartu postingan terluar (outermost post cards)
            function getPostCards() {
                let candidates = [];
                if (isSearchMode) {
                    candidates = Array.from(document.querySelectorAll('div[role="feed"] > div, div[role="article"], div[data-pagelet*="Search"] > div, div[data-pagelet*="FeedUnit"]'));
                    if (candidates.length === 0) {
                        candidates = Array.from(document.querySelectorAll('div[role="main"] div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"]'));
                    }
                } else {
                    candidates = Array.from(document.querySelectorAll('div[role="feed"] > div, div[role="article"]'));
                    if (candidates.length === 0) {
                        candidates = Array.from(document.querySelectorAll('div[data-ad-preview="message"], div[class*="x1yztbdb"]'));
                    }
                }
                let postCards = [];
                for (let c of candidates) {
                    if (!c || c.offsetHeight < 50) continue;
                    let isChild = false;
                    for (let other of postCards) {
                        if (other.contains(c)) { isChild = true; break; }
                    }
                    if (!isChild) {
                        postCards = postCards.filter(existing => !c.contains(existing));
                        postCards.push(c);
                    }
                }
                return postCards;
            }

            let feedNodes = getPostCards();

            for (let idx = 0; idx < feedNodes.length; idx++) {
                let p = feedNodes[idx];
                if (p.getAttribute('data-fb-seen') === 'true') {
                    continue;
                }

                let cardFullText = (p.innerText || '').trim();
                let cardLower = cardFullText.toLowerCase();

                let hasPostLink = !!p.querySelector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], a[href*="/videos/"], a[href*="/reel/"], a[href*="/reels/"], a[href*="/watch"], a[href*="/share/v/"], a[href*="/share/r/"], a[href*="/share/p/"], a[href*="multi_permalinks"], a[href*="set=gm."], a[href*="set=pcb."], a[href*="?v="], a[href*="&v="]');
                let hasPostMessage = !!p.querySelector('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"]');
                let hasVideo = !!p.querySelector('video, div[data-video-id], [aria-label*="Video" i], [aria-label*="Reel" i], [aria-label*="Putar" i], [aria-label*="Play" i]');

                // Lewati widget non-post (saran teman, ikuti profil, saran grup, filter) - Jangan lewati jika postingan memuat video
                let isWidget = !hasVideo && (
                    cardLower === 'ikuti' || cardLower === 'follow' || cardLower === 'tambah jadi teman' || cardLower === 'gabung' ||
                    cardLower.startsWith('orang yang mungkin anda kenal') ||
                    cardLower.startsWith('saran untuk anda') ||
                    cardLower.startsWith('hasil untuk') ||
                    cardLower.startsWith('menampilkan hasil') ||
                    cardLower.startsWith('filter') ||
                    (cardLower.includes('tambah jadi teman') && !hasPostLink) ||
                    (!hasPostLink && !hasPostMessage && (cardLower.includes('ikuti') || cardLower.includes('follow') || cardLower.includes('gabung')))
                );

                if (isWidget) {
                    p.setAttribute('data-fb-seen', 'true');
                    continue;
                }

                // Helper cerdas & multi-layer untuk menarik caption/deskripsi postingan Facebook
                function resolveFacebookPostCaption(card) {
                    if (!card) return '';

                    // 1. Otomatis klik tombol 'Lihat selengkapnya' / 'See more' agar caption lengkap tidak terpotong
                    try {
                        let seeMoreBtns = card.querySelectorAll('div[role="button"], span[role="button"]');
                        for (let btn of seeMoreBtns) {
                            let bTxt = (btn.innerText || btn.textContent || '').trim().toLowerCase();
                            if (bTxt === 'lihat selengkapnya' || bTxt === 'see more' || bTxt === 'baca selengkapnya' || bTxt === 'more' || bTxt === 'selengkapnya') {
                                btn.click();
                            }
                        }
                    } catch(e) {}

                    // 2. Selector utama pesan/teks postingan Facebook Web & Comet
                    let primarySelectors = [
                        'div[data-ad-preview="message"]',
                        'div[data-ad-comet-preview="message"]',
                        'div[data-testid="post_message"]',
                        'div[id*="post_message"]',
                        'div[class*="userContent"]',
                        'div.x1iorvi4',
                        'div[dir="auto"][style*="text-align"]'
                    ];

                    for (let sel of primarySelectors) {
                        let msgEl = card.querySelector(sel);
                        if (msgEl) {
                            let txt = (msgEl.innerText || msgEl.textContent || '').trim();
                            if (txt.length > 3) {
                                return txt;
                            }
                        }
                    }

                    // 3. Scan semua blok teks dir="auto" dengan memfilter header/author/tombol sistem
                    let allBlocks = Array.from(card.querySelectorAll('div[dir="auto"], span[dir="auto"]'));
                    let validCandidates = [];

                    for (let b of allBlocks) {
                        if (b.closest('div[role="button"], button, [aria-label*="Suka"], [aria-label*="Komentar"], [aria-label*="Bagikan"], [aria-label*="Like"], [aria-label*="Comment"]')) {
                            continue;
                        }
                        if (b.closest('h2, h3, h4, [role="heading"]')) {
                            continue;
                        }
                        let t = (b.innerText || b.textContent || '').trim();
                        let tLower = t.toLowerCase();

                        if (
                            t.length < 5 ||
                            tLower.startsWith('hasil untuk') ||
                            tLower.startsWith('menampilkan hasil') ||
                            tLower === 'suka' || tLower === 'komentar' || tLower === 'bagikan' ||
                            tLower === 'like' || tLower === 'comment' || tLower === 'share' ||
                            tLower === 'ikuti' || tLower === 'follow' || tLower === 'tambah jadi teman' ||
                            tLower.includes('grup publik') || tLower.includes('public group') ||
                            tLower.includes('anggota') || tLower.includes('members') ||
                            tLower === 'lihat selengkapnya' || tLower === 'see more' ||
                            tLower.endsWith(' yang lalu') || tLower.endsWith(' ago')
                        ) {
                            continue;
                        }
                        validCandidates.push(t);
                    }

                    if (validCandidates.length > 0) {
                        validCandidates.sort((a, b) => b.length - a.length);
                        return validCandidates[0];
                    }

                    // 4. Fallback jika postingan berupa foto poster / infografis
                    let img = card.querySelector('img[alt]');
                    if (img && img.alt && img.alt.length > 15 && !img.alt.toLowerCase().includes('profil') && !img.alt.toLowerCase().includes('avatar')) {
                        return '[Foto] ' + img.alt.trim();
                    }

                    return '';
                }

                let postText = resolveFacebookPostCaption(p);

                // Fallback jika caption belum didapatkan dari selector standar
                if (postText.length <= 3 && cardFullText.length > 5) {
                    let lines = cardFullText.split('\\n').map(l => l.trim()).filter(l => l.length > 5);
                    for (let line of lines) {
                        let lLower = line.toLowerCase();
                        if (lLower.startsWith('hasil untuk') || lLower.startsWith('menampilkan') ||
                            lLower === 'suka' || lLower === 'komentar' || lLower === 'bagikan' ||
                            lLower === 'ikuti' || lLower === 'follow' || lLower === 'tambah jadi teman' ||
                            lLower.includes('grup publik') || lLower.includes('anggota')) continue;
                        postText = line;
                        break;
                    }
                    if (postText.length <= 3 && (hasPostLink || hasPostMessage)) {
                        postText = cardFullText.substring(0, 120);
                    }
                }

                // Jika tetap tidak ada teks dan bukan postingan valid, lewati kartu ini
                if (postText.length <= 2 || (!hasPostLink && !hasPostMessage && postText.length < 15)) {
                    p.setAttribute('data-fb-seen', 'true');
                    continue;
                }

                if (postText.toLowerCase().startsWith('hasil untuk') || postText.toLowerCase().startsWith('menampilkan hasil')) {
                    p.setAttribute('data-fb-seen', 'true');
                    continue;
                }

                // Helper untuk membaca teks asli dari elemen HTML, termasuk SVG <use xlink:href="#Svg...">
                function resolveElementTextWithSvg(element) {
                    if (!element) return '';
                    let result = '';
                    
                    let aria = element.getAttribute('aria-label');
                    if (aria) result += aria + ' ';
                    
                    let labelledBy = element.getAttribute('aria-labelledby');
                    if (labelledBy) {
                        let ids = labelledBy.split(/\\s+/);
                        for (let id of ids) {
                            let target = document.getElementById(id);
                            if (target) {
                                result += (target.textContent || target.innerText || '') + ' ';
                                let subUses = target.querySelectorAll('use');
                                for (let u of subUses) {
                                    let href = u.getAttribute('xlink:href') || u.getAttribute('href') || '';
                                    if (href.startsWith('#')) {
                                        let ref = document.getElementById(href.substring(1));
                                        if (ref) result += (ref.textContent || ref.innerText || '') + ' ';
                                    }
                                }
                            }
                        }
                    }

                    let useNodes = element.querySelectorAll('use');
                    for (let u of useNodes) {
                        let href = u.getAttribute('xlink:href') || u.getAttribute('href') || '';
                        if (href.startsWith('#')) {
                            let ref = document.getElementById(href.substring(1));
                            if (ref) {
                                result += (ref.textContent || ref.innerText || '') + ' ';
                            }
                        }
                    }

                    let svgTexts = element.querySelectorAll('svg text, svg tspan');
                    for (let st of svgTexts) {
                        result += (st.textContent || st.innerText || '') + ' ';
                    }

                    result += (element.innerText || element.textContent || '') + ' ';
                    return result.replace(/\\s+/g, ' ').trim();
                }

                let author = 'Warga / Anonim';
                let authorEl = p.querySelector('h2 a, h3 a, h4 a, h2 strong, h3 strong, h4 strong, a strong, strong span, a[role="link"] span, h2, h3');
                if (authorEl) {
                    let resolvedAuth = resolveElementTextWithSvg(authorEl);
                    if (resolvedAuth) {
                        let cleanA = resolvedAuth.split('\\n')[0].replace(/·\\s*(?:Ikuti|Follow|Gabung|Join|Disponsori|Sponsored).*$/i, '').trim();
                        if (cleanA && !cleanA.toLowerCase().startsWith('hasil untuk') && cleanA.toLowerCase() !== 'facebook' && cleanA.toLowerCase() !== 'ikuti' && cleanA.toLowerCase() !== 'tambah jadi teman') {
                            author = cleanA;
                        }
                    }
                }

                let authorLinkEl = p.querySelector('h2 a[href], h3 a[href], h4 a[href], strong a[href], a[role="link"][tabindex="0"]');
                let profileUrl = authorLinkEl ? (authorLinkEl.href || '').split('?')[0] : '';

                let signature = author + ':::' + postText.substring(0, 45);

                let targetGroupName = arguments[3] || '';
                let postUrl = '';
                let postId = '';
                let rawPostLink = '';
                let groupId = targetGroupName;
                let rdid = '';
                let isVideoPost = hasVideo || !!p.querySelector('video, div[data-video-id], [aria-label*="Video" i], [aria-label*="Reel" i]');

                // 1. Periksa apakah halaman aktif berada di dalam grup
                let currHref = window.location.href || '';
                let pageGrpM = currHref.match(/facebook\\.com\\/groups\\/([^/?#]+)/);
                if (pageGrpM && !['search', 'feed', 'joins', 'create', 'discover'].includes(pageGrpM[1].toLowerCase())) {
                    groupId = pageGrpM[1];
                }

                // Helper komprehensif untuk deteksi dan ekstraksi link video/reel/post/photo
                function parsePostOrVideoLink(url, currentGroupId) {
                    if (!url || typeof url !== 'string') return null;
                    if (url.includes('/search/') || url.includes('/hashtag/') || url.includes('/notifications')) return null;

                    // 1. Facebook Watch
                    let mWatch = url.match(/[?&]v=([0-9]{6,25})/i) || url.match(/\\/watch\\/?\\?v=([0-9]{6,25})/i);
                    if (mWatch) {
                        return { type: 'video', id: mWatch[1], canonicalUrl: `https://www.facebook.com/watch/?v=${mWatch[1]}` };
                    }

                    // 2. Facebook Reel (/reel/ atau /reels/)
                    let mReel = url.match(/\\/(?:reel|reels)\\/([0-9]{6,25})/i);
                    if (mReel) {
                        return { type: 'reel', id: mReel[1], canonicalUrl: `https://www.facebook.com/reel/${mReel[1]}/` };
                    }

                    // 3. Photo Links (/photo/, photo.php, /photos/)
                    if (url.includes('/photo') || url.includes('photo.php')) {
                        let mSet = url.match(/set=(?:gm|pcb)\\.([0-9]{6,25})/i);
                        if (mSet) {
                            let postId = mSet[1];
                            let gId = currentGroupId;
                            let mIdor = url.match(/idorvanity=([0-9]+)/i);
                            if (mIdor) gId = mIdor[1];
                            if (gId) {
                                return { type: 'post', id: postId, groupId: gId, canonicalUrl: `https://www.facebook.com/groups/${gId}/posts/${postId}` };
                            }
                            return { type: 'post', id: postId, canonicalUrl: `https://www.facebook.com/permalink.php?story_fbid=${postId}` };
                        }
                        let mFbid = url.match(/[?&]fbid=([0-9]{6,25})/i);
                        if (mFbid) {
                            let fbid = mFbid[1];
                            let mSetA = url.match(/[?&]set=(a\\.[0-9.]+)/i);
                            let photoUrl = mSetA ? `https://www.facebook.com/photo/?fbid=${fbid}&set=${mSetA[1]}` : `https://www.facebook.com/photo/?fbid=${fbid}`;
                            return { type: 'photo', id: fbid, canonicalUrl: photoUrl };
                        }
                    }

                    // 4. Video dalam Grup (/groups/{groupId}/videos/{videoId})
                    let mGrpVid = url.match(/\\/groups\\/([^/?#]+)\\/videos\\/([0-9]{6,25})/i);
                    if (mGrpVid) {
                        let vId = mGrpVid[2];
                        return { type: 'video', id: vId, canonicalUrl: `https://www.facebook.com/watch/?v=${vId}` };
                    }

                    // 5. Video Halaman/User (/author/videos/{videoId})
                    let mUsrVid = url.match(/facebook\\.com\\/([^/?#]+)\\/videos\\/([0-9]{6,25})/i);
                    if (mUsrVid && !['groups', 'watch', 'permalink.php'].includes(mUsrVid[1].toLowerCase())) {
                        return { type: 'video', id: mUsrVid[2], author: mUsrVid[1], canonicalUrl: `https://www.facebook.com/watch/?v=${mUsrVid[2]}` };
                    }

                    // 6. Share link (/share/v/, /share/r/, /share/p/)
                    let mShare = url.match(/\\/share\\/(v|r|p)\\/([a-zA-Z0-9_-]+)/i);
                    if (mShare) {
                        let sType = mShare[1] === 'v' ? 'video' : (mShare[1] === 'r' ? 'reel' : 'post');
                        return { type: sType, id: mShare[2], canonicalUrl: url.split('?')[0] };
                    }

                    // 7. Postingan Grup dengan set=gm. atau set=pcb.
                    let mSetAny = url.match(/set=(?:gm|pcb)\\.([0-9]{6,25})/i);
                    if (mSetAny) {
                        let pId = mSetAny[1];
                        if (currentGroupId && pId !== currentGroupId) {
                            return { type: 'post', id: pId, groupId: currentGroupId, canonicalUrl: `https://www.facebook.com/groups/${currentGroupId}/posts/${pId}` };
                        }
                        return { type: 'post', id: pId, canonicalUrl: `https://www.facebook.com/permalink.php?story_fbid=${pId}` };
                    }

                    // 8. Postingan Grup (/groups/{groupId}/posts/{postId} atau permalink/{postId})
                    let mGrpPost = url.match(/\\/groups\\/([^/?#]+)\\/(?:user\\/[^/?#]+\\/)?(?:posts|permalink)\\/([0-9]{6,25})/i);
                    if (mGrpPost) {
                        let gId = mGrpPost[1];
                        let pId = mGrpPost[2];
                        if (pId !== gId) {
                            return { type: 'post', id: pId, groupId: gId, canonicalUrl: `https://www.facebook.com/groups/${gId}/posts/${pId}` };
                        }
                    }

                    // 9. Parameter query legacy (multi_permalinks, story_fbid)
                    let mMulti = url.match(/[?&]multi_permalinks=([0-9]{6,25})/i);
                    if (mMulti) {
                        let pId = mMulti[1];
                        if (currentGroupId && pId !== currentGroupId) {
                            return { type: 'post', id: pId, groupId: currentGroupId, canonicalUrl: `https://www.facebook.com/groups/${currentGroupId}/posts/${pId}` };
                        }
                        return { type: 'post', id: pId, canonicalUrl: `https://www.facebook.com/permalink.php?story_fbid=${pId}` };
                    }
                    let mStory = url.match(/[?&]story_fbid=([0-9]{6,25})/i);
                    if (mStory) {
                        let pId = mStory[1];
                        if (currentGroupId && pId !== currentGroupId) {
                            return { type: 'post', id: pId, groupId: currentGroupId, canonicalUrl: `https://www.facebook.com/permalink.php?story_fbid=${pId}&id=${currentGroupId}` };
                        }
                        return { type: 'post', id: pId, canonicalUrl: `https://www.facebook.com/permalink.php?story_fbid=${pId}` };
                    }

                    // 10. User / Page Post (/author/posts/{postId})
                    let mUsrPost = url.match(/facebook\\.com\\/([^/?#]+)\\/posts\\/([0-9]{6,25})/i);
                    if (mUsrPost && !['groups', 'permalink.php', 'story.php'].includes(mUsrPost[1].toLowerCase())) {
                        return { type: 'post', id: mUsrPost[2], author: mUsrPost[1], canonicalUrl: `https://www.facebook.com/${mUsrPost[1]}/posts/${mUsrPost[2]}` };
                    }

                    return null;
                }

                // 2. Scan link di dalam kartu, prioritaskan link video, reel, photo, watch, permalink, posts
                let links = p.querySelectorAll('a[href*="/watch"], a[href*="/reel/"], a[href*="/reels/"], a[href*="/videos/"], a[href*="/photo"], a[href*="photo.php"], a[href*="/posts/"], a[href*="/permalink/"], a[href*="multi_permalinks"], a[href*="set=gm."], a[href*="set=pcb."], a[href*="story_fbid="], a[href*="/share/"], a[href*="Uzpf"], a[href*="/groups/"], a[role="link"][href], a[href]');
                for (let a of links) {
                    let href = a.href || a.getAttribute('href') || '';
                    if (!href) continue;

                    if (href.includes('rdid=')) {
                        let mRd = href.match(/[?&]rdid=([a-zA-Z0-9_-]+)/);
                        if (mRd && mRd[1] && !rdid) rdid = mRd[1];
                    }

                    let grpM = href.match(/facebook\\.com\\/groups\\/([^/?#]+)/) || href.match(/\\/groups\\/([^/?#]+)/);
                    if (grpM && !['search', 'feed', 'joins', 'create', 'discover'].includes(grpM[1].toLowerCase())) {
                        if (!groupId) groupId = grpM[1];
                    }

                    let parsed = parsePostOrVideoLink(href, groupId);
                    if (parsed) {
                        postId = parsed.id;
                        postUrl = parsed.canonicalUrl;
                        if (parsed.type === 'video' || parsed.type === 'reel') isVideoPost = true;
                        break;
                    }
                }

                // Fallback 1: Cek atribut video pada DOM kartu (data-video-id, video tag)
                if (!postId) {
                    let vIdEl = p.querySelector('[data-video-id]');
                    if (vIdEl) {
                        let vId = vIdEl.getAttribute('data-video-id');
                        if (vId && /^[0-9]{6,25}$/.test(vId)) {
                            postId = vId;
                            isVideoPost = true;
                            postUrl = `https://www.facebook.com/watch/?v=${vId}`;
                        }
                    }
                }

                // Fallback 2: Scan link kartu untuk mencari token Uzpf (jika belum ditemukan parsed link)
                if (!postId) {
                    for (let a of links) {
                        let href = a.href || a.getAttribute('href') || '';
                        let uzId = decodeUzpf(href);
                        if (uzId && uzId !== groupId) {
                            postId = uzId;
                            postUrl = `https://www.facebook.com/groups/${groupId}/posts/${uzId}`;
                            break;
                        }
                    }
                }

                // Fallback 3: Scan innerHTML kartu postingan untuk mencari ID video / postingan
                if (!postId) {
                    let inner = p.innerHTML || '';
                    let mInner = inner.match(/(?:video_id[":\\[=]+|data-video-id="|multi_permalinks[":\\[=]+|story_fbid[":\\[=]+|post_id[":\\[=]+|top_level_post_id[":\\[=]+)([0-9]{8,25})/i);
                    if (mInner && mInner[1] && mInner[1] !== groupId) {
                        postId = mInner[1];
                        let isInnerVid = inner.includes('video_id') || inner.includes('data-video-id') || isVideoPost;
                        if (isInnerVid) {
                            isVideoPost = true;
                            postUrl = `https://www.facebook.com/watch/?v=${postId}`;
                        } else if (groupId) {
                            postUrl = `https://www.facebook.com/groups/${groupId}/posts/${postId}`;
                        }
                    }
                }

                // Susun Canonical Direct Post Format jika belum terbentuk
                if (!postUrl && groupId && postId && postId !== groupId) {
                    if (isVideoPost) postUrl = `https://www.facebook.com/watch/?v=${postId}`;
                    else postUrl = `https://www.facebook.com/groups/${groupId}/posts/${postId}`;
                }
                if (!postUrl && postId) {
                    if (isVideoPost) postUrl = `https://www.facebook.com/watch/?v=${postId}`;
                    else postUrl = `https://www.facebook.com/permalink.php?story_fbid=${postId}`;
                }
                if (!postUrl && groupId) {
                    postUrl = `https://www.facebook.com/groups/${groupId}`;
                }

                let cleanUrl = postUrl ? postUrl.split('?')[0].replace(/\\/$/, '') : '';

                // DEDUPLIKASI: Lewati jika postingan ini sudah pernah diproses
                let isSpecificPostUrl = cleanUrl && !cleanUrl.includes('/search/') && (
                    cleanUrl.includes('/posts/') || cleanUrl.includes('/permalink/') || cleanUrl.includes('story_fbid') ||
                    cleanUrl.includes('/videos/') || cleanUrl.includes('/reel/') || cleanUrl.includes('/reels/') ||
                    cleanUrl.includes('/watch') || cleanUrl.includes('/share/') || cleanUrl.includes('multi_permalinks') ||
                    cleanUrl.includes('/photo')
                );
                if (seenSignatures.includes(signature) || (postId && seenPostIds.includes(postId)) || (isSpecificPostUrl && seenPostUrls.includes(cleanUrl))) {
                    p.setAttribute('data-fb-seen', 'true');
                    continue;
                }

                // EKSTRAKSI TANGGAL POSTINGAN SECARA PRESISI DARI ELEMEN TIMESTAMP KHUSUS
                let postDate = '';
                const monthRegex = /\\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|agt|agu|aug|sep|okt|oct|nov|des|dec)\\b/i;
                const yearRegex = /\\b(19\\d{2}|20\\d{2})\\b/;
                const relTimeRegex = /\\b\\d+\\s*(?:thn|th|tahun|yr|yrs|year|years|mgg|minggu|wk|week|weeks|hr|hari|day|days|jam|jm|hour|hours|mnt|menit|min|mins|lalu|ago)\\b/i;

                let timeCandidates = [];

                // 1. Scan semua elemen dengan aria-label di dalam p (di luar pesan & komentar)
                let ariaEls = p.querySelectorAll('[aria-label]');
                for (let el of ariaEls) {
                    if (el.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"], form')) continue;
                    let aria = (el.getAttribute('aria-label') || '').trim();
                    if (aria) timeCandidates.push(aria);
                }

                // 2. Scan semua link permalink/timestamp di dalam kartu
                let timeLinks = p.querySelectorAll('abbr, a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], a[href*="/videos/"], a[href*="/reel/"], a[role="link"]');
                for (let tl of timeLinks) {
                    if (tl.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"], form')) continue;
                    let aria = (tl.getAttribute('aria-label') || '').trim();
                    let txt = resolveElementTextWithSvg(tl);
                    if (aria) timeCandidates.push(aria);
                    if (txt) timeCandidates.push(txt);
                }

                // 3. Scan span di dalam kartu
                let headerSpans = p.querySelectorAll('span[dir="auto"], span[id]');
                for (let sp of headerSpans) {
                    if (sp.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"], form, [role="button"], button')) continue;
                    let txt = resolveElementTextWithSvg(sp);
                    if (txt) timeCandidates.push(txt);
                }

                // Evaluasi kandidat tanggal
                for (let rawCand of timeCandidates) {
                    if (!rawCand) continue;
                    // Potong suffix privacy seperti " · Dibagikan kepada Publik" atau " · "
                    let cand = rawCand.split('·')[0].split('\\u00b7')[0].trim();
                    if (cand.length < 2 || cand.length > 70) continue;
                    let cLower = cand.toLowerCase();
                    if (cLower.includes('komentar') || cLower.includes('reaksi') || cLower.includes('suka') || 
                        cLower.includes('bagikan') || cLower.includes('ikuti') || cLower.includes('follow') || 
                        cLower.includes('gabung') || cLower.includes('tambah jadi teman') || cLower.includes('kirim pesan') ||
                        cLower.includes('foto profil') || cLower.includes('foto sampul') || cLower.startsWith('hasil untuk')) continue;

                    let isDate = (
                        yearRegex.test(cand) ||
                        (monthRegex.test(cand) && /\\d/.test(cand)) ||
                        relTimeRegex.test(cand) ||
                        cLower.includes('kemarin') || cLower.includes('yesterday') ||
                        cLower.includes('baru saja') || cLower.includes('just now') ||
                        cLower.endsWith(' yang lalu') || cLower.endsWith(' lalu') || cLower.endsWith(' ago')
                    );

                    if (isDate) {
                        if (yearRegex.test(cand)) {
                            postDate = cand;
                            break;
                        } else if (!postDate) {
                            postDate = cand;
                        }
                    }
                }

                if (!postDate) {
                    let abbrEl = p.querySelector('abbr');
                    if (abbrEl) {
                        postDate = (abbrEl.innerText || abbrEl.textContent || abbrEl.getAttribute('title') || '').trim();
                    }
                }

                if (!postDate) {
                    postDate = 'Terkini';
                }

                let commentCount = 0;
                let reactionCount = 0;
                let shareCount = 0;
                let playCount = 0;
                let hasCommentStats = false;

                // 1. Ekstraksi Jumlah Komentar
                let allSpansAndLinks = p.querySelectorAll('div[role="button"], a, span[dir="auto"], span, div[dir="auto"]');
                for (let s of allSpansAndLinks) {
                    let t = resolveElementTextWithSvg(s).toLowerCase();
                    let aria = (s.getAttribute('aria-label') || '').toLowerCase();
                    
                    let mCom = t.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?)\\s*(?:komentar|comment|comments|balasan|replies|reply)/i) ||
                               aria.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?)\\s*(?:komentar|comment|comments|balasan|replies|reply)/i);
                    if (mCom) {
                        let numStr = mCom[1].replace(/\\s/g, '').replace(',', '.');
                        if (numStr.endsWith('rb') || numStr.endsWith('k')) {
                            commentCount = Math.round(parseFloat(numStr) * 1000);
                        } else if (numStr.endsWith('jt') || numStr.endsWith('m')) {
                            commentCount = Math.round(parseFloat(numStr) * 1000000);
                        } else {
                            commentCount = parseInt(numStr.replace(/[^0-9]/g, '')) || 0;
                        }
                        hasCommentStats = true;
                        break;
                    }
                }

                if (!hasCommentStats) {
                    for (let s of allSpansAndLinks) {
                        let t = (s.innerText || s.textContent || '').trim();
                        let aria = (s.getAttribute('aria-label') || '').toLowerCase();
                        let parentTxt = s.parentElement ? (s.parentElement.innerText || s.parentElement.textContent || '').toLowerCase() : '';
                        let parentAria = s.parentElement ? (s.parentElement.getAttribute('aria-label') || '').toLowerCase() : '';

                        if (/^\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?$/i.test(t)) {
                            let isCom = (
                                aria.includes('komentar') || aria.includes('comment') ||
                                parentAria.includes('komentar') || parentAria.includes('comment') ||
                                parentTxt.includes('komentar') || parentTxt.includes('comment')
                            );
                            if (isCom) {
                                let numStr = t.replace(/\\s/g, '').replace(',', '.');
                                if (numStr.endsWith('rb') || numStr.endsWith('k')) {
                                    commentCount = Math.round(parseFloat(numStr) * 1000);
                                } else if (numStr.endsWith('jt') || numStr.endsWith('m')) {
                                    commentCount = Math.round(parseFloat(numStr) * 1000000);
                                } else {
                                    commentCount = parseInt(numStr.replace(/[^0-9]/g, '')) || 0;
                                }
                                hasCommentStats = true;
                                break;
                            }
                        }
                    }
                }

                // 2. Ekstraksi Reaksi / Suka
                for (let s of allSpansAndLinks) {
                    let aria = (s.getAttribute('aria-label') || '').toLowerCase();
                    let mReact = aria.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k)?)\\s*(?:reaksi|suka|like|orang menanggapi)/i);
                    if (mReact) {
                        let numStr = mReact[1].replace(/\\s/g, '').replace(',', '.');
                        if (numStr.endsWith('rb') || numStr.endsWith('k')) {
                            reactionCount = Math.round(parseFloat(numStr) * 1000);
                        } else {
                            reactionCount = parseInt(numStr.replace(/[^0-9]/g, '')) || 0;
                        }
                        break;
                    }
                }

                // 3. Ekstraksi Shares & Plays
                for (let s of allSpansAndLinks) {
                    let t = resolveElementTextWithSvg(s).toLowerCase();
                    let mShare = t.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k)?)\\s*(?:kali dibagikan|dibagikan|shares|share)/i);
                    if (mShare) {
                        let numStr = mShare[1].replace(/\\s/g, '').replace(',', '.');
                        shareCount = numStr.endsWith('rb') || numStr.endsWith('k') ? Math.round(parseFloat(numStr) * 1000) : (parseInt(numStr.replace(/[^0-9]/g, '')) || 0);
                        break;
                    }
                }

                for (let s of allSpansAndLinks) {
                    let t = resolveElementTextWithSvg(s).toLowerCase();
                    let mPlay = t.match(/(\\d+(?:[.,]\\d+)?\\s*(?:rb|k|jt|m)?)\\s*(?:tayangan|views|view|x ditonton)/i);
                    if (mPlay) {
                        let numStr = mPlay[1].replace(/\\s/g, '').replace(',', '.');
                        if (numStr.endsWith('rb') || numStr.endsWith('k')) playCount = Math.round(parseFloat(numStr) * 1000);
                        else if (numStr.endsWith('jt') || numStr.endsWith('m')) playCount = Math.round(parseFloat(numStr) * 1000000);
                        else playCount = parseInt(numStr.replace(/[^0-9]/g, '')) || 0;
                        break;
                    }
                }

                let isAd = (
                    cardFullText.includes('Bersponsor') || cardFullText.includes('Sponsored') ||
                    p.querySelector('[data-ad-preview], [data-ad-comet-preview]') !== null
                ) ? 'Yes' : 'No';
                let isSponsored = (
                    cardFullText.includes('Kemitraan berbayar') || cardFullText.includes('Paid partnership') ||
                    cardFullText.includes('Bersponsor') || cardFullText.includes('Sponsored')
                ) ? 'Yes' : 'No';
                let isPinned = (
                    cardFullText.includes('Disematkan') || cardFullText.includes('Pinned post') ||
                    p.querySelector('svg[aria-label*="semat" i], svg[aria-label*="pin" i]') !== null
                ) ? 'Yes' : 'No';

                let locationStr = '';
                let locMatch = cardFullText.match(/(?:—|\\-|\\bat\\b|\\bdi\\b)\\s+([A-Z][a-zA-Z0-9\\s,.-]{2,30})(?:\\s*·|\\s*\\n|$)/);
                if (locMatch && !['Facebook', 'Terkini', 'Suka', 'Komentar', 'Bagikan'].includes(locMatch[1].trim())) {
                    locationStr = locMatch[1].trim();
                }

                let musicMeta = '';
                let audioEl = p.querySelector('a[href*="/audio/"], a[href*="/music/"], span[aria-label*="audio" i]');
                if (audioEl) {
                    musicMeta = (audioEl.innerText || audioEl.textContent || '').trim();
                }

                // Tandai elemen postingan yang terpilih ini dengan atribut unik di DOM
                p.setAttribute('data-fb-seen', 'true');
                p.setAttribute('data-target-post', 'true');

                return {
                    dom_index: idx,
                    signature: signature,
                    post_id: postId || '',
                    author: author,
                    profile_url: profileUrl,
                    post_text: postText,
                    post_date: postDate,
                    post_url: postUrl || (groupId ? `https://www.facebook.com/groups/${groupId}` : window.location.href),
                    comments_count: commentCount,
                    reactions_count: reactionCount,
                    shares_count: shareCount,
                    plays_count: playCount,
                    is_video: isVideoPost,
                    is_ad: isAd,
                    is_pinned: isPinned,
                    is_sponsored: isSponsored,
                    location: locationStr,
                    music_meta: musicMeta,
                    card_full_text: cardFullText,
                    has_comment_stats: hasCommentStats
                };
            }

            return null;
        """, list(seen_signatures), list(seen_post_ids), list(seen_post_urls), group_name or '', is_search_mode)

        # Jika belum ada postingan baru di layar, scroll feed pencarian ke bawah
        if not next_post:
            empty_scrolls += 1

            # Fallback pertama: recent_posts -> chronosort
            if is_search_mode and not filter_fallback_done and total_posts_saved == 0 and empty_scrolls >= 3:
                print("\n[!] Filter 'recent_posts' tidak menghasilkan postingan.")
                print("[*] Mencoba fallback ke filter lama (chronosort)...")
                filter_version_used = "chrono"
                search_url = build_search_url(keyword, use_filter=True, filter_version="chrono")
                driver.get(search_url)
                pause_ctrl.sleep(3.5)
                filter_fallback_done = True
                empty_scrolls = 0
                continue

            # Fallback kedua: chronosort -> tanpa filter sama sekali (klik manual)
            if is_search_mode and filter_fallback_done and total_posts_saved == 0 and empty_scrolls >= 3:
                if filter_version_used == "chrono":
                    print("\n[!] Filter 'chronosort' juga gagal. Mencoba TANPA filter...")
                    search_url = build_search_url(keyword, use_filter=False)
                    driver.get(search_url)
                    pause_ctrl.sleep(3.5)
                    apply_recent_posts_filter(driver)  # klik manual tombol "Terbaru"
                    filter_version_used = "none"
                    empty_scrolls = 0
                    continue

            if is_search_mode:
                perform_search_feed_scroll(driver, distance=750)
            else:
                perform_feed_scroll(driver, distance=750)
            pause_ctrl.sleep(random.uniform(1.2, 1.8))
            continue

        # Postingan baru ditemukan
        empty_scrolls = 0
        p_sig = next_post.get('signature')
        p_id = next_post.get('post_id')
        p_author = next_post.get('author')
        p_profile_url = next_post.get('profile_url', '')
        p_text = next_post.get('post_text')
        p_card_full = next_post.get('card_full_text', '')
        p_date = next_post.get('post_date')
        raw_p_url = next_post.get('post_url')
        p_is_video = bool(next_post.get('is_video', False))

        # Standardisasi format URL Facebook ke canonical permalink (misal https://www.facebook.com/groups/.../permalink/.../)
        p_url = format_facebook_url(
            raw_url=raw_p_url,
            current_page_url=driver.current_url,
            post_id=p_id,
            author=p_author,
            group_name=group_name
        )
        if not p_is_video and any(vm in (p_url or '').lower() for vm in ['/watch', '/reel/', '/reels/', '/videos/', '/share/v/', '/share/r/']):
            p_is_video = True

        if not p_id or p_id == group_name:
            m_pid_check = (
                re.search(r'/(?:posts|permalink|videos|reel|reels)/([0-9]+)', p_url or '') or
                re.search(r'[?&](?:story_fbid|multi_permalinks|fbid|v)=([0-9]+)', p_url or '')
            )
            if m_pid_check:
                p_id = m_pid_check.group(1)

        clean_url = p_url.split('?')[0].rstrip('/') if p_url else ''
        dom_idx = next_post.get('dom_index', 0)
        p_comments_count = next_post.get('comments_count', 0)
        p_reactions_count = next_post.get('reactions_count', 0)
        p_shares_count = next_post.get('shares_count', 0)
        p_plays_count = next_post.get('plays_count', 0)
        p_is_ad = next_post.get('is_ad', 'No')
        p_is_pinned = next_post.get('is_pinned', 'No')
        p_is_sponsored = next_post.get('is_sponsored', 'No')
        p_location = next_post.get('location', '')
        p_music_meta = next_post.get('music_meta', '')

        # CHECK SHEET DEDUPLICATION (PYTHON LEVEL)
        is_spec_url = is_specific_post_url(clean_url)
        if p_sig in seen_signatures or (p_id and p_id in seen_post_ids) or (is_spec_url and clean_url in seen_post_urls):
            seen_signatures.add(p_sig)
            print(f"  [SUDAH ADA DI SHEET] Dilewati @{p_author}: \"{p_text[:40]}...\"")
            continue

        seen_signatures.add(p_sig)
        if p_id: seen_post_ids.add(p_id)
        if is_spec_url: seen_post_urls.add(clean_url)

        # FILTER TAHUN: Lewati postingan usang (misal tahun 2024 atau sebelumnya jika min_year=2025)
        if is_outdated_post(p_date, min_year=min_year):
            print(f"  [DILEWATI] Postingan Usang ({p_date}) @{p_author}: \"{p_text[:40]}...\" (Filter aktif: Hanya tahun {min_year}+)")
            continue

        # FILTER KATA KUNCI: Cek kesesuaian kata kunci pada teks, author, dan seluruh kartu
        if not is_keyword_relevant(p_text, author=p_author, keyword=keyword, group_name=group_name, card_full_text=p_card_full):
            short_txt = (p_text or p_card_full or '').strip().replace('\n', ' ')
            preview = f'"{short_txt[:40]}..."' if short_txt else '<Tanpa Teks / Gambar Saja>'
            print(f"  [DILEWATI] Tidak Memuat Kata Kunci '{keyword}' @{p_author}: {preview}")
            continue

        total_posts_saved += 1

        csv_keyword_label = f"[{group_name}] {keyword}" if group_name else keyword
        p_hashtags = extract_hashtags(p_text)
        p_lang = detect_language(p_text)

        target_str = f"/{max_posts}" if max_posts > 0 else ""
        print("\n" + "=" * 65)
        com_info = f" ({p_comments_count} komentar)" if p_comments_count > 0 else ""
        print(f"[POST #{total_posts_saved}{target_str}] @{p_author} ({p_date}){com_info}")
        print(f"  * URL Awal: {p_url}")
        print(f"  \"{p_text[:75]}...\"")
        print("  [*] LANGKAH 2: Klik Postingan & Buka Dialog Komentar...")

        # LANGKAH 2: KLIK TOGGLE KOMENTAR / POSTINGAN TERSEBUT SECARA PRESISI
        driver.execute_script("""
            let p = document.querySelector('[data-target-post="true"]');
            if (p) {
                p.removeAttribute('data-target-post');
            } else {
                let targetIdx = arguments[0];
                let feedNodes = document.querySelectorAll('div[role="feed"] > div, div[role="article"]');
                p = feedNodes[targetIdx];
            }
            if (!p) return;

            p.scrollIntoView({ behavior: 'smooth', block: 'center' });

            function getElText(el) {
                if (!el) return '';
                let res = el.innerText || el.textContent || '';
                let uses = el.querySelectorAll('use');
                for (let u of uses) {
                    let href = u.getAttribute('xlink:href') || u.getAttribute('href') || '';
                    if (href.startsWith('#')) {
                        let ref = document.getElementById(href.substring(1));
                        if (ref) res += ' ' + (ref.textContent || ref.innerText || '');
                    }
                }
                return res.trim();
            }

            // 1. Target Pertama: Tombol komentar atau angka komentar di kartu postingan
            let allNodes = p.querySelectorAll('div[role="button"], span[dir="auto"], span, div[dir="auto"]');
            for (let el of allNodes) {
                if (el.closest('a[href*="/permalink/"], a[href*="/posts/"], a[href*="/photo/"], a[href*="/groups/"]')) continue;
                let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                let txt = getElText(el).toLowerCase();
                
                let isCommentCount = (
                    /\\b\\d+\\s*(?:komentar|comment|comments|balasan|replies)\\b/i.test(txt) ||
                    /\\b\\d+\\s*(?:komentar|comment|comments|balasan|replies)\\b/i.test(aria)
                );
                
                if (isCommentCount) {
                    let clickTarget = el.closest('div[role="button"]') || el;
                    try { clickTarget.click(); return; } catch(e) {}
                }
            }

            // 2. Target Kedua: Tombol aksi komentar
            let actionBtns = p.querySelectorAll('div[role="button"]');
            for (let b of actionBtns) {
                if (b.closest('a[href*="/permalink/"], a[href*="/posts/"], a[href*="/photo/"]')) continue;
                let aria = (b.getAttribute('aria-label') || '').toLowerCase();
                let txt = getElText(b).toLowerCase();
                
                let isCommentAction = (
                    aria === 'beri komentar' || aria === 'komentari' || aria === 'komentar' || aria === 'comment' || aria === 'leave a comment' ||
                    aria.includes('komentari') || aria.includes('beri komentar') ||
                    txt === 'komentari' || txt === 'komentar' || txt === 'comment'
                );
                
                if (isCommentAction) {
                    try { b.click(); return; } catch(e) {}
                }
            }

            // 3. Target Ketiga: Teks postingan / area pesan postingan (memicu dialog tanpa navigasi tautan penuh)
            let textEl = p.querySelector('div[dir="auto"], div[data-ad-preview="message"]');
            if (textEl) {
                try { textEl.click(); return; } catch(e) {}
            }

            // 4. Target Keempat: Permalink / timestamp anchor postingan atau video
            let permalink = p.querySelector('a[href*="/watch"], a[href*="/reel/"], a[href*="/reels/"], a[href*="/videos/"], a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], a[href*="/share/"]');
            if (permalink) {
                try { permalink.click(); return; } catch(e) {}
            }

            // 5. Target Kelima: Container video atau tombol play video
            let vidEl = p.querySelector('video, div[data-video-id], [aria-label*="Video" i], [aria-label*="Putar" i], [aria-label*="Play" i]');
            if (vidEl) {
                try { vidEl.click(); return; } catch(e) {}
            }
        """, dom_idx)

        pause_ctrl.sleep(random.uniform(1.2, 1.8))

        # Reset network interception buffer agar respons pencarian feed tidak tercampur ke komentar postingan ini
        try:
            driver.execute_script("window._scraped_data = [];")
        except Exception:
            pass

        # Ekstraksi URL dan Tanggal langsung dari dialog yang baru saja terbuka saat postingan diklik
        try:
            active_info = driver.execute_script("""
                let cur = window.location.href || '';
                let dialog = document.querySelector('div[role="dialog"], div[aria-modal="true"], div[data-pagelet*="Tahoe"], div[data-pagelet*="Watch"]');
                let foundLink = '';
                let dialogDate = '';
                if (dialog) {
                    let dLinks = dialog.querySelectorAll('a[href*="/watch"], a[href*="/reel/"], a[href*="/reels/"], a[href*="/videos/"], a[href*="/photo"], a[href*="photo.php"], a[href*="/posts/"], a[href*="/permalink/"], a[href*="multi_permalinks"], a[href*="set=gm."], a[href*="set=pcb."], a[href*="story_fbid="], a[href*="/share/"], a[href*="Uzpf"]');
                    for (let dl of dLinks) {
                        let h = dl.href || '';
                        if (h && !h.includes('/search/') && !h.includes('/search?') && !h.includes('/hashtag/')) {
                            // Abaikan tautan murni grup root
                            let isPureGroup = /^https?:\\/\\/(?:www\\.)?facebook\\.com\\/groups\\/[^/?#]+\\/?(?:\\?[^#]*)?$/i.test(h);
                            if (!isPureGroup) {
                                foundLink = h;
                                break;
                            }
                        }
                    }

                    // Cek elemen video langsung di dialog
                    if (!foundLink) {
                        let dVid = dialog.querySelector('[data-video-id]');
                        if (dVid) {
                            let dVidId = dVid.getAttribute('data-video-id');
                            if (dVidId) foundLink = `https://www.facebook.com/watch/?v=${dVidId}`;
                        }
                    }

                    const monthRegex = /\\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|agt|agu|aug|sep|okt|oct|nov|des|dec)\\b/i;
                    const yearRegex = /\\b(19\\d{2}|20\\d{2})\\b/;
                    const relTimeRegex = /\\b\\d+\\s*(?:thn|th|tahun|yr|yrs|year|years|mgg|minggu|wk|week|weeks|hr|hari|day|days|jam|jm|hour|hours|mnt|menit|min|mins|lalu|ago)\\b/i;

                    let dTimeCandidates = [];
                    let dTimeLinks = dialog.querySelectorAll('abbr, a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], [aria-label], span[dir="auto"]');
                    for (let tl of dTimeLinks) {
                        if (tl.closest('div[data-ad-preview="message"], div[data-ad-comet-preview="message"], div[data-testid="post_message"], form, [role="article"] [role="article"]')) continue;
                        let aria = (tl.getAttribute('aria-label') || '').trim();
                        let txt = (tl.innerText || tl.textContent || '').trim();
                        if (aria) dTimeCandidates.push(aria);
                        if (txt) dTimeCandidates.push(txt);
                    }

                    for (let rawCand of dTimeCandidates) {
                        if (!rawCand) continue;
                        let cand = rawCand.split('·')[0].split('\\u00b7')[0].trim();
                        if (cand.length < 2 || cand.length > 70) continue;
                        let cLower = cand.toLowerCase();
                        if (cLower.includes('komentar') || cLower.includes('reaksi') || cLower.includes('suka') || cLower.includes('bagikan') || cLower.includes('ikuti') || cLower.includes('tambah jadi teman')) continue;
                        let isDate = (
                            yearRegex.test(cand) ||
                            (monthRegex.test(cand) && /\\d/.test(cand)) ||
                            relTimeRegex.test(cand) ||
                            cLower.includes('kemarin') || cLower.includes('yesterday') ||
                            cLower.includes('baru saja') || cLower.includes('just now') ||
                            cLower.endsWith(' yang lalu') || cLower.endsWith(' lalu') || cLower.endsWith(' ago')
                        );
                        if (isDate) {
                            if (yearRegex.test(cand)) {
                                dialogDate = cand;
                                break;
                            } else if (!dialogDate) {
                                dialogDate = cand;
                            }
                        }
                    }
                }
                return { current_url: cur, dialog_link: foundLink, dialog_date: dialogDate };
            """)
            if active_info:
                d_date = active_info.get('dialog_date')
                if d_date:
                    p_date = d_date
                    print(f"  * Tanggal Terkonfirmasi dari Dialog: {p_date}")

                cand_cur = active_info.get('current_url', '')
                cand_dlg = active_info.get('dialog_link', '')
                # Prioritaskan URL spesifik (bukan link grup root dan bukan search)
                cand_link = ''
                if cand_cur and is_specific_post_url(cand_cur):
                    cand_link = cand_cur
                elif cand_dlg and is_specific_post_url(cand_dlg):
                    cand_link = cand_dlg

                if cand_link:
                    refined_p_url = format_facebook_url(
                        raw_url=cand_link,
                        current_page_url=driver.current_url,
                        post_id=p_id,
                        author=p_author,
                        group_name=group_name
                    )
                    if refined_p_url and is_specific_post_url(refined_p_url):
                        p_url = refined_p_url
                        m_pid_new = (
                            re.search(r'/(?:posts|permalink|videos|reel|reels)/([0-9]+)', p_url) or
                            re.search(r'[?&](?:story_fbid|multi_permalinks|fbid|v)=([0-9]+)', p_url)
                        )
                        if m_pid_new and (not p_id or p_id == group_name):
                            p_id = m_pid_new.group(1)
        except Exception:
            pass

        # VERIFIKASI TANGGAL KETAT (LANGKAH 2): Lewati jika postingan terbukti usang dari tanggal dialog
        if is_outdated_post(p_date, min_year=min_year):
            print(f"  [DILEWATI] Postingan Usang ({p_date}) @{p_author}: \"{p_text[:40]}...\" (Filter aktif: Hanya tahun {min_year}+)")
            if is_search_mode:
                close_search_dialog(driver, search_url=search_url)
            else:
                close_post_dialog(driver, search_url=search_url)
            continue

        # JIKA TANGGAL MASIH 'Terkini', PERIKSA HASHTAG SEBAGAI PENGAMAN TAMBAHAN
        if p_date == 'Terkini':
            p_tags = extract_hashtags(p_text)
            if p_tags:
                for t in p_tags.split(','):
                    t_clean = t.strip()
                    t_years = [int(y) for y in re.findall(r'\b(19\d{2}|20\d{2})\b', t_clean) if 1990 <= int(y) <= 2099]
                    if t_years and all(y < min_year for y in t_years):
                        print(f"  [DILEWATI] Postingan Usang dari Hashtag '{t_clean}' @{p_author}: \"{p_text[:40]}...\" (Filter aktif: Hanya tahun {min_year}+)")
                        if is_search_mode:
                            close_search_dialog(driver, search_url=search_url)
                        else:
                            close_post_dialog(driver, search_url=search_url)
                        continue

        # Pastikan URL Postingan selalu berupa link postingan langsung (bukan generic search URL atau grup root)
        if not p_url or not is_specific_post_url(p_url):
            if p_is_video and p_id and p_id != group_name:
                p_url = f"https://www.facebook.com/watch/?v={p_id}"
            elif group_name and p_id and p_id != group_name:
                p_url = f"https://www.facebook.com/groups/{group_name}/posts/{p_id}"
            elif p_id:
                if p_is_video:
                    p_url = f"https://www.facebook.com/watch/?v={p_id}"
                else:
                    p_url = f"https://www.facebook.com/permalink.php?story_fbid={p_id}"
            elif group_name:
                p_url = f"https://www.facebook.com/groups/{group_name}"

        # Jaminan post_id tidak pernah kosong
        if not p_id or p_id == group_name:
            m_final_id = (
                re.search(r'/(?:posts|permalink|videos|reel|reels)/([0-9]+)', p_url or '') or
                re.search(r'[?&](?:story_fbid|multi_permalinks|fbid|v)=([0-9]+)', p_url or '')
            )
            if m_final_id:
                p_id = m_final_id.group(1)
            else:
                p_id = f"fb_{abs(hash(p_sig)) % 1000000000}"

        p_subtitles = "[Video]" if p_is_video else ""

        print(f"  * URL Postingan: {p_url} {'[VIDEO]' if p_is_video else ''}")

        pause_ctrl.sleep(1.2)

        # LANGKAH 3: UBAH FILTER MENJADI SEMUA KOMENTAR
        print("  [*] LANGKAH 3: Mengubah Filter Menjadi 'Semua Komentar'...")
        switch_filter_to_all_comments(driver)

        # LANGKAH 4: SCROLL SAMPAI HABIS & BONGKAR SEMUA BALASAN KOMENTAR
        print("  [*] LANGKAH 4: Memeriksa & mengambil komentar postingan...")
        post_comments = exhaustively_scroll_and_extract_comments(
            driver, max_idle_scrolls=4, max_total_comments_limit=max_comments_per_post, seen_comment_keys=seen_comment_keys, current_post_text=p_text
        )

        if post_comments:
            p_comments_count = max(p_comments_count, len(post_comments))

        # Simpan metadata postingan (25 kolom standar konsisten dengan URL direct post yang presisi)
        save_to_csv(post_csv, [
            "Facebook", csv_keyword_label, p_id, p_date, p_author,
            p_profile_url, "", 0, 0, "",
            "", p_text, p_reactions_count, p_shares_count, p_plays_count,
            p_comments_count, p_subtitles, p_lang, p_hashtags,
            p_is_ad, p_is_pinned, p_is_sponsored, p_location, p_music_meta, p_url
        ])

        # Simpan seluruh komentar & balasan postingan ini ke CSV
        if post_comments:
            for c in post_comments:
                c_prof_url = c.get('profile_url', '')
                c_username = c.get('username') or c.get('author', 'Warga')
                c_author = c.get('author', 'Warga')
                c_text = c.get('comment_text', '')
                c_lang = detect_language(c_text)
                c_is_rep = "Yes" if str(c.get('is_reply', '')).upper() in ['YA', 'YES', 'TRUE', '1'] else "No"
                save_to_csv(comment_csv, [
                    "Facebook", csv_keyword_label, p_id, p_date, p_author,
                    p_profile_url, p_text, p_reactions_count, p_shares_count, p_plays_count,
                    p_comments_count, c.get('comment_id'), c.get('comment_date'), c_author, c_username,
                    c_prof_url, c_text, c.get('likes', 0), c.get('reply_count', 0), c_is_rep,
                    c.get('reply_to', ''), c_lang, p_hashtags, p_location, p_url
                ])
                total_comments_saved += 1
            print(f"  [+] Selesai Post #{total_posts_saved}. Total {len(post_comments)} komentar & balasan baru tersimpan!")
        else:
            # Jika postingan tidak memiliki komentar, link postingan TETAP disimpan di comment_csv
            save_to_csv(comment_csv, [
                "Facebook", csv_keyword_label, p_id, p_date, p_author,
                p_profile_url, p_text, p_reactions_count, p_shares_count, p_plays_count,
                0, f"no_comment_{p_id}", p_date, "-", "-",
                "", "[Tidak ada komentar]", 0, 0, "No",
                "", p_lang, p_hashtags, p_location, p_url
            ])
            total_comments_saved += 1
            print(f"  [+] Selesai Post #{total_posts_saved}. Link postingan ({p_url}) berhasil dicatat ke file komentar & postingan!")

        # Tutup dialog postingan dan pastikan kembali ke feed pencarian
        if is_search_mode:
            close_search_dialog(driver, search_url=search_url)
        else:
            close_post_dialog(driver, search_url=search_url)
        pause_ctrl.sleep(0.4)
        # Scroll feed pencarian ke bawah untuk memicu postingan berikutnya
        if is_search_mode:
            perform_search_feed_scroll(driver, distance=450)
        else:
            perform_feed_scroll(driver, distance=450)
        pause_ctrl.sleep(0.4)

    print(f"\n[*] Selesai pencarian '{keyword}'. Total {total_posts_saved} post & {total_comments_saved} komentar tersimpan di '{comment_csv}'.")


# ==========================================
# 6. MODE LIVE INTERCEPTOR (ASISTEN MANUAL)
# ==========================================
def run_live_interactive_sniffer():
    print("\n" + "=" * 65)
    print("      MODE LIVE INTERCEPTOR (ASISTEN MONITORING MANUAL)")
    print("=" * 65)
    print("Pada mode ini:")
    print("1. Browser Facebook akan terbuka dengan sesi login Anda.")
    print("2. Anda bebas membuka postingan, grup, mencari isu, atau mengklik komentar apa saja.")
    print("3. Script di background akan OTOMATIS MENYEDOT dan MENYIMPAN seluruh komentar & balasan")
    print("   yang muncul di layar (via XHR/GraphQL & DOM) langsung ke CSV di folder 'results/'!")
    print("=" * 65)

    base_name = input("Nama file output CSV (default: fb_live_comments): ").strip() or "fb_live_comments"
    if base_name.endswith(".csv"):
        base_name = base_name[:-4]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    daily_dir = get_daily_results_dir()
    comment_csv = os.path.join(daily_dir, f"{base_name}_{timestamp}_comments.csv")
    init_comments_csv(comment_csv)
    print(f"[*] Komentar & balasan akan otomatis disimpan ke: {comment_csv}")

    print("\n[*] Menjalankan browser dengan Stealth Shield & Network Interceptor aktif...")
    try:
        driver, profile_dir = get_driver()
        driver.get("https://www.facebook.com")
        time.sleep(3)
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    print("\n" + "=" * 65)
    print(" >>> LIVE MONITORING AKTIF! SILAKAN BUKA FACEBOOK DI BROWSER <<<")
    print(" Buka postingan warga, klik komentar, atau scroll feed.")
    print(" Tekan Ctrl+C di terminal ini jika Anda selesai.")
    print("=" * 65 + "\n")

    seen_comments = set()
    total_captured = 0

    try:
        while True:
            combined = extract_comments_from_active_container(driver)

            for c in combined:
                c_text = c.get('comment_text', '').strip()
                if not c_text or c_text in seen_comments or len(c_text) < 2:
                    continue
                seen_comments.add(c_text)
                total_captured += 1

                c_author = c.get('author', 'Warga')
                c_date = c.get('comment_date', 'Terkini')
                c_id = c.get('comment_id', f"fb_{total_captured}")
                c_likes = c.get('likes', 0)
                is_rep = c.get('is_reply', 'TIDAK')
                rep_to = c.get('reply_to', '')
                rep_cnt = c.get('reply_count', 0)
                current_url = format_facebook_url(driver.current_url)

                c_prof_url = c.get('profile_url', '')
                c_username = c.get('username') or c_author
                c_is_rep_str = "Yes" if str(is_rep).upper() in ['YA', 'YES', 'TRUE', '1'] else "No"
                c_lang = detect_language(c_text)
                save_to_csv(comment_csv, [
                    "Facebook", "Live_Monitoring", "Manual_Live", "Terkini", "Live_Post",
                    "", "Postingan Live Monitor", 0, 0, 0,
                    0, c_id, c_date, c_author, c_username,
                    c_prof_url, c_text, c_likes, rep_cnt, c_is_rep_str,
                    rep_to, c_lang, "", "", current_url
                ])

                if is_rep == 'YA':
                    target_str = f" [Balasan ke @{rep_to}]" if rep_to else " [Balasan]"
                    print(f"   └──{target_str} [#{total_captured}] @{c_author}: \"{c_text}\" (likes: {c_likes})")
                else:
                    print(f"[#{total_captured}] @{c_author} ({c_date}): \"{c_text}\" (likes: {c_likes})")

            pause_ctrl.sleep(1.0)

    except KeyboardInterrupt:
        print("\n\n" + "=" * 65)
        print(f"[SELESAI] Live Monitoring Berakhir. Total {total_captured} komentar & balasan tersimpan ke {comment_csv}!")
        print("=" * 65)
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ==========================================
# 7. MENU UTAMA (MENDUKUNG CLI & INTERAKTIF)
# ==========================================
def run_facebook_scraper():
    import argparse
    parser = argparse.ArgumentParser(description="Facebook Regional Intelligence Scraper (Humas Bupati)")
    parser.add_argument("--mode", type=str, choices=["0", "1", "2", "3"], help="Mode scraper (0=Setup, 1=Keywords, 2=Groups, 3=Live)")
    parser.add_argument("--group", type=str, help="URL grup Facebook target")
    parser.add_argument("--groups-file", type=str, help="Path file daftar link grup (.txt)")
    parser.add_argument("--output", type=str, help="Nama prefix file output")
    parser.add_argument("--keyword", type=str, help="Kata kunci tunggal pencarian")
    parser.add_argument("--keywords-file", type=str, help="Path file daftar kata kunci (.txt)")
    parser.add_argument("--max-posts", type=int, help="Maksimal postingan per kata kunci")
    parser.add_argument("--max-comments", type=int, help="Maksimal komentar per postingan")
    parser.add_argument("--min-year", type=int, default=2025, help="Tahun minimal postingan yang diambil (default: 2025, tolak tahun 2024 dan sebelumnya)")
    parser.add_argument("--resume", action="store_true", help="Lanjutkan sesi scraping terakhir secara otomatis")
    parser.add_argument("--resume-session", type=str, help="Nama atau ID sesi spesifik yang ingin dilanjutkan")
    args, unknown = parser.parse_known_args()

    mode = args.mode
    if not mode:
        print("=" * 65)
        print("       FACEBOOK REGIONAL INTELLIGENCE SCRAPER (HUMAS BUPATI)")
        print("=" * 65)
        print("PILIHAN MENU:")
        print("  0. Setup & Simpan Sesi Login Facebook (Cukup Login 1 Kali)")
        print("  1. Pencarian Otomatis Kata Kunci Isu Daerah (4 Langkah Otomatis Penuh)")
        print("  2. Monitoring Otomatis Grup Facebook Warga (Buka Grup -> Cari di Dalam Grup)")
        print("  3. Mode Live Interceptor (Bebas Scroll/Klik FB, Script Otomatis Sedot Komentar)")
        print("=" * 65)
        mode = input("Pilih menu [0/1/2/3] (default: 1): ").strip() or "1"

    if mode == "0":
        setup_facebook_session()
        return
    elif mode == "3":
        run_live_interactive_sniffer()
        return

    base_dir = os.path.dirname(os.path.abspath(__file__))
    keywords = []
    groups = []
    base_output_name = args.output or ""
    max_posts_target = args.max_posts or 20
    max_comments_limit = args.max_comments or 150
    min_post_year = args.min_year if args.min_year is not None else 2025
    is_resuming = False
    session_base_name = ""
    progress_data = {}

    if mode == "1":
        if args.keyword:
            keywords = [args.keyword]
        elif args.keywords_file:
            keywords = load_keywords(args.keywords_file, prompt_fallback=False)
            print(f"[*] Memuat {len(keywords)} kata kunci dari file: '{args.keywords_file}'")
        else:
            keywords = select_keywords_source(base_dir)
            if not keywords:
                print("[!] Tidak ada kata kunci yang dipilih. Scraper dibatalkan.")
                return
        preview_kw = ", ".join(keywords[:10]) + ("..." if len(keywords) > 10 else "")
        print(f"\n[*] Memuat {len(keywords)} kata kunci: {preview_kw}")

        recent_sessions = get_recent_scrape_sessions(limit=5)
        latest_session = recent_sessions[0] if recent_sessions else None

        if args.resume and latest_session:
            is_resuming = True
            session_base_name = latest_session["session_id"]
        elif args.resume_session:
            is_resuming = True
            session_base_name = args.resume_session
        elif latest_session and not base_output_name:
            print("\n" + "=" * 65)
            print("STATUS SESI SCRAPING TERDAHULU:")
            print(f"  Sesi Terakhir : '{latest_session['session_id']}' ({latest_session['time_str']})")
            print(f"  Data Tersimpan: {latest_session['posts_count']} postingan, {latest_session['comments_count']} komentar")
            print("=" * 65)
            print("PILIHAN SESI:")
            print("  1. Buat Sesi Baru (File CSV baru) [Default]")
            print(f"  2. Lanjutkan / Tambahkan ke Sesi Terakhir ('{latest_session['session_id']}')")
            print("-" * 65)
            s_choice = input("Pilih opsi sesi [1/2] (default: 1): ").strip() or "1"
            if s_choice == "2":
                is_resuming = True
                session_base_name = latest_session["session_id"]

        if is_resuming:
            base_output_name = session_base_name
            post_csv, comment_csv = get_output_csv_paths(base_output_name, is_resume=True)
            progress_data = load_session_progress(base_output_name, post_csv, comment_csv)
            done_kws = set(progress_data.get("completed_keywords", []))
            if done_kws:
                rem_kws = [k for k in keywords if k not in done_kws]
                if rem_kws:
                    print(f"[*] [RESUME AKTIF] {len(done_kws)} kata kunci selesai dilewati, {len(rem_kws)} tersisa.")
                    keywords = rem_kws
        else:
            if not base_output_name:
                base_output_name = input("Nama file output (default: fb_isu_daerah): ").strip() or "fb_isu_daerah"
            post_csv, comment_csv = get_output_csv_paths(base_output_name, is_resume=False)
            session_base_name = os.path.basename(post_csv).replace("_posts.csv", "")
            progress_data = {
                "session_id": session_base_name,
                "completed_groups": [],
                "completed_keywords": [],
                "total_posts": 0,
                "total_comments": 0,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            save_session_progress(session_base_name, progress_data)

        if not args.max_posts:
            try:
                p_in = input("Maksimal postingan per kata kunci [0 untuk tanpa batas] (default: 20): ").strip()
                max_posts_target = int(p_in) if p_in else 20
            except ValueError:
                max_posts_target = 20
        if not args.max_comments:
            try:
                c_in = input("Maksimal komentar per postingan [0 untuk semua komentar] (default: 150): ").strip()
                max_comments_limit = int(c_in) if c_in else 150
            except ValueError:
                max_comments_limit = 150

    elif mode == "2":
        if args.group:
            groups = [args.group]
        elif args.groups_file:
            groups = load_groups(args.groups_file, prompt_fallback=False)
            print(f"[*] Memuat {len(groups)} link grup dari file: '{args.groups_file}'")
        else:
            groups = select_groups_source(base_dir)
            if not groups:
                print("[!] Tidak ada link grup yang dipilih. Scraper dibatalkan.")
                return

        if args.keyword:
            keywords = [args.keyword]
        elif args.keywords_file:
            keywords = load_keywords(args.keywords_file, prompt_fallback=False)
            print(f"[*] Memuat {len(keywords)} kata kunci dari file: '{args.keywords_file}'")
        else:
            print("\nPILIHAN METODE PENCARIAN DI DALAM GRUP:")
            print("  A. Berdasarkan Kata Kunci (Pilih File / Input Manual) [Default]")
            print("  B. Feed Terbaru (Tanpa Kata Kunci)")
            m_grp = input("Pilih metode [A/B] (default: A): ").strip().upper() or "A"
            if m_grp == "A":
                keywords = select_keywords_source(base_dir)
                if not keywords:
                    print("[!] Tidak ada kata kunci yang dipilih. Scraper dibatalkan.")
                    return
            else:
                keywords = ["Feed Terbaru"]

        recent_sessions = get_recent_scrape_sessions(limit=5)
        latest_session = recent_sessions[0] if recent_sessions else None

        if args.resume and latest_session:
            is_resuming = True
            session_base_name = latest_session["session_id"]
        elif args.resume_session:
            is_resuming = True
            session_base_name = args.resume_session
        elif latest_session and not base_output_name:
            p_prog = load_session_progress(latest_session["session_id"], latest_session["post_csv"], latest_session["comment_csv"], groups)
            done_cnt = len(p_prog.get("completed_groups", []))
            remain_cnt = max(0, len(groups) - done_cnt)

            print("\n" + "=" * 65)
            print("STATUS SESI SCRAPING TERDAHULU:")
            print(f"  Sesi Terakhir : '{latest_session['session_id']}' ({latest_session['time_str']})")
            print(f"  Data Tersimpan: {latest_session['posts_count']} postingan, {latest_session['comments_count']} komentar")
            print(f"  Progres Grup  : {done_cnt} selesai, {remain_cnt} tersisa dari {len(groups)} grup")
            print("=" * 65)
            print("PILIHAN SESI:")
            print("  1. Buat Sesi Baru (Mulai dari grup ke-1 dengan file CSV baru) [Default]")
            print(f"  2. Lanjutkan Sesi Terakhir ('{latest_session['session_id']}') [Lanjut {remain_cnt} grup]")
            print("  3. Pilih Sesi CSV Lain untuk Dilanjutkan")
            print("-" * 65)

            s_choice = input("Pilih opsi sesi [1/2/3] (default: 1): ").strip() or "1"
            if s_choice == "2":
                is_resuming = True
                session_base_name = latest_session["session_id"]
            elif s_choice == "3":
                print("\nDAFTAR SESI SEBELUMNYA:")
                for idx, s_info in enumerate(recent_sessions, 1):
                    print(f"  {idx}. {s_info['session_id']} ({s_info['time_str']}) - {s_info['posts_count']} posts, {s_info['comments_count']} comments")
                s_pick = input(f"Pilih nomor sesi [1-{len(recent_sessions)}] (default: 1): ").strip()
                try:
                    s_idx = int(s_pick) - 1 if s_pick else 0
                    if 0 <= s_idx < len(recent_sessions):
                        is_resuming = True
                        session_base_name = recent_sessions[s_idx]["session_id"]
                except ValueError:
                    pass

        if is_resuming:
            base_output_name = session_base_name
            post_csv, comment_csv = get_output_csv_paths(base_output_name, is_resume=True)
            progress_data = load_session_progress(base_output_name, post_csv, comment_csv, groups)

            completed_ids = {get_group_identifier(cg) for cg in progress_data.get("completed_groups", [])}
            all_total_grps = len(groups)
            groups_to_run = [g for g in groups if get_group_identifier(g) not in completed_ids]

            print("\n" + "=" * 65)
            print(f"[*] [RESUME AKTIF] Melanjutkan Sesi: '{base_output_name}'")
            print(f"  * File Postingan : {post_csv}")
            print(f"  * File Komentar  : {comment_csv}")
            print(f"  * Grup Selesai   : {len(completed_ids)} grup (dilewati)")
            print(f"  * Grup Tersisa   : {len(groups_to_run)} dari total {all_total_grps} grup yang akan di-scrape")
            print("=" * 65)

            if not groups_to_run:
                print("[✓] Seluruh grup dalam daftar sudah selesai diproses sebelumnya!")
                tanya_ulang = input("Apakah Anda ingin memproses ulang seluruh grup dari awal? [y/N]: ").strip().lower()
                if tanya_ulang == 'y':
                    groups_to_run = groups
                    progress_data["completed_groups"] = []
                else:
                    return
            groups = groups_to_run
        else:
            if not base_output_name:
                base_output_name = input("Nama file output (default: fb_grup_monitoring): ").strip() or "fb_grup_monitoring"
            post_csv, comment_csv = get_output_csv_paths(base_output_name, is_resume=False)
            session_base_name = os.path.basename(post_csv).replace("_posts.csv", "")
            progress_data = {
                "session_id": session_base_name,
                "completed_groups": [],
                "completed_keywords": [],
                "total_posts": 0,
                "total_comments": 0,
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            save_session_progress(session_base_name, progress_data)

        if not args.max_posts:
            try:
                p_in = input("Maksimal postingan per grup / pencarian [0 untuk tanpa batas] (default: 20): ").strip()
                max_posts_target = int(p_in) if p_in else 20
            except ValueError:
                max_posts_target = 20
        if not args.max_comments:
            try:
                c_in = input("Maksimal komentar per postingan [0 untuk semua komentar] (default: 150): ").strip()
                max_comments_limit = int(c_in) if c_in else 150
            except ValueError:
                max_comments_limit = 150

    init_posts_csv(post_csv)
    init_comments_csv(comment_csv)

    print("\n" + "=" * 65)
    print("  [KONTROL JEDA AKTIF] KONTROL KEYBOARD INTERAKTIF:")
    print("  * Tekan tombol [P] atau [SPASI] di keyboard untuk MENJEDA (Pause) / MELANJUTKAN.")
    print("  * Tekan tombol [Q] di keyboard untuk BERHENTI & SIMPAN data yang sudah didapat.")
    print("=" * 65)
    pause_ctrl.start_listener()

    print("\n[*] Menjalankan browser Facebook...")
    try:
        driver, profile_dir = get_driver()
        driver.get("https://www.facebook.com")
        pause_ctrl.sleep(2.0)
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        if mode == "1":
            for kw in keywords:
                if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                    break
                driver = ensure_driver_alive(driver)

                # Jika keyword adalah URL postingan langsung (Permalink)
                if kw.startswith("http://") or kw.startswith("https://"):
                    process_direct_post_url(driver, kw, post_csv, comment_csv, max_comments_per_post=max_comments_limit)
                    if kw not in progress_data.setdefault("completed_keywords", []):
                        progress_data["completed_keywords"].append(kw)
                    save_session_progress(session_base_name, progress_data)
                    continue

                search_url = build_search_url(kw, use_filter=True, filter_version="recent")
                try:
                    driver.get(search_url)
                    pause_ctrl.sleep(3.5)
                    process_search_workflow(
                        driver, kw, post_csv, comment_csv,
                        max_posts=max_posts_target,
                        max_comments_per_post=max_comments_limit,
                        min_year=min_post_year,
                        is_search_mode=True,
                    )
                    if kw not in progress_data.setdefault("completed_keywords", []):
                        progress_data["completed_keywords"].append(kw)
                    save_session_progress(session_base_name, progress_data)
                except Exception as kw_err:
                    print(f"\n[!] Gangguan saat pencarian '{kw}': {kw_err}")
                    print("[*] Data yang sudah diperoleh tetap aman di CSV. Melanjutkan ke kata kunci berikutnya...")
                    pause_ctrl.sleep(2.0)

        elif mode == "2":
            for grp in groups:
                if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                    break
                grp_clean = grp.rstrip('/')
                grp_slug = grp_clean.split('/')[-1]

                driver = ensure_driver_alive(driver)

                try:
                    print("\n" + "=" * 65)
                    print(f"[*] MEMBUKA GRUP FACEBOOK: {grp_clean}")
                    print("=" * 65)
                    driver.get(grp_clean)
                    pause_ctrl.sleep(3.5)

                    # 1. PERIKSA APAKAH HALAMAN / GRUP RUSAK ATAU TIDAK DAPAT DIAKSES
                    is_broken, broken_reason = is_page_or_group_broken(driver, expected_url=grp_clean)
                    if is_broken:
                        print(f"\n[!] [GRUP RUSAK / TIDAK DAPAT DIAKSES] '{grp_slug}' ({broken_reason})")
                        print("[*] Melewati seluruh kata kunci dan langsung lanjut ke link grup berikutnya...\n")
                        if grp not in progress_data.setdefault("completed_groups", []):
                            progress_data["completed_groups"].append(grp)
                        save_session_progress(session_base_name, progress_data)
                        pause_ctrl.sleep(1.0)
                        continue

                    for kw in keywords:
                        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                            break
                        driver = ensure_driver_alive(driver)

                        # Jika keyword adalah URL postingan langsung (Permalink)
                        if kw.startswith("http://") or kw.startswith("https://"):
                            process_direct_post_url(driver, kw, post_csv, comment_csv, max_comments_per_post=max_comments_limit)
                            continue
                        elif kw == "Feed Terbaru":
                            target_url = f"{grp_clean}/?sorting_setting=CHRONOLOGICAL"
                            print(f"[*] Membuka Feed Kronologis Terbaru di grup '{grp_slug}'...")
                            driver.get(target_url)
                            pause_ctrl.sleep(3.5)
                            w_res = process_search_workflow(
                                driver, "Feed Terbaru", post_csv, comment_csv,
                                max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                                custom_search_url=target_url, group_name=grp_slug,
                                min_year=min_post_year
                            )
                            if w_res == "BROKEN":
                                print(f"\n[!] Grup '{grp_slug}' rusak / tidak dapat diakses. Melewati sisa kata kunci dan lanjut ke grup berikutnya...\n")
                                break
                        else:
                            target_url = f"{grp_clean}/search/?q={urllib.parse.quote(kw)}&filters={FB_CHRONOSORT_FILTER}"
                            print(f"[*] Melakukan pencarian '{kw}' di dalam grup '{grp_slug}' (Filter: Postingan Terbaru)...")
                            driver.get(target_url)
                            pause_ctrl.sleep(3.5)
                            w_res = process_search_workflow(
                                driver, kw, post_csv, comment_csv,
                                max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                                custom_search_url=target_url, group_name=grp_slug,
                                min_year=min_post_year
                            )
                            if w_res == "BROKEN":
                                print(f"\n[!] Halaman pencarian grup '{grp_slug}' rusak / dialihkan. Melewati sisa kata kunci dan lanjut ke grup berikutnya...\n")
                                break

                    if grp not in progress_data.setdefault("completed_groups", []):
                        progress_data["completed_groups"].append(grp)
                    save_session_progress(session_base_name, progress_data)

                except Exception as grp_err:
                    print(f"\n[!] Gangguan pada grup '{grp_slug}': {grp_err}")
                    print("[*] Data yang sudah diperoleh tetap aman di CSV. Melanjutkan ke grup berikutnya...")
                    pause_ctrl.sleep(2.0)

        print("\n" + "=" * 65)
        print("  [SELESAI] Scraping Facebook Berhasil Selesai Penuh!")
        print(f"  * Folder Output  : results/")
        print(f"  * File Postingan : {post_csv}")
        print(f"  * File Komentar  : {comment_csv}")
        print("  * Analisis Sentimen & Topik: Jalankan 'python app.py'")
        print("=" * 65)

    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna. Data tersimpan di CSV.")
    finally:
        try:
            if os.path.exists(post_csv):
                with open(post_csv, mode='r', encoding='utf-8', errors='replace') as f:
                    progress_data["total_posts"] = max(0, sum(1 for _ in f) - 1)
            if os.path.exists(comment_csv):
                with open(comment_csv, mode='r', encoding='utf-8', errors='replace') as f:
                    progress_data["total_comments"] = max(0, sum(1 for _ in f) - 1)
            if session_base_name:
                save_session_progress(session_base_name, progress_data)
        except Exception:
            pass

        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_facebook_scraper()
