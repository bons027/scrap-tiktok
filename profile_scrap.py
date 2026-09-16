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
import re
import random
import shutil
import urllib.parse
import threading
import queue
import glob
from datetime import datetime
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Patch untuk mencegah bug WinError 6 pada Windows saat shutdown undetected-chromedriver
uc.Chrome.__del__ = lambda self: None

# Folder output default untuk menyimpan seluruh file CSV hasil scraping
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# Thread-safe Locks & Global Tracking
csv_lock = threading.Lock()
seen_lock = threading.Lock()
global_seen_video_ids = set()

# ==========================================
# KONTROLER JEDA (PAUSE / RESUME / STOP)
# ==========================================
try:
    import msvcrt
except ImportError:
    msvcrt = None


def cleanup_zombie_chrome():
    """
    Membersihkan sisa proses chrome.exe & chromedriver.exe scraper dari sesi sebelumnya
    yang tertinggal (zombie) serta menghapus lock file profil.
    Aman: Hanya menghentikan proses yang lokasinya berada di folder proyek ini.
    """
    import subprocess
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profiles = [os.path.join(base_dir, "tiktok_chrome_profile")]
    profiles.extend([os.path.join(base_dir, f"tiktok_chrome_profile_w{i}") for i in range(1, 10)])

    for p in profiles:
        if os.path.exists(p):
            for root, dirs, files in os.walk(p):
                for f in files:
                    if f in ["lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"] or f.endswith(".lock"):
                        try:
                            os.remove(os.path.join(root, f))
                        except Exception:
                            pass

    if sys.platform == "win32":
        try:
            b_clean = base_dir.replace('\\', '/')
            cmd = f'Get-Process -Name chrome, chromedriver -ErrorAction SilentlyContinue | Where-Object {{ $_.Path -and ($_.Path.Replace("\\\\", "/") -like "*{b_clean}*") }} | Stop-Process -Force'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, timeout=6)
        except Exception:
            pass


class PauseController:
    """
    Kontroler Jeda (Pause / Resume / Stop) Interaktif & Thread-Safe.
    Mendengarkan penekanan tombol keyboard secara non-blocking di terminal Windows.
    - Tekan 'P' atau 'Space' : Jeda (Pause) / Lanjut (Resume)
    - Tekan 'Q'             : Berhenti secara aman & simpan seluruh data ke CSV
    """
    def __init__(self):
        self.is_paused = False
        self.stop_requested = False
        self.lock = threading.Lock()
        self._listener_thread = None
        self._listener_started = False

    def start_listener(self):
        with self.lock:
            if self._listener_started or not msvcrt:
                return
            self._listener_started = True

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
                time.sleep(0.1)

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


# Inisialisasi Kontroler Jeda Global
pause_ctrl = PauseController()

# ==========================================
# 1. JAVASCRIPT INTERCEPTOR (FETCH & XHR)
# ==========================================
JS_INTERCEPTOR = """
window._scraped_data = [];
function pushData(type, payload) {
    if (window._scraped_data.length > 1000) {
        window._scraped_data.shift();
    }
    window._scraped_data.push({ type: type, timestamp: Date.now(), payload: payload });
}
const originalFetch = window.fetch;
window.fetch = new Proxy(originalFetch, {
    apply: async function(target, thisArg, argumentsList) {
        const [input, init] = argumentsList;
        const response = await target.apply(thisArg, argumentsList);
        const url = typeof input === 'string' ? input : (input?.url || '');
        if (url.includes('/api/') || url.includes('item_list') || url.includes('search_item') || url.includes('comment') || url.includes('post/item_list')) {
            const clonedResponse = response.clone();
            try {
                const text = await clonedResponse.text();
                let data;
                try { data = JSON.parse(text); } catch { data = text; }
                pushData('INTERCEPTED_FETCH', { url: url, method: init?.method || 'GET', data: data });
            } catch (err) {}
        }
        return response;
    }
});
const OrigXMLHttpRequest = window.XMLHttpRequest;
window.XMLHttpRequest = new Proxy(OrigXMLHttpRequest, {
    construct(target, args) {
        const xhr = new target(...args);
        let requestUrl = '';
        let requestMethod = 'GET';
        xhr.open = new Proxy(xhr.open, {
            apply(openTarget, openThis, openArgs) {
                requestMethod = openArgs[0];
                requestUrl = openArgs[1];
                return openTarget.apply(openThis, openArgs);
            }
        });
        xhr.addEventListener('load', function() {
            if (requestUrl && (requestUrl.includes('/api/') || requestUrl.includes('item_list') || requestUrl.includes('search_item') || requestUrl.includes('comment') || requestUrl.includes('post/item_list'))) {
                try {
                    let data;
                    try { data = JSON.parse(xhr.responseText); } catch { data = xhr.responseText; }
                    pushData('INTERCEPTED_XHR', { url: requestUrl, method: requestMethod, data: data });
                } catch (e) {}
            }
        });
        return xhr;
    }
});
"""

# ==========================================
# 2. FUNGSI DRIVER & ISOLATED WORKER PROFILES
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

