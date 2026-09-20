@echo off
chcp 65001 >nul
title Atualização e Sincronização do Cluster CCO (Máquinas 1 e 2)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0atualizacao_cluster.ps1"
if %errorlevel% neq 0 (
    echo.
    echo Ocorreu uma pendência durante a execução.
    pause
)
