@echo off
title Sistema Cafe - Produccion
chcp 65001 >nul

echo ============================================
echo    SISTEMA CAFE - Modo Produccion
echo ============================================
echo.

:: ── 1. Build del frontend (modo production) ──
echo [1/3] Construyendo frontend...
cd /d %~dp0frontend
call npm run build -- --mode production >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Fallo el build del frontend.
    echo  Asegurate de haber corrido "npm install" antes.
    pause
    exit /b 1
)
echo  OK - Frontend listo en dist/

:: ── 2. Obtener IP local ───────────────────────
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4" ^| findstr /v "127.0.0.1"') do (
    set LOCAL_IP=%%a
    goto :found_ip
)
:found_ip
set LOCAL_IP=%LOCAL_IP: =%

:: ── 3. Matar proceso previo en puerto 8000 ────
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 1 /nobreak >nul

:: ── 4. Arrancar backend ───────────────────────
echo [2/3] Iniciando servidor...
cd /d %~dp0backend

start "Sistema Cafe - Servidor" cmd /k "cd /d %~dp0backend && set ENV_FILE=.env.prod && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

timeout /t 4 /nobreak >nul

:: ── 5. Mostrar info ───────────────────────────
echo [3/3] Sistema listo.
echo.
echo ============================================
echo  URL para las baristas (mismo WiFi):
echo.
echo    http://%LOCAL_IP%:8000
echo.
echo  Comparte esta URL con las baristas.
echo  En Chrome: Menu > "Agregar a pantalla inicio"
echo ============================================
echo.
echo  Para detener: cierra la ventana "Sistema Cafe - Servidor"
echo.

start http://localhost:8000
pause
