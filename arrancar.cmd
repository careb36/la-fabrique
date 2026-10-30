@echo off
rem Consola en UTF-8 para que los acentos del lanzador se vean bien.
chcp 65001 >nul
rem Doble clic o cmd: delega en arrancar.ps1 sin tocar la politica de ejecucion.
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0arrancar.ps1" %*
if errorlevel 1 (
    echo.
    echo El arranque termino con error. Pulsa una tecla para cerrar...
    pause >nul
)
endlocal
