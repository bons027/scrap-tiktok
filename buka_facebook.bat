@echo off
title Buka Browser Facebook (Profil & Cookies Scraper)
cd /d "%~dp0"

echo ============================================================
echo   MEMBUKA BROWSER DENGAN COOKIES FACEBOOK SCRAPER
echo ============================================================
echo Lokasi Profil: %~dp0facebook_chrome_profile
echo.

if exist "%~dp0chrome-win64\chrome.exe" (
    start "" "%~dp0chrome-win64\chrome.exe" --user-data-dir="%~dp0facebook_chrome_profile" --no-first-run --no-default-browser-check "https://www.facebook.com"
) else if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="%~dp0facebook_chrome_profile" --no-first-run --no-default-browser-check "https://www.facebook.com"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" --user-data-dir="%~dp0facebook_chrome_profile" --no-first-run --no-default-browser-check "https://www.facebook.com"
) else (
    echo [!] Chrome tidak ditemukan otomatis. Menjalankan lewat Python...
    python -c "import undetected_chromedriver as uc; uc.Chrome(user_data_dir=r'%~dp0facebook_chrome_profile').get('https://www.facebook.com'); input('Tekan Enter untuk tutup...')"
)

echo Browser berhasil dibuka!
