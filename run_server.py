"""
Inicializador do Painel Operacional PowerON vs TRBOnet
Verifica disponibilidade de portas, inicia o servidor Flask e abre o navegador automaticamente.
"""

import sys
import os
import socket
import webbrowser
import threading
import time

def ensure_port_5000_or_find(preferred_port=5000):
    """
    Garante que a porta preferencial (5000) seja utilizada com máxima prioridade.
    Se estiver ocupada por processo Python anterior, tenta liberar de forma limpa.
    """
    import subprocess
    for attempt in range(4):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if s.connect_ex(('127.0.0.1', preferred_port)) != 0:
                return preferred_port
        # Se for Windows e porta ocupada, tenta identificar processo
        if os.name == 'nt' and attempt == 0:
            try:
                cmd = f"Get-NetTCPConnection -LocalPort {preferred_port} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess"
                res = subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
                pid = res.stdout.strip()
                if pid and pid.isdigit() and int(pid) != os.getpid():
                    # Encerra processo órfão anterior
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
                    time.sleep(1.2)
                    continue
            except Exception:
                pass
        time.sleep(0.8)
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

    from app import app, start_background_jobs
    start_background_jobs()

    port = ensure_port_5000_or_find(5000)
    url = f"http://127.0.0.1:{port}"

    print("\n" + "="*75)
    print("[INICIADO] ALERTAS OPERACIONAIS OP (PowerON vs TRBOnet)")
    print(f"[OK] Servidor Local Iniciado com Sucesso: {url}")
    print("[INFO] Auditoria e Conciliacao em Tempo Real Ativa")
    print("="*75 + "\n", flush=True)

    # Abrir navegador em thread separada
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # Iniciar servidor Flask multithread
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
