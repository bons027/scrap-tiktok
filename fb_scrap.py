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

# Parameter URL Facebook untuk Filter 'Postingan Terbaru' (Chronological Recent Sort)
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
    - Jika memuat tahun eksplisit (misal '15 Agustus 2024') dan tahun < min_year -> True (Outdated).
    - Jika memuat durasi tahun relatif (misal '2 thn lalu', '3 tahun lalu', '2 yrs ago') -> dihitung berdasarkan tahun berjalan.
    - Jika tanggal relatif baru ('2 jam lalu', 'Kemarin', '3 hari yang lalu') -> False (Terkini).
    - Jika tahun >= min_year ('2025', '2026') -> False (Terkini).
    """
    if not date_str:
        return False
    d = str(date_str).strip()
    
    # 1. Cek tahun 4 digit eksplisit (1990 - 2099)
    years = re.findall(r'\b(19\d{2}|20\d{2})\b', d)
    if years:
        for y_str in years:
            try:
                y = int(y_str)
                if 1990 <= y < min_year:
                    return True
                elif y >= min_year:
                    return False
            except Exception:
                pass

    # 2. Cek format relatif dalam hitungan tahun (contoh: "2 thn lalu", "3 tahun yang lalu", "2 yrs ago")
    rel_match = re.search(r'(\d+)\s*(?:thn|th|tahun|yr|yrs|year|years)\b', d, re.IGNORECASE)
    if rel_match:
        try:
            n_years = int(rel_match.group(1))
            current_year = datetime.now().year
            est_year = current_year - n_years
            if est_year < min_year:
                return True
        except Exception:
            pass

    return False


def extract_comments_from_json_tree(obj, results=None, parent_author=None, is_reply=False):
    """
    Mengekstrak komentar dan deep replies dari struktur pohon GraphQL secara rekursif.
    Mendukung berbagai variasi skema JSON Facebook modern (preferred_body, message, body, translation).
    """
    if results is None:
        results = []

    if isinstance(obj, dict):
        # Ekstraksi teks komentar dari berbagai jalur skema GraphQL Facebook
        text = ""
        if 'preferred_body' in obj and isinstance(obj['preferred_body'], dict):
            text = str(obj['preferred_body'].get('text', '')).strip()
        elif 'body' in obj and isinstance(obj['body'], dict):
            text = str(obj['body'].get('text', '')).strip()
        elif 'message' in obj and isinstance(obj['message'], dict):
            text = str(obj['message'].get('text', '')).strip()
        elif 'comment_text' in obj and isinstance(obj['comment_text'], dict):
            text = str(obj['comment_text'].get('text', '')).strip()
        elif 'translation' in obj and isinstance(obj['translation'], dict):
            text = str(obj['translation'].get('text', '')).strip()
        elif obj.get('__typename') == 'Comment' and 'text' in obj:
            text = str(obj.get('text', '')).strip()

        cid = str(obj.get('id', obj.get('legacy_fbid', obj.get('legacy_token', ''))))

        if text and is_valid_comment_text(text) and not text.startswith("http"):
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
                        extract_comments_from_json_tree(sub_replies, results, parent_author=author, is_reply=True)

        for k, v in obj.items():
            if k not in ['feedback', 'comment_parent']:  # hindari double traversal jika sudah diproses
                extract_comments_from_json_tree(v, results, parent_author=parent_author, is_reply=is_reply)

    elif isinstance(obj, list):
        for item in obj:
            extract_comments_from_json_tree(item, results, parent_author=parent_author, is_reply=is_reply)

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

    driver = uc.Chrome(**driver_kwargs)

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": CDP_STEALTH_AND_INTERCEPTOR})
    except Exception:
        pass

    return driver, profile_dir


def load_keywords(filepath="keywords.txt"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("# Masukkan 1 keyword per baris\njalan rusak Klaten\nBupati Klaten\n")
            
    with open(full_path, 'r', encoding='utf-8') as f:
        keywords = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
        
    if not keywords:
        manual_kw = input("Keyword: ").strip()
        if manual_kw:
            keywords = [manual_kw]
            
    return keywords


def load_groups(filepath="groups.txt"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("# Masukkan 1 link grup Facebook per baris\n# https://www.facebook.com/groups/namagrup\n")
            
    with open(full_path, 'r', encoding='utf-8') as f:
        groups = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
        
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
    Memformat URL postingan Facebook secara standar & konsisten sesuai format canonical permalink:
    - Postingan Grup: https://www.facebook.com/groups/{group_id}/permalink/{post_id}/ (atau ?rdid=... jika ada)
    - Postingan Reel: https://www.facebook.com/reel/{reel_id}/
    - Postingan User/Page: https://www.facebook.com/{author_username}/posts/{post_id}/
    """
    raw_url = (raw_url or '').strip()
    current_page_url = (current_page_url or '').strip()
    post_id = str(post_id or '').strip()

    rdid = ''
    # Ekstraksi rdid jika ada di raw_url atau current_page_url
    if 'rdid=' in raw_url:
        m_rd = re.search(r'[?&]rdid=([a-zA-Z0-9_-]+)', raw_url)
        if m_rd:
            rdid = m_rd.group(1)
    elif 'rdid=' in current_page_url:
        m_rd = re.search(r'[?&]rdid=([a-zA-Z0-9_-]+)', current_page_url)
        if m_rd:
            rdid = m_rd.group(1)

    rdid_suffix = f"?rdid={rdid}" if rdid else ""

    # 1. Cari group_id / group_slug
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

    # 2. Cari post_id jika belum ada
    extracted_post_id = post_id
    if not extracted_post_id:
        m_fbid = re.search(r'[?&](?:story_fbid|multi_permalinks|fbid)=([0-9]+)', raw_url)
        if m_fbid:
            extracted_post_id = m_fbid.group(1)
        if not extracted_post_id:
            m_pid = re.search(r'/(?:posts|permalink|videos|reel)/([0-9]+)', raw_url)
            if m_pid:
                extracted_post_id = m_pid.group(1)
        if not extracted_post_id:
            m_set = re.search(r'set=(?:gm|pcb)\.([0-9]+)', raw_url)
            if m_set:
                extracted_post_id = m_set.group(1)

    # Cek apakah story_fbid memiliki id=group_id
    if not group_id and ('story_fbid=' in raw_url or 'multi_permalinks=' in raw_url):
        m_id = re.search(r'[?&]id=([0-9]+)', raw_url)
        if m_id:
            group_id = m_id.group(1)

    # 3. Format Permalink Grup (Format canonical utama)
    if group_id and extracted_post_id:
        return f"https://www.facebook.com/groups/{group_id}/permalink/{extracted_post_id}/{rdid_suffix}"

    # 4. Format Reel / Video
    if '/reel/' in raw_url or (extracted_post_id and '/reel/' in (raw_url or current_page_url)):
        r_id = extracted_post_id or (re.search(r'/reel/([0-9]+)', raw_url).group(1) if re.search(r'/reel/([0-9]+)', raw_url) else '')
        if r_id:
            return f"https://www.facebook.com/reel/{r_id}/"

    # 5. Format User / Halaman Post
    m_user_post = re.search(r'facebook\.com/([^/?#]+)/posts/([0-9]+)', raw_url)
    if m_user_post and m_user_post.group(1).lower() not in ['groups', 'permalink.php', 'story.php']:
        return f"https://www.facebook.com/{m_user_post.group(1)}/posts/{m_user_post.group(2)}/{rdid_suffix}"

    # 6. Jika ada author dan post_id
    if extracted_post_id and author and author != 'Warga':
        author_slug = re.sub(r'[^a-zA-Z0-9.]', '', author.lower())
        if author_slug and len(author_slug) >= 3:
            return f"https://www.facebook.com/{author_slug}/posts/{extracted_post_id}/{rdid_suffix}"

    if raw_url and not raw_url.startswith('https://www.facebook.com/search/'):
        return raw_url

    if extracted_post_id:
        return f"https://www.facebook.com/permalink.php?story_fbid={extracted_post_id}"

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
    dari seluruh sheet / file CSV (di folder results/ dan root) agar data yang sudah
    pernah diambil langsung di-SKIP tanpa diproses ulang.
    """
    seen_post_signatures = set()
    seen_post_ids = set()
    seen_post_urls = set()
    seen_comment_keys = set()

    files_to_check = set()
    if os.path.exists(current_post_csv):
        files_to_check.add(os.path.abspath(current_post_csv))
    if os.path.exists(current_comment_csv):
        files_to_check.add(os.path.abspath(current_comment_csv))

    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Scan folder results/ dan subfolder harian
    if os.path.exists(RESULTS_DIR):
        for root_dir, _, fnames in os.walk(RESULTS_DIR):
            for f in fnames:
                if f.endswith(".csv"):
                    files_to_check.add(os.path.join(root_dir, f))

    # Scan root directory for relevant CSV files
    for f in os.listdir(base_dir):
        if f.endswith(".csv") and ("post" in f.lower() or "comment" in f.lower() or "fb" in f.lower() or "isu" in f.lower() or "uji" in f.lower() or "tes" in f.lower()):
            files_to_check.add(os.path.join(base_dir, f))

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
                            seen_post_urls.add(clean_u)

                    # Track comment
                    if is_comment_file or 'comment_text' in row_lower:
                        cid = (row_lower.get('comment_id') or '').strip()
                        c_txt = (row_lower.get('comment_text') or '').strip()
                        c_auth = (row_lower.get('profile_name') or row_lower.get('author_name') or row_lower.get('author') or '').strip()
                        if cid and cid not in ['comment_id']:
                            seen_comment_keys.add(cid)
                        if c_txt:
                            seen_comment_keys.add(f"{c_auth}:::{c_txt[:50]}")
        except Exception:
            pass

    return seen_post_signatures, seen_post_ids, seen_post_urls, seen_comment_keys


def perform_feed_scroll(driver, distance=750):
    """
    Scroll feed dengan ritme responsif dan cepat untuk memuat postingan baru.
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
        """, distance)
    except Exception:
        pass
    time.sleep(random.uniform(0.01, 0.02))


def scroll_comment_container_center(driver, distance=550):
    """
    Melakukan scroll roda mouse KHUSUS di bagian tengah dialog komentar,
    memicu lazy loading komentar Facebook tanpa menggeser feed halaman luar.
    Menggunakan humanized step wheel events.
    """
    try:
        dialog = driver.find_element(By.CSS_SELECTOR, 'div[role="dialog"]')
        ActionChains(driver).move_to_element(dialog).scroll_by_amount(0, distance).perform()
    except Exception:
        pass

    try:
        driver.execute_script("""
            const distance = arguments[0];
            const dialog = document.querySelector('div[role="dialog"]');
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
def extract_comments_from_active_container(driver):
    """
    Mengekstrak komentar dan deep replies dari XHR GraphQL interceptor dan DOM dialog yang aktif.
    Mendukung resolusi SVG <use xlink:href="#Svg..."> untuk author dan teks komentar.
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
            let results = [];
            let scope = document.querySelector('div[role="dialog"]') || document;
            
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

            let dialog = document.querySelector('div[role="dialog"]');
            let scope = dialog || document;

            let commentElements = [];
            if (dialog) {
                commentElements = Array.from(dialog.querySelectorAll('div[aria-label*="Komentar oleh" i], div[aria-label*="Comment by" i], div[role="article"], div[aria-label*="Komentar" i], div[aria-label*="Comment" i], div[aria-label*="Balasan" i], div[aria-label*="Reply" i], ul > li, div[class*="x1y1aw1k"]'));
            } else {
                commentElements = Array.from(document.querySelectorAll('div[aria-label*="Komentar oleh" i], div[aria-label*="Comment by" i], div[role="article"][aria-label*="Komentar" i], div[role="article"][aria-label*="Comment" i], div[role="article"][aria-label*="Balasan" i], div[role="article"][aria-label*="Reply" i], ul > li div[role="article"], ul > li div[class*="x1r8uery"], div[class*="x1y1aw1k"]'));
            }

            commentElements.forEach((el, idx) => {
                if (el.closest('[role="navigation"]') || el.closest('[aria-label*="Notifikasi"]')) return;
                // Lewati jika elemen ini adalah kartu postingan utama feed
                if (!dialog && el.matches('div[role="feed"] > div')) return;

                let authorEl = el.querySelector('a span[dir="auto"], a strong, span > strong, strong, a[role="link"]');
                let author = authorEl ? resolveText(authorEl).split('\\n')[0].trim() : 'Warga';
                if (!author || author.toLowerCase().startsWith('hasil untuk') || author === 'Komentar') author = 'Warga';

                let authorLink = authorEl ? (authorEl.closest('a') ? authorEl.closest('a').href : (authorEl.tagName === 'A' ? authorEl.href : '')) : '';
                let cleanAuthorUrl = authorLink ? authorLink.split('?')[0].split('&')[0] : '';
                let uname = author;
                if (cleanAuthorUrl) {
                    let mU = cleanAuthorUrl.match(/facebook\\.com\\/([^/?#]+)/);
                    if (mU && mU[1] && mU[1] !== 'profile.php' && mU[1] !== 'people') uname = mU[1];
                }

                let textEl = el.querySelector('div[dir="auto"][lang], div[dir="auto"][style*="text-align"], div[dir="auto"], span[dir="auto"]');
                let commentText = textEl ? resolveText(textEl) : '';

                // Jika commentText sama dengan author (karena memilih author wrapper), cari text node berikutnya
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

                let timeEl = el.querySelector('abbr, a[aria-label*="lalu"], a[aria-label*="ago"], span[id*="timestamp"], a[role="link"] span');
                let commentDate = timeEl ? (resolveText(timeEl) || timeEl.getAttribute('aria-label') || 'Terkini') : 'Terkini';

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
                    if (pAuth) replyTo = resolveText(pAuth).split('\\n')[0].trim();
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
        """)
    except Exception:
        pass

    combined = []
    for c in (net_comments or []) + (dom_comments or []):
        c_txt = c.get('comment_text', '')
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
                if (txt.includes('semua komentar') || txt.includes('all comments')) {
                    item.click();
                    break;
                }
            }
        """)
        pause_ctrl.sleep(random.uniform(0.2, 0.35))
    except Exception:
        pass


def unfold_all_reply_threads(driver):
    """
    Membongkar dan mengklik seluruh tombol 'Lihat balasan' / 'View replies'
    secara otomatis agar balasan komentar di dalam thread terbuka dan ter-intercept.
    """
    try:
        clicked_count = driver.execute_script("""
            let scope = document.querySelector('div[role="dialog"]') || document;
            let buttons = Array.from(scope.querySelectorAll('div[role="button"], span[dir="auto"], a[role="button"], span'));
            let clickCount = 0;

            for (let b of buttons) {
                if (b.offsetParent === null) continue; // elemen tidak tampak
                let txt = (b.innerText || b.textContent || '').trim().toLowerCase();
                let aria = (b.getAttribute('aria-label') || '').toLowerCase();

                let isReplyTrigger = (
                    /\\b(\\d+\\s*balasan|lihat\\s*(\\d+\\s*)?balasan|balasan\\s*lainnya|\\d+\\s*repl(y|ies)|view\\s*(\\d+\\s*)?repl(y|ies)|view\\s*more\\s*replies|komentar\\s*sebelumnya|previous\\s*comments)\\b/i.test(txt) ||
                    aria.includes('balasan') || aria.includes('repl')
                );

                if (isReplyTrigger && !b.getAttribute('data-unfolded')) {
                    b.setAttribute('data-unfolded', 'true');
                    try {
                        b.click();
                        clickCount++;
                    } catch(e) {}
                }
            }
            return clickCount;
        """)
        return clicked_count or 0
    except Exception:
        return 0


def exhaustively_scroll_and_extract_comments(driver, max_idle_scrolls=3, max_total_comments_limit=150, seen_comment_keys=None):
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
        extracted = extract_comments_from_active_container(driver)
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


def get_output_csv_paths(base_output_name):
    if not base_output_name:
        base_output_name = "fb_isu_daerah"
    if base_output_name.endswith(".csv"):
        base_output_name = base_output_name[:-4]

    # Tambahkan timestamp (tanggal & waktu) otomatis agar file unik dan tidak tertukar
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_with_time = f"{base_output_name}_{timestamp}"

    if os.path.isabs(base_output_name) or os.path.dirname(base_output_name):
        dir_name = os.path.dirname(base_output_name)
        base_file = os.path.basename(base_output_name)
        post_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_posts.csv")
        comment_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_comments.csv")
    else:
        daily_dir = get_daily_results_dir()
        post_csv = os.path.join(daily_dir, f"{base_with_time}_posts.csv")
        comment_csv = os.path.join(daily_dir, f"{base_with_time}_comments.csv")
    return post_csv, comment_csv


def close_post_dialog(driver, search_url=None):
    """
    Menutup modal dialog komentar atau mengembalikan navigasi jika
    browser terlempar ke halaman permalink/beranda, agar tetap fokus di feed pencarian.
    """
    # 1. Tutup modal dialog jika ada di DOM
    try:
        driver.execute_script("""
            let dialog = document.querySelector('div[role="dialog"]');
            if (dialog) {
                let closeBtn = dialog.querySelector(
                    'div[aria-label="Tutup"], div[aria-label="Close"], svg[aria-label="Tutup"], div[role="button"][aria-label*="Tutup"], div[role="button"][aria-label*="Close"]'
                );
                if (closeBtn) {
                    closeBtn.closest('div[role="button"], span')?.click() || closeBtn.click();
                }
            }
        """)
        time.sleep(0.15)
    except Exception:
        pass

    try:
        has_dialog = driver.execute_script("return !!document.querySelector('div[role=\"dialog\"]');")
        if has_dialog:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.15)
    except Exception:
        pass

    # 2. Cek apakah browser terlempar ke halaman permalink (/permalink/, /posts/, /photo/) atau beranda utama
    if search_url:
        curr = driver.current_url
        is_trapped = (
            '/permalink/' in curr or 
            '/photo/' in curr or 
            curr.rstrip('/') in ['https://www.facebook.com', 'https://www.facebook.com/', 'https://web.facebook.com', 'https://m.facebook.com']
        )
        if is_trapped:
            print("  [*] Mengembalikan navigasi dari permalink/beranda ke feed pencarian...")
            try:
                driver.back()
                time.sleep(1.0)
            except Exception:
                pass
            if '/permalink/' in driver.current_url or '/photo/' in driver.current_url or driver.current_url.rstrip('/') in ['https://www.facebook.com', 'https://web.facebook.com']:
                driver.get(search_url)
                time.sleep(1.5)


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


def process_search_workflow(driver, keyword, post_csv, comment_csv, max_posts=20, max_comments_per_post=150, custom_search_url=None, group_name=None, min_year=2025):
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
    search_url = custom_search_url or f"https://www.facebook.com/search/posts/?q={urllib.parse.quote(keyword)}&filters={FB_CHRONOSORT_FILTER}"

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

    # Coba aktifkan filter 'Postingan Terbaru' jika tombol tersedia
    apply_recent_posts_filter(driver)

    while (max_posts == 0 or total_posts_saved < max_posts) and empty_scrolls < 8:
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        # Pastikan modal dialog tertutup dan tetap di halaman pencarian
        close_post_dialog(driver, search_url=search_url)

        # Cari postingan berikutnya yang belum diproses dari feed
        next_post = driver.execute_script("""
            let seenSignatures = arguments[0];
            let seenPostIds = arguments[1];
            let seenPostUrls = arguments[2];
            let feedNodes = document.querySelectorAll('div[role="feed"] > div, div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"]');

            for (let idx = 0; idx < feedNodes.length; idx++) {
                let p = feedNodes[idx];

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

                if (postText.length > 3 && !postText.toLowerCase().startsWith('hasil untuk') && !postText.toLowerCase().startsWith('menampilkan hasil')) {
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
                    let authorEl = p.querySelector('h2 strong, h3 strong, h4 strong, a strong, strong span, h2 a, h3 a, a[role="link"] span, h2, h3');
                    if (authorEl) {
                        let resolvedAuth = resolveElementTextWithSvg(authorEl);
                        if (resolvedAuth) {
                            author = resolvedAuth.split('\\n')[0].trim();
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

                    // 1. Periksa apakah halaman aktif berada di dalam grup
                    let currHref = window.location.href || '';
                    let pageGrpM = currHref.match(/facebook\\.com\\/groups\\/([^/?#]+)/);
                    if (pageGrpM && !['search', 'feed', 'joins', 'create', 'discover'].includes(pageGrpM[1].toLowerCase())) {
                        groupId = pageGrpM[1];
                    }

                    // 2. Scan semua link di dalam kartu postingan (prioritaskan timestamp link, permalink, multi_permalinks, posts)
                    let links = p.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"], a[href*="multi_permalinks"], a[href*="story_fbid="], a[href*="/videos/"], a[href*="/reel/"], a[href*="/groups/"], a[role="link"][href], a[href]');
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

                        if (href.includes('/posts/') || href.includes('/permalink/') || href.includes('/videos/') || href.includes('/reel/') || href.includes('story_fbid=') || href.includes('multi_permalinks') || href.includes('set=gm.') || href.includes('set=pcb.') || href.includes('fbid=')) {
                            if (!rawPostLink) rawPostLink = href;
                            let match = href.match(/(?:posts|permalink|videos|reel|story_fbid=|multi_permalinks=|multi_permalinks%3D|set=gm\\.|set=pcb\\.|fbid=)[/=?%3D]?([0-9]{8,25})/i);
                            if (match && match[1]) {
                                postId = match[1];
                                break;
                            }
                        }
                    }

                    // Fallback 1: Scan link dengan digit panjang (10-25 digit) yang bukan group id
                    if (!postId) {
                        for (let a of links) {
                            let href = a.href || a.getAttribute('href') || '';
                            let match = href.match(/([0-9]{10,25})/);
                            if (match && match[1] && match[1] !== groupId) {
                                postId = match[1];
                                if (!rawPostLink) rawPostLink = href;
                                break;
                            }
                        }
                    }

                    // Fallback 2: Scan innerHTML kartu postingan untuk mencari ID postingan (multi_permalinks, post_id, story_fbid)
                    if (!postId) {
                        let inner = p.innerHTML || '';
                        let mInner = inner.match(/(?:multi_permalinks[":\\[=]+|story_fbid[":\\[=]+|post_id[":\\[=]+|target_fbid[":\\[=]+|feedback_target_id[":\\[=]+|mf_story_key[":\\[=]+)([0-9]{8,25})/i);
                        if (mInner && mInner[1] && mInner[1] !== groupId) {
                            postId = mInner[1];
                        }
                    }

                    // Susun Canonical Permalink Format
                    let rdidQuery = rdid ? `?rdid=${rdid}` : '';
                    if (groupId && postId && postId !== groupId) {
                        postUrl = `https://www.facebook.com/groups/${groupId}/permalink/${postId}/${rdidQuery}`;
                    } else if (rawPostLink) {
                        if (rawPostLink.includes('/reel/')) {
                            let mR = rawPostLink.match(/\\/reel\\/([0-9]+)/);
                            if (mR) postUrl = `https://www.facebook.com/reel/${mR[1]}/`;
                        } else if (rawPostLink.includes('/posts/')) {
                            let mUp = rawPostLink.match(/facebook\\.com\\/([^/?#]+)\\/posts\\/([0-9]+)/);
                            if (mUp && !['groups', 'permalink.php', 'story.php'].includes(mUp[1].toLowerCase())) {
                                postUrl = `https://www.facebook.com/${mUp[1]}/posts/${mUp[2]}/${rdidQuery}`;
                            }
                        }
                        if (!postUrl) {
                            postUrl = rawPostLink.split('?')[0];
                            if (rdid) postUrl += rdidQuery;
                        }
                    }

                    let cleanUrl = postUrl ? postUrl.split('?')[0].replace(/\\/$/, '') : '';

                    // DEDUPLIKASI: Lewati jika postingan ini sudah ada di sheet sebelumnya
                    if (seenSignatures.includes(signature) || (postId && seenPostIds.includes(postId)) || (cleanUrl && seenPostUrls.includes(cleanUrl))) {
                        continue;
                    }

                    // EKSTRAKSI TANGGAL POSTINGAN SECARA PRESISI DARI SVG <use> & ELEMEN KARTU
                    let postDate = '';
                    const monthRegex = /\\b(?:januari|februari|maret|april|mei|juni|juli|agustus|september|oktober|november|desember|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|agt|agu|aug|sep|okt|oct|nov|des|dec)\\b/i;
                    const yearRegex = /\\b(19\\d{2}|20\\d{2})\\b/;
                    const relTimeRegex = /\\b\\d+\\s*(?:thn|th|tahun|yr|yrs|year|years|mgg|minggu|wk|week|weeks|hr|hari|day|days|jam|jm|hour|hours|mnt|menit|min|mins|lalu|ago)\\b/i;

                    let candidateElements = p.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid="], a[role="link"], span[dir="auto"], span, div[dir="auto"], abbr, svg');
                    for (let el of candidateElements) {
                        let resolved = resolveElementTextWithSvg(el);
                        if (!resolved) continue;

                        let resLower = resolved.toLowerCase();
                        if (resLower.includes('komentar') || resLower.includes('reaksi') || resLower.includes('bagikan') || resLower.includes('kirim pesan') || resLower.includes('jawab')) {
                            continue;
                        }

                        let isDate = (
                            yearRegex.test(resolved) ||
                            (monthRegex.test(resolved) && /\\d/.test(resolved)) ||
                            relTimeRegex.test(resolved) ||
                            resLower.includes('kemarin') ||
                            resLower.includes('yesterday') ||
                            resLower.includes('pukul') ||
                            resLower.includes('baru saja') ||
                            resLower.includes('just now') ||
                            resLower.includes('lalu') ||
                            resLower.includes('ago')
                        );

                        if (isDate) {
                            postDate = resolved;
                            if (yearRegex.test(resolved)) break;
                        }
                    }

                    // Fallback: periksa seluruh tag <use> di dalam kartu postingan p
                    if (!postDate) {
                        let allUsesInCard = p.querySelectorAll('use');
                        for (let u of allUsesInCard) {
                            let href = u.getAttribute('xlink:href') || u.getAttribute('href') || '';
                            if (href.startsWith('#')) {
                                try {
                                    let ref = document.getElementById(href.substring(1));
                                    if (ref) {
                                        let refTxt = (ref.textContent || ref.innerText || '').trim();
                                        if (refTxt && (yearRegex.test(refTxt) || relTimeRegex.test(refTxt) || monthRegex.test(refTxt))) {
                                            postDate = refTxt;
                                            if (yearRegex.test(refTxt)) break;
                                        }
                                    }
                                } catch(e) {}
                            }
                        }
                    }

                    if (!postDate) {
                        let fullCardText = p.innerText || '';
                        let foundYears = fullCardText.match(/\\b(19\\d{2}|20\\d{2})\\b/g);
                        if (foundYears) {
                            for (let y of foundYears) {
                                if (parseInt(y) < 2025) {
                                    postDate = y;
                                    break;
                                }
                            }
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

                    let cardFullText = p.innerText || '';
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

                    return {
                        dom_index: idx,
                        signature: signature,
                        post_id: postId || String(Math.abs(hashString(postText))),
                        author: author,
                        profile_url: profileUrl,
                        post_text: postText,
                        post_date: postDate,
                        post_url: postUrl || window.location.href,
                        comments_count: commentCount,
                        reactions_count: reactionCount,
                        shares_count: shareCount,
                        plays_count: playCount,
                        is_ad: isAd,
                        is_pinned: isPinned,
                        is_sponsored: isSponsored,
                        location: locationStr,
                        music_meta: musicMeta,
                        has_comment_stats: hasCommentStats
                    };
                }
            }

            function hashString(str) {
                let hash = 0;
                for (let i = 0; i < str.length; i++) {
                    hash = ((hash << 5) - hash) + str.charCodeAt(i);
                    hash |= 0;
                }
                return hash;
            }

            return null;
        """, list(seen_signatures), list(seen_post_ids), list(seen_post_urls), group_name or '')

        # Jika belum ada postingan baru di layar, scroll feed pencarian ke bawah
        if not next_post:
            empty_scrolls += 1
            perform_feed_scroll(driver, distance=750)
            pause_ctrl.sleep(random.uniform(0.4, 0.7))
            continue

        # Postingan baru ditemukan
        empty_scrolls = 0
        p_sig = next_post.get('signature')
        p_id = next_post.get('post_id')
        p_author = next_post.get('author')
        p_profile_url = next_post.get('profile_url', '')
        p_text = next_post.get('post_text')
        p_date = next_post.get('post_date')
        raw_p_url = next_post.get('post_url')

        # Standardisasi format URL Facebook ke canonical permalink (misal https://www.facebook.com/groups/.../permalink/.../)
        p_url = format_facebook_url(
            raw_url=raw_p_url,
            current_page_url=driver.current_url,
            post_id=p_id,
            author=p_author,
            group_name=group_name
        )
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
        if p_sig in seen_signatures or (p_id and p_id in seen_post_ids) or (clean_url and clean_url in seen_post_urls):
            seen_signatures.add(p_sig)
            print(f"  [SUDAH ADA DI SHEET] Dilewati @{p_author}: \"{p_text[:40]}...\"")
            continue

        seen_signatures.add(p_sig)
        if p_id: seen_post_ids.add(p_id)
        if clean_url: seen_post_urls.add(clean_url)

        # FILTER TAHUN: Lewati postingan usang (misal tahun 2024 atau sebelumnya)
        if is_outdated_post(p_date, min_year=min_year):
            print(f"  [DILEWATI] Postingan Usang ({p_date}) @{p_author}: \"{p_text[:40]}...\" (Filter aktif: Hanya tahun {min_year}+)")
            continue

        total_posts_saved += 1

        csv_keyword_label = f"[{group_name}] {keyword}" if group_name else keyword
        p_hashtags = extract_hashtags(p_text)
        p_lang = detect_language(p_text)

        # Simpan metadata postingan (25 kolom standar konsisten)
        save_to_csv(post_csv, [
            "Facebook", csv_keyword_label, p_id, p_date, p_author,
            p_profile_url, "", 0, 0, "",
            "", p_text, p_reactions_count, p_shares_count, p_plays_count,
            p_comments_count, "", p_lang, p_hashtags,
            p_is_ad, p_is_pinned, p_is_sponsored, p_location, p_music_meta, p_url
        ])

        target_str = f"/{max_posts}" if max_posts > 0 else ""
        print("\n" + "=" * 65)
        com_info = f" ({p_comments_count} komentar)" if p_comments_count > 0 else ""
        print(f"[POST #{total_posts_saved}{target_str}] @{p_author} ({p_date}){com_info}")
        print(f"  * URL  : {p_url}")
        print(f"  \"{p_text[:75]}...\"")
        print("  [*] LANGKAH 2: Klik Toggle Komentar...")

        # LANGKAH 2: KLIK TOGGLE KOMENTAR PADA POSTINGAN TERSEBUT SECARA PRESISI (HINDARI PERMALINK LINK)
        driver.execute_script("""
            let targetIdx = arguments[0];
            let feedNodes = document.querySelectorAll('div[role="feed"] > div, div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"]');
            let p = feedNodes[targetIdx];
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

            // 1. Target Utama: Cari tombol/span angka komentar spesifik (misal "250 komentar" atau <span dir="auto">250</span>)
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

            // 2. Target Kedua: Cari tombol "Komentari" / "Beri komentar" / "Comment" di Action Bar
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

            // 3. Target Ketiga: Cari span angka murni yang berada dalam konteks komentar (seperti <span dir="auto">250</span>)
            for (let el of allNodes) {
                if (el.closest('a[href*="/permalink/"], a[href*="/posts/"], a[href*="/photo/"]')) continue;
                let txt = (el.innerText || el.textContent || '').trim();
                let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                let parentTxt = el.parentElement ? (el.parentElement.innerText || el.parentElement.textContent || '').toLowerCase() : '';
                let parentAria = el.parentElement ? (el.parentElement.getAttribute('aria-label') || '').toLowerCase() : '';

                if (/^\\d+(?:[.,]\\d+)?\\s*(?:rb|k|m)?$/i.test(txt)) {
                    let isCom = aria.includes('komentar') || aria.includes('comment') || parentAria.includes('komentar') || parentAria.includes('comment') || parentTxt.includes('komentar');
                    if (isCom) {
                        let clickTarget = el.closest('div[role="button"]') || el;
                        try { clickTarget.click(); return; } catch(e) {}
                    }
                }
            }

            // 4. Fallback: Klik teks postingan / area kartu postingan untuk memicu modal dialog
            let textEl = p.querySelector('div[dir="auto"], div[data-ad-preview="message"]');
            if (textEl) {
                try { textEl.click(); return; } catch(e) {}
            }
        """, dom_idx)

        pause_ctrl.sleep(random.uniform(0.4, 0.7))

        # LANGKAH 3: UBAH FILTER MENJADI SEMUA KOMENTAR
        print("  [*] LANGKAH 3: Mengubah Filter Menjadi 'Semua Komentar'...")
        switch_filter_to_all_comments(driver)

        # LANGKAH 4: SCROLL SAMPAI HABIS & BONGKAR SEMUA BALASAN KOMENTAR
        print("  [*] LANGKAH 4: Scroll kontainer komentar & bongkar balasan...")
        post_comments = exhaustively_scroll_and_extract_comments(
            driver, max_idle_scrolls=3, max_total_comments_limit=max_comments_per_post, seen_comment_keys=seen_comment_keys
        )

        # Simpan seluruh komentar & balasan postingan ini ke CSV (25 kolom terstandarisasi dengan konteks postingan)
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

        # Tutup dialog postingan dan pastikan kembali ke feed pencarian
        close_post_dialog(driver, search_url=search_url)
        pause_ctrl.sleep(0.15)
        # Scroll feed pencarian ke bawah sedikit untuk memuat postingan berikutnya
        perform_feed_scroll(driver, distance=350)
        pause_ctrl.sleep(0.2)

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
    parser.add_argument("--output", type=str, help="Nama prefix file output")
    parser.add_argument("--keyword", type=str, help="Kata kunci tunggal pencarian")
    parser.add_argument("--max-posts", type=int, help="Maksimal postingan per kata kunci")
    parser.add_argument("--max-comments", type=int, help="Maksimal komentar per postingan")
    parser.add_argument("--min-year", type=int, default=2025, help="Tahun minimal postingan yang diambil (default: 2025)")
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

    keywords = []
    groups = []
    base_output_name = args.output or ""
    max_posts_target = args.max_posts or 20
    max_comments_limit = args.max_comments or 150
    min_post_year = args.min_year or 2025

    if mode == "1":
        if args.keyword:
            keywords = [args.keyword]
        else:
            keywords = load_keywords("keywords.txt")
        print(f"\n[*] Memuat {len(keywords)} kata kunci: {', '.join(keywords)}")
        if not base_output_name:
            base_output_name = input("Nama file output (default: fb_isu_daerah): ").strip() or "fb_isu_daerah"
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
        else:
            groups = load_groups("groups.txt")
            if not groups:
                g_input = input("URL Grup FB (contoh: https://www.facebook.com/groups/namagrup): ").strip()
                if g_input: groups = [g_input]
                else: return

        if args.keyword:
            keywords = [args.keyword]
        else:
            print("Pilihan Metode Grup:\n  A. Kata Kunci di keywords.txt\n  B. Feed Terbaru")
            m_grp = input("Pilih [A/B] (default: A): ").strip().upper() or "A"
            keywords = load_keywords("keywords.txt") if m_grp == "A" else ["Feed Terbaru"]
        
        if not base_output_name:
            base_output_name = input("Nama file output (default: fb_grup_monitoring): ").strip() or "fb_grup_monitoring"

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

    post_csv, comment_csv = get_output_csv_paths(base_output_name)
    init_posts_csv(post_csv)
    init_comments_csv(comment_csv)

    print("\n" + "=" * 65)
    print("  [KONTROL JEDA AKTIF] KONTROL KEYBOARD INTERAKTIF:")
    print("  * Tekan tombol [P] atau [SPASI] di keyboard untuk MENJEDA (Pause) / MELANJUTKAN.")
    print("  * Tekan tombol [Q] di keyboard untuk BERHENTI & SIMPAN data yang sudah didapat.")
    print("=" * 65)

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
                search_url = f"https://www.facebook.com/search/posts/?q={urllib.parse.quote(kw)}&filters={FB_CHRONOSORT_FILTER}"
                driver.get(search_url)
                pause_ctrl.sleep(2.0)
                process_search_workflow(driver, kw, post_csv, comment_csv, max_posts=max_posts_target, max_comments_per_post=max_comments_limit, min_year=min_post_year)

        elif mode == "2":
            for grp in groups:
                if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                    break
                grp_clean = grp.rstrip('/')
                grp_slug = grp_clean.split('/')[-1]

                # 1. Buka halaman utama grup terlebih dahulu
                print("\n" + "=" * 65)
                print(f"[*] MEMBUKA GRUP FACEBOOK: {grp_clean}")
                print("=" * 65)
                driver.get(grp_clean)
                pause_ctrl.sleep(2.0)

                for kw in keywords:
                    if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                        break
                    if kw == "Feed Terbaru":
                        target_url = f"{grp_clean}/?sorting_setting=CHRONOLOGICAL"
                        print(f"[*] Membuka Feed Kronologis Terbaru di grup '{grp_slug}'...")
                        driver.get(target_url)
                        pause_ctrl.sleep(2.0)
                        process_search_workflow(
                            driver, "Feed Terbaru", post_csv, comment_csv,
                            max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                            custom_search_url=target_url, group_name=grp_slug,
                            min_year=min_post_year
                        )
                    else:
                        target_url = f"{grp_clean}/search/?q={urllib.parse.quote(kw)}&filters={FB_CHRONOSORT_FILTER}"
                        print(f"[*] Melakukan pencarian '{kw}' di dalam grup '{grp_slug}' (Filter: Postingan Terbaru)...")
                        driver.get(target_url)
                        pause_ctrl.sleep(2.0)
                        process_search_workflow(
                            driver, kw, post_csv, comment_csv,
                            max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                            custom_search_url=target_url, group_name=grp_slug,
                            min_year=min_post_year
                        )

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
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    run_facebook_scraper()


