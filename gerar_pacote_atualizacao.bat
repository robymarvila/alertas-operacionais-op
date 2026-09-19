@echo off
chcp 65001 >nul
title Gerar Pacote de Atualização do Cluster CCO

echo ==============================================================================
echo  GERADOR DE PACOTE DE ATUALIZACAO CLUSTER (SEM GITHUB)
echo ==============================================================================
echo.
echo [1/2] Empacotando codigos atualizados para a Maquina 2...
python export_update.py

if exist atualizacao_cluster.zip (
    echo.
    echo ==============================================================================
    echo  [SUCESSO] Pacote gerado: atualizacao_cluster.zip
    echo ==============================================================================
    echo.
    echo COMO ATUALIZAR A MAQUINA 2:
    echo 1. Copie o arquivo "atualizacao_cluster.zip" para a pasta do sistema na Maquina 2.
    echo    (Voce pode enviar via rede local, WhatsApp Web, Teams, Pen Drive ou Nuvem).
    echo 2. Na Maquina 2, execute o script: "aplicar_atualizacao_backup.bat"
    echo.
) else (
    echo [ERRO] Falha ao gerar atualizacao_cluster.zip.
)

pause
