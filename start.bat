@echo off
title Geo Photo v3
color 0A
echo ===================================================
echo   GEO PHOTO v3 - Demarrage
echo ===================================================
echo.

set ADB="C:\Program Files\BlueStacks_nxt\HD-Adb.exe"
set SCRIPT_DIR=%~dp0

:: Chercher mitmdump dans plusieurs emplacements
set MITMDUMP=
where mitmdump.exe >nul 2>&1 && for /f "delims=" %%i in ('where mitmdump.exe') do set MITMDUMP="%%i"
if not defined MITMDUMP if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\Scripts\mitmdump.exe" set MITMDUMP="%LOCALAPPDATA%\Python\pythoncore-3.14-64\Scripts\mitmdump.exe"
if not defined MITMDUMP if exist "%ProgramFiles%\mitmproxy\bin\mitmdump.exe" set MITMDUMP="%ProgramFiles%\mitmproxy\bin\mitmdump.exe"
if not defined MITMDUMP if exist "%LOCALAPPDATA%\Programs\Python\Python313\Scripts\mitmdump.exe" set MITMDUMP="%LOCALAPPDATA%\Programs\Python\Python313\Scripts\mitmdump.exe"
if not defined MITMDUMP if exist "%LOCALAPPDATA%\Programs\Python\Python312\Scripts\mitmdump.exe" set MITMDUMP="%LOCALAPPDATA%\Programs\Python\Python312\Scripts\mitmdump.exe"
if not defined MITMDUMP (
    echo   ERREUR: mitmdump.exe non trouve!
    echo   Installez mitmproxy: pip install mitmproxy
    pause
    exit /b 1
)

:: 1. Tout arreter proprement
echo [1/6] Nettoyage...
taskkill /F /IM mitmdump.exe >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: 2. Verifier BlueStacks
echo [2/6] Verification BlueStacks...
%ADB% devices 2>nul | findstr "device" >nul
if errorlevel 1 (
    echo   ERREUR: BlueStacks non connecte.
    pause
    exit /b 1
)
echo   BlueStacks OK

:: 3. Supprimer proxy + force stop app
echo [3/6] Reset...
%ADB% shell "settings put global http_proxy :0" >nul 2>&1
%ADB% shell "am force-stop app.certificall" >nul 2>&1
%ADB% shell "settings put secure mock_location 0" >nul 2>&1
timeout /t 2 /nobreak >nul

:: 4. Lancer mitmproxy
echo [4/6] Demarrage proxy MITM...
start "MITM Proxy" /min %MITMDUMP% --listen-host 0.0.0.0 --listen-port 8888 -s "%SCRIPT_DIR%mitm_script.py" --set block_global=false
timeout /t 3 /nobreak >nul

:: 5. Configurer proxy + lancer Certificall
echo [5/6] Configuration proxy + lancement Certificall...
%ADB% shell "settings put global http_proxy 10.0.2.2:8888" >nul 2>&1
timeout /t 1 /nobreak >nul
%ADB% shell "monkey -p app.certificall -c android.intent.category.LAUNCHER 1" >nul 2>&1

:: 6. Lancer le dashboard
echo [6/6] Demarrage dashboard...
echo.
echo ===================================================
echo   TOUT EST PRET !
echo   Dashboard: http://127.0.0.1:8420
echo.
echo   1. Cliquez sur la carte pour la position GPS
echo   2. Glissez une photo dans la zone d'upload
echo   3. Dans Certificall: photo via pict2cam
echo.
echo   Les erreurs reseau des autres apps sont normales.
echo   Ignorez-les, seul Certificall compte.
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
