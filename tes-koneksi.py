import os
import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

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

def test_connection():
    print("=" * 50)
    print("      TES KONEKSI CHROME & CHROMEDRIVER LOKAL")
    print("=" * 50)
    
    chrome_path = find_binary(["chrome.exe"], ["chrome-win64", "chrome", ""])
    chromedriver_path = find_binary(["chromedriver.exe"], ["chromedriver-win64", "chromedriver", ""])
    
    print(f"[*] Path Chrome       : {chrome_path if chrome_path else 'Tidak ditemukan lokal (menggunakan default sistem)'}")
    print(f"[*] Path ChromeDriver : {chromedriver_path if chromedriver_path else 'Tidak ditemukan lokal (menggunakan default sistem)'}")
    
    options = Options()
    if chrome_path:
        options.binary_location = chrome_path
    
    # Argumen stabilitas
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    
    service = Service(executable_path=chromedriver_path) if chromedriver_path else Service()
    
    print("\n[1/3] Membuka browser Chrome...")
    driver = webdriver.Chrome(service=service, options=options)
    
    try:
        print("[2/3] Mengakses https://www.google.com...")
        driver.get("https://www.google.com")
        print(f"[+] Berhasil! Judul halaman: '{driver.title}'")
        
        print("\n[3/3] Mengakses https://www.tiktok.com...")
        driver.get("https://www.tiktok.com")
        print(f"[+] Berhasil membuka TikTok! Judul halaman: '{driver.title}'")
        
        print("\n" + "=" * 50)
        print(" SEMUA TES BERHASIL! Browser berjalan normal.")
        print("=" * 50)
        
        input("\nTekan Enter untuk menutup browser...")
    except Exception as e:
        print(f"\n[ERROR] Terjadi kesalahan: {e}")
    finally:
        driver.quit()
        print("[*] Browser ditutup.")

if __name__ == "__main__":
    test_connection()