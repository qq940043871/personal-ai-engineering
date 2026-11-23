@echo off
chcp 65001 >nul
setlocal

rem ============================================================
rem  PDF / 扫描件 -> 结构化 Markdown（MinerU + 结构归一化）
rem
rem  用法：
rem    00_pdf_to_md_mineru.bat 结算细则.pdf
rem    00_pdf_to_md_mineru.bat 结算细则.pdf D:\out
rem    00_pdf_to_md_mineru.bat 结算细则.pdf D:\out vlm
rem    00_pdf_to_md_mineru.bat .\pdfs                目录批量
rem    也可以直接把 PDF 拖到这个 bat 图标上
rem
rem  参数：
rem    %1  必填  PDF 文件或含 PDF 的目录
rem    %2  可选  输出根目录（默认 <本目录>\mineru_out）
rem    %3  可选  解析后端 pipeline / vlm / auto（默认 pipeline）
rem ============================================================

rem ---- 按本机实际情况修改这两行 ----
set "MINERU_ENV=C:\Users\qq940\anaconda3\envs\mineru"
set "MINERU_EXE=%MINERU_ENV%\Scripts\mineru.exe"

rem ---- 以下一般不用改 ----
set "SCRIPT_DIR=%~dp0"
set "SCRIPT=%SCRIPT_DIR%00_pdf_to_md_mineru.py"
set "INPUT=%~1"
set "OUTDIR=%~2"
set "BACKEND=%~3"
set "BACKEND_ARG="

if defined BACKEND set "BACKEND_ARG=-b %BACKEND%"
if not defined OUTDIR set "OUTDIR=%SCRIPT_DIR%mineru_out"

if not defined INPUT goto :usage
if not exist "%INPUT%" goto :no_input
if not exist "%SCRIPT%" goto :no_script
if not exist "%MINERU_EXE%" goto :no_mineru

rem 让 mineru.exe 能找到所属 conda 环境的 DLL（torch / cudnn 等）
set "PATH=%MINERU_ENV%;%MINERU_ENV%\Scripts;%MINERU_ENV%\Library\bin;%PATH%"
set "PYTHONIOENCODING=utf-8"

rem 优先用 mineru 环境的 python（版本与 MinerU 对齐），否则回退系统 python
set "PY=%MINERU_ENV%\python.exe"
if not exist "%PY%" set "PY=python"

echo [信息] 输入     : %INPUT%
echo [信息] 输出根   : %OUTDIR%
echo [信息] 后端     : %BACKEND%
echo [信息] python   : %PY%
echo [信息] mineru   : %MINERU_EXE%
echo.

"%PY%" "%SCRIPT%" "%INPUT%" -o "%OUTDIR%" --mineru "%MINERU_EXE%" %BACKEND_ARG%
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [完成] 产物：%OUTDIR%\^<pdf名^>\^<pdf名^>_norm.md
    echo [下一步] python 02_add_split_to_periods.py ^<上面的_norm.md^> 1_1_new_process.md
) else (
    echo [失败] 退出码 %RC%，详见上面的错误输出。
)
goto :end

:usage
echo [用法] 把 PDF 拖到本文件上，或在命令行执行：
echo     %~nx0 ^<pdf或目录^> [输出目录] [pipeline^|vlm^|auto]
echo 示例：
echo     %~nx0 结算细则.pdf
echo     %~nx0 结算细则.pdf D:\out vlm
goto :end_fail

:no_input
echo [错误] 输入不存在：%INPUT%
goto :end_fail

:no_script
echo [错误] 找不到脚本：%SCRIPT%
goto :end_fail

:no_mineru
echo [错误] 找不到 mineru.exe：%MINERU_EXE%
echo        该 conda 环境可能已损坏（editable 安装的源码被移走）。
echo        修复：conda activate mineru ^&^& pip install -U "mineru[core]"
goto :end_fail

:end_fail
set "RC=1"

:end
if "%RC%"=="" set "RC=1"
endlocal & exit /b %RC%
