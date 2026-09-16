@echo off
title Facebook Regional Intelligence Scraper
cd /d "%~dp0"
set "PYTHON_CMD=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

echo ============================================================
echo   MENJALANKAN FACEBOOK SCRAPER
echo ============================================================
taskkill /f /im chromedriver.exe >nul 2>&1
powershell -Command "Get-Process chrome -ErrorAction SilentlyContinue | Where-Object { $_.Path -like '*scrap-tiktok-main*' } | Stop-Process -Force" >nul 2>&1
"%PYTHON_CMD%" fb_scrap.py
pause
