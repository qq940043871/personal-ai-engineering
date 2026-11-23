@echo off
rem ownrag-java 文档统计回填（doc_stats）启动器。
rem 用法：
rem   backfill-doc-stats.bat                  rem dry-run：只算不写，看样例口径
rem   backfill-doc-stats.bat --apply          rem 真正写回 parse_reviews + report.json
rem   backfill-doc-stats.bat --doc <docId> --apply
rem   backfill-doc-stats.bat --help
rem 依赖 target\cp.txt（mvn dependency:build-classpath -Dmdep.outputFile=target/cp.txt 生成）。
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist "target\cp.txt" goto :nocp
if not exist "target\classes\com\ownrag\tools\BackfillDocStats.class" (
    echo [backfill] 编译中（mvn -o -q compile）...
    call mvn -o -q compile
    if errorlevel 1 goto :fail
)

set CP=
set /p CP=<"target\cp.txt"
java -cp "target\classes;%CP%" com.ownrag.tools.BackfillDocStats %*
set RC=%ERRORLEVEL%
if "%RC%"=="0" goto :done
echo [backfill] 退出码 %RC%
:done
endlocal & exit /b %RC%

:nocp
echo [backfill] 缺 target\cp.txt，先生成依赖清单：
echo     mvn -q dependency:build-classpath -Dmdep.outputFile=target/cp.txt
exit /b 1

:fail
echo [backfill] mvn compile 失败（先确保能正常构建再回填）
exit /b 1
