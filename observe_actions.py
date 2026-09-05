import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import time
import json
import os
import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains

# Patch WinError 6 pada shutdown
uc.Chrome.__del__ = lambda self: None

# ==========================================
# JS DOM EVENT SPY & ACTION RECORDER
# ==========================================
JS_DOM_SPY = """
window._user_dom_events = [];

function recordEvent(type, details) {
    window._user_dom_events.push({
        timestamp: new Date().toLocaleTimeString(),
        type: type,
        details: details
    });
}

function getCssPath(el) {
    if (!(el instanceof Element)) return '';
    let path = [];
    while (el && el.nodeType === Node.ELEMENT_NODE) {
        let selector = el.nodeName.toLowerCase();
        if (el.id) {
            selector += '#' + el.id;
            path.unshift(selector);
            break;
        } else {
            let sib = el, nth = 1;
            while (sib = sib.previousElementSibling) {
                if (sib.nodeName.toLowerCase() === selector) nth++;
            }
            if (el.className && typeof el.className === 'string' && el.className.trim()) {
                let classes = el.className.trim().split(/\\s+/).slice(0, 2).join('.');
                if (classes) selector += '.' + classes;
            }
            if (nth > 1) selector += ':nth-of-type(' + nth + ')';
        }
        path.unshift(selector);
        el = el.parentNode;
    }
    return path.join(' > ');
}

function getXPath(el) {
    if (!(el instanceof Element)) return '';
    let path = '';
    while (el && el.nodeType === Node.ELEMENT_NODE) {
        let idx = 1;
        let sib = el.previousSibling;
        while (sib) {
            if (sib.nodeType === 1 && sib.tagName === el.tagName) idx++;
            sib = sib.previousSibling;
        }
        let tag = el.tagName.toLowerCase();
        let attr = '';
        if (el.getAttribute('role')) attr = `[@role="${el.getAttribute('role')}"]`;
        else if (el.getAttribute('aria-label')) attr = `[@aria-label="${el.getAttribute('aria-label')}"]`;
        path = '/' + tag + attr + '[' + idx + ']' + path;
        el = el.parentNode;
    }
    return path;
}

// 1. DENGARKAN SETIAP KLIK USER
document.addEventListener('click', function(e) {
    let target = e.target;
    let buttonEl = target.closest('button, [role="button"], a, div[role="article"], div[aria-label]') || target;
    
    let info = {
        tag: target.tagName,
        text: (target.innerText || target.textContent || '').trim().substring(0, 80),
        aria_label: target.getAttribute('aria-label') || buttonEl.getAttribute('aria-label') || '',
        role: target.getAttribute('role') || buttonEl.getAttribute('role') || '',
        css_selector: getCssPath(buttonEl),
        xpath: getXPath(buttonEl),
        in_dialog: !!target.closest('div[role="dialog"]'),
        parent_tag: target.parentElement ? target.parentElement.tagName : ''
    };
    
    recordEvent('CLICK', info);
}, true);

// 2. DENGARKAN SETIAP SCROLL USER
let lastScrollTime = 0;
document.addEventListener('scroll', function(e) {
    let now = Date.now();
    if (now - lastScrollTime < 800) return; // Debounce
    lastScrollTime = now;
    
    let target = e.target;
    let isDoc = (target === document || target === document.documentElement || target === document.body);
    let el = isDoc ? (document.scrollingElement || document.documentElement) : target;
    
    let info = {
        container_tag: isDoc ? 'WINDOW / DOCUMENT' : el.tagName,
        in_dialog: !!(el.closest && el.closest('div[role="dialog"]')),
        scroll_top: el.scrollTop || window.scrollY,
        scroll_height: el.scrollHeight,
        client_height: el.clientHeight,
        css_selector: isDoc ? 'window' : getCssPath(el)
    };
    
    recordEvent('SCROLL', info);
}, true);
"""

