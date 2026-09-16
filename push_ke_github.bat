@echo off
title Push Update ke GitHub (bons027/scrap-tiktok)
cd /d "%~dp0"

echo ============================================================
echo   PUSH UPDATE KE GITHUB (bons027/scrap-tiktok)
echo ============================================================
echo.

:: Cari lokasi Git dari GitHub Desktop
for /d %%i in ("%LocalAppData%\GitHubDesktop\app-*") do (
    if exist "%%i\resources\app\git\cmd\git.exe" (
        set "GIT_EXE=%%i\resources\app\git\cmd\git.exe"
    )
)

if not defined GIT_EXE (
    where git >nul 2>nul && set "GIT_EXE=git"
)

if not defined GIT_EXE (
    echo [!] Git tidak ditemukan. Silakan buka aplikasi GitHub Desktop.
    pause
    exit /b 1
)

echo Menggunakan Git: %GIT_EXE%
echo.
echo Pilihan Push:
echo   [1] Push ke branch 'feat/local-media-and-fb-fix' (Untuk Pull Request) - DIREKOMENDASIKAN
echo   [2] Push langsung ke branch 'main'
echo.
set /p choice="Pilihan (1/2) [Default: 1]: "

if "%choice%"=="2" (
    echo.
    echo [*] Melakukan push ke origin main...
    "%GIT_EXE%" checkout main
    "%GIT_EXE%" push -u origin main
) else (
    echo.
    echo [*] Melakukan push ke origin feat/local-media-and-fb-fix...
    "%GIT_EXE%" checkout feat/local-media-and-fb-fix
    "%GIT_EXE%" push -u origin feat/local-media-and-fb-fix
    echo.
    echo [*] Jika push berhasil, Anda dapat membuat Pull Request di tautan:
    echo     https://github.com/bons027/scrap-tiktok/pull/new/feat/local-media-and-fb-fix
)

echo.
pause
