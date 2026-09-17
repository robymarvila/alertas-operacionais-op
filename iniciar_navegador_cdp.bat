@echo off
title Alertas Operacionais OP - Servidor Local e CDP
echo ==============================================================================
echo  INICIANDO NAVEGADOR CDP (PORTA 9222) E SERVIDOR LOCAL
echo  Portais: EquipesBrasil ENEL SP, TIBCO Spotfire e BidTech
echo ==============================================================================
echo.

set "URL_ENEL=https://equipesbrasil.enelint.global/teams-list"
set "URL_SPOTFIRE=http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%%205.0"
set "URL_BID=https://suite360.bidtech.com.br/app/checklists/visao-operacional"

:: 1. Verifica se porta 9222 ja esta ativa
netstat -ano | findstr "127.0.0.1:9222" | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    echo [OK] Navegador com depuracao remota CDP ja esta ativo na porta 9222.
    goto INICIAR_SERVIDOR
)

:: 2. Dispara Google Chrome ou Microsoft Edge
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo [INFO] Abrindo Google Chrome com depuracao remota na porta 9222...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.chrome_cdp" "%URL_ENEL%" "%URL_SPOTFIRE%" "%URL_BID%"
    goto AGUARDAR_CDP
)

if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    echo [INFO] Abrindo Microsoft Edge com depuracao remota na porta 9222...
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.edge_cdp" "%URL_ENEL%" "%URL_SPOTFIRE%" "%URL_BID%"
    goto AGUARDAR_CDP
)

echo [AVISO] Chrome ou Edge nao encontrados nos caminhos padrao.

:AGUARDAR_CDP
timeout /t 3 /nobreak >nul

:INICIAR_SERVIDOR
echo.
echo ==============================================================================
echo  INICIANDO SERVIDOR LOCAL (Python run_server.py)...
echo  Mantenha esta janela aberta para acompanhar os ciclos CDP em tempo real.
echo ==============================================================================
echo.
cd /d "%~dp0"
python run_server.py
pause
