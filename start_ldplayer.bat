@echo off
title Geo Photo v3 - LDPlayer
color 0A
echo ===================================================
echo   GEO PHOTO v3 - Demarrage (LDPlayer)
echo ===================================================
echo.

set ADB="%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"
set SCRIPT_DIR=%~dp0

:: Chercher mitmdump
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

:: 1. Nettoyage
echo [1/6] Nettoyage...
taskkill /F /IM mitmdump.exe >nul 2>&1
taskkill /F /IM adb.exe >nul 2>&1
taskkill /F /IM HD-Adb.exe >nul 2>&1
timeout /t 2 /nobreak >nul

:: Demarrer ADB proprement
%ADB% start-server >nul 2>&1
timeout /t 2 /nobreak >nul

:: 2. Verifier LDPlayer
echo [2/6] Verification LDPlayer...
%ADB% devices 2>nul | findstr "device" >nul
if errorlevel 1 (
    echo   ERREUR: LDPlayer non connecte.
    echo   Lancez LDPlayer et activez ADB dans Parametres.
    pause
    exit /b 1
)
echo   LDPlayer OK

:: 3. Reset
echo [3/6] Reset...
%ADB% shell "settings put global http_proxy :0" >nul 2>&1
%ADB% shell "am force-stop app.certificall" >nul 2>&1
%ADB% shell "settings put secure mock_location 0" >nul 2>&1
timeout /t 2 /nobreak >nul

:: 4. Lancer mitmproxy
echo [4/7] Demarrage proxy MITM...
start "MITM Proxy" /min %MITMDUMP% --listen-host 0.0.0.0 --listen-port 8888 -s "%SCRIPT_DIR%mitm_script.py" --set block_global=false
timeout /t 3 /nobreak >nul

:: 5. Configurer proxy (detecter IP automatiquement)
echo [5/7] Configuration proxy...

:: Detecter l'IP du PC (adaptateur avec gateway = reseau actif)
set PC_IP=
for /f "usebackq tokens=*" %%i in (`powershell -NoProfile -Command "((Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway }).IPv4Address.IPAddress | Select-Object -First 1)"`) do set PC_IP=%%i
if not defined PC_IP (
    echo   ERREUR: IP non detectee automatiquement.
    set /p PC_IP="  Entrez l'IP du PC: "
)
echo   IP du PC detectee: %PC_IP%
%ADB% shell "settings put global http_proxy %PC_IP%:8888" >nul 2>&1

:: Simuler batterie debranchee (empeche le popup "accessoire USB non autorise")
:: L'app Certificall detecte isCharging et bloque l'interface. Ceci trompe getBatteryInfo().
%ADB% shell "dumpsys battery unplug" >nul 2>&1
%ADB% shell "dumpsys battery set status 3" >nul 2>&1
echo   Batterie simulee: debranchee (bypass popup USB)

:: 6. Push Frida hooks (OBLIGATOIRE avant de lancer Certificall)
echo [6/7] Push Frida hooks...
python "%SCRIPT_DIR%push_hooks.py"
timeout /t 1 /nobreak >nul

:: Lancer Certificall (Frida Gadget dans l'APK charge /data/local/tmp/frida_hooks.js)
echo   Lancement Certificall...
%ADB% shell "monkey -p app.certificall -c android.intent.category.LAUNCHER 1" >nul 2>&1

:: 7. Dashboard
echo [7/7] Demarrage dashboard...
echo.
echo ===================================================
echo   TOUT EST PRET ! (LDPlayer)
echo   Dashboard: http://127.0.0.1:8420
echo.
echo   1. Cliquez sur la carte pour la position GPS
echo   2. Glissez une photo dans la zone d'upload
echo   3. Dans Certificall: photo via pict2cam
echo ===================================================
echo.

python "%SCRIPT_DIR%dashboard.py"

:: Nettoyage
echo.
echo Nettoyage...
taskkill /F /IM mitmdump.exe >nul 2>&1
%ADB% shell "settings put global http_proxy :0" >nul 2>&1
%ADB% shell "dumpsys battery reset" >nul 2>&1
echo Proxy supprime. Au revoir!
pause
