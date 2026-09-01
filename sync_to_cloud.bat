@echo off
title Sincronizador Nuvem CCO - TRBOnet x PowerON
echo ========================================================
echo   SINCRONIZADOR NUVEM CCO: TRBOnet + PowerON -^> Supabase
echo ========================================================
echo.
python sync_to_cloud.py --loop 120
pause
