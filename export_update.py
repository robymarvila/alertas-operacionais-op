"""
Script Utilitário: Gerar Pacote de Atualização do Cluster CCO
Cria um arquivo ZIP com os códigos-fonte atualizados para aplicar na Máquina 2 (Standby)
sem necessidade de enviar para o GitHub.
"""

import os
import zipfile
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ZIP_NAME = os.path.join(BASE_DIR, "atualizacao_cluster.zip")

# Arquivos e extensões a incluir
INCLUDED_EXTENSIONS = {'.py', '.html', '.js', '.css', '.bat', '.ps1', '.sql', '.txt', '.webmanifest'}
EXCLUDED_DIRS = {'.git', '.chrome_cdp', '.edge_cdp', 'downloads_relatorios', '__pycache__', '.system_generated', 'browser_recordings'}
EXCLUDED_FILES = {'node_config.json', 'atualizacao_cluster.zip', 'fleet_vehicles_cache.json', 'scanner_last_sync.json'}

def create_update_package():
    print(f"[EXPORTADOR CLUSTER] Empacotando atualizações em: {ZIP_NAME}")
    count = 0
    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(BASE_DIR):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS and not d.startswith('.')]
            for file in files:
                if file in EXCLUDED_FILES or file.endswith('.pyc'):
                    continue
                ext = os.path.splitext(file)[1].lower()
                if ext in INCLUDED_EXTENSIONS or file in ['requirements.txt']:
                    abs_path = os.path.join(root, file)
                    rel_path = os.path.relpath(abs_path, BASE_DIR)
                    zipf.write(abs_path, rel_path)
                    count += 1

    file_size_kb = os.path.getsize(ZIP_NAME) / 1024
    print(f"[EXPORTADOR CLUSTER] Sucesso! {count} arquivos empacotados ({file_size_kb:.1f} KB).")
    return ZIP_NAME

if __name__ == '__main__':
    create_update_package()
