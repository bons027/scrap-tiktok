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
import shutil
import urllib.parse
import threading
import queue
import glob
import re
import subprocess
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

# Thread-safe Locks & Global Deduplication Tracking
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
        self._start_keyboard_listener()

    def _start_keyboard_listener(self):
        if not msvcrt:
            return

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
        if (url.includes('/api/') || url.includes('item_list') || url.includes('search_item') || url.includes('comment')) {
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
    construct: function(target, args) {
        const xhr = new target(...args);
        xhr.addEventListener('load', () => {
             if (xhr.responseURL && (xhr.responseURL.includes('/api/') || xhr.responseURL.includes('item_list') || xhr.responseURL.includes('comment'))) {
                let responseData = xhr.responseText;
                try { responseData = JSON.parse(xhr.responseText); } catch {}
                pushData('INTERCEPTED_XHR', { url: xhr.responseURL, data: responseData });
             }
        });
        return new target(...args);
    }
});
"""

# ==========================================
# 2. FUNGSI DRIVER & ISOLATED WORKER PROFILES
# ==========================================
def find_binary(filenames, subdirs):
    """
    Mencari binary (chrome.exe / chromedriver.exe) di folder lokal atau folder di atasnya.
    """
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

def get_driver(worker_id=0):
    """
    Inisialisasi browser undetected-chromedriver dengan profil terisolasi per worker.
    Worker 0 menggunakan 'tiktok_chrome_profile'.
    Worker 1..N menggunakan 'tiktok_chrome_profile_wN' dengan sinkronisasi sesi dari master.
    """
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    driver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    version_main = get_chrome_major_version(chrome_path)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    master_profile = os.path.join(base_dir, "tiktok_chrome_profile")
    os.makedirs(master_profile, exist_ok=True)

    if worker_id == 0:
        profile_dir = master_profile
    else:
        profile_dir = os.path.join(base_dir, f"tiktok_chrome_profile_w{worker_id}")
        # Salin sesi dari profil master ke profil worker jika worker belum punya profil
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
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": JS_INTERCEPTOR})
    except Exception:
        pass

    return driver, profile_dir

# ==========================================
# 3. FUNGSI SESI & LOGIN TIKTOK
# ==========================================
def is_user_logged_in(driver):
    """
    Mengecek apakah sesi pengguna TikTok sedang aktif (sudah login).
    Mengecek cookies HttpOnly (sessionid, sid_tt, uid_tt) via Selenium dan elemen profil DOM.
    """
    try:
        cookies = driver.get_cookies()
        session_keys = {'sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt', 'uid_tt_ss', 'passport_auth_status'}
        for c in cookies:
            if c.get('name') in session_keys and c.get('value'):
                return True
    except Exception:
        pass

    try:
        dom_logged = driver.execute_script("""
            const avatar = document.querySelector(
                '[data-e2e="profile-icon"], [data-e2e="nav-profile"], [class*="AvatarContainer"], a[href*="/@"] img, img[class*="ImgAvatar"]'
            );
            if (avatar && avatar.offsetParent !== null) return true;

            const profileLink = document.querySelector('a[href*="/@"]');
            if (profileLink && profileLink.href && !profileLink.href.includes('/@login')) return true;

            return false;
        """)
        if dom_logged:
            return True
    except Exception:
        pass

    return False

def setup_tiktok_session():
    """
    Menu 0: Membuka browser TikTok interaktif untuk setup & simpan sesi login permanen.
    User dapat login via QR Code Aplikasi, Email, Google, atau No. HP.
    """
    print("\n" + "=" * 65)
    print("      SETUP & SIMPAN SESI LOGIN TIKTOK (PERMANEN)")
    print("=" * 65)
    print("Browser TikTok akan dibuka.")
    print("1. Silakan login ke akun TikTok Anda menggunakan:")
    print("   - Scan QR Code via Aplikasi TikTok di Smartphone (Paling Cepat)")
    print("   - Atau Login dengan Akun Google / Email / No. Handphone")
    print("2. Setelah berhasil login, sesi dan cookies akan tersimpan otomatis")
    print("   ke folder 'tiktok_chrome_profile/' dan otomatis terduplikasi ke semua worker!")
    print("=" * 65)

    try:
        driver, profile_dir = get_driver(worker_id=0)
        print(f"\n[*] Lokasi Profil Browser: {profile_dir}")
        print("[*] Membuka halaman login TikTok...")
        driver.get("https://www.tiktok.com/login")
        time.sleep(3)
        ensure_page_loaded(driver, max_wait=6)

        try:
            qr_link = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Use QR code') or contains(text(), 'Gunakan kode QR')]"))
            )
            qr_link.click()
            print("[*] Tab QR Code aktif. Silakan scan melalui aplikasi TikTok di ponsel Anda.")
        except Exception:
            pass

        print("\n" + "-" * 65)
        print(" >>> SILAKAN SELESAIKAN LOGIN DI JENDELA BROWSER TIKTOK <<<")
        print(" >>> Script memantau status login secara otomatis...     <<<")
        print(" >>> Atau tekan [ENTER] di terminal jika sudah login.   <<<")
        print("-" * 65)

        start_wait = time.time()
        max_login_wait = 180

        while time.time() - start_wait < max_login_wait:
            if is_user_logged_in(driver):
                print("\n[SUKSES] Login Berhasil Terdeteksi!")
                print(f"[INFO] Seluruh cookies dan sesi telah tersimpan permanen di:")
                print(f"       -> {profile_dir}")
                time.sleep(3)
                break
            time.sleep(2)

        if not is_user_logged_in(driver):
            input("\n[?] Jika Anda sudah selesai login di browser, tekan [ENTER] di sini: ")

        print("\n[SELESAI] Setup sesi selesai. Anda sekarang siap menjalankan scraping multi-browser!")

    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan saat setup sesi: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

def login_via_qr(driver):
    """
    Membuka halaman login TikTok dan menunggu user scan QR / login secara interaktif.
    """
    print("\n[LOGIN] Membuka halaman login TikTok...")
    driver.get("https://www.tiktok.com/login")
    time.sleep(3)
    ensure_page_loaded(driver, max_wait=6)

    try:
        try:
            qr_link = WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Use QR code') or contains(text(), 'Gunakan kode QR')]"))
            )
            qr_link.click()
            print("[LOGIN] Tab QR Code diaktifkan di layar browser.")
        except Exception:
            pass

        print("\n" + "-" * 65)
        print(" >>> SILAKAN SCAN QR CODE ATAU LOGIN DI BROWSER SEKARANG <<<")
        print(" >>> Setelah login berhasil, tekan [ENTER] di terminal.   <<<")
        print("-" * 65)

        input("Tekan [ENTER] jika Anda sudah selesai login di browser: ")

        if is_user_logged_in(driver):
            print("[LOGIN] Sesi login terkonfirmasi aktif! Melanjutkan...")
        else:
            print("[LOGIN] Melanjutkan proses scraping...")
        time.sleep(1.5)
        return True

    except Exception as e:
        print(f"[LOGIN] Melanjutkan: {e}")
        return False

def ensure_page_loaded(driver, max_wait=8):
    """
    Memastikan halaman tidak macet di pesan error 'Unknown error' / 'Something went wrong'.
    Otomatis mencari dan mengklik tombol 'Try again' / 'Coba lagi' / 'Refresh'.
    """
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

    if last_status == 'HAS_ERROR':
        try:
            driver.refresh()
            time.sleep(4)
        except Exception:
            pass
        return True
    return True

def perform_human_scroll(driver, distance=800):
    """
    Melakukan scroll multi-metode dengan mouse wheel dan event container.
    """
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

            const candidates = document.querySelectorAll('div, main, section, [data-e2e*="search"], [data-e2e*="item-list"]');
            for (const el of candidates) {
                if (el.scrollHeight > el.clientHeight + 50 && el.clientHeight > 150) {
                    const s = window.getComputedStyle(el);
                    if (s.overflowY === 'auto' || s.overflowY === 'scroll' || s.overflow === 'auto' || s.overflow === 'scroll') {
                        el.scrollTop += distance;
                        el.dispatchEvent(new Event('scroll', { bubbles: true }));
                        el.dispatchEvent(new WheelEvent('wheel', { deltaY: distance, bubbles: true }));
                    }
                }
            }
        """, distance)
    except Exception:
        pass

    try:
        if distance >= 500:
            ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
        elif distance <= -150:
            ActionChains(driver).send_keys(Keys.PAGE_UP).perform()
    except Exception:
        pass

