@echo off
title TikTok Profile & Comments Scraper
cd /d "%~dp0"
set "PYTHON_CMD=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

echo ============================================================
echo   MENJALANKAN TIKTOK PROFILE & COMMENTS SCRAPER
echo ============================================================
taskkill /f /im chromedriver.exe >nul 2>&1
"%PYTHON_CMD%" profile_scrap.py
pause