def find_binary(filenames, subdirs):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(base_dir)
    for d in [base_dir, parent_dir]:
        for subdir in subdirs:
            for fname in filenames:
                candidate = os.path.join(d, subdir, fname) if subdir else os.path.join(d, fname)
                if os.path.isfile(candidate):
                    return os.path.abspath(candidate)
    return None

def start_observer_session():
    print("=" * 70)
    print("      FACEBOOK ACTION RECORDER & DOM ACTIVITY OBSERVER")
    print("=" * 70)
    print("[*] Menyiapkan browser dengan profil login tersimpan...")

    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    chromedriver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    base_dir = os.path.dirname(os.path.abspath(__file__))
    profile_dir = os.path.join(base_dir, "facebook_chrome_profile")

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

    try:
        driver = uc.Chrome(**driver_kwargs)
        # Pasang DOM Spy via CDP
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": JS_DOM_SPY})
    except Exception as e:
        print(f"[ERROR] Gagal membuka browser: {e}")
        return

    try:
        print("\n[*] Membuka https://www.facebook.com ...")
        driver.get("https://www.facebook.com")
        time.sleep(3)

        print("\n" + "=" * 70)
        print(" >>> BROWSER AKTIF & AGENT SEDANG MENGAMATI SETIAP GERAKAN ANDA <<<")
        print("=" * 70)
        print("Silakan lakukan:")
        print(" 1. Cari kata kunci atau buka postingan Facebook mana saja.")
        print(" 2. Klik tombol komentar atau bagian manapun yang biasa Anda klik.")
        print(" 3. Lakukan scroll di area komentar yang Anda maksud.")
        print(" 4. Terminal ini akan MENCATAT SETIAP ELEMEN, CSS, & XPATH secara LIVE!")
        print("=" * 70)
        print(" Tekan Ctrl+C di terminal kapan saja untuk mengakhiri observasi.\n")

        recorded_actions = []

        while True:
            # Ambil data aktivitas DOM dari browser
            events = driver.execute_script("""
                let ev = window._user_dom_events || [];
                window._user_dom_events = [];
                return ev;
            """)

            if events:
                for ev in events:
                    recorded_actions.append(ev)
                    ev_type = ev.get('type')
                    dt = ev.get('details', {})
                    t_stamp = ev.get('timestamp')

                    if ev_type == 'CLICK':
                        print(f"[{t_stamp}] [KLIK TERDETEKSI]")
                        print(f"  ├─ Teks Elemen : \"{dt.get('text')}\"")
                        if dt.get('aria_label'):
                            print(f"  ├─ Aria-Label  : \"{dt.get('aria_label')}\"")
                        if dt.get('role'):
                            print(f"  ├─ Role        : \"{dt.get('role')}\"")
                        print(f"  ├─ Di Dalam Modal: {dt.get('in_dialog')}")
                        print(f"  ├─ CSS Selector: {dt.get('css_selector')}")
                        print(f"  └─ XPath       : {dt.get('xpath')}\n")

                    elif ev_type == 'SCROLL':
                        print(f"[{t_stamp}] [SCROLL TERDETEKSI]")
                        print(f"  ├─ Kontainer   : {dt.get('container_tag')}")
                        print(f"  ├─ Di Dalam Modal: {dt.get('in_dialog')}")
                        print(f"  ├─ Posisi Scroll: {dt.get('scroll_top')} / {dt.get('scroll_height')} px")
                        print(f"  └─ CSS Selector: {dt.get('css_selector')}\n")

            time.sleep(0.4)

    except KeyboardInterrupt:
        print("\n\n" + "=" * 70)
        print(f"[SELESAI] Sesi pengamatan selesai. Total {len(recorded_actions)} aksi berhasil dicatat.")
        # Simpan ke file JSON agar kita bisa pelajari polanya
        log_file = os.path.join(base_dir, "user_recorded_actions.json")
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(recorded_actions, f, indent=2, ensure_ascii=False)
        print(f"[*] Riwayat aksi disimpan ke: {log_file}")
        print("=" * 70)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == "__main__":
    start_observer_session()
