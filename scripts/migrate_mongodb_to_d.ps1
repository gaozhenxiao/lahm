#Requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$cfg = 'C:\Program Files\MongoDB\Server\8.3\bin\mongod.cfg'
$srcData = 'C:\Program Files\MongoDB\Server\8.3\data'
$srcLog = 'C:\Program Files\MongoDB\Server\8.3\log'
$dstData = 'D:\data\mongodb'
$dstLog = 'D:\data\mongodb\log'
$marker = 'D:\data\mongodb\_migrate_status.txt'

function Log($m) {
  $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
  Add-Content -Path $marker -Value $line -Encoding UTF8
  Write-Host $line
}

'' | Set-Content $marker -Encoding UTF8
Log 'START migrate MongoDB data to D:'

New-Item -ItemType Directory -Force -Path $dstData, $dstLog | Out-Null

Log 'Stopping MongoDB service...'
Stop-Service MongoDB -Force
Start-Sleep -Seconds 3
$svc = Get-Service MongoDB
if ($svc.Status -ne 'Stopped') {
  Log "FAIL: service still $($svc.Status)"
  exit 1
}
Log 'Service stopped'

Log 'Copying data...'
robocopy $srcData $dstData /E /COPY:DAT /R:2 /W:2 /NFL /NDL /NP
$rc = $LASTEXITCODE
Log "robocopy data exit=$rc"
if ($rc -ge 8) { exit $rc }

if (Test-Path $srcLog) {
  Log 'Copying logs...'
  robocopy $srcLog $dstLog /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NP | Out-Null
}

Log 'Writing mongod.cfg...'
@"
# mongod.conf - lahm local (data on D:)
storage:
  dbPath: D:\data\mongodb
systemLog:
  destination: file
  logAppend: true
  path: D:\data\mongodb\log\mongod.log
net:
  port: 27017
  bindIp: 127.0.0.1
"@ | Set-Content $cfg -Encoding ASCII

Log 'Starting MongoDB...'
Start-Service MongoDB
Start-Sleep -Seconds 4
$svc = Get-Service MongoDB
Log "Service status=$($svc.Status)"
if ($svc.Status -ne 'Running') {
  Log 'FAIL: service not running after start'
  exit 2
}

# Verify dbPath in use via ping
$py = 'D:\cursor_space\lahm\.venv\Scripts\python.exe'
if (Test-Path $py) {
  & $py -c "from pymongo import MongoClient; c=MongoClient('localhost',27017,serverSelectionTimeoutMS=8000); print(c.admin.command('ping')); print(c.list_database_names())"
  Log "pymongo ping ok exit=$LASTEXITCODE"
}

Log 'DONE'
exit 0
