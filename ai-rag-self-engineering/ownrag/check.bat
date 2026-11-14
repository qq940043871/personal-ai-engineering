@echo off
REM ============================================================================
REM  ownrag 本地门禁（个人骨架版的"CI"：一个键跑完，红了不过夜）
REM
REM    check.bat           lint -> type -> test + coverage
REM    check.bat eval      以上三步 + 召回回归（要求 data/ownrag.db 已有 policy_v1 语料，
REM                        全新 clone 上必然 0 命中属正常，故默认不跑）
REM
REM  跑不过就修，别加 ignore —— 门禁一旦常红就没人看了。
REM ============================================================================
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set PY=python
set FAILED=0

echo.
echo [1/3] ruff check        （lint + 导入排序）
%PY% -m ruff check .
if errorlevel 1 set FAILED=1

echo.
echo [2/3] mypy              （类型检查，口径见 pyproject [tool.mypy]）
%PY% -m mypy
if errorlevel 1 set FAILED=1

echo.
echo [3/3] pytest + coverage （fail_under 见 pyproject [tool.coverage.report]）
%PY% -m pytest -q --cov=ownrag --cov-report=term
if errorlevel 1 set FAILED=1

if /i "%~1"=="eval" (
    echo.
    echo [eval]  召回回归      （判中率不到 100%% 即失败）
    %PY% scripts\eval_recall.py --qa data\eval\qa.example.jsonl --kb policy_v1
    if errorlevel 1 set FAILED=1
)

echo.
if "%FAILED%"=="1" (
    echo [ownrag] 门禁未通过：先修上面的红项再提交。
    exit /b 1
)

echo [ownrag] 门禁通过。
exit /b 0
