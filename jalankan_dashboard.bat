@echo off
title TikTok Sentiment AI Dashboard
cd /d "%~dp0"
set "PYTHON_CMD=python"
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (
    set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

echo ============================================================
echo   MENJALANKAN TIKTOK SENTIMENT DAN OPINION AI DASHBOARD
echo ============================================================
"%PYTHON_CMD%" app.py
pause
