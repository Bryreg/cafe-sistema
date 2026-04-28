@echo off
title Sistema Cafe - DESARROLLO
color 0A

echo ============================================
echo   SISTEMA CAFE ^| Entorno: DESARROLLO
echo   Backend : http://localhost:8000
echo   Frontend: http://localhost:5174
echo ============================================
echo.

:: Matar procesos previos en estos puertos
powershell -Command "Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -Command "Get-NetTCPConnection -LocalPort 5174 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: Crear directorios de uploads si no existen
if not exist "%~dp0backend\uploads_dev" mkdir "%~dp0backend\uploads_dev"

:: Iniciar Backend DEV
echo [1/2] Backend DEV en puerto 8000...
start "Backend - DEV" cmd /k "cd /d %~dp0backend && set ENV_FILE=.env.dev && python -m uvicorn app.main:app --port 8000 --reload"

timeout /t 4 /nobreak >nul

:: Iniciar Frontend DEV
echo [2/2] Frontend DEV en puerto 5174...
start "Frontend - DEV" cmd /k "cd /d %~dp0frontend && npm run dev -- --mode development"

timeout /t 5 /nobreak >nul

start http://localhost:5174

echo.
echo [DEV] Sistema corriendo. Cierra las ventanas de cmd para detener.
