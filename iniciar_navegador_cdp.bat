@echo off
title Iniciar Navegador CDP - Enel e Spotfire
echo ==============================================================================
echo  INICIANDO NAVEGADOR COM DEPURACAO CDP (PORTA 9222)
echo  Portais: EquipesBrasil ENEL SP e TIBCO Spotfire
echo ==============================================================================
echo.

set "URL_ENEL=https://equipesbrasil.enelint.global/teams-list"
set "URL_SPOTFIRE=http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%%205.0"

:: 1. Tenta Google Chrome (com perfil dedicado CDP)
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo [INFO] Abrindo Google Chrome com depuracao remota na porta 9222...
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.chrome_cdp" "%URL_ENEL%" "%URL_SPOTFIRE%"
    goto SUCESSO
)

:: 2. Alternativa: Microsoft Edge (com perfil dedicado CDP)
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    echo [INFO] Abrindo Microsoft Edge com depuracao remota na porta 9222...
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\.edge_cdp" "%URL_ENEL%" "%URL_SPOTFIRE%"
    goto SUCESSO
)

echo [ERRO] Nem o Chrome nem o Edge foram encontrados nos caminhos padrao.
pause
exit /b 1

:SUCESSO
echo.
echo ==============================================================================
echo  [OK] Navegador iniciado na porta 9222!
echo  [INFO] Mantenha as abas do EquipesBrasil e do Spotfire abertas.
echo  [INFO] Os agentes autonomos de coleta (CDP) agora conseguem se conectar.
echo ==============================================================================
ping 127.0.0.1 -n 3 >nul
