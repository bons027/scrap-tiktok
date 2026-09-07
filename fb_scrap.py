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


def extract_comments_from_json_tree(obj, results=None, parent_author=None, is_reply=False):
    """
    Mengekstrak komentar dan deep replies dari struktur pohon GraphQL secara rekursif.
    """
    if results is None:
        results = []

    if isinstance(obj, dict):
        if 'body' in obj and isinstance(obj['body'], dict) and 'text' in obj['body']:
            text = str(obj['body'].get('text', '')).strip()
            cid = str(obj.get('id', obj.get('legacy_token', '')))

            # Filter notifikasi ID & noise
            if not cid.startswith('bm90aWZpY2F0aW9u') and 'notification' not in cid.lower() and is_valid_comment_text(text) and not text.startswith("http"):
                author = 'Warga'
                if 'author' in obj and isinstance(obj['author'], dict):
                    author = obj['author'].get('name', 'Warga')
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
                    'comment_date': c_date,
                    'comment_text': text,
                    'likes': likes,
                    'reply_count': reply_count,
                    'is_reply': 'YA' if has_parent else 'TIDAK',
                    'reply_to': reply_to_target
                })

                # Jika komentar ini memiliki node balasan di dalamnya, traverse dengan menandai is_reply=True
                if 'feedback' in obj and isinstance(obj['feedback'], dict):
                    sub_replies = obj['feedback'].get('replies', {})
                    if isinstance(sub_replies, dict):
                        extract_comments_from_json_tree(sub_replies, results, parent_author=author, is_reply=True)

        for k, v in obj.items():
            if k != 'feedback':  # hindari double traversal jika sudah diproses
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


def get_driver():
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
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


def init_posts_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'search_keyword', 'post_id', 'post_date', 'author_name',
                'post_text', 'reactions_count', 'comments_count', 'shares_count', 'post_url'
            ])


def init_comments_csv(filename):
    if not os.path.isfile(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'post_id', 'search_keyword', 'comment_id', 'comment_date',
                'author_name', 'comment_text', 'likes', 'reply_count', 'is_reply', 'reply_to', 'post_url'
            ])


