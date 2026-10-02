"""
Processamento e Ingestão dos Dados de Outubro/2026 do Scanner 5.0
Arquivo: C:\\Users\\robym\\Downloads\\Scanner 5.0 - Tabela Completa todas Colunas - 2026-10-02T120604.405.csv
"""

import os
import sys
import shutil
import time
from datetime import datetime

ROOT_DIR = r"c:\Users\robym\Desktop\Documentos\Analise de dados\alertas-operacionais-op\alertas-operacionais-op"
sys.path.insert(0, ROOT_DIR)

from coletor_spotfire_cdp import (
    processar_arquivo_scanner_para_registros,
    set_last_scanner_sync_time
)
from supabase_client import (
    push_scanner_records_to_supabase,
    fetch_scanner_records_by_date,
    update_engine_health
)
from delivery_manager import delivery_manager

SOURCE_OCT = r"C:\Users\robym\Downloads\Scanner 5.0 - Tabela Completa todas Colunas - 2026-10-02T120604.405.csv"
DEST_OCT = r"C:\Users\robym\Desktop\Documentos\Base_Equipes\Equipe\10_Scanner 5.0 - Equipe - Outubro 2026.csv"


def process_october_data():
    print("\n" + "="*80)
    print(">>> PROCESSAMENTO E INGESTÃO DE OUTUBRO/2026 (SCANNER 5.0)")
    print("="*80, flush=True)

    if not os.path.exists(SOURCE_OCT):
        print(f"[ERRO] Arquivo de Outubro não encontrado: {SOURCE_OCT}", flush=True)
        return False

    # 1. Arquivamento
    print("[1/5] Arquivando como 10_Scanner 5.0 - Equipe - Outubro 2026.csv...", flush=True)
    os.makedirs(os.path.dirname(DEST_OCT), exist_ok=True)
    shutil.copy2(SOURCE_OCT, DEST_OCT)
    print(f" -> Arquivado com sucesso em: {DEST_OCT}")

    # 2. Extração e Normalização
    print("[2/5] Extraindo registros com Pandas...", flush=True)
    records = processar_arquivo_scanner_para_registros(DEST_OCT, target_dates=None)
    print(f" -> Extraídos {len(records)} registros normalizados para Outubro/2026.", flush=True)

    if not records:
        print("[ERRO] Nenhum registro extraído. Abortando.", flush=True)
        return False

    # 3. UPSERT no Supabase
    print("[3/5] Inserindo no Supabase (team_scanner_records)...", flush=True)
    push_res = push_scanner_records_to_supabase(records)
    saved = push_res.get("count", 0)
    print(f" -> {saved} registros salvos no Supabase com sucesso!", flush=True)

    # 4. Reconciliação no Delivery Manager
    print("[4/5] Reconciliando com o Delivery Manager...", flush=True)
    delivery_manager.reconcile_with_spotfire_records(records, date_ref="2026-10-01")

    # Invalida cache de auditoria mensal para Outubro
    delivery_manager.clear_audit_cache("2026-10")
    avail_dates = delivery_manager.get_available_audit_dates(force_refresh=True)
    print(f" -> Datas disponíveis atualizadas. Total de meses: {len(avail_dates.get('months', []))}")

    # Atualiza timestamp
    ts_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    set_last_scanner_sync_time(ts_now)

    # 5. Validação da consulta
    print("[5/5] Testando retorno de get_monthly_audit_data('2026-10')...", flush=True)
    m_data = delivery_manager.get_monthly_audit_data("2026-10")
    raw_cnt = len(m_data.get("raw_records", []))
    days_cnt = len(m_data.get("days", []))
    print(f" -> Outubro/2026 no sistema: {raw_cnt} equipes retornadas em {days_cnt} dias!")

    print("\n" + "="*80)
    print(f"✓ INGESTÃO DE OUTUBRO/2026 CONCLUÍDA COM SUCESSO!")
    print(f"  Total de equipes ativas em Outubro/2026: {raw_cnt}")
    print("="*80 + "\n", flush=True)
    return True


if __name__ == "__main__":
    process_october_data()
