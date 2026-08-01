$ErrorActionPreference="Stop"
$old="C:\Program Files\MongoDB\Server\8.3\data"
$oldLog="C:\Program Files\MongoDB\Server\8.3\log"
# Do NOT delete while service uses D - safe to remove old copies
if (Test-Path $old) {
  $sz=(Get-ChildItem $old -Recurse -EA SilentlyContinue | Measure-Object Length -Sum).Sum
  Remove-Item $old -Recurse -Force
  "removed old data bytes=$sz" | Out-File D:\data\mongodb\_cleanup.txt -Append
}
if (Test-Path $oldLog) {
  Remove-Item $oldLog -Recurse -Force -EA SilentlyContinue
  "removed old log" | Out-File D:\data\mongodb\_cleanup.txt -Append
}
New-Item -ItemType Directory -Force -Path $old,$oldLog | Out-Null
"DONE cleanup" | Out-File D:\data\mongodb\_cleanup.txt -Append
