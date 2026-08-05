# 柳暗花明：启动后端(8000) + 前端(3000)
# 用法：powershell -ExecutionPolicy Bypass -File scripts\startup\start_lahm.ps1
param(
    [switch]$Restart,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Continue"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = Join-Path $Root "env\Scripts\python.exe" }
if (-not (Test-Path $Py)) { $Py = "python" }

$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$BackendLog = Join-Path $LogDir "lahm_backend.log"
$FrontendLog = Join-Path $LogDir "lahm_frontend.log"

function Stop-PortOwner([int]$Port) {
    $conns = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        try { Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue } catch {}
    }
}

if ($Restart) {
    Write-Host "[lahm] restart: freeing ports $BackendPort / $FrontendPort"
    Stop-PortOwner $BackendPort
    Stop-PortOwner $FrontendPort
    Start-Sleep -Seconds 2
}

# MongoDB 通常为 Windows 服务；若未监听则提示
$mongoOk = Get-NetTCPConnection -State Listen -LocalPort 27017 -ErrorAction SilentlyContinue
if (-not $mongoOk) {
    Write-Host "[lahm] WARN: MongoDB :27017 not listening; try Start-Service MongoDB"
    try { Start-Service MongoDB -ErrorAction SilentlyContinue } catch {}
}

# Redis（本机安装在 D:\Programs\Redis）
$redisOk = Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue
if (-not $redisOk) {
    $redisExe = "D:\Programs\Redis\Redis\redis-server.exe"
    $redisConf = "D:\data\redis\redis.conf"
    if (Test-Path $redisExe) {
        Write-Host "[lahm] starting Redis :6379"
        if (Test-Path $redisConf) {
            Start-Process -FilePath $redisExe -ArgumentList "`"$redisConf`"" -WindowStyle Minimized
        } else {
            Start-Process -FilePath $redisExe -WindowStyle Minimized
        }
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 500
            if (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue) { break }
        }
    } else {
        Write-Host "[lahm] WARN: Redis not found at $redisExe"
    }
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 6379 -ErrorAction SilentlyContinue)) {
    Write-Host "[lahm] WARN: Redis :6379 still down; backend may fail to start"
}

$beListening = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
if (-not $beListening) {
    Write-Host "[lahm] starting backend :$BackendPort"
    $beArgs = "-m uvicorn app.main:app --host 127.0.0.1 --port $BackendPort --log-level info"
    Start-Process -FilePath $Py -ArgumentList $beArgs -WorkingDirectory $Root -WindowStyle Hidden `
        -RedirectStandardOutput $BackendLog -RedirectStandardError (Join-Path $LogDir "lahm_backend.err.log")
} else {
    Write-Host "[lahm] backend already on :$BackendPort"
}

$feListening = Get-NetTCPConnection -State Listen -LocalPort $FrontendPort -ErrorAction SilentlyContinue
if (-not $feListening) {
    $npm = (Get-Command npm -ErrorAction SilentlyContinue).Source
    if (-not $npm) {
        Write-Host "[lahm] ERROR: npm not found; skip frontend"
    } else {
        Write-Host "[lahm] starting frontend :$FrontendPort"
        $feDir = Join-Path $Root "frontend"
        # vite 默认 3000；用 cmd 以支持重定向
        $cmd = 'npm run dev -- --host 127.0.0.1 --port ' + $FrontendPort + ' > "' + $FrontendLog + '" 2>&1'
        Start-Process -FilePath "cmd.exe" -ArgumentList @('/c', $cmd) -WorkingDirectory $feDir -WindowStyle Hidden
    }
} else {
    Write-Host "[lahm] frontend already on :$FrontendPort"
}

# 等待端口就绪再回报
for ($i = 0; $i -lt 30; $i++) {
    $be2 = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
    $fe2 = Get-NetTCPConnection -State Listen -LocalPort $FrontendPort -ErrorAction SilentlyContinue
    if ($be2 -and $fe2) { break }
    Start-Sleep -Seconds 1
}
$be2 = Get-NetTCPConnection -State Listen -LocalPort $BackendPort -ErrorAction SilentlyContinue
$fe2 = Get-NetTCPConnection -State Listen -LocalPort $FrontendPort -ErrorAction SilentlyContinue
$beStatus = if ($be2) { 'UP' } else { 'DOWN' }
$feStatus = if ($fe2) { 'UP' } else { 'DOWN' }
Write-Host "[lahm] backend=$beStatus frontend=$feStatus"
Write-Host "[lahm] API http://127.0.0.1:$BackendPort  UI http://127.0.0.1:$FrontendPort"
