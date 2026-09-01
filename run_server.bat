@echo off
title alertas-operacionais-op (PowerON vs TRBOnet)
echo =======================================================================
echo Iniciando alertas-operacionais-op: PowerON vs TRBOnet (Servidor Local)
echo =======================================================================
cd /d "%~dp0"
python run_server.py
pause
