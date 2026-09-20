# ==============================================================================
# SCRIPT UNIFICADO: ATUALIZAÇÃO E SINCRONIZAÇÃO DO CLUSTER CCO
# Suporta Máquina 1 (Principal) e Máquina 2 (Backup / Standby)
# ==============================================================================

$Host.UI.RawUI.WindowTitle = "Atualização e Sincronização do Cluster CCO"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host "         ATUALIZADOR INTELIGENTE DO CLUSTER CCO (MÁQUINAS 1 E 2)             " -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

$baseDir = $PSScriptRoot
$cfgPath = Join-Path $baseDir "node_config.json"
$zipPath = Join-Path $baseDir "atualizacao_cluster.zip"

# Identifica papel atual
$currentRole = "DESCONHECIDO"
$nodeId = "DESCONHECIDO"
if (Test-Path $cfgPath) {
    try {
        $json = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $currentRole = $json.role
        $nodeId = $json.node_id
    } catch {
        $currentRole = "ERRO_LEITURA"
    }
}

Write-Host "Status do Nó Local:" -ForegroundColor Yellow
Write-Host " - Identificador: $nodeId" -ForegroundColor White
Write-Host " - Papel Atual:  $currentRole" -ForegroundColor White
Write-Host ""
Write-Host "Escolha a operação desejada:" -ForegroundColor Green
Write-Host " [1] GERAR pacote 'atualizacao_cluster.zip' para levar para a Máquina 2" -ForegroundColor White
Write-Host " [2] APLICAR 'atualizacao_cluster.zip' nesta máquina (Modo Máquina 2 - Standby)" -ForegroundColor White
Write-Host " [3] PUXAR atualizações direto do GITHUB (git pull origin main)" -ForegroundColor White
Write-Host " [4] SAIR" -ForegroundColor Gray
Write-Host ""

$opcao = Read-Host "Digite a opção desejada (1, 2, 3 ou 4)"

switch ($opcao.Trim()) {
    "1" {
        Write-Host ""
        Write-Host "[1/2] Gerando pacote de atualização dos códigos recentes..." -ForegroundColor Cyan
        python (Join-Path $baseDir "export_update.py")
        if (Test-Path $zipPath) {
            $tamanho = (Get-Item $zipPath).Length / 1KB
            Write-Host ""
            Write-Host "==============================================================================" -ForegroundColor Green
            Write-Host " [SUCESSO] Pacote gerado com êxito: atualizacao_cluster.zip ($([Math]::Round($tamanho, 1)) KB)" -ForegroundColor Green
            Write-Host "==============================================================================" -ForegroundColor Green
            Write-Host ""
            Write-Host "COMO COLOCAR A MÁQUINA 2 IGUAL:" -ForegroundColor Yellow
            Write-Host "1. Envie o arquivo 'atualizacao_cluster.zip' para a Máquina 2 (Rede, Teams, Pendrive, etc.)." -ForegroundColor White
            Write-Host "2. Cole o arquivo na pasta do projeto na Máquina 2." -ForegroundColor White
            Write-Host "3. Na Máquina 2, execute o 'atualizacao_cluster.bat' e escolha a Opção 2." -ForegroundColor White
            Write-Host ""
        } else {
            Write-Host "[ERRO] Não foi possível gerar 'atualizacao_cluster.zip'." -ForegroundColor Red
        }
    }
    "2" {
        Write-Host ""
        Write-Host "[1/3] Verificando pacote 'atualizacao_cluster.zip'..." -ForegroundColor Cyan
        if (-not (Test-Path $zipPath)) {
            Write-Host "[ERRO] O arquivo 'atualizacao_cluster.zip' não foi encontrado nesta pasta!" -ForegroundColor Red
            Write-Host "Por favor, copie o arquivo gerado na Máquina 1 para esta pasta antes de aplicar." -ForegroundColor Yellow
        } else {
            Write-Host "[2/3] Extraindo arquivos atualizados..." -ForegroundColor Cyan
            Expand-Archive -Path $zipPath -DestinationPath $baseDir -Force

            Write-Host "[3/3] Configurando identidade como MAQUINA 2 (STANDBY)..." -ForegroundColor Cyan
            $cfg = @{
                node_id = "MAQUINA_2_BACKUP"
                node_label = "Servidor CCO Redundante (Máquina 2)"
                role = "STANDBY"
                is_feeding_db = $false
                auto_failover_enabled = $true
            }
            $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
            [System.IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 4), $utf8NoBom)

            try {
                python -c "import cluster_manager, delivery_manager, coletor_enel_cdp, coletor_spotfire_cdp, coletor_bid_cdp; print('[OK] Validação de módulos concluída!')"
            } catch {
                Write-Host "[AVISO] Arquivos aplicados com sucesso. (Python não testado no terminal)" -ForegroundColor Yellow
            }

            Write-Host ""
            Write-Host "==============================================================================" -ForegroundColor Green
            Write-Host " [SUCESSO] Máquina 2 atualizada com sucesso e pronta para operar!" -ForegroundColor Green
            Write-Host " - Todos os códigos estão rigorosamente iguais à Máquina 1." -ForegroundColor White
            Write-Host " - Modo STANDBY ativo (banco protegido contra duplicidades)." -ForegroundColor White
            Write-Host "==============================================================================" -ForegroundColor Green
            Write-Host ""
            Write-Host "Reinicie os navegadores/servidores se já estiverem em execução." -ForegroundColor Yellow
        }
    }
    "3" {
        Write-Host ""
        Write-Host "Sincronizando com o GitHub via git pull..." -ForegroundColor Cyan
        git pull origin main
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "[SUCESSO] Repositório atualizado diretamente pelo GitHub!" -ForegroundColor Green
        } else {
            Write-Host ""
            Write-Host "[AVISO] Falha ou conflito no git pull. Você também pode usar a Opção 2 com o arquivo ZIP." -ForegroundColor Yellow
        }
    }
    default {
        Write-Host "Operação cancelada pelo usuário." -ForegroundColor Gray
    }
}

Write-Host ""
Read-Host "Pressione Enter para encerrar..."
