@echo off
chcp 65001 >nul

REM 运行磁盘清理工具（不带参数进入交互模式）
cd /d "%~dp0"
python disk_cleaner.py %*

pause
