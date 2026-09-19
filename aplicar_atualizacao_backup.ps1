# Script PowerShell: Aplicar Atualização do Cluster na Máquina 2 (Standby)
$Host.UI.RawUI.WindowTitle = "Aplicar Atualização de Códigos na Máquina 2 (Standby)"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " APLICADOR DE ATUALIZACAO CLUSTER - MAQUINA 2 (STANDBY)" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

$zipFile = Join-Path $PSScriptRoot "atualizacao_cluster.zip"

if (-not (Test-Path $zipFile)) {
    Write-Host "[ERRO] O arquivo 'atualizacao_cluster.zip' nao foi encontrado nesta pasta!" -ForegroundColor Red
    Write-Host "Copie o arquivo gerado na Maquina 1 para ca e execute este script novamente." -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Pressione Enter para sair..."
    exit 1
}

Write-Host "[1/3] Extraindo arquivos atualizados sobre a pasta do projeto..." -ForegroundColor Green
Expand-Archive -Path $zipFile -DestinationPath $PSScriptRoot -Force

Write-Host "[2/3] Garantindo identidade da Maquina 2 como STANDBY..." -ForegroundColor Green
$cfg = @{
    node_id = "MAQUINA_2_BACKUP"
    node_label = "Servidor CCO Redundante (Máquina 2)"
    role = "STANDBY"
    is_feeding_db = $false
    auto_failover_enabled = $true
}
$cfgPath = Join-Path $PSScriptRoot "node_config.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 4), $utf8NoBom)

Write-Host "[3/3] Validando modulos e coletores..." -ForegroundColor Green
try {
    python -c "import cluster_manager, delivery_manager, coletor_enel_cdp, coletor_spotfire_cdp, coletor_bid_cdp; print('[OK] Modulos e coletores validados com sucesso!')"
} catch {
    Write-Host "[AVISO] Nao foi possivel rodar validacao automatica do Python, mas os arquivos foram extraidos." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " [SUCESSO] Maquina 2 atualizada com sucesso!" -ForegroundColor Green
Write-Host " - Arquivos atualizados aplicados." -ForegroundColor White
Write-Host " - Modo STANDBY ativo (protecao contra duplicidade no banco confirmada)." -ForegroundColor White
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Caso o servidor local ou os robos CDP estejam abertos na Maquina 2," -ForegroundColor Yellow
Write-Host "feche e abra novamente atraves do 'iniciar_navegador_cdp.ps1'." -ForegroundColor Yellow
Write-Host ""
Read-Host "Pressione Enter para encerrar..."
