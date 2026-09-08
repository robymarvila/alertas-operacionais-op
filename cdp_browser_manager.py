"""
Gerenciador Autônomo do Navegador CDP (Chrome DevTools Protocol)
Responsável por garantir que o navegador (Google Chrome ou Microsoft Edge)
esteja em execução com a porta 9222 aberta e com as abas dos portais operacionais
(EquipesBrasil ENEL SP e TIBCO Spotfire) ativas.
"""

import os
import sys
import socket
import subprocess
import time
import urllib.request
import urllib.parse
import json

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

URL_ENEL = "https://equipesbrasil.enelint.global/teams-list"
URL_SPOTFIRE = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%205.0"

# Caminhos padrão do Google Chrome e Microsoft Edge no Windows
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe")
]

EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
]

_LAST_LAUNCH_ATTEMPT = 0
_LAUNCH_COOLDOWN_SECONDS = 30  # Evita disparos repetidos caso o usuário feche a janela


def is_cdp_port_open(host=CDP_HOST, port=CDP_PORT, timeout=1.0) -> bool:
    """Verifica se a porta 9222 está aberta e aceitando conexões TCP."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def get_available_browser():
    """Retorna o executável e a pasta de perfil CDP para Chrome ou Edge."""
    user_home = os.path.expanduser("~")

    # 1. Prioriza Google Chrome
    for p in CHROME_PATHS:
        if os.path.exists(p):
            profile_dir = os.path.join(user_home, ".chrome_cdp")
            os.makedirs(profile_dir, exist_ok=True)
            return {
                "name": "Google Chrome",
                "exe": p,
                "profile_dir": profile_dir
            }

    # 2. Alternativa: Microsoft Edge
    for p in EDGE_PATHS:
        if os.path.exists(p):
            profile_dir = os.path.join(user_home, ".edge_cdp")
            os.makedirs(profile_dir, exist_ok=True)
            return {
                "name": "Microsoft Edge",
                "exe": p,
                "profile_dir": profile_dir
            }

    return None


def garantir_navegador_cdp_ativo(max_wait_seconds=10) -> bool:
    """
    Verifica se o navegador está ativo na porta 9222.
    Se não estiver, dispara o navegador de forma autônoma com porta 9222 e abas operacionais.
    """
    global _LAST_LAUNCH_ATTEMPT

    if is_cdp_port_open():
        return True

    now = time.time()
    if now - _LAST_LAUNCH_ATTEMPT < _LAUNCH_COOLDOWN_SECONDS:
        # Aguarda cooldown para não floodar processos
        return False

    _LAST_LAUNCH_ATTEMPT = now
    browser = get_available_browser()
    if not browser:
        print("[CDP MANAGER ERROR] Nenhum navegador compatível (Chrome ou Edge) foi encontrado.", flush=True)
        return False

    print(f"[CDP MANAGER] Navegador na porta {CDP_PORT} não detectado. Iniciando de forma autônoma ({browser['name']})...", flush=True)

    args = [
        browser["exe"],
        f"--remote-debugging-port={CDP_PORT}",
        f"--user-data-dir={browser['profile_dir']}",
        "--no-first-run",
        "--no-default-browser-check",
        URL_ENEL,
        URL_SPOTFIRE
    ]

    try:
        if os.name == 'nt':
            # No Windows, dispara via WMI Win32_Process.Create para desvincular de Job Objects
            cmd_line = f'"{browser["exe"]}" --remote-debugging-port={CDP_PORT} --user-data-dir="{browser["profile_dir"]}" --no-first-run --no-default-browser-check "{URL_ENEL}" "{URL_SPOTFIRE}"'
            ps_cmd = f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine = '{cmd_line}'}}"
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
            print(f"[CDP MANAGER] {browser['name']} disparado com sucesso via WMI independente.", flush=True)
        else:
            proc = subprocess.Popen(args, close_fds=True)
            print(f"[CDP MANAGER] {browser['name']} disparado com sucesso (PID: {proc.pid}).", flush=True)
    except Exception as err:
        print(f"[CDP MANAGER ERROR] Falha ao iniciar {browser['name']}: {err}", flush=True)
        return False

    # Aguarda a porta 9222 responder
    for i in range(max_wait_seconds):
        time.sleep(1)
        if is_cdp_port_open():
            print(f"[CDP MANAGER OK] Porta {CDP_PORT} ativa e operacional após {i+1}s!", flush=True)
            return True

    print(f"[CDP MANAGER WARN] Tempo limite atingido ({max_wait_seconds}s) aguardando porta {CDP_PORT}.", flush=True)
    return False


def listar_alvos_cdp():
    """Consulta os alvos abertos no navegador via endpoint HTTP do CDP."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []


def garantir_abas_operacionais():
    """
    Garante que tanto a aba do EquipesBrasil quanto a aba do Spotfire
    estejam presentes no navegador. Se alguma não existir, abre uma nova aba.
    """
    if not is_cdp_port_open():
        if not garantir_navegador_cdp_ativo():
            return False

    targets = listar_alvos_cdp()
    has_enel = False
    has_spotfire = False

    for t in targets:
        if t.get('type') == 'page':
            u = (t.get('url') or '').lower()
            title = (t.get('title') or '').lower()
            if 'spotfire' in u or 'spotfire' in title or 'elabziplra00' in u:
                has_spotfire = True
            elif 'equipesbrasil.enelint.global' in u or 'filtro avançado' in title:
                has_enel = True

    # Abre aba do Enel SP se ausente
    if not has_enel:
        try:
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{urllib.parse.quote(URL_ENEL, safe=':/?=&')}"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                print("[CDP MANAGER] Nova aba do EquipesBrasil ENEL SP criada com sucesso.", flush=True)
        except Exception as e:
            print(f"[CDP MANAGER WARN] Falha ao criar aba da Enel: {e}", flush=True)

    # Abre aba do Spotfire se ausente
    if not has_spotfire:
        try:
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{urllib.parse.quote(URL_SPOTFIRE, safe=':/?=&')}"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                print("[CDP MANAGER] Nova aba do TIBCO Spotfire criada com sucesso.", flush=True)
        except Exception as e:
            print(f"[CDP MANAGER WARN] Falha ao criar aba do Spotfire: {e}", flush=True)

    return True
