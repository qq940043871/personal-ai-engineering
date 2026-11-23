@echo off
chcp 65001 >nul
setlocal
title Dify 1.20.0 知识库上传工具
cd /d "%~dp0"

set "SCRIPT=%~dp0dify_uploader_v120.py"
if not exist "%SCRIPT%" (
    echo [ERROR] 找不到 dify_uploader_v120.py，请把本脚本放在同一目录
    pause
    exit /b 1
)

rem ================= 1. 定位 Python =================
set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if not defined PY if exist "%~dp0..\..\.venv\Scripts\python.exe" set "PY=%~dp0..\..\.venv\Scripts\python.exe"
if not defined PY (
    for /f "delims=" %%P in ('where python 2^>nul') do (
        if not defined PY set "PY=%%P"
    )
)
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [ERROR] 没找到 Python。请先安装 Python 3.9+ 并勾选 "Add python.exe to PATH"
    pause
    exit /b 1
)

rem ================= 2. 依赖自检 =================
echo [INFO] 解释器：%PY%
"%PY%" -c "import sys;print('[INFO] Python', sys.version.split()[0])" || goto :err

"%PY%" -c "import tkinter" 2>nul || (
    echo [ERROR] 当前 Python 未包含 tkinter，无法启动图形界面
    pause
    exit /b 1
)

"%PY%" -c "import requests" 2>nul || (
    echo [WARN] 缺少 requests，正在安装...
    "%PY%" -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple requests || goto :err
)

rem ================= 3. 仅自检（start_dify_v120.bat --check） =================
if /i "%~1"=="--check" (
    "%PY%" -c "from dify_uploader_v120 import DifyUploaderApp, DifyClient; print('[OK] 模块导入正常')" || goto :err
    echo [OK] 环境自检通过
    exit /b 0
)

rem ================= 4. 启动界面（优先 pythonw，无黑窗） =================
set "PYW="
for %%I in ("%PY%") do (
    if exist "%%~dpIpythonw.exe" set "PYW=%%~dpIpythonw.exe"
)
if defined PYW (
    start "" "%PYW%" "%SCRIPT%"
) else (
    start "" "%PY%" "%SCRIPT%"
)
echo [OK] 已启动 Dify 1.20.0 知识库上传工具
timeout /t 2 >nul
exit /b 0

:err
echo.
echo [ERROR] 执行失败，错误码 %errorlevel%
pause
exit /b 1
