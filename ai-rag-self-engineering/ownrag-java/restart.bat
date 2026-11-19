@echo off
rem ownrag-java restart launcher (double-click friendly).
rem Usage: restart.bat [ -NoBuild ] [ -WithTests ] [ -Foreground ] [ -Port 8421 ]
rem Delegates to restart.ps1 with ExecutionPolicy Bypass.
chcp 65001 >nul
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart.ps1" %*
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo [restart.bat] restart failed, exit=%RC%
if "%~1"=="" pause
endlocal & exit /b %RC%
