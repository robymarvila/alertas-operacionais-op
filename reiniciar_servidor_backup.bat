@echo off
chcp 65001 >nul
title Reiniciar Servidor da Máquina 2 (Standby)

echo ==============================================================================
echo  REINICIANDO SERVIDOR LOCAL DA MAQUINA 2 (STANDBY)
echo ==============================================================================
echo.
echo [1/3] Finalizando processos Python anteriores na Maquina 2...
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force"

echo [2/3] Confirmando papel como STANDBY...
powershell -Command "$cfg = @{ node_id = 'MAQUINA_2_BACKUP'; node_label = 'Servidor CCO Redundante (Máquina 2)'; role = 'STANDBY'; is_feeding_db = $false; auto_failover_enabled = $true }; $utf8NoBom = New-Object System.Text.UTF8Encoding($false); [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot 'node_config.json'), ($cfg | ConvertTo-Json -Depth 4), $utf8NoBom)"

echo [3/3] Iniciando servidor local com os novos codigos...
echo.
echo ==============================================================================
echo  [OK] Maquina 2 reiniciada em modo STANDBY REPOUSO!
echo  Mantenha esta janela aberta para telemetria.
echo ==============================================================================
echo.
python run_server.py
pause
