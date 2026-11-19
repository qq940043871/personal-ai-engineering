# ownrag-java 一键重启脚本（Windows / PowerShell）
#
# 用法（在本目录下）：
#   .\restart.ps1                  # 打包（跳过测试）→ 停旧实例 → 起新实例 → 等 /health
#   .\restart.ps1 -WithTests       # 打包前先跑全量测试（60 例）
#   .\restart.ps1 -NoBuild         # 不改代码，只重启（复用现有 jar，秒级）
#   .\restart.ps1 -Foreground      # 前台运行，日志直接打在当前控制台（Ctrl+C 退出）
#   .\restart.ps1 -Port 8421       # 换端口
#   双击 restart.bat 效果等同 .\restart.ps1
#
# 为什么先打包再停旧实例：构建失败时不会留下"旧的已经杀掉、新的起不来"的空窗。
# 日志：logs\app-<时间戳>.log（Spring 自己写，UTF-8，绕开 PowerShell 重定向的中文乱码问题）

[CmdletBinding()]
param(
    [int]$Port = 8420,
    [switch]$NoBuild,
    [switch]$WithTests,
    [switch]$Foreground,
    [int]$TimeoutSec = 120
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
if (-not $root) { $root = (Get-Location).Path }
Push-Location $root

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Warn($msg) { Write-Host "!!  $msg" -ForegroundColor Yellow }
function Write-Ok($msg)   { Write-Host "OK  $msg" -ForegroundColor Green }

# ---------------------------------------------------------------- 1. 定位 jar
function Get-AppJar {
    $jar = Get-ChildItem (Join-Path $root 'target') -Filter 'ownrag-java-*.jar' -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -notlike '*.original' } |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($jar) { return $jar.FullName }
    return $null
}

# ---------------------------------------------------------------- 2. 构建
if (-not $NoBuild) {
    if (-not (Get-Command mvn -ErrorAction SilentlyContinue)) {
        Write-Warn '找不到 mvn，无法构建；请先装 Maven 或改用 -NoBuild'
        exit 1
    }
    $mvnArgs = @('-B', '-q')
    if (-not $WithTests) { $mvnArgs += '-DskipTests' }
    $mvnArgs += 'package'
    Write-Step ("构建：mvn " + ($mvnArgs -join ' '))
    & mvn @mvnArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "构建失败（exit $LASTEXITCODE）：旧实例未动，继续用当前跑的版本"
        Pop-Location; exit 1
    }
    Write-Ok '构建完成'
} else {
    Write-Step '跳过构建（-NoBuild）'
}

$jarPath = Get-AppJar
if (-not $jarPath) {
    Write-Warn 'target 下没有 ownrag-java-*.jar；去掉 -NoBuild 重新构建'
    Pop-Location; exit 1
}

# ---------------------------------------------------------------- 3. 停旧实例（按端口找监听者，比记 PID 稳）
function Get-PortOwners([int]$p) {
    $owners = @()
    $tcp = Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue
    if ($tcp) {
        $owners = @(Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique)
    } else {
        # 老系统兜底：netstat 第 5 列是 PID
        $owners = @(netstat -ano | Select-String ":$p\s+.*LISTENING" |
            ForEach-Object { ($_ -split '\s+')[-1] } | Sort-Object -Unique)
    }
    return @($owners | Where-Object { $_ -and $_ -ne 0 -and $_ -ne $PID })
}

$owners = Get-PortOwners $Port
if ($owners.Count -gt 0) {
    foreach ($procId in $owners) {
        $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
        Write-Step ("停止旧实例：PID $procId" + $(if ($proc) { "（$($proc.ProcessName)）" } else { '' }))
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
    }
    # 端口释放要等一下（TIME_WAIT / JVM 关停 SQLite 连接）
    $waited = 0
    while ((Get-PortOwners $Port).Count -gt 0 -and $waited -lt 20) {
        Start-Sleep -Milliseconds 500
        $waited++
    }
    if ((Get-PortOwners $Port).Count -gt 0) {
        Write-Warn "端口 $Port 仍被占用，新实例可能起不来（用 netstat -ano | findstr :$Port 查）"
    } else {
        Write-Ok "端口 $Port 已释放"
    }
} else {
    Write-Step "端口 $Port 没有在跑的实例，直接启动"
}

# ---------------------------------------------------------------- 4. 启动
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("app-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")

$javaArgs = @(
    '-jar', "`"$jarPath`"",
    "--server.port=$Port",
    "--logging.file.name=`"$logFile`""
)

# PATH 上的 java.exe 常是 Oracle javapath 转发器（它再起真 JVM），PID 会对不上；
# 有 JAVA_HOME 就直接用真 JVM，端口归属与 PID 才一致。
$javaExe = 'java'
if ($env:JAVA_HOME) {
    $cand = Join-Path $env:JAVA_HOME 'bin\java.exe'
    if (Test-Path $cand) { $javaExe = $cand }
}

if ($Foreground) {
    Write-Step "前台启动（Ctrl+C 退出），日志：$logFile"
    & $javaExe @javaArgs
    Pop-Location; exit $LASTEXITCODE
}

Write-Step "启动：$javaExe -jar $(Split-Path $jarPath -Leaf)（端口 $Port）"
$proc = Start-Process -FilePath $javaExe -ArgumentList $javaArgs -WorkingDirectory $root `
    -WindowStyle Hidden -PassThru
Write-Ok "已拉起 PID $($proc.Id)"

# ---------------------------------------------------------------- 5. 等健康检查
Write-Step "等 /health（最多 $TimeoutSec 秒）…"
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$healthy = $false
while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) { break }
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 2 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch {
        # 启动期连接被拒是正常的，继续等
    }
    Start-Sleep -Milliseconds 800
}

# ---------------------------------------------------------------- 6. 结果
if ($healthy) {
    $livePid = @(Get-PortOwners $Port) -join ','
    Write-Ok "服务已就绪：http://127.0.0.1:$Port/ui"
    Write-Host "    PID $livePid（端口监听者）· 日志 $logFile" -ForegroundColor DarkGray
    if (Test-Path $logFile) {
        # 把启动期关键行捞出来（含历史库口径修正，便于确认迁移是否跑过）
        $lines = Get-Content $logFile -Encoding UTF8 -ErrorAction SilentlyContinue |
            Select-String -Pattern '口径修正|启动完成|KB 白名单'
        if ($lines) { $lines | ForEach-Object { Write-Host ("    " + $_.Line.Trim()) -ForegroundColor DarkGray } }
    }
    Write-Host "    停止：Get-NetTCPConnection -LocalPort $Port -State Listen | ForEach-Object { Stop-Process -Id `$_.OwningProcess -Force }" -ForegroundColor DarkGray
    Pop-Location
    exit 0
}

$why = '仍无响应'
if ($proc.HasExited) { $why = '进程已退出（多为配置/端口/依赖错误，见下方日志）' }
Write-Warn "启动失败或超时：$why"
if (Test-Path $logFile) {
    Write-Host "---- 日志尾部（$logFile） ----" -ForegroundColor Yellow
    Get-Content $logFile -Encoding UTF8 -Tail 40 | ForEach-Object { Write-Host $_ }
    Write-Host '----'
} else {
    Write-Warn "日志文件还没生成：$logFile"
}
Pop-Location
exit 1
