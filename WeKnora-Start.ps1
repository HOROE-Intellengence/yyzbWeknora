# WeKnora 一键启动脚本
# 功能：确保 Docker 引擎就绪 -> 启动容器 -> 等 localhost 真正起来 -> 自动打开浏览器
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'WeKnora 启动中...'

$ProjectDir = $PSScriptRoot
$DockerCli  = (Get-Command docker -ErrorAction Stop).Source
$DockerApp  = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'
$SiteUrl    = 'http://localhost:8081'   # 与 .env 的 FRONTEND_PORT 保持一致（80 被 Dify 的 nginx 占用）
$HealthUrl  = 'http://localhost:8080/health'
$ComposeArgs = @('compose')
$MigrationMarker = Join-Path $ProjectDir '.weknora-migration.json'
if (Test-Path -LiteralPath $MigrationMarker) {
    $Migration = Get-Content -LiteralPath $MigrationMarker -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $Migration.overlay)) { throw '迁移覆盖配置不存在，请检查 .weknora-migration.json。' }
    $ComposeArgs += @('-p', $Migration.project, '-f', (Join-Path $ProjectDir 'docker-compose.yml'), '-f', $Migration.overlay)
}

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    $m" -ForegroundColor Yellow }
function Err($m)  { Write-Host "    $m" -ForegroundColor Red }

Write-Host ''
Write-Host '============ WeKnora 一键启动 ============' -ForegroundColor White
Write-Host ''

# 1) 检查 Docker 引擎
Step '检查 Docker 引擎...'
& $DockerCli info *> $null
if ($LASTEXITCODE -ne 0) {
    Warn 'Docker 未运行，正在启动 Docker Desktop（首次约需 1-2 分钟）...'
    if (Test-Path $DockerApp) { Start-Process -FilePath $DockerApp -WindowStyle Hidden } else { Err "找不到 Docker Desktop：$DockerApp"; Read-Host '按回车退出'; exit 1 }
    $engineOk = $false
    for ($i = 1; $i -le 60; $i++) {
        Start-Sleep -Seconds 3
        & $DockerCli info *> $null
        if ($LASTEXITCODE -eq 0) { $engineOk = $true; break }
        Write-Host ("    等待引擎就绪... ${i}/60") -ForegroundColor DarkGray
    }
    if (-not $engineOk) { Err 'Docker 引擎启动超时，请手动打开 Docker Desktop 后重试。'; Read-Host '按回车退出'; exit 1 }
}
Ok 'Docker 引擎已就绪。'

# 2) 启动容器
Step '启动 WeKnora 容器...'
Set-Location $ProjectDir
if (Test-Path -LiteralPath $MigrationMarker) {
    & $DockerCli @ComposeArgs up -d --no-build --pull never
} else {
    & $DockerCli @ComposeArgs up -d
}
if ($LASTEXITCODE -ne 0) { Err '容器启动失败，请查看上方错误信息。'; Read-Host '按回车退出'; exit 1 }
Ok '容器已拉起。'

# 3) 等待服务真正就绪（先等后端健康，再确认前端页面），就绪后才开浏览器
Step '等待服务就绪（localhost 起来后再开浏览器）...'
$ready = $false
for ($i = 1; $i -le 60; $i++) {
    $backendOk = $false; $frontendOk = $false
    try { if ((Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $backendOk = $true } } catch {}
    if ($backendOk) { try { if ((Invoke-WebRequest -Uri $SiteUrl -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200) { $frontendOk = $true } } catch {} }
    if ($backendOk -and $frontendOk) { $ready = $true; break }
    Start-Sleep -Seconds 2
    Write-Host ("    等待中... ${i}/60") -ForegroundColor DarkGray
}

Write-Host ''
if ($ready) {
    Ok '服务已就绪！正在打开浏览器...'
    Start-Process $SiteUrl
    Write-Host ''
    Write-Host "  WeKnora 已启动 -> $SiteUrl" -ForegroundColor Green
} else {
    Warn "服务启动较慢，稍后请手动打开 $SiteUrl"
}
Write-Host ''
Write-Host '此窗口 3 秒后自动关闭。' -ForegroundColor DarkGray
Start-Sleep -Seconds 3
