# Script PowerShell: Iniciar Navegador CDP (Porta 9222) e Servidor Local
$Host.UI.RawUI.WindowTitle = "Painel Operacional CCO & Entrega - Servidor Local CDP"

Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " INICIANDO NAVEGADOR CDP (PORTA 9222) E SERVIDOR LOCAL" -ForegroundColor Cyan
Write-Host " Portais Operacionais: EquipesBrasil ENEL SP, TIBCO Spotfire e BidTech" -ForegroundColor Cyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

$urlEnel = "https://equipesbrasil.enelint.global/teams-list"
$urlSpotfire = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%205.0"
$urlBid = "https://suite360.bidtech.com.br/app/checklists/visao-operacional"

$cdpPort = 9222
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$userProfile = [System.Environment]::GetFolderPath('UserProfile')

function Test-CdpPortOpen {
    $tcp = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $tcp.BeginConnect("127.0.0.1", $cdpPort, $null, $null)
        $wait = $iar.AsyncWaitHandle.WaitOne(800, $false)
        if ($wait -and $tcp.Connected) {
            $tcp.EndConnect($iar)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $tcp.Close()
    }
}

$isCdpActive = Test-CdpPortOpen

if ($isCdpActive) {
    Write-Host "[OK] Navegador com depuracao remota CDP (porta 9222) ja esta ativo e operacional!" -ForegroundColor Green
} else {
    if (Test-Path $chromePath) {
        Write-Host "[INFO] Abrindo Google Chrome com depuracao remota na porta 9222..." -ForegroundColor Green
        $userData = Join-Path $userProfile ".chrome_cdp"
        Start-Process -FilePath $chromePath -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=$userData", "--no-first-run", "--no-default-browser-check", $urlEnel, $urlSpotfire, $urlBid
        Write-Host "[OK] Google Chrome disparado com sucesso!" -ForegroundColor Green
    } elseif (Test-Path $edgePath) {
        Write-Host "[INFO] Abrindo Microsoft Edge com depuracao remota na porta 9222..." -ForegroundColor Green
        $userData = Join-Path $userProfile ".edge_cdp"
        Start-Process -FilePath $edgePath -ArgumentList "--remote-debugging-port=9222", "--user-data-dir=$userData", "--no-first-run", "--no-default-browser-check", $urlEnel, $urlSpotfire, $urlBid
        Write-Host "[OK] Microsoft Edge disparado com sucesso!" -ForegroundColor Green
    } else {
        Write-Host "[AVISO] Nem o Chrome nem o Edge foram encontrados nos caminhos padrao." -ForegroundColor Yellow
    }

    # Aguarda a porta 9222 responder
    Write-Host "[INFO] Aguardando conexao CDP na porta 9222..." -ForegroundColor Gray
    $tentativas = 0
    while (-not (Test-CdpPortOpen) -and $tentativas -lt 6) {
        Start-Sleep -Seconds 1
        $tentativas++
    }
    if (Test-CdpPortOpen) {
        Write-Host "[OK] Conexao CDP pronta na porta 9222!" -ForegroundColor Green
    } else {
        Write-Host "[AVISO] Porta 9222 ainda em inicializacao. O servidor conectara assim que disponivel." -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host " INICIANDO SERVIDOR LOCAL (Python run_server.py)..." -ForegroundColor Cyan
Write-Host " Mantenha este terminal aberto para acompanhar as coletas CDP em tempo real." -ForegroundColor DarkCyan
Write-Host "==============================================================================" -ForegroundColor Cyan
Write-Host ""

Set-Location -Path $PSScriptRoot
while ($true) {
    python run_server.py
    Write-Host "[INFO] Servidor local encerrado. Reiniciando em 2 segundos (Pressione Ctrl+C para interromper)..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
}
