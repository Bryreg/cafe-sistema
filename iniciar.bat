@echo off
title Sistema Café

echo Iniciando Sistema Cafe...

:: Matar procesos viejos en los puertos
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force" >nul 2>&1

:: Iniciar Backend
echo [1/2] Iniciando backend...
start "Backend - Sistema Cafe" cmd /k "cd /d %~dp0backend && python -m uvicorn app.main:app --port 8000"

:: Esperar que el backend arranque
timeout /t 4 /nobreak >nul

:: Iniciar Frontend
echo [2/2] Iniciando frontend...
start "Frontend - Sistema Cafe" cmd /k "cd /d %~dp0frontend && npm run dev -- --port 5174"

:: Esperar que el frontend arranque
timeout /t 5 /nobreak >nul

:: Abrir navegador
echo Abriendo navegador...
start http://localhost:5174

echo.
echo Sistema Cafe corriendo:
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5174
echo.
echo Cierra las ventanas de cmd para detener los servidores.
