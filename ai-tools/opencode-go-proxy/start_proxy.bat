@echo off
setlocal

REM ================================================================
REM   OpenCode Go  ->  WorkBuddy  -  Session-Header Inject Proxy
REM
REM   WHY THIS EXISTS
REM   OpenCode Go requires every request to carry the header
REM   "x-opencode-session". WorkBuddy cannot send custom headers,
REM   so it always gets HTTP 400 (MissingSessionID).
REM   This proxy injects the missing header for you.
REM
REM   KEEP THIS WINDOW OPEN while you use the model.
REM   Closing it stops the proxy and WorkBuddy will fail to connect.
REM
REM   If your API key leaked, rotate it in the OpenCode Console,
REM   then replace the value on the KEY line below.
REM ================================================================

set "OPENCODE_API_KEY=oc_sk_de841b233e97_L3wBR5Jm582tRbUmJFRGLhn5AO7LboN3"
set "LUNA_PROXY_PORT=8787"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if "%OPENCODE_API_KEY%"=="" (
    echo [ERROR] OPENCODE_API_KEY is empty. Edit this file and fill it in.
    pause
    exit /b 1
)

cd /d "%~dp0"

echo ================================================================
echo   Starting OpenCode Go proxy ...
echo   Keep this window OPEN. Close it to stop the proxy.
echo ================================================================
echo.

"C:\Users\qq940\.workbuddy\binaries\python\versions\3.13.12\python.exe" -u oc_session_proxy.py

echo.
echo Proxy exited.
pause
