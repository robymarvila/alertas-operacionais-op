# Script PowerShell: Iniciar Navegador com Depuração CDP (Porta 9222)
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " INICIANDO NAVEGADOR COM DEPURACAO CDP (PORTA 9222)" -ForegroundColor Cyan
Write-Host " Portais: EquipesBrasil ENEL SP e TIBCO Spotfire" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

$urlEnel = "https://equipesbrasil.enelint.global/teams-list"
$urlSpotfire = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%205.0"

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$userProfile = [System.Environment]::GetFolderPath('UserProfile')

if (Test-Path $chromePath) {
    Write-Host "[INFO] Abrindo Google Chrome com depuracao remota na porta 9222..." -ForegroundColor Green
    $userData = Join-Path $userProfile ".chrome_cdp"
    Start-Process -FilePath $chromePath -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=$userData", "--no-first-run", "--no-default-browser-check", $urlEnel, $urlSpotfire
    Write-Host "[OK] Google Chrome iniciado com sucesso!" -ForegroundColor Green
} elseif (Test-Path $edgePath) {
    Write-Host "[INFO] Abrindo Microsoft Edge com depuracao remota na porta 9222..." -ForegroundColor Green
    $userData = Join-Path $userProfile ".edge_cdp"
    Start-Process -FilePath $edgePath -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=$userData", "--no-first-run", "--no-default-browser-check", $urlEnel, $urlSpotfire
    Write-Host "[OK] Microsoft Edge iniciado com sucesso!" -ForegroundColor Green
} else {
    Write-Host "[ERRO] Nem o Chrome nem o Edge foram encontrados." -ForegroundColor Red
}
