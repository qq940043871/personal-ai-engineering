@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   郑州发布 - 招聘信息监听流水线
echo ============================================================
echo.

set "PY="
if exist "%~dp0.venv\Scripts\python.exe" set "PY=%~dp0.venv\Scripts\python.exe"
if "%PY%"=="" if exist "C:\Users\qq940\anaconda3\python.exe" set "PY=C:\Users\qq940\anaconda3\python.exe"
if "%PY%"=="" (
  where python >nul 2>nul && set "PY=python"
)
if "%PY%"=="" (
  echo [错误] 没找到 Python。请先安装 Python 或修改本脚本里的 PY 路径。
  pause
  exit /b 1
)
echo [1/4] 使用解释器: %PY%

echo [2/4] 检查依赖...
"%PY%" -c "import feedparser,requests,bs4,yaml" 2>nul
if errorlevel 1 (
  echo       缺少依赖，正在安装（首次运行会慢一点）...
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [错误] 依赖安装失败，请检查网络。
    pause
    exit /b 1
  )
) else (
  echo       依赖齐全
)

echo [3/4] 读取配置...
if not exist "config.yaml" (
  echo [错误] 找不到 config.yaml
  pause
  exit /b 1
)

echo [4/4] 执行流水线...
echo.
"%PY%" -m src.pipeline
set "RC=%errorlevel%"

echo.
if "%RC%"=="0" (
  echo ============================================================
  echo   完成！日报已生成到 out\ 目录
  echo ============================================================
  for /f "delims=" %%f in ('dir /b /o-d "out\jobs_*.html" 2^>nul') do (
    start "" "out\%%f"
    goto :done
  )
) else (
  echo [失败] 流水线返回错误码 %RC%，请查看上方输出。
)
:done
pause
