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

# Folder output default untuk menyimpan seluruh file CSV hasil scraping
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

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
# 2. FUNGSI DRIVER & PERSISTENT PROFILE
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

def get_driver():
    """
    Inisialisasi browser undetected-chromedriver dengan profil permanen 'tiktok_chrome_profile'.
    Sesi login, cookies, dan token akan tersimpan permanen di profil ini.
    """
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, "tiktok_chrome_profile")
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
    # 1. Cek cookies resmi TikTok via Selenium (mampu membaca seluruh HttpOnly cookies)
    try:
        cookies = driver.get_cookies()
        session_keys = {'sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt', 'uid_tt_ss', 'passport_auth_status'}
        for c in cookies:
            if c.get('name') in session_keys and c.get('value'):
                return True
    except Exception:
        pass

    # 2. Cek elemen DOM di browser
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
    print("   ke folder 'tiktok_chrome_profile/' dan tidak perlu login lagi!")
    print("=" * 65)

    try:
        driver, profile_dir = get_driver()
        print(f"\n[*] Lokasi Profil Browser: {profile_dir}")
        print("[*] Membuka halaman login TikTok...")
        driver.get("https://www.tiktok.com/login")
        time.sleep(3)
        ensure_page_loaded(driver, max_wait=6)

        # Coba alihkan ke tab QR code jika tersedia
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
        max_login_wait = 180  # 3 menit

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

        print("\n[SELESAI] Setup sesi selesai. Anda sekarang siap menjalankan scraping TikTok!")

    except Exception as e:
        print(f"[ERROR] Terjadi kesalahan saat setup sesi: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

def login_via_qr(driver):
    """
    Mengecek apakah sesi login sudah aktif.
    Jika sudah login, langsung lanjut tanpa membuka halaman login.
    Jika belum, memberi opsi scan QR atau lanjut Guest Mode.
    """
    print("\n[*] Memeriksa status sesi login TikTok...")
    try:
        driver.get("https://www.tiktok.com")
        time.sleep(2.5)
        ensure_page_loaded(driver, max_wait=5)
        
        if is_user_logged_in(driver):
            print("[LOGIN] Sesi login tersimpan AKTIF terdeteksi! Melanjutkan pencarian...")
            return True
    except Exception:
        pass

    print("[LOGIN] Sesi login belum terdeteksi (Guest Mode aktif). Melanjutkan pencarian...")
    return True

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
                print("    [*] Terdeteksi tombol 'Try again' / 'Coba lagi'. Berhasil diklik otomatis!")
                time.sleep(3)
                return True
            elif status == 'OK':
                return True
        except Exception:
            pass
        time.sleep(1.5)

    if last_status == 'HAS_ERROR':
        print("    [!] Halaman masih menampilkan error. Melakukan refresh otomatis...")
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
# 4. FUNGSI CSV & OUTPUT PATHS
# ==========================================
def get_output_csv_paths(base_output_name):
    if not base_output_name:
        base_output_name = "tiktok_isu_daerah"
    if base_output_name.endswith(".csv"):
        base_output_name = base_output_name[:-4]

    # Tambahkan timestamp (tanggal & waktu) otomatis agar file unik dan tidak tertukar
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_with_time = f"{base_output_name}_{timestamp}"

    if os.path.isabs(base_output_name) or os.path.dirname(base_output_name):
        dir_name = os.path.dirname(base_output_name)
        base_file = os.path.basename(base_output_name)
        video_csv = os.path.join(dir_name, f"{base_file}_{timestamp}.csv")
        comment_csv = os.path.join(dir_name, f"{base_file}_{timestamp}_comments.csv")
    else:
        video_csv = os.path.join(RESULTS_DIR, f"{base_with_time}.csv")
        comment_csv = os.path.join(RESULTS_DIR, f"{base_with_time}_comments.csv")
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

def init_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['search_keyword', 'video_id', 'upload_date', 'username', 'description', 'play_count', 'digg_count', 'comment_count', 'video_url'])

def init_comments_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['video_id', 'search_keyword', 'comment_id', 'comment_date', 'username', 'nickname', 'comment_text', 'likes', 'reply_count', 'video_url'])

