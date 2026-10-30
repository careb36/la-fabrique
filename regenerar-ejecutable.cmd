@echo off
rem Regenera el ejecutable empaquetado del asistente (profesor3\dist) para que
rem lleve la apariencia actual. Se puede dejar abierto o cerrar al terminar.
chcp 65001 >nul
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0arrancar.ps1" -Recompilar -SoloCompilar %*
if errorlevel 1 (
    echo.
    echo La recompilacion termino con error. Pulsa una tecla para cerrar...
    pause >nul
) else (
    echo.
    echo Listo. El ejecutable esta en profesor3\dist\AI-Workspace.exe
    pause >nul
)
endlocal
