@echo off
title Sistema Cafe - PRODUCCION
color 0F

echo ============================================
echo   SISTEMA CAFE ^| Entorno: PRODUCCION
echo   Backend : http://localhost:8002
echo   Frontend: http://localhost:5176
echo ============================================
echo.

:: IMPORTANTE: Editar backend\.env.prod y cambiar SECRET_KEY antes de entregar al cliente

:: Matar procesos previos en estos puertos
powershell -Command "Get-NetTCPConnection -LocalPort 8002 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
powershell -Command "Get-NetTCPConnection -LocalPort 5176 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

:: Crear directorios de uploads si no existen
if not exist "%~dp0backend\uploads" mkdir "%~dp0backend\uploads"

:: Iniciar Backend PROD
echo [1/3] Backend PRODUCCION en puerto 8002...
start "Backend - MASTER" cmd /k "cd /d %~dp0backend && set ENV_FILE=.env.prod && python -m uvicorn app.main:app --port 8002"

timeout /t 4 /nobreak >nul

:: Build y serve del frontend en modo produccion
echo [2/3] Compilando frontend...
cd /d %~dp0frontend
call npm run build -- --mode production

echo [3/3] Iniciando servidor de produccion...
start "Frontend - MASTER" cmd /k "cd /d %~dp0frontend && npm run preview -- --mode production"

timeout /t 4 /nobreak >nul

start http://localhost:5176

echo.
echo [MASTER] Sistema de produccion corriendo.
echo Cierra las ventanas de cmd para detener.