def save_to_csv(filename, data_row):
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(data_row)

def load_videos_from_csv(csv_path):
    if not os.path.exists(csv_path):
        # Coba cari di folder results/ jika tidak ada di root
        cand = os.path.join(RESULTS_DIR, csv_path)
        if os.path.exists(cand):
            csv_path = cand
        else:
            print(f"[ERROR] File {csv_path} tidak ditemukan!")
            return []

    videos = []
    with open(csv_path, mode='r', encoding='utf-8', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            vid_id = row.get('video_id', '').strip()
            vid_url = row.get('video_url', '').strip()
            kw = row.get('search_keyword', 'Unknown').strip()
            if vid_id and vid_url and vid_id.lower() != 'none':
                videos.append({
                    'video_id': vid_id,
                    'video_url': vid_url,
                    'keyword': kw,
                    'username': row.get('username', ''),
                    'description': row.get('description', '')
                })
    return videos

# ==========================================
# 5. FUNGSI SCRAPING KOMENTAR PER VIDEO
# ==========================================
def scrape_comments_for_video(driver, video_url, video_id, keyword, comments_csv, max_comments=50):
    if not video_url or not video_id:
        return 0
        
    print(f"\n  [KOMENTAR] Mengakses video ID {video_id}: {video_url}")
    driver.get(video_url)
    time.sleep(3)
    ensure_page_loaded(driver, max_wait=6)
    dismiss_guest_popup(driver)
    
    # 1. Pastikan tab/sidebar komentar terbuka
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
    time.sleep(2)
    
    seen_comment_ids = set()
    total_captured = 0
    empty_scrolls = 0
    api_finished = False
    
    max_scrolls = 200 if max_comments == 0 else max(5, (max_comments // 15) + 5)
    
    for scroll_idx in range(max_scrolls):
        dismiss_guest_popup(driver)
        new_in_batch = 0
        
        # 1. Ambil dari API interceptor
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
                                
                            save_to_csv(comments_csv, [
                                video_id, keyword, cid, cdate, uname, nname, txt, likes, replies, video_url
                            ])
                            new_in_batch += 1
                            total_captured += 1
                            print(f"      + [{cdate}] @{uname}: {txt[:40]}... (likes: {likes})")
                            
                            if max_comments > 0 and total_captured >= max_comments:
                                break
                                
                if max_comments > 0 and total_captured >= max_comments:
                    break

        # 2. Fallback DOM jika komentar tidak lewat API
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
                    save_to_csv(comments_csv, [
                        video_id, keyword, cid, "Unknown", c['username'], c['nickname'], c['text'], 0, 0, video_url
                    ])
                    new_in_batch += 1
                    total_captured += 1
                    print(f"      + [DOM] @{c['username']}: {c['text'][:40]}...")
                    if max_comments > 0 and total_captured >= max_comments:
                        break

        if max_comments > 0 and total_captured >= max_comments:
            print(f"    [!] Batas maksimal {max_comments} komentar tercapai.")
            break

        if api_finished and new_in_batch == 0:
            print("    [!] Semua komentar untuk video ini telah selesai dimuat (has_more=0).")
            break

        if new_in_batch == 0:
            empty_scrolls += 1
            if empty_scrolls >= 5:
                print("    [!] Selesai (5x scroll tidak menemukan komentar baru).")
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
        time.sleep(random.uniform(2.2, 3.5))

    print(f"    -> Selesai video {video_id}. Total {total_captured} komentar tersimpan.")
    return total_captured

# ==========================================
# 6. MENU UTAMA & LOGIKA SCRAPER
# ==========================================
def run_scraper():
    import argparse
    parser = argparse.ArgumentParser(description="TikTok Intelligence Scraper (Video & Komentar)")
    parser.add_argument("--mode", type=str, choices=["0", "1", "2", "3"], help="Mode scraper (0=Setup Sesi, 1=Video Saja, 2=Video+Komen, 3=Komen dari CSV)")
    parser.add_argument("--output", type=str, help="Nama dasar file output CSV")
    parser.add_argument("--keyword", type=str, help="Kata kunci tunggal pencarian")
    parser.add_argument("--max-comments", type=int, help="Maksimal komentar per video")
    parser.add_argument("--max-videos", type=int, help="Maksimal video yang diproses")
    parser.add_argument("--no-login", action="store_true", help="Gunakan Guest Mode (tanpa login)")
    args, unknown = parser.parse_known_args()

    mode = args.mode
    if not mode:
        print("=" * 65)
        print("       TIKTOK INTELLIGENCE SCRAPER (LOCAL SELENIUM)")
        print("=" * 65)
        print("PILIHAN MENU:")
        print("  0. Setup & Simpan Sesi Login TikTok (Cukup Login 1 Kali)")
        print("  1. Scrap Video Metadata Saja (Berdasarkan keywords.txt)")
        print("  2. Scrap Video + Komentar Sekaligus (Otomatis & Lengkap)")
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
                    max_vid_input = input("Maksimal video yang diambil komentarnya [0 untuk semua video] (default: 0): ").strip()
                    max_videos_for_comments = int(max_vid_input) if max_vid_input else 0
                except ValueError:
                    max_videos_for_comments = 0

    elif mode == "3":
        csv_source = input("Masukkan nama file CSV sumber video (default: data_tiktok.csv): ").strip() or "data_tiktok.csv"
        existing_videos = load_videos_from_csv(csv_source)
        if not existing_videos:
            return
            
        print(f"[*] Berhasil memuat {len(existing_videos)} video dari {csv_source}")
        prefix = os.path.splitext(os.path.basename(csv_source))[0]
        if not base_output_name:
            base_output_name = input(f"Nama file output komentar (default: {prefix}_comments): ").strip() or f"{prefix}_comments"
        
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

    # Inisialisasi Browser dengan Persistent Profile
    print("\n[*] Menjalankan browser TikTok...")
    try:
        driver, profile_dir = get_driver()
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        # Pengecekan Sesi Login
        if not args.no_login:
            login_via_qr(driver)
        else:
            print("[*] Mode Guest (Tanpa Login) aktif.")

        # MODE 1 & 2: Scraping Video
        collected_videos = []
        if mode in ["1", "2"]:
            for index, keyword in enumerate(keywords):
                print(f"\n[{index+1}/{len(keywords)}] Memproses Keyword: '{keyword}'")
                safe_keyword = urllib.parse.quote(keyword)
                target_url = f"https://www.tiktok.com/search?q={safe_keyword}"
                
                driver.get(target_url)
                seen_video_ids = set()
                consecutive_empty_scrolls = 0
                is_searching = True
                time.sleep(3)
                ensure_page_loaded(driver, max_wait=8)
                
                while is_searching:
                    captured_data = driver.execute_script("var d = window._scraped_data; window._scraped_data = []; return d;")
                    data_found_in_batch = False

                    if captured_data:
                        for item in captured_data:
                            tipe = item.get('type')
                            payload = item.get('payload', {})
                            
                            if tipe in ['INTERCEPTED_FETCH', 'INTERCEPTED_XHR']:
                                data_asli = payload.get('data', {})
                                
                                if isinstance(data_asli, dict):
                                    has_more = data_asli.get('has_more')
                                    if has_more == 0 or has_more is False:
                                        print("    [!] API: Data video pencarian habis (has_more=0).")
                                        is_searching = False
                                        
                                videos = []
                                if isinstance(data_asli, dict):
                                    if 'itemList' in data_asli:
                                        videos = data_asli['itemList']
                                    elif 'data' in data_asli and isinstance(data_asli['data'], list):
                                        videos = data_asli['data']
                                    
                                if videos:
                                    for vid in videos:
                                        vid_obj = vid.get('item', vid) if isinstance(vid, dict) and 'type' in vid else vid
                                        if not isinstance(vid_obj, dict): continue

                                        vid_id = str(vid_obj.get('id', ''))
                                        if not vid_id or vid_id in seen_video_ids: continue
                                        
                                        seen_video_ids.add(vid_id)
                                        data_found_in_batch = True
                                        
                                        author_nickname = vid_obj.get('author', {}).get('nickname', 'Unknown')
                                        author_unique_id = vid_obj.get('author', {}).get('uniqueId', 'Unknown')
                                        desc = vid_obj.get('desc', '')
                                        stats = vid_obj.get('stats', {})
                                        
                                        create_time_unix = vid_obj.get('createTime')
                                        try:
                                            upload_date = datetime.fromtimestamp(int(create_time_unix)).strftime('%Y-%m-%d %H:%M:%S') if create_time_unix else "Unknown"
                                        except Exception:
                                            upload_date = "Error"

                                        vid_url = f"https://www.tiktok.com/@{author_unique_id}/video/{vid_id}"
                                        
                                        save_to_csv(video_csv, [
                                            keyword, vid_id, upload_date, author_nickname, desc, 
                                            stats.get('playCount', 0), stats.get('diggCount', 0), 
                                            stats.get('commentCount', 0), vid_url
                                        ])
                                        
                                        collected_videos.append({
                                            'video_id': vid_id,
                                            'video_url': vid_url,
                                            'keyword': keyword,
                                            'username': author_nickname,
                                            'description': desc
                                        })
                                        
                                        print(f"    + [{upload_date}] {desc[:35]}... ({stats.get('commentCount', 0)} komentar)")

                    if not is_searching:
                        break

                    page_text = driver.execute_script("return document.body.innerText")
                    if "Tidak ada hasil lainnya" in page_text or "No more results" in page_text:
                        print("    [!] Visual: Text 'Tidak ada hasil' ditemukan.")
                        is_searching = False
                        break
                    
                    if data_found_in_batch:
                        consecutive_empty_scrolls = 0
                    else:
                        consecutive_empty_scrolls += 1
                        if consecutive_empty_scrolls >= 5:
                            print("    [!] Timeout: 5x Scroll kosong.")
                            is_searching = False
                            break

                    dismiss_guest_popup(driver)
                    ensure_page_loaded(driver, max_wait=2)
                    
                    scroll_px = random.randint(600, 1000)
                    perform_human_scroll(driver, scroll_px)

                    if random.random() < 0.25:
                        time.sleep(random.uniform(0.7, 1.2))
                        perform_human_scroll(driver, -random.randint(150, 250))

                    time.sleep(random.uniform(3.0, 4.8))
                
                print(f"    -> Selesai keyword '{keyword}'. Total video: {len(seen_video_ids)}")
                time.sleep(2)

        # Target video untuk komentar
        target_videos_for_comments = []
        if mode == "2":
            target_videos_for_comments = collected_videos
        elif mode == "3":
            target_videos_for_comments = existing_videos

        if target_videos_for_comments and comment_csv:
            if max_videos_for_comments > 0:
                target_videos_for_comments = target_videos_for_comments[:max_videos_for_comments]

            print("\n" + "=" * 65)
            print(f"  MULAI SCRAPING KOMENTAR UNTUK {len(target_videos_for_comments)} VIDEO")
            print("=" * 65)

            total_all_comments = 0
            for v_idx, v_data in enumerate(target_videos_for_comments):
                print(f"\n--- [{v_idx+1}/{len(target_videos_for_comments)}] Memproses Komentar Video ---")
                print(f"Judul/Deskripsi : {v_data.get('description', '')[:50]}...")
                v_count = scrape_comments_for_video(
                    driver=driver,
                    video_url=v_data['video_url'],
                    video_id=v_data['video_id'],
                    keyword=v_data.get('keyword', 'Unknown'),
                    comments_csv=comment_csv,
                    max_comments=max_comments_per_video
                )
                total_all_comments += v_count
                time.sleep(2)

            print("\n" + "=" * 65)
            print(f" [SELESAI] Total {total_all_comments} komentar berhasil disimpan ke {comment_csv}")
            print("=" * 65)

    except KeyboardInterrupt:
        print("\n[!] Dihentikan User.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print(f"\n" + "=" * 65)
        print("  [SELESAI] Hasil Scraping:")
        if video_csv and os.path.exists(video_csv):
            print(f"  * File Video    : {video_csv}")
        if comment_csv and os.path.exists(comment_csv):
            print(f"  * File Komentar : {comment_csv}")
        print("  * Analisis Sentimen & Topik: Jalankan 'python app.py'")
        print("=" * 65)

if __name__ == "__main__":
    run_scraper()