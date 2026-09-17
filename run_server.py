import sys
import os
import socket
import webbrowser
import threading
import time
import argparse

def get_lan_ip():
    """Identifica o endereço IP local na rede (Wi-Fi ou Ethernet)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'

def is_port_in_use(port, host='0.0.0.0'):
    """Verifica se uma porta está ocupada."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(('127.0.0.1', port)) == 0

def find_available_port(preferred_port=5050, max_attempts=50):
    """Encontra uma porta livre a partir da porta preferida sem derrubar outros serviços."""
    for p in range(preferred_port, preferred_port + max_attempts):
        if not is_port_in_use(p):
            return p
    return preferred_port

def open_browser(url):
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Não foi possível abrir o navegador automaticamente: {e}", flush=True)

if __name__ == '__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Inicializador do Painel Operacional CCO & Entrega")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5050)), help="Porta do servidor (padrão: 5050)")
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "0.0.0.0"), help="IP/Host de vinculação (padrão: 0.0.0.0)")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador automaticamente")
    args = parser.parse_args()

    from app import app, start_background_jobs

    port = find_available_port(args.port)
    host = args.host
    lan_ip = get_lan_ip()

    url_local = f"http://localhost:{port}"
    url_loopback = f"http://127.0.0.1:{port}"
    url_network = f"http://{lan_ip}:{port}"

    print("\n" + "="*78)
    print("  SERVIDOR LOCAL INICIADO - ALERTAS OPERACIONAIS OP (CCO & ENTREGA)")
    print("="*78)
    print(f"  [OK] Painel Local:         {url_local}  ou  {url_loopback}")
    print(f"  [OK] Acesso Rede / PWA:    {url_network}")
    print(f"  [OK] Host Vinculado:       {host} na porta {port}")
    print(f"  [OK] Depuracao CDP Port:   127.0.0.1:9222")
    print("="*78)
    print("  [INFO] Motores de Coleta Autonoma Ativos (CDP & WebSocket):")
    print("         - Enel SP (EquipesBrasil):        a cada 2 min (120s)")
    print("         - BidTech (Visao Operacional):     a cada 2 min (120s)")
    print("         - TIBCO Spotfire (Scanner 5.0):   a cada 30 min (1800s)")
    print("         - TRBOnet One (Radios & GPS):      a cada 2 min (120s)")
    print("="*78 + "\n", flush=True)

    # Garante abas dos portais abertas no Chrome/Edge CDP
    try:
        from cdp_browser_manager import garantir_abas_operacionais
        garantir_abas_operacionais()
    except Exception as e:
        print(f"[CDP MANAGER WARN] Verificação de abas CDP: {e}", flush=True)

    start_background_jobs()

    if not args.no_browser:
        threading.Thread(target=open_browser, args=(url_local,), daemon=True).start()

    # Iniciar servidor Flask multithread
    app.run(host=host, port=port, debug=False, threaded=True)
