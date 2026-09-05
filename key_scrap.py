import sys
# Pastikan encoding output terminal mendukung karakter UTF-8 / emoji
try:
    sys.stdout.reconfigure(encoding='utf-8')
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

# ==========================================
# 1. JAVASCRIPT INTERCEPTOR (FETCH & XHR)
# ==========================================
JS_INTERCEPTOR = """
window._scraped_data = [];
function pushData(type, payload) {
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
# 2. FUNGSI LOGIN, ERROR HANDLING & SCROLLING
# ==========================================
def ensure_page_loaded(driver, max_wait=8):
    """
    Memastikan halaman tidak macet di pesan error 'Unknown error' / 'Something went wrong'.
    Otomatis mencari dan mengklik tombol 'Try again' / 'Coba lagi' / 'Refresh'.
    Jika masih macet, melakukan refresh halaman secara otomatis.
    """
    start_time = time.time()
    last_status = 'OK'
    while time.time() - start_time < max_wait:
        try:
            status = driver.execute_script("""
                // 1. Cek tombol Try again / Coba lagi / Refresh
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
                
                // 2. Cek teks error pada halaman
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
    Melakukan scroll multi-metode:
    1. Real Mouse Wheel Action via Selenium ActionChains (sama persis seperti gerakan scroll mouse fisik).
    2. JS Container Scroll (mencari elemen dengan overflow-y / scrollHeight > clientHeight).
    3. Keyboard Page Down / Up jika jarak scroll besar.
    """
    # 1. Real Mouse Wheel (ActionChains) - meniru gerakan roda mouse fisik yang berhasil kamu lakukan manual
    try:
        ActionChains(driver).scroll_by_amount(0, distance).perform()
    except Exception:
        pass

    # 2. JS Scroll ke Window, Document, dan semua Container Div yang scrollable
    try:
        driver.execute_script("""
            const distance = arguments[0];
            // Coba scroll window & documentElement
            window.scrollBy(0, distance);
            if (document.documentElement) document.documentElement.scrollTop += distance;
            if (document.body) document.body.scrollTop += distance;

            // Cari semua container yang memiliki scroll (TikTok sering pakai container div tersendiri)
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

    # 3. Fallback Keyboard (Page Down / Page Up)
    try:
        if distance >= 500:
            ActionChains(driver).send_keys(Keys.PAGE_DOWN).perform()
        elif distance <= -150:
            ActionChains(driver).send_keys(Keys.PAGE_UP).perform()
    except Exception:
        pass

def login_via_qr(driver):
    """
    Mengecek apakah sesi login sudah aktif. Jika belum, membuka halaman login dan menunggu user scan QR.
    Sesi akan otomatis tersimpan di folder profil browser lokal.
    """
    print("\n[LOGIN] Memeriksa status sesi login TikTok...")
    try:
        driver.get("https://www.tiktok.com")
        time.sleep(3)
        ensure_page_loaded(driver, max_wait=6)
        
        is_logged_in = driver.execute_script("""
            return !!(
                document.querySelector('[data-e2e="profile-icon"]') || 
                document.querySelector('a[href*="/@"]') ||
                document.cookie.includes('sessionid')
            );
        """)
        if is_logged_in:
            print("[LOGIN] Sesi tersimpan ditemukan! Anda sudah dalam keadaan login.")
            return True
    except Exception:
        pass

    print("[LOGIN] Belum login. Mengarahkan ke halaman login TikTok...")
    driver.get("https://www.tiktok.com/login")
    ensure_page_loaded(driver, max_wait=6)

    try:
        try:
            qr_link = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((By.XPATH, "//*[contains(text(), 'Use QR code')]"))
            )
            qr_link.click()
            print("[LOGIN] Mode QR Code diaktifkan.")
        except Exception:
            print("[LOGIN] Sepertinya sudah di halaman QR Code.")

        print(">>> SILAKAN SCAN QR CODE DI LAYAR SEKARANG <<<")
        print(">>> Script akan menunggu sampai Anda berhasil login (maks 120 detik)... <<<")

        WebDriverWait(driver, 120).until(
            lambda d: "login" not in d.current_url
        )
        
        print("[LOGIN] Login Berhasil terdeteksi! Sesi tersimpan secara otomatis di profil.")
        time.sleep(5)
        return True
        
    except Exception as e:
        print(f"[ERROR] Gagal login atau waktu habis: {e}")
        return False

