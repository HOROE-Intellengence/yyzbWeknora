# WeKnora 一键关闭脚本
# 功能：停止所有 WeKnora 容器（数据保留，不会丢失知识库）
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Host.UI.RawUI.WindowTitle = 'WeKnora 关闭中...'

$ProjectDir = $PSScriptRoot
$DockerCli  = (Get-Command docker -ErrorAction Stop).Source
$ComposeArgs = @('compose')
$MigrationMarker = Join-Path $ProjectDir '.weknora-migration.json'
if (Test-Path -LiteralPath $MigrationMarker) {
    $Migration = Get-Content -LiteralPath $MigrationMarker -Raw | ConvertFrom-Json
    if (-not (Test-Path -LiteralPath $Migration.overlay)) { throw '迁移覆盖配置不存在，请检查 .weknora-migration.json。' }
    $ComposeArgs += @('-p', $Migration.project, '-f', (Join-Path $ProjectDir 'docker-compose.yml'), '-f', $Migration.overlay)
}

function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }

Write-Host ''
Write-Host '============ WeKnora 一键关闭 ============' -ForegroundColor White
Write-Host ''

& $DockerCli info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host '    Docker 引擎未运行，WeKnora 本就是停止状态。' -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    exit 0
}

Step '正在停止 WeKnora 容器...'
Set-Location $ProjectDir
& $DockerCli @ComposeArgs stop

Write-Host ''
Write-Host '    WeKnora 已停止（数据完整保留，下次启动即可继续使用）。' -ForegroundColor Green
Write-Host ''
Write-Host '此窗口 3 秒后自动关闭。' -ForegroundColor DarkGray
Start-Sleep -Seconds 3
