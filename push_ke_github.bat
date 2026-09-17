@echo off
title Sinkronisasi Update ke GitHub
cd /d "%~dp0"

echo ============================================================
echo   SINKRONISASI UPDATE KE GITHUB
echo   - GitHub Ori  : https://github.com/pratamaaja239-star/scrap-tiktok
echo   - GitHub Fork : https://github.com/bons027/scrap-tiktok
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
echo Pilihan Target Sinkronisasi:
echo   [1] Singkronkan ke KEDUANYA (GitHub Ori + GitHub bons027) [DIREKOMENDASIKAN]
echo   [2] Singkronkan HANYA ke GitHub Ori
echo   [3] Singkronkan HANYA ke GitHub bons027
echo.
set /p choice="Pilihan (1/2/3) [Default: 1]: "

if "%choice%"=="" set choice=1

echo.
echo [*] Memastikan branch lokal aktif...
"%GIT_EXE%" checkout main

if "%choice%"=="2" goto SYNC_ORI
if "%choice%"=="3" goto SYNC_BONS

:SYNC_ALL
echo.
echo [*] 1/2 Mengirim update ke GitHub Ori (pratamaaja239-star)...
"%GIT_EXE%" push origin main
"%GIT_EXE%" push origin feat/local-media-and-fb-fix

echo.
echo [*] 2/2 Mengirim update ke GitHub bons027...
"%GIT_EXE%" push upstream main
"%GIT_EXE%" push upstream feat/local-media-and-fb-fix
goto SELESAI

:SYNC_ORI
echo.
echo [*] Mengirim update ke GitHub Ori (pratamaaja239-star)...
"%GIT_EXE%" push origin main
"%GIT_EXE%" push origin feat/local-media-and-fb-fix
goto SELESAI

:SYNC_BONS
echo.
echo [*] Mengirim update ke GitHub bons027...
"%GIT_EXE%" push upstream main
"%GIT_EXE%" push upstream feat/local-media-and-fb-fix
goto SELESAI

:SELESAI
echo.
echo ============================================================
echo   Sinkronisasi selesai!
echo   - Cek GitHub Ori : https://github.com/pratamaaja239-star/scrap-tiktok
echo   - Cek GitHub Fork: https://github.com/bons027/scrap-tiktok
echo ============================================================
pause