def get_driver(worker_id=0):
    if worker_id == 0:
        cleanup_zombie_chrome()

    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    chromedriver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    master_profile = os.path.join(base_dir, "tiktok_chrome_profile")
    os.makedirs(master_profile, exist_ok=True)

    if worker_id == 0:
        profile_dir = master_profile
    else:
        profile_dir = os.path.join(base_dir, f"tiktok_chrome_profile_w{worker_id}")
        if not os.path.exists(profile_dir) and os.path.exists(master_profile):
            try:
                shutil.copytree(
                    master_profile, profile_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('*.lock', 'lockfile', 'Singleton*', 'RunningChromeVersion')
                )
            except Exception:
                pass
        os.makedirs(profile_dir, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1280,900")
    options.add_argument("--disable-notifications")
    options.add_argument("--mute-audio")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")

    driver_kwargs = {
        "options": options,
        "user_data_dir": profile_dir
    }
    if chrome_path:
        driver_kwargs["browser_executable_path"] = chrome_path
    if chromedriver_path:
        driver_kwargs["driver_executable_path"] = chromedriver_path

    driver = uc.Chrome(**driver_kwargs)

    try:
        driver.set_page_load_timeout(35)
        driver.set_script_timeout(20)
    except Exception:
        pass

    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": JS_INTERCEPTOR})
    except Exception:
        pass

    return driver, profile_dir

# ==========================================
# 3. HELPER UTILS & CLEANING
# ==========================================
def clean_username(raw_text):
    """
    Membersihkan input username dari URL, karakter '@', query string, dll.
    Contoh: 'https://www.tiktok.com/@jokowi?lang=id' -> 'jokowi'
    Contoh: '@kemendagri' -> 'kemendagri'
    """
    text = raw_text.strip()
    if not text:
        return ""
    if '/@' in text:
        text = text.split('/@')[1]
    elif text.startswith('@'):
        text = text[1:]
    
    # Bersihkan jika ada query params atau path lanjutan
    text = text.split('?')[0].split('/')[0].strip()
    return text

def pause_media_playback(driver):
    """
    Menghentikan pemutaran video/audio di halaman agar beban CPU, GPU, & RAM tetap ringan,
    serta mencegah browser Chrome membeku tanpa mengganggu status render UI.
    """
    try:
        driver.execute_script("""
            try {
                let mediaElements = document.querySelectorAll('video, audio');
                mediaElements.forEach(el => {
                    el.pause();
                    el.muted = true;
                    el.removeAttribute('autoplay');
                });
            } catch(e) {}
        """)
    except Exception:
        pass

def ensure_page_loaded(driver, max_wait=8):
    start_time = time.time()
    last_status = 'OK'
    while time.time() - start_time < max_wait:
        try:
            status = driver.execute_script("""
                const elements = Array.from(document.querySelectorAll('button, [role="button"], a, div[class*="Button"]'));
                for (const el of elements) {
                    const text = (el.innerText || el.textContent || '').toLowerCase().trim();
                    if (text === 'try again' || text === 'coba lagi' || text === 'refresh' || text === 'muat ulang') {
                        if (el.offsetParent !== null) {
                            el.click();
                            return 'CLICKED_RETRY';
                        }
                    }
                }
                const bodyText = (document.body ? document.body.innerText : '').toLowerCase();
                const hasError = bodyText.includes('something went wrong') || 
                                 bodyText.includes('unknown error') || 
                                 bodyText.includes('terjadi kesalahan') ||
                                 bodyText.includes('tidak dapat memuat konten');
                if (hasError) return 'HAS_ERROR';
                return 'OK';
            """)
            last_status = status
            if status == 'CLICKED_RETRY':
                time.sleep(3)
                return True
            elif status == 'OK':
                return True
        except Exception:
            pass
        time.sleep(1.5)
    return True

def dismiss_guest_popup(driver):
    """
    Menghilangkan popup login jika scraping berjalan dalam mode guest
    tanpa merusak container video atau komentar.
    """
    try:
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

        driver.execute_script("""
            // 1. Klik tombol 'Got it' / 'Mengerti' jika ada
            let btns = Array.from(document.querySelectorAll('button'));
            let gotIt = btns.find(b => {
                let t = (b.innerText || '').trim().toLowerCase();
                return t === 'got it' || t === 'mengerti' || t === 'oke';
            });
            if (gotIt) {
                try { gotIt.click(); } catch(e) {}
            }

            // 2. Klik tombol close login jika ada
            let closeBtns = document.querySelectorAll('[data-e2e="modal-close-inner-button"], button[aria-label="Close"], .tiktok-modal-close');
            closeBtns.forEach(btn => {
                try { btn.click(); } catch(e) {}
            });

            // 3. Sembunyikan HANYA modal yang spesifik berisi ajakan login/daftar
            let modals = document.querySelectorAll('div[class*="login-modal"], div[class*="DivLoginContainer"]');
            modals.forEach(el => {
                let t = (el.innerText || '').toLowerCase();
                if (t.includes('log in') || t.includes('masuk') || t.includes('daftar') || t.includes('sign up')) {
                    try {
                        el.style.setProperty('display', 'none', 'important');
                        el.style.setProperty('visibility', 'hidden', 'important');
                        el.style.setProperty('pointer-events', 'none', 'important');
                    } catch (e) {}
                }
            });

            // 4. Pastikan overflow body tidak terkunci
            ['html', 'body'].forEach(tag => {
                const el = document.querySelector(tag);
                if (el) {
                    const style = window.getComputedStyle(el);
                    if (el.style.overflow === 'hidden' || style.overflowY === 'hidden' || style.overflow === 'hidden') {
                        el.style.setProperty('overflow', 'auto', 'important');
                        el.style.setProperty('overflow-y', 'auto', 'important');
                    }
                }
            });
        """)
    except Exception:
        pass

def ensure_comments_tab_open(driver, max_retries=3):
    """
    Memastikan tab komentar pada video TikTok aktif dan terbuka.
    - Menutup popup/tips overlay seperti 'Got it'
    - Mengklik tombol tab 'Comments' / 'Komentar' secara presisi jika belum terbuka
    """
    for attempt in range(max_retries):
        # 1. Tutup tooltip / 'Got it' jika ada
        try:
            driver.execute_script("""
                let btns = Array.from(document.querySelectorAll('button'));
                let gotIt = btns.find(b => {
                    let t = (b.innerText || '').trim().toLowerCase();
                    return t === 'got it' || t === 'mengerti' || t === 'oke';
                });
                if (gotIt) {
                    try { gotIt.click(); } catch(e) {}
                }
            """)
        except Exception:
            pass

        # 2. Cek apakah komentar sudah muncul di DOM
        try:
            is_visible = driver.execute_script("""
                return document.querySelectorAll('[data-e2e="comment-level-1"], [class*="DivCommentItemWrapper"]').length > 0;
            """)
            if is_visible:
                return True
        except Exception:
            pass

        # 3. Klik tombol Comments / Komentar secara presisi
        try:
            driver.execute_script("""
                let btn = Array.from(document.querySelectorAll('button, [role="tab"]')).find(el => {
                    let t = (el.innerText || '').trim().toLowerCase();
                    return t === 'comments' || t === 'komentar';
                });
                if (btn) {
                    btn.click();
                    return true;
                }
                return false;
            """)
        except Exception:
            pass

        time.sleep(1.5)
        try:
            is_visible = driver.execute_script("""
                return document.querySelectorAll('[data-e2e="comment-level-1"], [class*="DivCommentItemWrapper"]').length > 0;
            """)
            if is_visible:
                return True
        except Exception:
            pass

    return False

def extract_dom_comments_from_page(driver):
    """
    Ekstrak data komentar langsung dari struktur DOM TikTok desktop terbaru.
    Mengambil username (@user), nickname, teks komentar, tanggal, dan like count.
    """
    try:
        return driver.execute_script("""
            let items = [];
            let wrappers = document.querySelectorAll('[class*="DivCommentItemWrapper"]');
            if (wrappers.length === 0) {
                let spans = document.querySelectorAll('[data-e2e="comment-level-1"]');
                wrappers = Array.from(spans).map(s => s.closest('div[class*="DivCommentItem"]') || s.parentElement.parentElement);
            }

            wrappers.forEach((w, idx) => {
                if (!w) return;
                let userLinks = Array.from(w.querySelectorAll('a[href*="/@"]'));
                let profileUrl = userLinks.length > 0 ? userLinks[0].href : '';
                let username = '';
                if (profileUrl.includes('/@')) {
                    username = profileUrl.split('/@')[1].split('?')[0].split('/')[0];
                }
                let nickname = '';
                for (let a of userLinks) {
                    let txt = (a.innerText || '').trim();
                    if (txt) { nickname = txt; break; }
                }
                if (!nickname && username) nickname = username;

                let textSpan = w.querySelector('[data-e2e="comment-level-1"], [data-e2e="comment-level-2"]');
                let text = textSpan ? textSpan.innerText.trim() : '';

                let raw = w.innerText || '';
                let lines = raw.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                if (!text && lines.length >= 2) {
                    text = lines[1];
                }
                if (!nickname && lines.length >= 1) {
                    nickname = lines[0];
                }

                let dateStr = 'Unknown';
                for (let line of lines) {
                    if (/^(\\d+-\\d+|\\d+d ago|\\d+h ago|\\d+m ago|\\d+w ago|\\d+ jam lalu|\\d+ hari lalu)/i.test(line)) {
                        dateStr = line;
                        break;
                    }
                }

                let likeEl = w.querySelector('[class*="DivActionItemContainer"], [aria-label*="like" i], [data-e2e="comment-like-count"]');
                let likes = likeEl ? likeEl.innerText.trim() : '0';

                let rawCid = w.getAttribute('id') || w.getAttribute('data-id') || '';

                if (text) {
                    items.push({
                        cid: rawCid,
                        username: username || nickname || 'anonymous',
                        nickname: nickname || username || 'anonymous',
                        text: text,
                        date: dateStr,
                        likes: likes
                    });
                }
            });
            return items;
        """) or []
    except Exception:
        return []

def scroll_comments_container(driver):
    """
    Menggulir kontainer komentar TikTok secara presisi.
    Mendukung scroll container DivCommentMain ataupun scrollable parent.
    """
    try:
        scrolled = driver.execute_script("""
            let target = document.querySelector('[class*="DivCommentMain"]');
            if (!target) {
                let comment = document.querySelector('[data-e2e="comment-level-1"]');
                let curr = comment;
                while (curr && curr !== document.documentElement) {
                    let style = window.getComputedStyle(curr);
                    if (curr.scrollHeight > curr.clientHeight + 20 && (style.overflowY === 'auto' || style.overflowY === 'scroll')) {
                        target = curr;
                        break;
                    }
                    curr = curr.parentElement;
                }
            }
            if (target) {
                target.scrollTop += 1500;
                target.dispatchEvent(new Event('scroll', { bubbles: true }));
                target.dispatchEvent(new WheelEvent('wheel', { deltaY: 1500, bubbles: true }));
                return true;
            }
            window.scrollBy(0, 1000);
            return false;
        """)
        return scrolled
    except Exception:
        return False


def perform_human_scroll(driver, distance=1400):
    try:
        ActionChains(driver).scroll_by_amount(0, distance).perform()
    except Exception:
        pass

    try:
        driver.execute_script("""
            const distance = arguments[0];
            window.scrollBy(0, distance);
            if (document.documentElement) document.documentElement.scrollTop += distance;
            if (document.body) document.body.scrollTop += distance;
        """, distance)
    except Exception:
        pass

# ==========================================
# 4. FUNGSI CSV & CHECKPOINT (THREAD-SAFE)
# ==========================================
def get_profile_csv_paths(username):
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', username)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    video_csv = os.path.join(RESULTS_DIR, f"{safe_name}_videos_{timestamp}.csv")
    comment_csv = os.path.join(RESULTS_DIR, f"{safe_name}_comments_{timestamp}.csv")
    return video_csv, comment_csv

def init_video_csv(filename):
    with csv_lock:
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "target_profile", "video_id", "upload_date", "author_nickname", 
                    "description", "play_count", "like_count", "comment_count", 
                    "share_count", "video_url"
                ])

