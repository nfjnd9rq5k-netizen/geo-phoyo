@echo off
echo Arret de Geo Photo v3...
set ADB="C:\Program Files\BlueStacks_nxt\HD-Adb.exe"

:: Arreter le proxy
taskkill /F /IM mitmdump.exe >nul 2>&1
echo   Proxy MITM arrete

:: Arreter le dashboard
taskkill /F /IM python.exe >nul 2>&1
echo   Dashboard arrete

:: Supprimer le proxy de BlueStacks
%ADB% shell "settings put global http_proxy :0" >nul 2>&1
echo   Proxy BlueStacks supprime

echo.
echo Tout est arrete. BlueStacks fonctionne normalement.
pause
