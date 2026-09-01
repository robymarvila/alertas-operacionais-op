"""
Script de Sincronização Local -> Supabase (Nuvem)
Executa a leitura do TRBOnet One e da escala PowerON e sincroniza com o banco de dados em nuvem.
Pode ser executado sob demanda ou em loop contínuo a cada X minutos.
"""

import time
import sys
from datetime import datetime
from data_manager import data_manager
from supabase_client import push_snapshot_to_supabase

def executar_sincronizacao_completa():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}] INICIANDO SINCRONIZAÇÃO NUVEM")
    print(f"=======================================================")

    # 1. Carregar PowerON
    print("[1/3] Lendo Arquivo Calendário do PowerON...")
    try:
        res_pw = data_manager.carregar_arquivo_calendario_poweron()
        print(f"      -> {res_pw.get('message', 'Ok')}")
    except Exception as e:
        print(f"      -> [Aviso] Falha ao ler PowerON: {e}")

    # 2. Capturar TRBOnet One
    print("[2/3] Capturando Rádios do TRBOnet One via UIAutomation...")
    try:
        from coletar_trbonet_completo import extrair_dados_trbonet
        radios = extrair_dados_trbonet()
        if radios:
            data_manager.update_data(trbonet_dict=radios, source_label="Sincronizador Automático")
            print(f"      -> {len(radios)} rádios capturados com sucesso!")
        else:
            print("      -> Nenhum rádio capturado ou janela fechada.")
    except Exception as e:
        print(f"      -> [Aviso] Falha na captura do TRBOnet: {e}")

    # 3. Consolidar e Enviar para o Supabase
    print("[3/3] Enviando Snapshot Consolidado para o Supabase...")
    data = data_manager.consolidate_data()
    summary = data.get("summary", {})
    print(f"      -> Total Equipes: {summary.get('total_teams', 0)} | Rádios: {summary.get('total_trbonet', 0)} | Conformidade: {summary.get('compliance_rate', 0)}%")
    
    res_supa = push_snapshot_to_supabase(data)
    if res_supa.get("status") == "success":
        print(f"      -> [OK] Sincronização em Nuvem Concluída com Sucesso!")
    else:
        print(f"      -> [ERRO] Falha ao enviar para o Supabase: {res_supa.get('message')}")

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--loop':
        intervalo = int(sys.argv[2]) if len(sys.argv) > 2 else 120
        print(f"[*] Modo Contínuo Ativo: Sincronizando a cada {intervalo} segundos (Pressione Ctrl+C para parar)...")
        while True:
            executar_sincronizacao_completa()
            print(f"\nAguardando {intervalo} segundos para a próxima sincronização...")
            time.sleep(intervalo)
    else:
        executar_sincronizacao_completa()
