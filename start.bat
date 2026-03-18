@echo off
title Geo Photo v3
color 0A
echo ===================================================
echo   GEO PHOTO v3 - Demarrage automatique
echo ===================================================
echo.

:: Chemins
set ADB="C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
set MITMDUMP="%LOCALAPPDATA%\Python\pythoncore-3.14-64\Scripts\mitmdump.exe"
set SCRIPT_DIR=%~dp0

:: 1. Verifier Python
echo [1/6] Verification des dependances...
python -m pip install piexif pytz timezonefinder frida-tools geopy Pillow mitmproxy >nul 2>&1

:: 2. Verifier BlueStacks
echo [2/6] Verification BlueStacks...
%ADB% devices 2>nul | findstr "device" >nul
if errorlevel 1 (
    echo   ERREUR: BlueStacks non connecte. Lancez BlueStacks d'abord.
    pause
    exit /b 1
)
echo   BlueStacks connecte!

:: 3. Verifier Certificall et pict2cam
echo [3/6] Verification des apps...
%ADB% shell "pm list packages app.certificall" 2>nul | findstr "certificall" >nul
if errorlevel 1 (
    echo   ERREUR: Certificall non installe.
    echo   Installez: %ADB% install certificall_patched.apk
    pause
    exit /b 1
)
echo   Certificall: OK

%ADB% shell "pm list packages com.adriangl.pict2cam" 2>nul | findstr "pict2cam" >nul
if errorlevel 1 (
    echo   ATTENTION: pict2cam non installe.
)

:: 4. Configurer proxy et mock_location
echo [4/6] Configuration proxy + securite...
%ADB% shell "settings put global http_proxy 10.0.2.2:8888" >nul 2>&1
%ADB% shell "settings put secure mock_location 0" >nul 2>&1
%ADB% shell "chmod 755 /data/local/tmp" >nul 2>&1
echo   Proxy: 10.0.2.2:8888
echo   Mock location: OFF

:: 5. Lancer mitmproxy en arriere-plan
echo [5/6] Demarrage du proxy MITM...
taskkill /F /IM mitmdump.exe >nul 2>&1
timeout /t 1 /nobreak >nul
start "MITM Proxy" /min %MITMDUMP% --listen-host 0.0.0.0 --listen-port 8888 -s "%SCRIPT_DIR%mitm_script.py" --set block_global=false --ignore-hosts "(?!.*certificall)"
timeout /t 2 /nobreak >nul
echo   Proxy MITM demarre (port 8888)

:: 6. Lancer le dashboard
echo [6/6] Demarrage du dashboard...
echo.
echo ===================================================
echo   TOUT EST PRET !
echo   Dashboard: http://127.0.0.1:8420
echo.
echo   1. Cliquez sur la carte pour choisir la position
echo   2. Glissez une photo dans la zone d'upload
echo   3. Cliquez "Lancer Certificall"
echo   4. Dans l'app: photo via pict2cam
echo ===================================================
echo.

python "%SCRIPT_DIR%dashboard.py"

:: Nettoyage a la fermeture
echo.
echo Nettoyage...
taskkill /F /IM mitmdump.exe >nul 2>&1
%ADB% shell "settings put global http_proxy :0" >nul 2>&1
echo Proxy supprime. Au revoir!
pause
