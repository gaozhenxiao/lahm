# 注册柳暗花明为当前用户登录自启动（计划任务）
# 用法：powershell -ExecutionPolicy Bypass -File scripts\startup\register_lahm_autostart.ps1
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$TaskName = "LahmAutoStart"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$StartPs1 = Join-Path $Root "scripts\startup\start_lahm.ps1"
$Tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartPs1`""

if ($Unregister) {
    schtasks /Delete /TN $TaskName /F 2>$null | Out-Null
    Write-Host "[lahm] removed scheduled task: $TaskName"
    exit 0
}

if (-not (Test-Path $StartPs1)) { throw "missing $StartPs1" }

# 登录后延迟 40 秒，等 Mongo/网络就绪
schtasks /Create /TN $TaskName /TR $Tr /SC ONLOGON /DELAY 0000:40 /RL LIMITED /F | Out-Null
Write-Host "[lahm] registered: $TaskName (ONLOGON +40s)"
schtasks /Query /TN $TaskName /FO LIST /V | Select-String -Pattern 'TaskName|Status|Task To Run|Schedule Type|Delay'