def save_to_csv(filename, data_row):
    with open(filename, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(data_row)


def perform_feed_scroll(driver, distance=650):
    """
    Scroll feed dengan fisika humanized acak untuk mencegah flag anti-bot.
    """
    steps = random.randint(3, 6)
    step_dist = distance / steps
    for _ in range(steps):
        try:
            ActionChains(driver).scroll_by_amount(0, int(step_dist)).perform()
        except Exception:
            pass
        try:
            driver.execute_script("""
                const dist = arguments[0];
                window.scrollBy(0, dist);
                if (document.documentElement) document.documentElement.scrollTop += dist;
                if (document.body) document.body.scrollTop += dist;
            """, step_dist)
        except Exception:
            pass
        time.sleep(random.uniform(0.04, 0.12))


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
    """
    # 1. Dari XHR/GraphQL Network (Termasuk child replies yang ter-intercept)
    net_comments = []
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

    # 2. Dari DOM dialog tengah (Mendeteksi struktur reply berjenjang)
    dom_comments = driver.execute_script("""
        let results = [];
        let scope = document.querySelector('div[role="dialog"]') || document;
        
        let commentElements = scope.querySelectorAll(
            'div[role="article"], div[aria-label*="Komentar oleh"], div[aria-label*="Comment by"], div[aria-label*="Komentar"], div[aria-label*="Comment"], div[class*="x1y1aw1k"], ul > li'
        );

        commentElements.forEach((el, idx) => {
            if (el.closest('[role="navigation"]') || el.closest('[aria-label*="Notifikasi"]')) return;

            let authorEl = el.querySelector('a span[dir="auto"], a strong, span > strong, strong');
            let author = authorEl ? authorEl.innerText.trim().split('\\n')[0] : 'Warga';

            let textEl = el.querySelector('div[dir="auto"][lang], div[dir="auto"]');
            let commentText = textEl ? textEl.innerText.trim() : '';

            if (commentText === author) {
                let altTextEls = el.querySelectorAll('div[dir="auto"]');
                if (altTextEls.length > 1) {
                    commentText = altTextEls[1].innerText.trim();
                }
            }

            let timeEl = el.querySelector('abbr, a[aria-label*="lalu"], a[aria-label*="ago"], span[id*="timestamp"]');
            let commentDate = timeEl ? (timeEl.getAttribute('aria-label') || timeEl.innerText || 'Terkini') : 'Terkini';

            // Ekstraksi Likes
            let likes = 0;
            let likeEl = el.querySelector('span[aria-label*="reaksi"], span[aria-label*="like"]');
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
            
            // Cek apakah bersarang di dalam article/list lain
            let parentArticle = el.parentElement ? el.parentElement.closest('div[role="article"], ul > li') : null;
            if (parentArticle && parentArticle !== el) {
                isReply = true;
                let pAuth = parentArticle.querySelector('a span[dir="auto"], strong');
                if (pAuth) replyTo = pAuth.innerText.trim().split('\\n')[0];
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

    combined = []
    for c in net_comments + (dom_comments or []):
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
        time.sleep(random.uniform(1.1, 1.6))

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
        time.sleep(random.uniform(1.3, 1.8))
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


def exhaustively_scroll_and_extract_comments(driver, max_idle_scrolls=4, max_total_comments_limit=500):
    """
    LANGKAH 4: Scroll kontainer komentar sampai HABIS dan membongkar semua deep replies:
    - Otomatis membuka semua thread balasan (Lihat balasan, Lihat balasan lainnya, View replies)
    - Melakukan scroll pada kontainer tengah dengan anti-bot wheel jitter
    - Mengumpulkan komentar utama dan balasan secara komprehensif
    - Selesai jika tidak ada komentar/balasan baru setelah beberapa putaran.
    """
    seen_in_this_post = set()
    collected_for_post = []
    consecutive_no_new = 0
    total_scrolls = 0
    max_scroll_limit = 50

    while consecutive_no_new < max_idle_scrolls and total_scrolls < max_scroll_limit:
        total_scrolls += 1

        # 1. Unfold semua thread balasan (deep replies) yang muncul di layar
        unfolded_replies = unfold_all_reply_threads(driver)
        if unfolded_replies > 0:
            time.sleep(random.uniform(1.2, 1.8))

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

        # 3. Scroll kontainer tengah dialog komentar dengan humanized jitter
        scroll_comment_container_center(driver, distance=random.randint(500, 650))
        time.sleep(random.uniform(1.6, 2.5))

        # 4. Ekstrak komentar & balasan yang baru masuk
        extracted = extract_comments_from_active_container(driver)
        new_found_this_step = 0

        for c in extracted:
            c_txt = c.get('comment_text', '').strip()
            if c_txt and c_txt not in seen_in_this_post:
                seen_in_this_post.add(c_txt)
                collected_for_post.append(c)
                new_found_this_step += 1
                c_author = c.get('author', 'Warga')
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

        if len(collected_for_post) >= max_total_comments_limit:
            break

    return collected_for_post


# Folder output default untuk menyimpan seluruh file CSV hasil scraping
RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


def get_output_csv_paths(base_output_name):
    if not base_output_name:
        base_output_name = "fb_isu_daerah"
    if base_output_name.endswith(".csv"):
        base_output_name = base_output_name[:-4]

    if os.path.isabs(base_output_name) or os.path.dirname(base_output_name):
        post_csv = f"{base_output_name}_posts.csv"
        comment_csv = f"{base_output_name}_comments.csv"
    else:
        post_csv = os.path.join(RESULTS_DIR, f"{base_output_name}_posts.csv")
        comment_csv = os.path.join(RESULTS_DIR, f"{base_output_name}_comments.csv")
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
        time.sleep(0.5)
    except Exception:
        pass

    try:
        has_dialog = driver.execute_script("return !!document.querySelector('div[role=\"dialog\"]');")
        if has_dialog:
            ActionChains(driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
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
                time.sleep(1.8)
            except Exception:
                pass
            # Jika setelah back masih belum kembali ke search, arahkan langsung ke search_url
            if '/permalink/' in driver.current_url or '/photo/' in driver.current_url or driver.current_url.rstrip('/') in ['https://www.facebook.com', 'https://web.facebook.com']:
                driver.get(search_url)
                time.sleep(2.5)


def apply_recent_posts_filter(driver, retries=3):
    """
    Mengaktifkan filter 'Terbaru' / 'Postingan terbaru' pada feed pencarian Facebook atau grup.
    Mendukung elemen switch presisi:
    <input role="switch" type="checkbox" aria-label="Terbaru" ...>
    """
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
                    time.sleep(2.5)  # Tunggu feed Facebook me-refresh postingan terbaru
                    return True

        except Exception as e:
            pass

        if attempt < retries - 1:
            time.sleep(1.2)

    return False


def process_search_workflow(driver, keyword, post_csv, comment_csv, max_posts=20, max_comments_per_post=150, custom_search_url=None, group_name=None):
    """
    Workflow 4 Langkah Berurutan (Post per Post):
    1. Buka Keyword di Facebook Search Feed / Group Search.
    2. Aktifkan Filter 'Postingan Terbaru'.
    3. Ambil postingan berikutnya di feed -> Klik Toggle Komentar (Bukan Permalink).
    4. Ubah filter 'Paling Relevan' menjadi 'Semua Komentar'.
    5. Scroll kontainer komentar & bongkar balasan sampai HABIS -> Simpan CSV -> Tutup Dialog / Kembali ke Search -> Lanjut Post Berikutnya!
    """
    processed_signatures = set()
    total_posts_saved = 0
    total_comments_saved = 0
    empty_scrolls = 0
    search_url = custom_search_url or f"https://www.facebook.com/search/posts/?q={urllib.parse.quote(keyword)}"

    title_info = f"Grup '{group_name}' | Kata Kunci: '{keyword}'" if group_name else f"Kata Kunci: '{keyword}'"
    print(f"\n" + "=" * 65)
    print(f"[*] LANGKAH 1: Memproses {title_info}")
    print(f"[*] Lokasi Penyimpanan Hasil:")
    print(f"    - Postingan: {post_csv}")
    print(f"    - Komentar : {comment_csv}")
    print("=" * 65)

    # Coba aktifkan filter 'Postingan Terbaru' jika tombol tersedia
    apply_recent_posts_filter(driver)

    while total_posts_saved < max_posts and empty_scrolls < 8:
        # Pastikan modal dialog tertutup dan tetap di halaman pencarian
        close_post_dialog(driver, search_url=search_url)

        # Cari postingan berikutnya yang belum diproses dari feed
        next_post = driver.execute_script("""
            let seenList = arguments[0];
            let feedNodes = document.querySelectorAll('div[role="feed"] > div, div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"]');

            for (let idx = 0; idx < feedNodes.length; idx++) {
                let p = feedNodes[idx];
                let textEl = p.querySelector('div[dir="auto"], div[data-ad-preview="message"], div[id*="post_message"]');
                let postText = textEl ? (textEl.innerText || '').trim() : '';

                if (postText.length > 8 && !postText.toLowerCase().startsWith('hasil untuk') && !postText.toLowerCase().startsWith('menampilkan hasil')) {
                    let author = 'Warga / Anonim';
                    let authorEl = p.querySelector('h2 strong, h3 strong, h4 strong, a strong, strong span, h2 a, h3 a, a[role="link"] span');
                    if (authorEl && authorEl.innerText) {
                        author = authorEl.innerText.trim().split('\\n')[0];
                    }

                    let timeEl = p.querySelector('abbr, a[aria-label*="lalu"], a[aria-label*="ago"], span[id*="timestamp"]');
                    let postDate = timeEl ? (timeEl.getAttribute('aria-label') || timeEl.innerText || 'Terkini') : 'Terkini';

                    let signature = author + ':::' + postText.substring(0, 45);

                    if (seenList.includes(signature)) {
                        continue;
                    }

                    let postUrl = '';
                    let postId = '';
                    let links = p.querySelectorAll('a[href*="/posts/"], a[href*="/permalink/"], a[href*="/videos/"], a[href*="/reel/"], a[href*="story_fbid="], a[href*="multi_permalinks="], a[href*="/groups/"], a[role="link"]');
                    for (let a of links) {
                        let href = a.href || '';
                        if (href.includes('/posts/') || href.includes('/permalink/') || href.includes('/videos/') || href.includes('story_fbid=') || href.includes('multi_permalinks=')) {
                            postUrl = href.split('?')[0];
                            let match = href.match(/(?:posts|permalink|videos|story_fbid=|multi_permalinks=)[/=?]?([0-9]+)/);
                            if (match && match[1]) postId = match[1];
                            break;
                        }
                    }

                    return {
                        dom_index: idx,
                        signature: signature,
                        post_id: postId || String(Math.abs(hashString(postText))),
                        author: author,
                        post_text: postText,
                        post_date: postDate,
                        post_url: postUrl || window.location.href
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
        """, list(processed_signatures))

        # Jika belum ada postingan baru di layar, scroll feed pencarian ke bawah
        if not next_post:
            empty_scrolls += 1
            perform_feed_scroll(driver, distance=650)
            time.sleep(random.uniform(2.0, 3.2))
            continue

        # Postingan baru ditemukan
        empty_scrolls = 0
        p_sig = next_post.get('signature')
        processed_signatures.add(p_sig)
        total_posts_saved += 1

        p_id = next_post.get('post_id')
        p_author = next_post.get('author')
        p_text = next_post.get('post_text')
        p_date = next_post.get('post_date')
        p_url = next_post.get('post_url')
        dom_idx = next_post.get('dom_index', 0)

        csv_keyword_label = f"[{group_name}] {keyword}" if group_name else keyword

        # Simpan metadata postingan
        save_to_csv(post_csv, [
            csv_keyword_label, p_id, p_date, p_author, p_text,
            0, 0, 0, p_url
        ])

        print("\n" + "=" * 65)
        print(f"[POST #{total_posts_saved}/{max_posts}] @{p_author} ({p_date})")
        print(f"  \"{p_text[:75]}...\"")
        print("  [*] LANGKAH 2: Klik Toggle Komentar...")

        # LANGKAH 2: KLIK TOGGLE KOMENTAR PADA POSTINGAN TERSEBUT SECARA PRESISI (HINDARI PERMALINK LINK)
        driver.execute_script("""
            let targetIdx = arguments[0];
            let feedNodes = document.querySelectorAll('div[role="feed"] > div, div[role="article"], div[data-ad-preview="message"], div[class*="x1yztbdb"]');
            let p = feedNodes[targetIdx];
            if (!p) return;

            p.scrollIntoView({ behavior: 'smooth', block: 'center' });

            // 1. Cari tombol komentar spesifik
            let clickTargets = p.querySelectorAll(
                'div[aria-label*="Komentar"], div[aria-label*="Comment"], div[aria-label*="komentar"], div[role="button"][tabindex="0"], span[dir="auto"]'
            );

            for (let el of clickTargets) {
                // Hindari mengklik link anchor yang membungkus ke permalink luar
                if (el.closest('a[href*="/permalink/"], a[href*="/posts/"], a[href*="/photo/"]')) {
                    continue;
                }
                let txt = (el.innerText || el.textContent || '').toLowerCase();
                let aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('komentar') || aria.includes('comment') || txt === 'komentar' || txt.includes('komentar') || txt.includes('balasan')) {
                    try { el.click(); return; } catch(e) {}
                }
            }

            // 2. Fallback: Cari tombol role="button" di bagian bawah kartu postingan (Action Bar)
            let bottomButtons = p.querySelectorAll('div[role="button"]');
            for (let b of bottomButtons) {
                let aria = (b.getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('komentar') || aria.includes('comment') || aria.includes('jawab')) {
                    try { b.click(); return; } catch(e) {}
                }
            }
        """, dom_idx)

        time.sleep(random.uniform(2.0, 2.8))

        # LANGKAH 3: UBAH FILTER MENJADI SEMUA KOMENTAR
        print("  [*] LANGKAH 3: Mengubah Filter Menjadi 'Semua Komentar'...")
        switch_filter_to_all_comments(driver)

        # LANGKAH 4: SCROLL SAMPAI HABIS & BONGKAR SEMUA BALASAN KOMENTAR
        print("  [*] LANGKAH 4: Scroll kontainer komentar & bongkar balasan...")
        post_comments = exhaustively_scroll_and_extract_comments(
            driver, max_idle_scrolls=4, max_total_comments_limit=max_comments_per_post
        )

        # Simpan seluruh komentar & balasan postingan ini ke CSV
        for c in post_comments:
            save_to_csv(comment_csv, [
                p_id, csv_keyword_label, c.get('comment_id'), c.get('comment_date'),
                c.get('author'), c.get('comment_text'), c.get('likes', 0),
                c.get('reply_count', 0), c.get('is_reply', 'TIDAK'), c.get('reply_to', ''), p_url
            ])
            total_comments_saved += 1

        print(f"  [+] Selesai Post #{total_posts_saved}. Total {len(post_comments)} komentar & balasan tersimpan!")

        # Tutup dialog postingan dan pastikan kembali ke feed pencarian (bukan tertahan di permalink)
        close_post_dialog(driver, search_url=search_url)
        time.sleep(0.8)
        # Scroll feed pencarian ke bawah sedikit untuk memuat postingan berikutnya
        perform_feed_scroll(driver, distance=400)
        time.sleep(1.2)

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

    comment_csv = os.path.join(RESULTS_DIR, f"{base_name}.csv")
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
                current_url = driver.current_url

                save_to_csv(comment_csv, [
                    "Live_Monitoring", "Manual_Browse", c_id, c_date,
                    c_author, c_text, c_likes, rep_cnt, is_rep, rep_to, current_url
                ])

                if is_rep == 'YA':
                    target_str = f" [Balasan ke @{rep_to}]" if rep_to else " [Balasan]"
                    print(f"   └──{target_str} [#{total_captured}] @{c_author}: \"{c_text}\" (likes: {c_likes})")
                else:
                    print(f"[#{total_captured}] @{c_author} ({c_date}): \"{c_text}\" (likes: {c_likes})")

            time.sleep(1.0)

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
                p_in = input("Maksimal postingan per kata kunci (default: 20): ").strip()
                max_posts_target = int(p_in) if p_in else 20
            except ValueError:
                max_posts_target = 20

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

    post_csv, comment_csv = get_output_csv_paths(base_output_name)
    init_posts_csv(post_csv)
    init_comments_csv(comment_csv)

    print("\n[*] Menjalankan browser Facebook...")
    try:
        driver, profile_dir = get_driver()
        driver.get("https://www.facebook.com")
        time.sleep(3)
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        if mode == "1":
            for kw in keywords:
                search_url = f"https://www.facebook.com/search/posts/?q={urllib.parse.quote(kw)}"
                driver.get(search_url)
                time.sleep(3.5)
                process_search_workflow(driver, kw, post_csv, comment_csv, max_posts=max_posts_target, max_comments_per_post=max_comments_limit)

        elif mode == "2":
            for grp in groups:
                grp_clean = grp.rstrip('/')
                grp_slug = grp_clean.split('/')[-1]

                # 1. Buka halaman utama grup terlebih dahulu
                print("\n" + "=" * 65)
                print(f"[*] MEMBUKA GRUP FACEBOOK: {grp_clean}")
                print("=" * 65)
                driver.get(grp_clean)
                time.sleep(3.5)

                for kw in keywords:
                    if kw == "Feed Terbaru":
                        target_url = f"{grp_clean}/?sorting_setting=CHRONOLOGICAL"
                        print(f"[*] Membuka Feed Kronologis Terbaru di grup '{grp_slug}'...")
                        driver.get(target_url)
                        time.sleep(3.5)
                        process_search_workflow(
                            driver, "Feed Terbaru", post_csv, comment_csv,
                            max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                            custom_search_url=target_url, group_name=grp_slug
                        )
                    else:
                        target_url = f"{grp_clean}/search/?q={urllib.parse.quote(kw)}"
                        print(f"[*] Melakukan pencarian '{kw}' di dalam grup '{grp_slug}'...")
                        driver.get(target_url)
                        time.sleep(3.5)
                        process_search_workflow(
                            driver, kw, post_csv, comment_csv,
                            max_posts=max_posts_target, max_comments_per_post=max_comments_limit,
                            custom_search_url=target_url, group_name=grp_slug
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


