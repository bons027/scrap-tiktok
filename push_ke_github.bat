@echo off
title Sinkronisasi Update ke GitHub Ori
cd /d "%~dp0"

echo ============================================================
echo   SINKRONISASI UPDATE KE GITHUB ORI (pratamaaja239-star)
echo   Repositori: https://github.com/pratamaaja239-star/scrap-tiktok
echo ============================================================
echo.

:: Cari lokasi Git dari GitHub Desktop atau sistem PATH
for /d %%i in ("%LocalAppData%\GitHubDesktop\app-*") do (
    if exist "%%~i\resources\app\git\cmd\git.exe" (
        set "GIT_EXE=%%~i\resources\app\git\cmd\git.exe"
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
echo [*] Memastikan branch lokal aktif...
"%GIT_EXE%" checkout main

echo.
echo [*] Mengirim seluruh update ke GitHub Ori (pratamaaja239-star)...
"%GIT_EXE%" push origin main
"%GIT_EXE%" push origin feat/local-media-and-fb-fix

echo.
echo ============================================================
echo   Selesai! Seluruh update sudah tersinkron ke GitHub Ori:
echo   https://github.com/pratamaaja239-star/scrap-tiktok
echo.
echo   Catatan untuk akun bons027:
echo   Buka https://github.com/bons027/scrap-tiktok
echo   Lalu klik tombol "Sync fork" untuk update repository Anda.
echo ============================================================
pause