def dismiss_guest_popup(driver):
    """
    Menghilangkan popup login jika scraping berjalan dalam mode guest.
    """
    try:
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

        driver.execute_script("""
            const selectors = [
                'div[class*="login-modal"]',
                'div[class*="DivLoginContainer"]',
                'div[class*="DivModalContainer"]',
                'div[role="dialog"]',
                'div[class*="mask"]',
                'div[class*="backdrop"]',
                '[data-e2e="modal-close-inner-button"]',
                'button[aria-label="Close"]',
                '.tiktok-modal-close'
            ];
            for (let s of selectors) {
                document.querySelectorAll(s).forEach(el => {
                    try {
                        el.style.setProperty('display', 'none', 'important');
                        el.style.setProperty('visibility', 'hidden', 'important');
                        el.style.setProperty('pointer-events', 'none', 'important');
                    } catch (e) {}
                });
            }

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

# ==========================================
# 4. FUNGSI CSV & OUTPUT PATHS (THREAD-SAFE)
# ==========================================
def get_output_csv_paths(base_output_name):
    if not base_output_name:
        base_output_name = "tiktok_isu_daerah"
    if base_output_name.endswith(".csv"):
        base_output_name = base_output_name[:-4]

    # Sisipkan timestamp (tanggal & waktu) otomatis agar unik
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_with_time = f"{base_output_name}_{timestamp}"

    if os.path.isabs(base_output_name) or os.path.dirname(base_output_name):
        dir_name = os.path.dirname(base_output_name)
        base_file = os.path.basename(base_output_name)
        video_csv = os.path.join(dir_name, f"{base_file}_{timestamp}.csv")
        comment_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_comments.csv")
    else:
        daily_dir = get_daily_results_dir()
        video_csv = os.path.join(daily_dir, f"{base_with_time}.csv")
        comment_csv = os.path.join(daily_dir, f"{base_with_time}_comments.csv")
    return video_csv, comment_csv

def load_keywords(filepath="keywords.txt"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        print(f"[!] File {filepath} tidak ditemukan. Membuat template default...")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("# Masukkan 1 keyword per baris\nBupati Klaten\njalan rusak Klaten\n")
            
    with open(full_path, 'r', encoding='utf-8') as f:
        keywords = [line.strip() for line in f if line.strip() and not line.strip().startswith('#')]
        
    if not keywords:
        print("[!] File keywords kosong! Masukkan keyword langsung:")
        manual_kw = input("Keyword: ").strip()
        if manual_kw:
            keywords = [manual_kw]
            
    return keywords

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

def init_csv(filename):
    with csv_lock:
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
    with csv_lock:
        if not os.path.isfile(filename):
            with open(filename, mode='w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'platform', 'search_keyword', 'post_id', 'comment_id', 'comment_date',
                    'profile_name', 'username', 'profile_url', 'comment_text', 'likes',
                    'reply_count', 'is_reply', 'reply_to', 'video_url'
                ])

def save_to_csv(filename, data_row):
    """
    Fungsi penyimpanan CSV aman dari bentrok multi-threading (Thread-Safe Lock).
    """
    with csv_lock:
        with open(filename, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(data_row)

def is_outdated_post(date_str, min_year=2025):
    """
    Mengecek apakah tanggal postingan/video lebih tua dari min_year (contoh: 2024, 2023, 2022).
    - Jika memuat tahun eksplisit (misal '2024-11-05', '15 Agustus 2024') dan tahun < min_year -> True (Outdated).
    - Jika memuat durasi tahun relatif (misal '2 thn lalu', '3 tahun lalu', '2 yrs ago') -> dihitung berdasarkan tahun berjalan.
    - Jika tanggal relatif baru atau tahun >= min_year -> False (Terkini).
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


def load_videos_from_csv(csv_path, min_year=2025):
    if not os.path.exists(csv_path):
        cand = os.path.join(RESULTS_DIR, csv_path)
        if os.path.exists(cand):
            csv_path = cand
        else:
            # Cari recursive di subfolder harian results/
            matched = glob.glob(os.path.join(RESULTS_DIR, "**", os.path.basename(csv_path)), recursive=True)
            if matched and os.path.exists(matched[0]):
                csv_path = matched[0]
            else:
                print(f"[ERROR] File {csv_path} tidak ditemukan!")
                return []

    videos = []
    seen_ids = set()
    with open(csv_path, mode='r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_lower = {k.lower().strip(): v for k, v in row.items() if k and v}
            vid_id = str(row_lower.get('post_id') or row_lower.get('video_id') or '').strip()
            vid_url = (row_lower.get('video_url') or row_lower.get('post_url') or '').strip()
            kw = (row_lower.get('search_keyword') or 'Unknown').strip()
            u_date = (row_lower.get('post_date') or row_lower.get('upload_date') or '').strip()
            u_name = (row_lower.get('profile_name') or row_lower.get('username') or row_lower.get('author_name') or '').strip()
            u_desc = (row_lower.get('description') or row_lower.get('post_text') or '').strip()

            # Filter tahun jika tanggal terdeteksi lebih usang dari min_year
            if u_date and is_outdated_post(u_date, min_year=min_year):
                continue

            # Hindari duplikasi ID video saat memuat CSV
            if vid_id and vid_url and vid_id.lower() != 'none' and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                videos.append({
                    'video_id': vid_id,
                    'video_url': vid_url,
                    'keyword': kw,
                    'username': u_name,
                    'description': u_desc,
                    'upload_date': u_date
                })
    return videos

def get_already_scraped_video_ids(comments_csv_path):
    """
    Membaca seluruh video_id yang sudah pernah berhasil di-scrape di file comments_csv.
    Digunakan untuk auto-resume jika proses scraping sempat terhenti di tengah jalan.
    """
    if not comments_csv_path or not os.path.exists(comments_csv_path):
        return set()
    
    scraped_ids = set()
    try:
        with open(comments_csv_path, mode='r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            for row in reader:
                row_lower = {k.lower().strip(): v for k, v in row.items() if k and v}
                v_id = str(row_lower.get('post_id') or row_lower.get('video_id') or '').strip()
                if v_id and v_id.lower() != 'none' and v_id not in ['video_id', 'post_id']:
                    scraped_ids.add(v_id)
    except Exception:
        pass
    except Exception:
        pass
    return scraped_ids

# ==========================================
# 5. FUNGSI SCRAPING KOMENTAR PER VIDEO
# ==========================================
def scrape_comments_for_video(driver, video_url, video_id, keyword, comments_csv, max_comments=50, worker_prefix=""):
    if not video_url or not video_id:
        return 0
    if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
        return 0
        
    w_tag = f"[{worker_prefix}] " if worker_prefix else ""
    print(f"\n  {w_tag}Mengakses Video ID {video_id}: {video_url}")
    driver.get(video_url)
    pause_ctrl.sleep(2.5)
    ensure_page_loaded(driver, max_wait=6)
    dismiss_guest_popup(driver)
    
    # Pastikan tab komentar aktif
    try:
        driver.execute_script("""
            let els = document.querySelectorAll('[role="tab"], button, [data-e2e*="comment"], [data-e2e*="tab"]');
            els.forEach(el => {
                let txt = (el.innerText || el.textContent || '').trim().toLowerCase();
                let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                let e2e = (el.getAttribute('data-e2e') || '').toLowerCase();
                if (txt.includes('comment') || txt.includes('komentar') || e2e.includes('comment') || aria.includes('comment')) {
                    try { el.click(); } catch(e) {}
                }
            });
        """)
    except Exception:
        pass
    pause_ctrl.sleep(1.8)
    
    seen_comment_ids = set()
    total_captured = 0
    empty_scrolls = 0
    api_finished = False
    
    max_scrolls = 200 if max_comments == 0 else max(5, (max_comments // 15) + 5)
    
    for scroll_idx in range(max_scrolls):
        if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
            break

        dismiss_guest_popup(driver)
        new_in_batch = 0
        
        # 1. Interceptor API
        captured_data = driver.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
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
                            if not cid or cid in seen_comment_ids:
                                continue
                            seen_comment_ids.add(cid)
                            
                            u_info = c.get('user', {}) or {}
                            uname = u_info.get('unique_id', 'Unknown')
                            nname = u_info.get('nickname', 'Unknown')
                            txt = c.get('text', '')
                            likes = c.get('digg_count', 0)
                            replies = c.get('reply_comment_total', 0)
                            ctime = c.get('create_time')
                            try:
                                cdate = datetime.fromtimestamp(int(ctime)).strftime('%Y-%m-%d %H:%M:%S') if ctime else "Unknown"
                            except Exception:
                                cdate = "Error"
                                
                            prof_url = f"https://www.tiktok.com/@{uname}" if uname and uname != 'Unknown' else ""
                            save_to_csv(comments_csv, [
                                "TikTok", keyword, video_id, cid, cdate,
                                nname, uname, prof_url, txt, likes,
                                replies, "No", "", video_url
                            ])
                            new_in_batch += 1
                            total_captured += 1
                            print(f"    {w_tag}+ [{cdate}] @{uname}: {txt[:40]}... (likes: {likes})")
                            
                            if max_comments > 0 and total_captured >= max_comments:
                                break
                                
                if max_comments > 0 and total_captured >= max_comments:
                    break

        # 2. Fallback DOM
        dom_comments = driver.execute_script("""
            let results = [];
            document.querySelectorAll('[data-e2e="comment-level-1"], [class*="DivCommentItemContainer"]').forEach((el, idx) => {
                let userEl = el.querySelector('a[href*="/@"]') || el.querySelector('[data-e2e="comment-username"]') || {};
                let textEl = el.querySelector('[data-e2e="comment-level-1-text"]') || el.querySelector('[class*="PCommentText"]') || el;
                let user = (userEl.innerText || '').trim();
                let user_url = userEl.href || '';
                let uname = user_url.includes('/@') ? user_url.split('/@')[1].split('?')[0] : user;
                let text = (textEl.innerText || '').trim();
                if (text) {
                    results.push({
                        cid: 'dom_' + idx,
                        username: uname || 'Unknown',
                        nickname: user || 'Unknown',
                        user_url: user_url || '',
                        text: text
                    });
                }
            });
            return results;
        """)
        if dom_comments:
            for c in dom_comments:
                cid = c['cid']
                if cid not in seen_comment_ids:
                    seen_comment_ids.add(cid)
                    dom_prof_url = c.get('user_url') or (f"https://www.tiktok.com/@{c['username']}" if c['username'] != 'Unknown' else "")
                    save_to_csv(comments_csv, [
                        "TikTok", keyword, video_id, cid, "Unknown",
                        c['nickname'], c['username'], dom_prof_url, c['text'], 0,
                        0, "No", "", video_url
                    ])
                    new_in_batch += 1
                    total_captured += 1
                    print(f"    {w_tag}+ [DOM] @{c['username']}: {c['text'][:40]}...")
                    if max_comments > 0 and total_captured >= max_comments:
                        break

        if max_comments > 0 and total_captured >= max_comments:
            break

        if api_finished and new_in_batch == 0:
            break

        if new_in_batch == 0:
            empty_scrolls += 1
            if empty_scrolls >= 5:
                break
        else:
            empty_scrolls = 0

        # Scroll kontainer komentar
        try:
            elem = driver.find_element(By.CSS_SELECTOR, '[class*="DivCommentMain"], [class*="CommentMain"], [class*="DivCommentListContainer"], [data-e2e="comment-list"]')
            ActionChains(driver).move_to_element(elem).scroll_by_amount(0, 1200).perform()
        except Exception:
            pass

        driver.execute_script("""
            let targets = document.querySelectorAll('[class*="DivCommentMain"], [class*="CommentMain"], [id*="comment" i], [data-e2e="comment-list"]');
            targets.forEach(el => {
                el.scrollTop += 1200;
                el.dispatchEvent(new Event('scroll', { bubbles: true }));
                el.dispatchEvent(new WheelEvent('wheel', { deltaY: 1200, bubbles: true }));
            });
        """)
        pause_ctrl.sleep(random.uniform(2.0, 3.2))

    print(f"  {w_tag}-> Selesai video {video_id}. Total {total_captured} komentar tersimpan.")
    return total_captured

# ==========================================
# 6. WORKER FUNCTION UNTUK MULTI-BROWSER
# ==========================================
def comment_scraping_worker(worker_id, video_queue, comments_csv, max_comments, total_videos, counter_lock, progress_dict):
    """
    Worker thread yang menjalankan 1 browser terisolasi untuk menyedot komentar dari antrean video.
    Menjamin tidak ada video yang diambil 2 kali karena diambil secara atomic dari queue.
    """
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
            scrape_comments_for_video(
                driver=driver,
                video_url=v_data['video_url'],
                video_id=v_data['video_id'],
                keyword=v_data.get('keyword', 'Unknown'),
                comments_csv=comments_csv,
                max_comments=max_comments,
                worker_prefix=worker_tag
            )
            video_queue.task_done()
            pause_ctrl.sleep(random.uniform(1.2, 2.2))

    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print(f"[*] [{worker_tag}] Selesai dan browser ditutup.")

# ==========================================
# 7. MENU UTAMA & LOGIKA SCRAPER
# ==========================================
def run_scraper():
    import argparse
    parser = argparse.ArgumentParser(description="TikTok Intelligence Scraper Multi-Browser (Video & Komentar)")
    parser.add_argument("--mode", type=str, choices=["0", "1", "2", "3"], help="Mode scraper (0=Setup Sesi, 1=Video Saja, 2=Video+Komen, 3=Komen dari CSV)")
    parser.add_argument("--workers", type=int, help="Jumlah browser paralel (1-4)")
    parser.add_argument("--output", type=str, help="Nama dasar file output CSV")
    parser.add_argument("--keyword", type=str, help="Kata kunci tunggal pencarian")
    parser.add_argument("--max-comments", type=int, help="Maksimal komentar per video")
    parser.add_argument("--max-videos", type=int, help="Maksimal video yang diproses")
    parser.add_argument("--min-year", type=int, default=2025, help="Tahun minimal video yang diambil (default: 2025)")
    parser.add_argument("--no-login", action="store_true", help="Gunakan Guest Mode (tanpa login)")
    args, unknown = parser.parse_known_args()

    mode = args.mode
    if not mode:
        print("=" * 65)
        print("   TIKTOK MULTI-BROWSER INTELLIGENCE SCRAPER (LOCAL SELENIUM)")
        print("=" * 65)
        print("PILIHAN MENU:")
        print("  0. Setup & Simpan Sesi Login TikTok (Cukup Login 1 Kali)")
        print("  1. Scrap Video Metadata Saja (Berdasarkan keywords.txt)")
        print("  2. Scrap Video + Komentar Sekaligus (Multi-Browser Cepat & Otomatis)")
        print("  3. Scrap Komentar dari File CSV Video yang Sudah Ada")
        print("=" * 65)
        mode = input("Pilih menu [0/1/2/3] (default: 2): ").strip() or "2"

    if mode == "0":
        setup_tiktok_session()
        return

    # Inisialisasi variabel
    keywords = []
    existing_videos = []
    base_output_name = args.output or ""
    max_comments_per_video = args.max_comments or 50
    max_videos_for_comments = args.max_videos or 0
    num_workers = args.workers or 1
    min_post_year = args.min_year or 2025

    if mode in ["1", "2"]:
        if args.keyword:
            keywords = [args.keyword]
        else:
            keywords = load_keywords("keywords.txt")
        if not keywords:
            print("[ERROR] Tidak ada keyword untuk diproses.")
            return
        print(f"\n[*] Berhasil memuat {len(keywords)} keyword: {', '.join(keywords)}")

        if not base_output_name:
            base_output_name = input("Masukkan nama file output (default: tiktok_isu_daerah): ").strip() or "tiktok_isu_daerah"

        video_csv, comment_csv = get_output_csv_paths(base_output_name)
        init_csv(video_csv)
        print(f"[*] Metadata video akan disimpan ke : {video_csv}")
        
        if mode == "2":
            init_comments_csv(comment_csv)
            print(f"[*] Komentar video akan disimpan ke : {comment_csv}")
            
            if not args.max_comments:
                try:
                    max_com_input = input("Maksimal komentar per video [contoh: 50, atau 0 untuk semua] (default: 50): ").strip()
                    max_comments_per_video = int(max_com_input) if max_com_input else 50
                except ValueError:
                    max_comments_per_video = 50
                    
            if not args.max_videos:
                try:
                    max_vid_input = input("Maksimal video yang dicari per keyword [0 untuk semua] (default: 30): ").strip()
                    max_videos_for_comments = int(max_vid_input) if max_vid_input else 30
                except ValueError:
                    max_videos_for_comments = 30

    elif mode == "3":
        # Temukan file-file CSV video yang ada di results/ (termasuk subfolder harian) atau root
        found_csvs = [
            os.path.relpath(f, RESULTS_DIR) if f.startswith(RESULTS_DIR) else os.path.basename(f)
            for f in glob.glob(os.path.join(RESULTS_DIR, "**", "*.csv"), recursive=True) + glob.glob("*.csv")
            if not f.endswith("_comments.csv") and not f.endswith("_posts.csv")
        ]
        default_csv = found_csvs[0] if found_csvs else "data_tiktok.csv"

        if found_csvs:
            print(f"\n[*] File CSV video terdeteksi: {', '.join(found_csvs[:5])}")

        csv_source = input(f"Masukkan nama file CSV sumber video (default: {default_csv}): ").strip() or default_csv
        existing_videos = load_videos_from_csv(csv_source, min_year=min_post_year)
        if not existing_videos:
            return
            
        print(f"[*] Berhasil memuat {len(existing_videos)} video unik dari {csv_source}")
        prefix = os.path.splitext(os.path.basename(csv_source))[0]
        default_comment_name = f"{prefix}_comments.csv"

        if not base_output_name:
            base_output_name = input(f"Nama file output komentar (default: {default_comment_name}): ").strip() or default_comment_name
        
        # Jika file sudah berupa file CSV komentar, gunakan path langsung
        if base_output_name.endswith(".csv"):
            if os.path.isabs(base_output_name) or os.path.dirname(base_output_name):
                comment_csv = base_output_name
            else:
                cand = os.path.join(RESULTS_DIR, base_output_name)
                comment_csv = cand if os.path.exists(cand) or os.path.exists(RESULTS_DIR) else base_output_name
            video_csv = ""
        else:
            video_csv, comment_csv = get_output_csv_paths(base_output_name)

        init_comments_csv(comment_csv)
        print(f"[*] Komentar akan disimpan ke: {comment_csv}")
        
        if not args.max_comments:
            try:
                max_com_input = input("Maksimal komentar per video (default: 50): ").strip()
                max_comments_per_video = int(max_com_input) if max_com_input else 50
            except ValueError:
                max_comments_per_video = 50
            
        if not args.max_videos:
            try:
                max_vid_input = input(f"Maksimal video yang diproses [1-{len(existing_videos)}, atau 0 untuk semua] (default: 0): ").strip()
                max_videos_for_comments = int(max_vid_input) if max_vid_input else 0
            except ValueError:
                max_videos_for_comments = 0

    # Pilihan Jumlah Browser Paralel
    if mode in ["2", "3"] and not args.workers:
        print("\n" + "=" * 65)
        print("          AKSELERASI MULTI-BROWSER (CONCURRENCY)")
        print("=" * 65)
        print("  1. 1 Browser (Standar)")
        print("  2. 2 Browser Sekaligus (2x Lebih Cepat)")
        print("  3. 3 Browser Sekaligus (3x Lebih Cepat - Direkomendasikan)")
        print("  4. 4 Browser Sekaligus (4x Super Cepat)")
        print("=" * 65)
        try:
            w_in = input("Pilih jumlah browser paralel [1/2/3/4] (default: 3): ").strip()
            num_workers = int(w_in) if w_in in ["1", "2", "3", "4"] else 3
        except ValueError:
            num_workers = 3

    # Pilihan Metode Login Sebelum Browser Dibuka
    mau_login = False
    if not args.no_login:
        print("\n" + "=" * 65)
        print("                  PILIHAN METODE LOGIN")
        print("=" * 65)
        print("  1. Login Mode (Scan QR Code / Login Akun di Browser Utama)")
        print("  2. Tanpa Login / Guest Mode (Langsung Scraping Cepat)")
        print("=" * 65)
        pilihan_login = input("Pilih metode login [1/2] (default: 2): ").strip()
        mau_login = (pilihan_login == "1")

    # Inisialisasi Browser Master untuk Pencarian Video
    print(f"\n[*] Menjalankan browser master TikTok (Total Worker: {num_workers})...")
    try:
        driver_master, profile_dir = get_driver(worker_id=0)
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        if mau_login:
            login_via_qr(driver_master)
        else:
            print("[*] Mode Tanpa Login (Guest Mode) dipilih. Melanjutkan langsung...")

        print("\n" + "=" * 65)
        print("  [KONTROL JEDA AKTIF] KONTROL KEYBOARD INTERAKTIF:")
        print("  * Tekan tombol [P] atau [SPASI] di keyboard untuk MENJEDA (Pause) / MELANJUTKAN.")
        print("  * Tekan tombol [Q] di keyboard untuk BERHENTI & SIMPAN data yang sudah didapat.")
        print("=" * 65)

        # -------------------------------------------------------------
        # TAHAP 1: PENCARIAN & DEDUP VIDEO LENGKAP
        # -------------------------------------------------------------
        collected_videos = []
        if mode in ["1", "2"]:
            print(f"\n[*] Filter Periode Video : Minimal Tahun {min_post_year} ke atas (Video <= {min_post_year-1} dilewati otomatis)")
            for index, keyword in enumerate(keywords):
                if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                    break

                print(f"\n[{index+1}/{len(keywords)}] Memproses Keyword: '{keyword}'")
                safe_keyword = urllib.parse.quote(keyword)
                target_url = f"https://www.tiktok.com/search?q={safe_keyword}"
                
                driver_master.get(target_url)
                consecutive_empty_scrolls = 0
                max_empty_limit = 10
                is_searching = True
                pause_ctrl.sleep(3)
                ensure_page_loaded(driver_master, max_wait=8)
                
                scroll_count = 0
                while is_searching:
                    if not pause_ctrl.check_pause() or pause_ctrl.is_stopped():
                        break

                    scroll_count += 1
                    data_found_in_batch = False

                    # 1. Ekstrak dari Interceptor API
                    captured_data = driver_master.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
                    if captured_data:
                        for item in captured_data:
                            tipe = item.get('type')
                            payload = item.get('payload', {})
                            
                            if tipe in ['INTERCEPTED_FETCH', 'INTERCEPTED_XHR']:
                                data_asli = payload.get('data', {})
                                videos = []
                                if isinstance(data_asli, dict):
                                    if 'itemList' in data_asli and isinstance(data_asli['itemList'], list):
                                        videos = data_asli['itemList']
                                    elif 'data' in data_asli and isinstance(data_asli['data'], list):
                                        videos = data_asli['data']
                                    
                                if videos:
                                    for vid in videos:
                                        vid_obj = vid.get('item', vid) if isinstance(vid, dict) and 'type' in vid else vid
                                        if not isinstance(vid_obj, dict): continue

                                        vid_id = str(vid_obj.get('id', ''))
                                        if not vid_id: continue

                                        author_dict = vid_obj.get('author', {}) or {}
                                        author_nickname = author_dict.get('nickname', 'Unknown')
                                        author_unique_id = author_dict.get('uniqueId', 'Unknown')
                                        author_profile_url = f"https://www.tiktok.com/@{author_unique_id}" if author_unique_id and author_unique_id != 'Unknown' else ""
                                        author_bio = author_dict.get('signature', '') or ""

                                        author_stats = vid_obj.get('authorStats', {}) or author_dict.get('stats', {}) or {}
                                        followers_count = author_stats.get('followerCount', 0)
                                        following_count = author_stats.get('followingCount', 0)

                                        desc = (
                                            vid_obj.get('desc') or
                                            vid_obj.get('title') or
                                            vid_obj.get('caption') or
                                            (vid_obj.get('contents', [{}])[0].get('desc') if isinstance(vid_obj.get('contents'), list) and vid_obj.get('contents') else '') or
                                            (vid_obj.get('share_info', {}).get('share_desc') if isinstance(vid_obj.get('share_info'), dict) else '') or
                                            (vid_obj.get('share_info', {}).get('share_title') if isinstance(vid_obj.get('share_info'), dict) else '') or
                                            ""
                                        ).strip()
                                        stats = vid_obj.get('stats', {}) or vid_obj.get('statsV2', {}) or {}
                                        
                                        likes = stats.get('diggCount', 0)
                                        shares = stats.get('shareCount', 0)
                                        plays = stats.get('playCount', 0)
                                        comment_count = stats.get('commentCount', 0)

                                        # Subtitel
                                        video_meta = vid_obj.get('video', {}) or {}
                                        sub_infos = video_meta.get('subtitleInfos', []) or video_meta.get('claInfo', {}).get('captionInfos', []) or []
                                        subtitles_list = [f"{s.get('lang', '')}: {s.get('text', '')}".strip() for s in sub_infos if isinstance(s, dict)]
                                        video_subtitles = " | ".join(subtitles_list) if subtitles_list else ""

                                        # Hashtags
                                        text_extra = vid_obj.get('textExtra', []) or []
                                        tag_names = []
                                        for t_ext in text_extra:
                                            if isinstance(t_ext, dict) and t_ext.get('hashtagName'):
                                                tag_names.append(f"#{t_ext['hashtagName']}")
                                        challenges = vid_obj.get('challenges', []) or []
                                        for ch in challenges:
                                            if isinstance(ch, dict) and ch.get('title'):
                                                tag_names.append(f"#{ch['title']}")
                                        if not tag_names:
                                            hashtags_used = extract_hashtags(desc)
                                        else:
                                            seen_tags = set()
                                            dedup_tags = []
                                            for tag in tag_names:
                                                if tag.lower() not in seen_tags:
                                                    seen_tags.add(tag.lower())
                                                    dedup_tags.append(tag)
                                            hashtags_used = ", ".join(dedup_tags)

                                        text_language = detect_language(desc)

                                        # Ad / Pinned / Sponsored
                                        is_ad = "Yes" if (vid_obj.get('isAd') or vid_obj.get('is_ad') or vid_obj.get('ad_info') or vid_obj.get('is_ad_label')) else "No"
                                        is_pinned = "Yes" if (vid_obj.get('isTop') or vid_obj.get('isPinned')) else "No"
                                        is_sponsored = "Yes" if (vid_obj.get('isCommerce') or vid_obj.get('isItemCommerce') or vid_obj.get('isSponsored') or vid_obj.get('brandOrganicType') == 1) else "No"

                                        # Location
                                        poi = vid_obj.get('poi', {}) or {}
                                        location_of_creation = poi.get('name') or vid_obj.get('locationCreated', '') or ""

                                        # Music Meta
                                        music_dict = vid_obj.get('music', {}) or {}
                                        m_title = music_dict.get('title', '')
                                        m_author = music_dict.get('authorName', '')
                                        music_meta = f"{m_title} - {m_author}".strip(' -') if (m_title or m_author) else ""

                                        create_time_unix = vid_obj.get('createTime')
                                        upload_date = "Terkini"
                                        upload_year = None
                                        if create_time_unix:
                                            try:
                                                dt = datetime.fromtimestamp(int(create_time_unix))
                                                upload_date = dt.strftime('%Y-%m-%d %H:%M:%S')
                                                upload_year = dt.year
                                            except Exception:
                                                upload_date = "Error"

                                        # FILTER TAHUN: Lewati video usang (misal tahun 2024 atau lebih lama)
                                        if (upload_year and upload_year < min_post_year) or is_outdated_post(upload_date, min_year=min_post_year) or is_outdated_post(desc, min_year=min_post_year):
                                            print(f"    [DILEWATI] Video Usang ({upload_date}) @{author_unique_id}: \"{desc[:35]}...\" (Filter aktif: Hanya tahun {min_post_year}+)")
                                            continue

                                        # DEDUKPLIKASI KETAT: Cek apakah ID video sudah pernah ditemukan
                                        with seen_lock:
                                            if vid_id in global_seen_video_ids:
                                                continue
                                            global_seen_video_ids.add(vid_id)

                                        data_found_in_batch = True
                                        vid_url = f"https://www.tiktok.com/@{author_unique_id}/video/{vid_id}"
                                        
                                        save_to_csv(video_csv, [
                                            "TikTok", keyword, vid_id, upload_date, author_nickname,
                                            author_profile_url, author_bio, followers_count, following_count, "",
                                            "", desc, likes, shares, plays,
                                            comment_count, video_subtitles, text_language, hashtags_used,
                                            is_ad, is_pinned, is_sponsored, location_of_creation, music_meta, vid_url
                                        ])
                                        
                                        collected_videos.append({
                                            'video_id': vid_id,
                                            'video_url': vid_url,
                                            'keyword': keyword,
                                            'username': author_nickname,
                                            'description': desc
                                        })
                                        
                                        print(f"    + [#{len(global_seen_video_ids)}] [{upload_date}] {desc[:35]}... ({comment_count} komentar)")

                    # 2. Ekstrak Fallback dari DOM HTML
                    try:
                        dom_vids = driver_master.execute_script("""
                            let results = [];
                            let cards = document.querySelectorAll(
                                'div[data-e2e="search_top-item"], div[data-e2e="search_video-item"], div[class*="DivItemContainer"], [data-e2e="search-card-container"], div[class*="DivVideoCardContainer"], div[class*="DivItemContainerV2"], [data-e2e="search-common-link"]'
                            );
                            for (let c of cards) {
                                let link = c.querySelector('a[href*="/video/"]') || (c.tagName === 'A' && c.href && c.href.includes('/video/') ? c : null);
                                if (link && link.href) {
                                    let href = link.href;
                                    let vid_id = href.includes('/video/') ? href.split('/video/')[1].split('?')[0].split('/')[0] : '';
                                    let authorEl = c.querySelector('a[href*="/@"], [data-e2e="search-card-user-unique-id"], [data-e2e="search-card-user-link"], [data-e2e="search-card-user-name"]');
                                    let author = authorEl ? (authorEl.innerText || '').trim() : 'Unknown';
                                    let authorUrl = authorEl ? (authorEl.href || '') : '';

                                    // Multi-layer selector untuk ekstraksi caption/deskripsi postingan TikTok
                                    let desc = '';
                                    let descSelectors = [
                                        '[data-e2e="search-card-video-caption"]',
                                        '[data-e2e="search-card-desc"]',
                                        '[data-e2e="search_card_desc"]',
                                        '[data-e2e="video-desc"]',
                                        '[data-e2e="browse-video-desc"]',
                                        '[class*="DivVideoDesc"]',
                                        '[class*="PVideoDesc"]',
                                        '[class*="DivTextContainer"]',
                                        '[class*="SpanText"]',
                                        '[class*="video-desc"]',
                                        'h1'
                                    ];
                                    for (let sel of descSelectors) {
                                        let el = c.querySelector(sel);
                                        if (el) {
                                            let txt = (el.innerText || el.textContent || '').trim();
                                            if (txt.length > 0) { desc = txt; break; }
                                        }
                                    }
                                    if (!desc) {
                                        let titleAttr = link.getAttribute('title') || c.getAttribute('aria-label') || '';
                                        if (titleAttr && titleAttr.length > 3) desc = titleAttr.trim();
                                    }
                                    if (!desc) {
                                        let imgEl = c.querySelector('img[alt]');
                                        if (imgEl && imgEl.alt && !imgEl.alt.toLowerCase().includes('avatar') && !imgEl.alt.toLowerCase().includes('profile')) {
                                            desc = imgEl.alt.trim();
                                        }
                                    }

                                    let playsEl = c.querySelector('[data-e2e="video-views"], [class*="video-count"], [class*="play-count"]');
                                    let playsTxt = playsEl ? (playsEl.innerText || '').trim() : '0';
                                    let musicEl = c.querySelector('a[href*="/music/"], [data-e2e="search-card-music"]');
                                    let musicTxt = musicEl ? (musicEl.innerText || '').trim() : '';
                                    if (vid_id) {
                                        results.push({ id: vid_id, url: href, author: author, author_url: authorUrl, desc: desc, plays: playsTxt, music: musicTxt });
                                    }
                                }
                            }
                            return results;
                        """)
                        if dom_vids:
                            for dv in dom_vids:
                                d_id = str(dv.get('id', ''))
                                if not d_id: continue

                                d_author = dv.get('author', 'Unknown')
                                d_author_url = dv.get('author_url', '')
                                d_desc = dv.get('desc', '')
                                d_url = dv.get('url', '')
                                d_plays = dv.get('plays', 0)
                                d_music = dv.get('music', '')
                                d_tags = extract_hashtags(d_desc)
                                d_lang = detect_language(d_desc)

                                # FILTER TAHUN: Lewati video usang jika deskripsi memuat tahun lama
                                if is_outdated_post(d_desc, min_year=min_post_year):
                                    print(f"    [DILEWATI] Video Usang (DOM) @{d_author}: \"{d_desc[:35]}...\" (Filter aktif: Hanya tahun {min_post_year}+)")
                                    continue

                                # DEDUKPLIKASI KETAT
                                with seen_lock:
                                    if d_id in global_seen_video_ids:
                                        continue
                                    global_seen_video_ids.add(d_id)

                                data_found_in_batch = True
                                
                                save_to_csv(video_csv, [
                                    "TikTok", keyword, d_id, "Terkini", d_author,
                                    d_author_url, "", 0, 0, "",
                                    "", d_desc, 0, 0, d_plays,
                                    0, "", d_lang, d_tags,
                                    "No", "No", "No", "", d_music, d_url
                                ])
                                collected_videos.append({
                                    'video_id': d_id,
                                    'video_url': d_url,
                                    'keyword': keyword,
                                    'username': d_author,
                                    'description': d_desc
                                })
                                print(f"    + [#{len(global_seen_video_ids)}] [DOM] {d_desc[:35]}... (@{d_author})")
                    except Exception:
                        pass
                    except Exception:
                        pass

                    if max_videos_for_comments > 0 and len(global_seen_video_ids) >= max_videos_for_comments:
                        print(f"    [*] Target batas {max_videos_for_comments} video tercapai.")
                        break

                    if data_found_in_batch:
                        consecutive_empty_scrolls = 0
                    else:
                        consecutive_empty_scrolls += 1
                        if consecutive_empty_scrolls >= max_empty_limit:
                            print(f"    [*] Selesai ({max_empty_limit}x scroll berturut-turut tanpa video baru).")
                            break

                    dismiss_guest_popup(driver_master)
                    ensure_page_loaded(driver_master, max_wait=1.5)
                    
                    scroll_px = random.randint(1200, 1800)
                    perform_human_scroll(driver_master, scroll_px)

                    if scroll_count % 2 == 0:
                        try:
                            driver_master.execute_script("window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });")
                        except Exception:
                            pass

                    pause_ctrl.sleep(random.uniform(2.5, 3.8))
                
                print(f"    -> Selesai keyword '{keyword}'. Total ditemukan: {len(global_seen_video_ids)} video unik.")
                pause_ctrl.sleep(1.5)

    finally:
        # Tutup browser master pencarian sebelum meluncurkan worker komentar
        try:
            driver_master.quit()
        except Exception:
            pass

    # -------------------------------------------------------------
    # TAHAP 2: SCRAPING KOMENTAR MULTI-BROWSER (DEDUP TERJAMIN)
    # -------------------------------------------------------------
    target_videos_for_comments = []
    if mode == "2":
        target_videos_for_comments = collected_videos
    elif mode == "3":
        target_videos_for_comments = existing_videos

    if target_videos_for_comments and comment_csv:
        # 1. Deduplikasi total daftar video
        unique_targets = []
        seen_queue_ids = set()
        for v in target_videos_for_comments:
            v_id = str(v.get('video_id', '')).strip()
            if v_id and v_id not in seen_queue_ids:
                seen_queue_ids.add(v_id)
                unique_targets.append(v)

        if max_videos_for_comments > 0:
            unique_targets = unique_targets[:max_videos_for_comments]

        total_target_videos = len(unique_targets)

        # 2. AUTO-RESUME CHECKPOINT: Cek video mana saja yang sudah pernah di-scrape ke comment_csv
        already_scraped_ids = get_already_scraped_video_ids(comment_csv)
        pending_targets = [v for v in unique_targets if str(v.get('video_id', '')).strip() not in already_scraped_ids]
        already_done_count = total_target_videos - len(pending_targets)

        if already_done_count > 0:
            print("\n" + "=" * 65)
            print("  [RESUME CHECKPOINT AKTIF] Melanjutkan Sesi Scraping")
            print("=" * 65)
            print(f"  * Total Video Target       : {total_target_videos} video")
            print(f"  * Sudah Selesai Di-scrape  : {already_done_count} video")
            print(f"  * Sisa yang Akan Diproses  : {len(pending_targets)} video (Lanjut dari Video #{already_done_count + 1})")
            print(f"  * Browser Paralel          : {num_workers} browser")
            print(f"  * File Output Komentar     : {comment_csv}")
            print("=" * 65)
        else:
            print("\n" + "=" * 65)
            print(f"   MULAI SCRAPING KOMENTAR DENGAN {num_workers} BROWSER PARALEL")
            print(f"   * Total Video Target : {total_target_videos} video (Nol Duplikasi)")
            print(f"   * File Output CSV    : {comment_csv}")
            print("=" * 65)

        if not pending_targets:
            print(f"\n[INFO] Seluruh {total_target_videos} video sudah selesai di-scrape komentarnya ke '{comment_csv}'.")
        else:
            # 3. Isi Queue hanya dengan video yang BELUM di-scrape
            video_queue = queue.Queue()
            for v in pending_targets:
                video_queue.put(v)

            # 4. Jalankan Worker Threads dengan counter akurat
            counter_lock = threading.Lock()
            progress_dict = {'done': already_done_count}
            threads = []

            actual_workers = min(num_workers, len(pending_targets)) if len(pending_targets) > 0 else 1

            for w_idx in range(actual_workers):
                t = threading.Thread(
                    target=comment_scraping_worker,
                    args=(w_idx, video_queue, comment_csv, max_comments_per_video, total_target_videos, counter_lock, progress_dict),
                    daemon=True
                )
                threads.append(t)
                t.start()
                # Stagger startup browser 2.5 detik untuk menjaga stabilitas RAM & CPU
                time.sleep(2.5)

            # Tunggu semua antrean video selesai
            video_queue.join()
            for t in threads:
                t.join()

            print("\n" + "=" * 65)
            print(f" [SELESAI] Seluruh komentar ({total_target_videos} video) tersimpan di: {comment_csv}")
            print("=" * 65)

    print(f"\n" + "=" * 65)
    print("  [SELESAI PENUH] Scraping TikTok Berhasil Tuntas!")
    if video_csv and os.path.exists(video_csv):
        print(f"  * File Video Unik : {video_csv}")
    if comment_csv and os.path.exists(comment_csv):
        print(f"  * File Komentar   : {comment_csv}")
    print("  * Analisis Sentimen & Topik: Jalankan 'python app.py'")
    print("=" * 65)

if __name__ == "__main__":
    try:
        run_scraper()
    except KeyboardInterrupt:
        print("\n[!] Dihentikan oleh pengguna. Seluruh data yang sudah terambil aman di CSV.")