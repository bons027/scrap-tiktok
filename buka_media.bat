@echo off
title Online Media & News Scraper (Portal Berita Indonesia)
cd /d "%~dp0"

echo ============================================================
echo   ONLINE MEDIA & NEWS SCRAPER (PORTAL BERITA INDONESIA)
echo   Format Standar 25 Kolom Terpadu (TikTok + Facebook + Media)
echo ============================================================
echo.

python news_scrap.py

echo.
echo ============================================================
echo   Scraping selesai atau dihentikan.
echo ============================================================
pause