def dismiss_guest_popup(driver):
    """
    Menghancurkan popup/overlay login secara paksa menggunakan kombinasi ESC,
    penyembunyian elemen via CSS, dan membuka gembok scroll di body & html.
    """
    try:
        # 1. Cara Halus: Coba tekan tombol ESC terlebih dahulu
        try:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        except Exception:
            pass

        # 2. Cara JS: Sembunyikan backdrop/modal login & hilangkan overflow hidden
        driver.execute_script("""
            // Sembunyikan elemen overlay / dialog login
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

            // Buka paksa gembok scroll HANYA jika terkunci hidden (tanpa merusak layout)
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
# 3. FUNGSI BANTUAN BINARY & CSV
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

def load_keywords(filepath="keywords.txt"):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    full_path = os.path.join(base_dir, filepath) if not os.path.isabs(filepath) else filepath
    
    if not os.path.exists(full_path):
        print(f"[!] File {filepath} tidak ditemukan. Membuat template default...")
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write("# Masukkan 1 keyword per baris\nresep masakan\noutfit pria\n")
            
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
    """
    Membaca daftar video dari file CSV hasil scraping sebelumnya.
    """
    if not os.path.exists(csv_path):
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
# 4. FUNGSI SCRAPING KOMENTAR PER VIDEO
# ==========================================
def scrape_comments_for_video(driver, video_url, video_id, keyword, comments_csv, max_comments=50):
    """
    Mengambil komentar dari sebuah video TikTok via interceptor XHR/Fetch & fallback DOM.
    Mendukung scroll kontainer DivCommentMain untuk mengambil seluruh komentar (pagination tak terbatas).
    """
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
    
    # Tentukan batas maksimal scroll (jika 0 = ambil semua komentar sampai habis)
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
                        # Cek apakah server menyatakan sudah tidak ada komentar lagi
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
                            print(f"      + [{cdate}] @{uname}: {txt[:35]}... (likes: {likes})")
                            
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
                    print(f"      + [DOM] @{c['username']}: {c['text'][:35]}...")
                    if max_comments > 0 and total_captured >= max_comments:
                        break

        # Batas tercapai
        if max_comments > 0 and total_captured >= max_comments:
            print(f"    [!] Batas maksimal {max_comments} komentar tercapai.")
            break

        # Selesai jika API sudah tidak punya komentar lagi
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

        # Scroll kontainer DivCommentMain (kontainer scroll resmi komentar TikTok)
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
        time.sleep(random.uniform(2.5, 4.0))

    print(f"    -> Selesai video {video_id}. Total {total_captured} komentar tersimpan.")
    return total_captured

# ==========================================
# 5. LOGIKA UTAMA SCRAPER
# ==========================================
def run_scraper():
    print("=" * 60)
    print("       TIKTOK SCRAPER - VIDEO & KOMENTAR (LOCAL SELENIUM)")
    print("=" * 60)
    print("Pilih Mode Scraping:")
    print("  1. Scrap Video Metadata Saja (Cepat)")
    print("  2. Scrap Video + Komentar Sekaligus")
    print("  3. Scrap Komentar dari File CSV Video yang Sudah Ada")
    print("=" * 60)
    mode = input("Pilih mode [1/2/3] (default: 1): ").strip()
    if mode not in ["1", "2", "3"]:
        mode = "1"

    # Inisialisasi variabel
    keywords = []
    existing_videos = []
    base_output_name = "data_tiktok"
    video_csv = ""
    comment_csv = ""
    max_comments_per_video = 50
    max_videos_for_comments = 0

    if mode in ["1", "2"]:
        keywords = load_keywords("keywords.txt")
        if not keywords:
            print("[ERROR] Tidak ada keyword untuk diproses.")
            return
        print(f"\n[*] Berhasil memuat {len(keywords)} keyword: {', '.join(keywords)}")
        base_output_name = input("Masukkan nama dasar file output (default: data_tiktok): ").strip() or "data_tiktok"
        if base_output_name.endswith(".csv"):
            base_output_name = base_output_name[:-4]
            
        video_csv = f"{base_output_name}.csv"
        init_csv(video_csv)
        print(f"[*] Metadata video akan disimpan ke : {video_csv}")
        
        if mode == "2":
            comment_csv = f"{base_output_name}_comments.csv"
            init_comments_csv(comment_csv)
            print(f"[*] Komentar video akan disimpan ke : {comment_csv}")
            
            try:
                max_com_input = input("Maksimal komentar per video [contoh: 50, atau 0 untuk semua] (default: 50): ").strip()
                max_comments_per_video = int(max_com_input) if max_com_input else 50
            except ValueError:
                max_comments_per_video = 50
                
            try:
                max_vid_input = input("Maksimal video yang diambil komentarnya [0 untuk semua video] (default: 0): ").strip()
                max_videos_for_comments = int(max_vid_input) if max_vid_input else 0
            except ValueError:
                max_videos_for_comments = 0

    elif mode == "3":
        csv_source = input("Masukkan nama file CSV sumber video (default: tes.csv): ").strip() or "tes.csv"
        if not csv_source.endswith(".csv"):
            csv_source += ".csv"
        existing_videos = load_videos_from_csv(csv_source)
        if not existing_videos:
            print(f"[ERROR] Tidak ada video valid di {csv_source}")
            return
            
        print(f"[*] Berhasil memuat {len(existing_videos)} video dari {csv_source}")
        prefix = csv_source[:-4]
        comment_csv = input(f"Masukkan nama file CSV output komentar (default: {prefix}_comments.csv): ").strip() or f"{prefix}_comments.csv"
        if not comment_csv.endswith(".csv"):
            comment_csv += ".csv"
        init_comments_csv(comment_csv)
        print(f"[*] Komentar akan disimpan ke: {comment_csv}")
        
        try:
            max_com_input = input("Maksimal komentar per video [contoh: 50, atau 0 untuk semua] (default: 50): ").strip()
            max_comments_per_video = int(max_com_input) if max_com_input else 50
        except ValueError:
            max_comments_per_video = 50
            
        try:
            max_vid_input = input(f"Maksimal video yang diproses [1-{len(existing_videos)}, atau 0 untuk semua] (default: 0): ").strip()
            max_videos_for_comments = int(max_vid_input) if max_vid_input else 0
        except ValueError:
            max_videos_for_comments = 0

    # Pilihan Login
    print("\n" + "=" * 60)
    print("                   PILIHAN METODE LOGIN")
    print("=" * 60)
    print("  1. Login Mode (Gunakan Profil/Sesi Tersimpan / Scan QR) [Direkomendasikan]")
    print("  2. Tanpa Login / Guest Mode (Langsung scraping)")
    print("=" * 60)
    pilihan_login = input("Pilih metode login [1/2] (default: 1): ").strip()
    mau_login = (pilihan_login != "2")

    # Deteksi binary lokal
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    chromedriver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    
    print(f"\n[*] Chrome binary       : {chrome_path or 'Default Sistem'}")
    print(f"[*] ChromeDriver binary : {chromedriver_path or 'Default Sistem'}")

    # Setup Chrome Options & Persistent Profile
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, "tiktok_chrome_profile")
    os.makedirs(profile_dir, exist_ok=True)
    print(f"[*] Chrome Profile dir  : {profile_dir}")

    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    
    driver_kwargs = {
        "options": options,
        "user_data_dir": profile_dir
    }
    if chrome_path:
        driver_kwargs["browser_executable_path"] = chrome_path
    if chromedriver_path:
        driver_kwargs["driver_executable_path"] = chromedriver_path

    print("\n[*] Menjalankan browser TikTok...")
    driver = uc.Chrome(**driver_kwargs)

    try:
        # Pasang Interceptor
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": JS_INTERCEPTOR})
        
        # Login atau Guest Mode
        if mau_login:
            login_via_qr(driver)
        else:
            print("[*] Mode Tanpa Login dipilih. Melanjutkan langsung...")
            time.sleep(2)

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
                                        
                                        print(f"    + [{upload_date}] {desc[:30]}... ({stats.get('commentCount', 0)} komentar)")

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
                    
                    # Human Jitter Multi-Method Scroll (Real Mouse Wheel + JS Container + Keyboard)
                    scroll_px = random.randint(600, 1000)
                    perform_human_scroll(driver, scroll_px)

                    # 25% kemungkinan scroll sedikit ke atas (seperti membaca sekilas)
                    if random.random() < 0.25:
                        time.sleep(random.uniform(0.7, 1.2))
                        perform_human_scroll(driver, -random.randint(150, 250))

                    # Delay acak yang lebih natural
                    time.sleep(random.uniform(3.5, 5.5))
                
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

            print("\n" + "=" * 60)
            print(f"  MULAI SCRAPING KOMENTAR UNTUK {len(target_videos_for_comments)} VIDEO")
            print("=" * 60)

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

            print("\n" + "=" * 60)
            print(f" [SELESAI] Total {total_all_comments} komentar berhasil disimpan ke {comment_csv}")
            print("=" * 60)

    except KeyboardInterrupt:
        print("\n[!] Dihentikan User.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
        print(f"\n[!] Selesai. Hasil scraping:")
        if video_csv and os.path.exists(video_csv):
            print(f"  - File Video    : {video_csv}")
        if comment_csv and os.path.exists(comment_csv):
            print(f"  - File Komentar : {comment_csv}")

if __name__ == "__main__":
    run_scraper()