@echo off
title Sistema Cafe - SANDBOX
color 0E

echo ============================================
echo   SISTEMA CAFE ^| Entorno: SANDBOX
echo   Backend : http://localhost:8001
echo   Frontend: http://localhost:5175
echo ============================================
echo.

:: Matar procesos previos en estos puertos
powershell -Command "Get-NetTCPConnection -LocalPort 8001 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -Command "Get-NetTCPConnection -LocalPort 5175 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: Crear directorios de uploads si no existen
if not exist "%~dp0backend\uploads_sandbox" mkdir "%~dp0backend\uploads_sandbox"

:: Iniciar Backend SANDBOX
echo [1/2] Backend SANDBOX en puerto 8001...
start "Backend - SANDBOX" cmd /k "cd /d %~dp0backend && set ENV_FILE=.env.sandbox && python -m uvicorn app.main:app --port 8001"

timeout /t 4 /nobreak >nul

:: Iniciar Frontend SANDBOX
echo [2/2] Frontend SANDBOX en puerto 5175...
start "Frontend - SANDBOX" cmd /k "cd /d %~dp0frontend && npm run dev -- --mode sandbox"

timeout /t 5 /nobreak >nul

start http://localhost:5175

echo.
echo [SANDBOX] Sistema corriendo. Cierra las ventanas de cmd para detener.
