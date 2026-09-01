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

def find_available_port(start_port=5000, max_attempts=20):
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    return start_port

def open_browser(url):
    time.sleep(1.5)
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"Não foi possível abrir o navegador automaticamente: {e}")

if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    from app import app

    port = find_available_port(5000)
    url = f"http://127.0.0.1:{port}"

    print("\n" + "="*75)
    print("[INICIADO] ALERTAS OPERACIONAIS OP (PowerON vs TRBOnet)")
    print(f"[OK] Servidor Local Iniciado com Sucesso: {url}")
    print("[INFO] Auditoria e Conciliacao em Tempo Real Ativa")
    print("="*75 + "\n")

    # Abrir navegador em thread separada
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # Iniciar servidor Flask
    app.run(host='0.0.0.0', port=port, debug=False)
