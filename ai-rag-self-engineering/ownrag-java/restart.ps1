# ownrag-java 一键重启脚本（Windows / PowerShell）
#
# 用法（在本目录下）：
#   .\restart.ps1                  # 停旧实例 → 打包（跳过测试）→ 起新实例 → 等 /health
#   .\restart.ps1 -WithTests       # 打包前先跑全量测试
#   .\restart.ps1 -NoBuild         # 不改代码，只重启（复用现有 jar，秒级）
#   .\restart.ps1 -Foreground      # 前台运行，日志直接打在当前控制台（Ctrl+C 退出）
#   .\restart.ps1 -Port 8421       # 换端口
#   双击 restart.bat 效果等同 .\restart.ps1
#
# 为什么先停旧实例再打包：Windows 上运行中的 java -jar 占着 target 里的 jar，
# repackage 的重命名会失败，失败后 target 里只剩 thin jar（可运行产物被毁）。
# 停之前已把上一版 jar 备份到 target\ownrag-java-last-good.jar，构建失败自动回滚。
# 日志：logs\app-<时间戳>.log（Spring 自己写，UTF-8，绕开 PowerShell 重定向的中文乱码问题）
# 密钥：启动前读本目录 .env（gitignored）注入进程环境；已在当前环境里的变量优先，不被覆盖。

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

# ---------------------------------------------------------------- 2. 停旧实例（按端口找监听者，比记 PID 稳）
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

# 备份"上一次能跑的 jar"：repackage 会先把 target 里的 fat jar 改名再重写，
# 中途失败（典型：jar 被运行中的 JVM 锁住）会把可运行产物留成 thin jar——java -jar 直接起不来。
# 只备份 fat jar（含 BOOT-INF）：target 里可能已经是坏掉的 thin jar，别把垃圾当"上一次能跑的"。
function Test-FatJar($path) {
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction SilentlyContinue
        $zip = [System.IO.Compression.ZipFile]::OpenRead($path)
        try {
            return ($null -ne ($zip.Entries | Where-Object { $_.FullName -like 'BOOT-INF/*' } |
                Select-Object -First 1))
        } finally { $zip.Dispose() }
    } catch { return $false }
}

$prevJar = Get-AppJar
$backupJar = Join-Path $root 'target\ownrag-java-last-good.jar'
if ($prevJar -and (Test-FatJar $prevJar)) {
    Copy-Item -LiteralPath $prevJar -Destination $backupJar -Force -ErrorAction SilentlyContinue
} else {
    $prevJar = $null
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
    Write-Step "端口 $Port 没有在跑的实例"
}

# ---------------------------------------------------------------- 3. 构建（必须在停旧实例之后）
# Windows 上运行中的 java -jar 会占着 target 里的 jar，repackage 的重命名步骤就失败；
# 先构建后停的旧顺序会踩这个坑，且失败后 target 里只剩 thin jar。备份已在上一步做好。
if (-not $NoBuild) {
    if (-not (Get-Command mvn -ErrorAction SilentlyContinue)) {
        Write-Warn '找不到 mvn，无法构建；请先装 Maven 或改用 -NoBuild'
        Pop-Location; exit 1
    }
    $mvnArgs = @('-B', '-q')
    if (-not $WithTests) { $mvnArgs += '-DskipTests' }
    $mvnArgs += 'package'
    Write-Step ("构建：mvn " + ($mvnArgs -join ' '))
    & mvn @mvnArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Warn "构建失败（exit $LASTEXITCODE）"
        if ($prevJar -and (Test-Path $backupJar)) {
            Copy-Item -LiteralPath $backupJar -Destination $prevJar -Force -ErrorAction SilentlyContinue
            Write-Warn ("已把上一次的 jar 回滚到 {0}——先 .\restart.ps1 -NoBuild 跑旧版本，再查构建日志" -f
                (Split-Path $prevJar -Leaf))
        }
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

# ---------------------------------------------------------------- 4. 注入 .env（密钥不落 YAML、不入库）
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    $injected = 0
    foreach ($line in Get-Content $envFile -Encoding UTF8) {
        $t = $line.Trim()
        if ($t -eq '' -or $t.StartsWith('#')) { continue }
        $eq = $t.IndexOf('=')
        if ($eq -le 0) { continue }
        $k = $t.Substring(0, $eq).Trim()
        $v = $t.Substring($eq + 1).Trim().Trim('"').Trim("'")
        if ([string]::IsNullOrEmpty([Environment]::GetEnvironmentVariable($k))) {
            [Environment]::SetEnvironmentVariable($k, $v, 'Process')
            $injected++
        }
    }
    Write-Ok ".env 已注入 $injected 项（已存在的环境变量优先）"
    if ([Environment]::GetEnvironmentVariable('OWNRAG_EMBED_API_KEY') -like '*REPLACE_WITH*') {
        Write-Warn '.env 里 OWNRAG_EMBED_API_KEY / OWNRAG_RERANK_API_KEY 还是占位符：embed/rerank 会 401 并降级'
    }
} else {
    Write-Warn '未找到 .env：模型 API Key 缺失时 chat/embed/rerank 全部降级（模板见 .env.example）'
}

# ---------------------------------------------------------------- 5. 启动
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

# ---------------------------------------------------------------- 6. 等健康检查
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

# ---------------------------------------------------------------- 7. 结果
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
