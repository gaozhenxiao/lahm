# 将 lahm 推送到 GitHub 新仓库（无旧历史）
# 用法：
#   1. 在 https://github.com/settings/tokens 创建 Fine-grained 或 classic token（需 repo 权限）
#   2. 在本目录 PowerShell 执行：
#        $env:GH_TOKEN = "ghp_xxx..."
#        .\scripts\push_lahm_github.ps1
#   或：
#        .\scripts\push_lahm_github.ps1 -Token "ghp_xxx..."

param(
    [string]$Token = $env:GH_TOKEN,
    [string]$RepoName = "lahm",
    [string]$Visibility = "public",
    [string]$Description = "柳暗花明 (lahm) - 多智能体研究与因子平台"
)

$ErrorActionPreference = "Stop"
$gh = "$env:ProgramFiles\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) {
    $gh = "$env:LOCALAPPDATA\Programs\GitHub CLI\gh.exe"
}
if (-not (Test-Path $gh)) {
    throw "未找到 gh.exe，请先安装 GitHub CLI"
}

if (-not $Token) {
    throw "请先设置 Token：`$env:GH_TOKEN='ghp_...' 或 -Token 参数"
}

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:GH_TOKEN = $Token
& $gh auth status 2>$null
if ($LASTEXITCODE -ne 0) {
    $Token | & $gh auth login --hostname github.com --with-token
}

$user = & $gh api user --jq .login
if (-not $user) { throw "无法获取 GitHub 用户名" }
Write-Host "GitHub user: $user"

$full = "$user/$RepoName"
$exists = $true
& $gh repo view $full 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { $exists = $false }

if (-not $exists) {
    Write-Host "Creating repo $full ($Visibility)..."
    & $gh repo create $RepoName --$Visibility --description $Description --confirm
} else {
    Write-Host "Repo already exists: $full"
}

# 确保在 orphan 分支
$branch = git branch --show-current
if ($branch -ne "lahm-main") {
    git checkout lahm-main
}

# 指向新仓库，断开 TradingAgents-CN
git remote remove origin 2>$null
git remote add origin "https://github.com/$full.git"

Write-Host "Pushing lahm-main -> main ..."
git push -u origin "lahm-main:main"

Write-Host ""
Write-Host "Done: https://github.com/$full"