def init_comments_csv(filename):
    with csv_lock:
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    "video_id", "target_profile", "comment_id", "comment_date", 
                    "commenter_username", "commenter_nickname", "comment_text", 
                    "likes", "replies", "video_url"
                ])

def save_to_csv(filename, data_row):
    with csv_lock:
        try:
            with open(filename, mode='a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(data_row)
        except Exception as e:
            print(f"[!] Gagal menulis ke CSV {filename}: {e}")

def get_already_scraped_video_ids(comments_csv_path):
    scraped_ids = set()
    if not comments_csv_path or not os.path.exists(comments_csv_path):
        return scraped_ids
    try:
        with open(comments_csv_path, mode='r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                v_id = str(row.get('video_id', '')).strip()
                if v_id and v_id.lower() != 'none' and v_id != 'video_id':
                    scraped_ids.add(v_id)
    except Exception:
        pass
    return scraped_ids

def load_profiles_from_file(filepath="profiles.txt"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    if not os.path.exists(full_path):
        return []
    profiles = []
    with open(full_path, "r", encoding="utf-8") as f:
        for line in f:
            val = line.strip()
            if val and not val.startswith("#"):
                clean = clean_username(val)
                if clean and clean not in profiles:
                    profiles.append(clean)
    return profiles

# ==========================================
# 5. SCRAPING METADATA PROFIL & VIDEO
# ==========================================
def extract_profile_header(driver):
    """Mengambil informasi biodata & statistik akun dari header profil TikTok."""
    try:
        info = driver.execute_script("""
            let nickname = document.querySelector('h1[data-e2e="user-title"], h2[data-e2e="user-title"]');
            let bio = document.querySelector('h2[data-e2e="user-bio"], div[data-e2e="user-bio"]');
            let following = document.querySelector('strong[data-e2e="following-count"]');
            let followers = document.querySelector('strong[data-e2e="followers-count"]');
            let likes = document.querySelector('strong[data-e2e="likes-count"]');

            return {
                nickname: nickname ? nickname.innerText.trim() : 'Unknown',
                bio: bio ? bio.innerText.trim() : '',
                following: following ? following.innerText.trim() : '0',
                followers: followers ? followers.innerText.trim() : '0',
                likes: likes ? likes.innerText.trim() : '0'
            };
        """)
        return info or {}
    except Exception:
        return {}

def scrape_profile_videos(driver, username, max_videos=0, video_csv=""):
    """
    Menjelajahi halaman profil TikTok (@username) dan mengumpulkan daftar seluruh video
    beserta view count, like count, comment count, dan URL videonya.
    """
    target_url = f"https://www.tiktok.com/@{username}"
    print(f"\n[*] Membuka Halaman Profil: {target_url}")
    try:
        driver.get(target_url)
    except Exception as e:
        print(f"[!] Timeout / error membuka profil: {e}")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

    pause_ctrl.sleep(3.0)
    ensure_page_loaded(driver, max_wait=8)
    dismiss_guest_popup(driver)
    pause_media_playback(driver)

    # Ambil data header akun
    p_info = extract_profile_header(driver)
    nickname = p_info.get('nickname', username)
    print("\n" + "=" * 65)
    print(f"  PROFIL DITEMUKAN: @{username} ({nickname})")
    print(f"  * Pengikut (Followers) : {p_info.get('followers', '0')}")
    print(f"  * Mengikuti (Following): {p_info.get('following', '0')}")
    print(f"  * Total Suka (Likes)   : {p_info.get('likes', '0')}")
    if p_info.get('bio'):
        print(f"  * Bio : {p_info.get('bio')[:60]}...")
    print("=" * 65)

    collected_videos = []
    seen_ids = set()
    consecutive_empty_scrolls = 0
    max_empty_limit = 8
    scroll_count = 0

    print(f"\n[*] Mengumpulkan daftar video dari profil @{username}...")
    while True:
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        scroll_count += 1
        found_in_batch = 0

        # 1. Interceptor API: Tangkap post/item_list dari network
        captured_data = None
        try:
            captured_data = driver.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
        except Exception:
            captured_data = None

        if captured_data:
            for item in captured_data:
                payload = item.get('payload', {})
                data_asli = payload.get('data', {})
                videos = []
                if isinstance(data_asli, dict):
                    if 'itemList' in data_asli and isinstance(data_asli['itemList'], list):
                        videos = data_asli['itemList']
                    elif 'data' in data_asli and isinstance(data_asli['data'], list):
                        videos = data_asli['data']

                for vid in videos:
                    vid_obj = vid.get('item', vid) if isinstance(vid, dict) and 'type' in vid else vid
                    if not isinstance(vid_obj, dict): continue
                    v_id = str(vid_obj.get('id', ''))
                    if not v_id or v_id in seen_ids:
                        continue
                    seen_ids.add(v_id)

                    desc = vid_obj.get('desc', '')
                    stats = vid_obj.get('stats', {})
                    create_time_unix = vid_obj.get('createTime')
                    try:
                        upload_date = datetime.fromtimestamp(int(create_time_unix)).strftime('%Y-%m-%d %H:%M:%S') if create_time_unix else "Unknown"
                    except Exception:
                        upload_date = "Error"

                    vid_url = f"https://www.tiktok.com/@{username}/video/{v_id}"
                    author_nick = vid_obj.get('author', {}).get('nickname', nickname)
                    p_cnt = stats.get('playCount', 0)
                    l_cnt = stats.get('diggCount', 0)
                    c_cnt = stats.get('commentCount', 0)
                    s_cnt = stats.get('shareCount', 0)

                    save_to_csv(video_csv, [
                        username, v_id, upload_date, author_nick, desc, 
                        p_cnt, l_cnt, c_cnt, s_cnt, vid_url
                    ])

                    collected_videos.append({
                        'video_id': v_id,
                        'video_url': vid_url,
                        'author_nickname': author_nick,
                        'description': desc,
                        'comment_count': c_cnt,
                        'play_count': p_cnt
                    })
                    found_in_batch += 1
                    print(f"  + [#{len(seen_ids)}] [{upload_date}] {desc[:35]}... (views: {p_cnt:,}, komen: {c_cnt:,})")

                    if max_videos > 0 and len(seen_ids) >= max_videos:
                        break

        # 2. DOM HTML Fallback (Ekstrak link dan card video langsung dari elemen halaman)
        try:
            dom_items = driver.execute_script("""
                let results = [];
                let links = document.querySelectorAll('a[href*="/video/"]');
                for (let a of links) {
                    let href = a.href || '';
                    if (!href.includes('/video/')) continue;
                    let parts = href.split('/video/');
                    let vid_id = parts[1].split('?')[0].split('/')[0].trim();
                    if (!vid_id || !/^\\d+$/.test(vid_id)) continue;

                    let card = a.closest('[data-e2e="user-post-item"], div[class*="DivItemContainer"], div[class*="DivVideoCardContainer"]') || a.parentElement || a;
                    let views = '0';
                    let desc = '';
                    if (card) {
                        let vEl = card.querySelector('[data-e2e="video-views"], strong, [class*="VideoViews"]');
                        if (vEl) views = (vEl.innerText || '').trim();
                        let dEl = card.querySelector('img[alt], a[title], [class*="VideoDesc"]');
                        if (dEl) desc = dEl.getAttribute('alt') || dEl.getAttribute('title') || (dEl.innerText || '').trim();
                    }
                    results.push({ id: vid_id, url: href, views: views, desc: desc });
                }
                return results;
            """)
            if dom_items:
                for d in dom_items:
                    v_id = str(d.get('id', '')).strip()
                    if not v_id or v_id in seen_ids:
                        continue
                    seen_ids.add(v_id)
                    v_url = d.get('url', f"https://www.tiktok.com/@{username}/video/{v_id}")
                    desc = d.get('desc', '')
                    views = d.get('views', '0')

                    save_to_csv(video_csv, [
                        username, v_id, "Terkini", nickname, desc,
                        views, 0, 0, 0, v_url
                    ])
                    collected_videos.append({
                        'video_id': v_id,
                        'video_url': v_url,
                        'author_nickname': nickname,
                        'description': desc,
                        'comment_count': 0,
                        'play_count': views
                    })
                    found_in_batch += 1
                    print(f"  + [#{len(seen_ids)}] [DOM] {desc[:35]}... (views: {views})")

                    if max_videos > 0 and len(seen_ids) >= max_videos:
                        break
        except Exception:
            pass

        if max_videos > 0 and len(seen_ids) >= max_videos:
            print(f"  [*] Target batas {max_videos} video profil tercapai.")
            break

        if found_in_batch > 0:
            consecutive_empty_scrolls = 0
        else:
            consecutive_empty_scrolls += 1
            if consecutive_empty_scrolls >= max_empty_limit:
                print(f"  [*] Selesai ({max_empty_limit}x scroll berturut-turut tanpa video baru). Seluruh video profil telah dimuat.")
                break

        dismiss_guest_popup(driver)
        pause_media_playback(driver)
        scroll_px = random.randint(1200, 1700)
        perform_human_scroll(driver, scroll_px)

        if scroll_count % 3 == 0:
            try:
                driver.execute_script("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });")
            except Exception:
                pass

        pause_ctrl.sleep(random.uniform(2.0, 3.2))

    print(f"\n[OK] Selesai mengambil video profil @{username}. Total: {len(collected_videos)} video tersimpan di {video_csv}")
    return collected_videos

# ==========================================
# 6. SCRAPING KOMENTAR VIDEO
# ==========================================
def scrape_comments_for_video(driver, video_url, video_id, profile_username, comments_csv, max_comments=50, worker_prefix=""):
    if not video_url or not video_id:
        return 0
    if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
        return 0

    w_tag = f"[{worker_prefix}] " if worker_prefix else ""
    print(f"\n  {w_tag}Mengakses Video ID {video_id}: {video_url}")
    try:
        driver.get(video_url)
    except Exception as e:
        print(f"  {w_tag}[WARN] Gagal/timeout load halaman video {video_id}: {e}")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass

    pause_ctrl.sleep(2.5)
    pause_media_playback(driver)
    ensure_page_loaded(driver, max_wait=6)
    dismiss_guest_popup(driver)
    pause_media_playback(driver)

    # Pastikan tab komentar aktif dan terbuka
    ensure_comments_tab_open(driver, max_retries=3)
    pause_ctrl.sleep(1.5)

    seen_keys = set()
    total_captured = 0
    empty_scrolls = 0
    api_finished = False

    max_scrolls = 200 if max_comments == 0 else max(8, (max_comments // 10) + 8)

    for scroll_idx in range(max_scrolls):
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        dismiss_guest_popup(driver)
        pause_media_playback(driver)
        new_in_batch = 0

        # 1. Interceptor API (Fetch / XHR)
        captured_data = None
        try:
            captured_data = driver.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
        except Exception:
            captured_data = None

        if captured_data:
            for item in captured_data:
                payload = item.get('payload', {})
                url = payload.get('url', '')
                if 'comment' in url:
                    data = payload.get('data', {})
                    if isinstance(data, dict):
                        has_more = data.get('has_more')
                        if has_more == 0 or has_more is False:
                            api_finished = True

                        raw_comments = data.get('comments') or []
                        for c in raw_comments:
                            if not isinstance(c, dict): continue
                            cid = str(c.get('cid', ''))
                            txt = c.get('text', '').strip()
                            if not txt: continue

                            u_info = c.get('user', {}) or {}
                            uname = u_info.get('unique_id', 'Unknown')
                            nname = u_info.get('nickname', uname)

                            key = (uname, txt)
                            if cid in seen_keys or key in seen_keys:
                                continue
                            if cid: seen_keys.add(cid)
                            seen_keys.add(key)

                            likes = c.get('digg_count', 0)
                            replies = c.get('reply_comment_total', 0)
                            ctime = c.get('create_time')
                            try:
                                cdate = datetime.fromtimestamp(int(ctime)).strftime('%Y-%m-%d %H:%M:%S') if ctime else "Unknown"
                            except Exception:
                                cdate = "Unknown"

                            save_to_csv(comments_csv, [
                                video_id, profile_username, cid or f"api_{total_captured}", cdate, uname, nname, txt, likes, replies, video_url
                            ])
                            new_in_batch += 1
                            total_captured += 1
                            print(f"    {w_tag}+ [{cdate}] @{uname} ({nname}): {txt[:40]}... (likes: {likes})")

                            if max_comments > 0 and total_captured >= max_comments:
                                break
                if max_comments > 0 and total_captured >= max_comments:
                    break

        # 2. Ekstrak Komentar dari Struktur DOM Halaman
        dom_comments = extract_dom_comments_from_page(driver)
        if dom_comments:
            for c in dom_comments:
                uname = c.get('username', 'Unknown')
                nname = c.get('nickname', uname)
                txt = c.get('text', '').strip()
                if not txt: continue

                key = (uname, txt)
                cid = c.get('cid', '')
                if cid and cid in seen_keys:
                    continue
                if key in seen_keys:
                    continue
                if cid: seen_keys.add(cid)
                seen_keys.add(key)

                gen_cid = cid if cid else f"dom_{hash(f'{uname}_{txt}') & 0xFFFFFFFFFFFFFFFF}"
                save_to_csv(comments_csv, [
                    video_id, profile_username, gen_cid, c.get('date', 'Unknown'), uname, nname, txt, c.get('likes', '0'), 0, video_url
                ])
                new_in_batch += 1
                total_captured += 1
                print(f"    {w_tag}+ [{c.get('date', 'Unknown')}] @{uname} ({nname}): {txt[:40]}... (likes: {c.get('likes', '0')})")

                if max_comments > 0 and total_captured >= max_comments:
                    break

        if max_comments > 0 and total_captured >= max_comments:
            break

        if api_finished and new_in_batch == 0 and total_captured > 0:
            break

        if new_in_batch == 0:
            empty_scrolls += 1
            if empty_scrolls >= 8:
                break
            # Jika belum dapat komentar sama sekali, coba pastikan tab aktif lagi
            if total_captured == 0:
                ensure_comments_tab_open(driver, max_retries=1)
        else:
            empty_scrolls = 0

        # Gulir panel komentar secara presisi
        scroll_comments_container(driver)
        pause_media_playback(driver)
        pause_ctrl.sleep(random.uniform(2.2, 3.2))

    print(f"  {w_tag}-> Selesai video {video_id}. Total {total_captured} komentar tersimpan.")
    return total_captured

# ==========================================
# 7. WORKER FUNCTION UNTUK MULTI-BROWSER
# ==========================================
def comment_scraping_worker(worker_id, video_queue, profile_username, comments_csv, max_comments, total_videos, counter_lock, progress_dict):
    worker_tag = f"Worker #{worker_id+1}"
    print(f"[*] [{worker_tag}] Membuka browser...")
    try:
        driver, _ = get_driver(worker_id=worker_id)
        driver.get("https://www.tiktok.com")
        pause_ctrl.sleep(2)
    except Exception as e:
        print(f"[ERROR] [{worker_tag}] Gagal membuka browser: {e}")
        return

    try:
        while True:
            if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                break

            try:
                v_data = video_queue.get_nowait()
            except queue.Empty:
                break

            with counter_lock:
                progress_dict['done'] += 1
                curr_idx = progress_dict['done']

            print(f"\n[{worker_tag}] ({curr_idx}/{total_videos}) Memproses Video: {v_data.get('description', '')[:45]}...")
            try:
                scrape_comments_for_video(
                    driver=driver,
                    video_url=v_data['video_url'],
                    video_id=v_data['video_id'],
                    profile_username=profile_username,
                    comments_csv=comments_csv,
                    max_comments=max_comments,
                    worker_prefix=worker_tag
                )
            except Exception as e:
                print(f"[!] [{worker_tag}] Error saat memproses video {v_data.get('video_id')}: {e}")
                is_alive = False
                try:
                    _ = driver.current_url
                    is_alive = True
                except Exception:
                    is_alive = False

                if not is_alive:
                    print(f"[*] [{worker_tag}] Browser freeze/terputus. Me-restart browser worker...")
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    try:
                        driver, _ = get_driver(worker_id=worker_id)
                        driver.get("https://www.tiktok.com")
                        pause_ctrl.sleep(2)
                    except Exception as err:
                        print(f"[ERROR] [{worker_tag}] Gagal membuka browser baru: {err}")
                        break
            finally:
                video_queue.task_done()

            pause_ctrl.sleep(random.uniform(1.2, 2.2))

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print(f"[*] [{worker_tag}] Selesai dan browser ditutup.")

# ==========================================
# 8. MENU UTAMA & WORKFLOW PROFIL SCRAPER
# ==========================================
def run_profile_scraper():
    import argparse
    parser = argparse.ArgumentParser(description="TikTok Profile & Comments Scraper (Berdasarkan Akun Profil)")
    parser.add_argument("--profile", type=str, help="Username atau URL profil TikTok target")
    parser.add_argument("--max-videos", type=int, help="Maksimal video dari profil yang diproses")
    parser.add_argument("--max-comments", type=int, help="Maksimal komentar per video")
    parser.add_argument("--workers", type=int, help="Jumlah browser paralel (1-4)")
    args, unknown = parser.parse_known_args()

    print("\n" + "=" * 65)
    print("      TIKTOK PROFILE & COMMENTS INTELLIGENCE SCRAPER")
    print("        (Scrape Video & Komentar dari Profil Akun)")
    print("=" * 65)
    target_profiles = []
    if args.profile:
        cleaned = clean_username(args.profile)
        if cleaned:
            target_profiles = [cleaned]

    if not target_profiles:
        print("PILIHAN TARGET PROFIL:")
        print("  * Ketik langsung Username atau Link Profil TikTok (contoh: @kemendagri)")
        print("  * Atau ketik '2' / 'file' untuk membaca dari file 'profiles.txt'")
        print("=" * 65)

        raw_in = input("Target Profil (contoh: @kemendagri, atau tekan Enter untuk @kemendagri): ").strip()

        if raw_in in ["2", "file", "profiles.txt"]:
            target_profiles = load_profiles_from_file("profiles.txt")
            if not target_profiles:
                print("[!] File 'profiles.txt' kosong. Menggunakan default: @kemendagri")
                target_profiles = ["kemendagri"]
            else:
                print(f"[*] Berhasil memuat {len(target_profiles)} profil dari profiles.txt: {', '.join(target_profiles)}")
        elif raw_in in ["1", ""]:
            file_profs = load_profiles_from_file("profiles.txt")
            if file_profs:
                target_profiles = file_profs
                print(f"[*] Menggunakan target dari profiles.txt: {', '.join(target_profiles)}")
            else:
                target_profiles = ["kemendagri"]
                print("[*] Menggunakan target default: @kemendagri")
        else:
            cleaned = clean_username(raw_in)
            if cleaned:
                target_profiles = [cleaned]
            else:
                target_profiles = ["kemendagri"]
                print("[*] Menggunakan target default: @kemendagri")

    if not target_profiles:
        print("[ERROR] Tidak ada profil yang dimasukkan untuk diproses.")
        return

    # Parameter Batas Video & Komentar
    max_videos = args.max_videos
    if max_videos is None:
        try:
            mv_in = input("\nMaksimal video profil yang diambil [0 untuk SEMUA video] (default: 20): ").strip()
            max_videos = int(mv_in) if mv_in else 20
        except ValueError:
            max_videos = 20

    max_comments = args.max_comments
    if max_comments is None:
        try:
            mc_in = input("Maksimal komentar per video [0 untuk SEMUA komentar] (default: 50): ").strip()
            max_comments = int(mc_in) if mc_in else 50
        except ValueError:
            max_comments = 50

    # Jumlah Browser Paralel untuk Komentar
    num_workers = args.workers
    if num_workers is None:
        print("\n" + "=" * 65)
        print("          AKSELERASI MULTI-BROWSER (CONCURRENCY)")
        print("=" * 65)
        print("  1. 1 Browser (Standar)")
        print("  2. 2 Browser Sekaligus (2x Lebih Cepat)")
        print("  3. 3 Browser Sekaligus (3x Cepat - Direkomendasikan)")
        print("  4. 4 Browser Sekaligus (4x Super Cepat)")
        print("=" * 65)
        try:
            w_in = input("Pilih jumlah browser paralel [1/2/3/4] (default: 2): ").strip()
            num_workers = int(w_in) if w_in in ["1", "2", "3", "4"] else 2
        except ValueError:
            num_workers = 2

    # Proses Setiap Profil Target
    processed_count = 0
    for p_idx, username in enumerate(target_profiles):
        print("\n" + "=" * 65)
        print(f"  MEMPROSES PROFIL ({p_idx+1}/{len(target_profiles)}): @{username}")
        print("=" * 65)

        video_csv, comment_csv = get_profile_csv_paths(username)
        init_video_csv(video_csv)
        init_comments_csv(comment_csv)

        # ---------------------------------------------------------
        # TAHAP 1: KUMPULKAN DAFTAR VIDEO DARI HALAMAN PROFIL
        # ---------------------------------------------------------
        print(f"\n[*] Membuka browser master untuk mengambil postingan profil @{username}...")
        try:
            driver_master, profile_dir = get_driver(worker_id=0)
        except Exception as e:
            print(f"[ERROR] Gagal membuka browser: {e}")
            return

        videos_to_process = []
        try:
            pause_ctrl.start_listener()
            print("\n" + "=" * 65)
            print("  [KONTROL JEDA AKTIF] Tekan [P] untuk Pause, [Q] untuk Stop & Simpan.")
            print("=" * 65)
            videos_to_process = scrape_profile_videos(
                driver=driver_master,
                username=username,
                max_videos=max_videos,
                video_csv=video_csv
            )
        finally:
            try:
                driver_master.quit()
            except Exception:
                pass

        if not videos_to_process:
            print(f"[WARN] Tidak ada video yang ditemukan pada profil @{username}.")
            print("  (Kemungkinan akun tidak memiliki video publik atau terhalang Captcha).")
            continue

        # ---------------------------------------------------------
        # TAHAP 2: SCRAPING KOMENTAR PER POSTINGAN VIDEO
        # ---------------------------------------------------------
        total_videos = len(videos_to_process)
        already_scraped_ids = get_already_scraped_video_ids(comment_csv)
        pending_videos = [v for v in videos_to_process if str(v.get('video_id', '')).strip() not in already_scraped_ids]
        already_done_count = total_videos - len(pending_videos)

        print("\n" + "=" * 65)
        print(f"  SCRAPING KOMENTAR POSTINGAN PROFIL @{username}")
        print(f"  * Total Video Target : {total_videos} video")
        print(f"  * Sudah Di-scrape    : {already_done_count} video")
        print(f"  * Sisa Diproses      : {len(pending_videos)} video")
        print(f"  * Max Komen / Video  : {'Semua' if max_comments == 0 else max_comments}")
        print(f"  * Browser Paralel    : {num_workers} browser")
        print(f"  * File Komentar CSV  : {comment_csv}")
        print("=" * 65)

        if not pending_videos:
            print(f"[INFO] Seluruh komentar video profil @{username} sudah lengkap di CSV.")
            processed_count += 1
            continue

        video_queue = queue.Queue()
        for v in pending_videos:
            video_queue.put(v)

        counter_lock = threading.Lock()
        progress_dict = {'done': already_done_count}
        threads = []
        actual_workers = min(num_workers, len(pending_videos)) if len(pending_videos) > 0 else 1

        pause_ctrl.start_listener()
        for w_idx in range(actual_workers):
            t = threading.Thread(
                target=comment_scraping_worker,
                args=(w_idx, video_queue, username, comment_csv, max_comments, total_videos, counter_lock, progress_dict),
                daemon=True
            )
            threads.append(t)
            t.start()
            time.sleep(2.5)

        video_queue.join()
        for t in threads:
            t.join()

        processed_count += 1
        print("\n" + "=" * 65)
        print(f"  [SELESAI PROFIL @{username}]")
        print(f"  * Data Video    : {video_csv}")
        print(f"  * Data Komentar : {comment_csv}")
        print("=" * 65)

    print("\n" + "=" * 65)
    if processed_count > 0:
        print(f"  [SELESAI SEMUA] Scraping ({processed_count} Profil) Tuntas!")
        print(f"  Semua hasil tersimpan di folder: {RESULTS_DIR}")
    else:
        print("  [SELESAI] Tidak ada profil/video yang berhasil diproses.")
    print("=" * 65)

if __name__ == "__main__":
    try:
        run_profile_scraper()
    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna. Seluruh data yang sudah terambil tersimpan aman di CSV.")
