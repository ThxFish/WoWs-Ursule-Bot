@echo off
setlocal

cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-windows.ps1"
set "URSULE_EXIT_CODE=%ERRORLEVEL%"

if not "%URSULE_EXIT_CODE%"=="0" (
    echo.
    echo Ursule Bot failed to start. See the error above for details.
    pause
)

exit /b %URSULE_EXIT_CODE%
