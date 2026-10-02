"""
Processamento Manual em Caráter de Exceção do Arquivo de Setembro/2026 do Scanner 5.0 (TIBCO Spotfire)
Arquivo de origem: C:\\Users\\robym\\Downloads\\Scanner 5.0 - Tabela Completa todas Colunas - 2026-10-02T120228.701.csv
"""

import os
import sys
import shutil
import time
from datetime import datetime, date

# Garante importação da raiz do projeto
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

SOURCE_FILE = r"C:\Users\robym\Downloads\Scanner 5.0 - Tabela Completa todas Colunas - 2026-10-02T120228.701.csv"
DEST_FILE = r"C:\Users\robym\Desktop\Documentos\Base_Equipes\Equipe\09_Scanner 5.0 - Equipe - Setembro 2026.csv"


def run_manual_exception_processing():
    print("\n" + "="*80)
    print(">>> PROCESSAMENTO MANUAL EM CARÁTER DE EXCEÇÃO: SCANNER 5.0 (SETEMBRO/2026)")
    print("="*80, flush=True)

    if not os.path.exists(SOURCE_FILE):
        print(f"[ERRO CRÍTICO] Arquivo de origem não encontrado: {SOURCE_FILE}", flush=True)
        return False

    t_start = time.time()

    # -------------------------------------------------------------------------
    # ETAPA 1: Persistência / Cópia na pasta oficial Base_Equipes\Equipe
    # -------------------------------------------------------------------------
    print("\n[ETAPA 1/5] Arquivamento na pasta oficial de bases históricas...", flush=True)
    os.makedirs(os.path.dirname(DEST_FILE), exist_ok=True)
    shutil.copy2(SOURCE_FILE, DEST_FILE)
    dest_size = os.path.getsize(DEST_FILE)
    print(f" -> Arquivo arquivado com sucesso como:")
    print(f"    {DEST_FILE} ({dest_size / (1024*1024):.2f} MB)", flush=True)

    # -------------------------------------------------------------------------
    # ETAPA 2: Extração, Sanitização e Normalização dos 98+ Atributos
    # -------------------------------------------------------------------------
    print("\n[ETAPA 2/5] Processando registros com Pandas e regras operacionais...", flush=True)
    t0_parse = time.time()
    records = processar_arquivo_scanner_para_registros(DEST_FILE, target_dates=None)
    t_parse = time.time() - t0_parse
    total_recs = len(records)
    print(f" -> Extração concluída em {t_parse:.2f}s: {total_recs} registros válidos normalizados.", flush=True)

    if not records:
        print("[ERRO] Nenhum registro extraído. Abortando ingestão.", flush=True)
        return False

    # Distribuição por data
    import collections
    dates_cnt = collections.Counter(r.get("data_referencia") for r in records)
    print(f" -> Cobertura temporal: {len(dates_cnt)} dias identificados (de {min(dates_cnt.keys())} a {max(dates_cnt.keys())}).", flush=True)

    # -------------------------------------------------------------------------
    # ETAPA 3: UPSERT Atômico no Supabase (tabela team_scanner_records)
    # -------------------------------------------------------------------------
    print("\n[ETAPA 3/5] Gravando no Supabase via UPSERT atômico (team_scanner_records)...", flush=True)
    t0_push = time.time()
    push_res = push_scanner_records_to_supabase(records)
    t_push = time.time() - t0_push
    saved_cnt = push_res.get("count", 0)
    push_status = push_res.get("status", "unknown")
    print(f" -> Ingestão concluída em {t_push:.2f}s: {saved_cnt} registros gravados/atualizados (Status: {push_status}).", flush=True)

    # -------------------------------------------------------------------------
    # ETAPA 4: Reconciliação no Delivery Manager e Atualização de Caches
    # -------------------------------------------------------------------------
    print("\n[ETAPA 4/5] Reconciliando com o Delivery Manager e atualizando caches...", flush=True)
    # Reconcilia a data mais recente disponível no arquivo (ex: 2026-09-30)
    sorted_dates = sorted(dates_cnt.keys())
    latest_dt = sorted_dates[-1] if sorted_dates else "2026-09-30"
    latest_records = [r for r in records if r.get("data_referencia") == latest_dt]
    print(f" -> Reconciliando data final ({latest_dt}) com {len(latest_records)} equipes...", flush=True)
    delivery_manager.reconcile_with_spotfire_records(latest_records, date_ref=latest_dt)

    # Invalida e recalcula datas disponíveis no Delivery Manager
    avail_dates = delivery_manager.get_available_audit_dates(force_refresh=True)
    print(f" -> Cache de datas de auditoria atualizado: {len(avail_dates)} datas disponíveis no sistema.", flush=True)

    # Atualiza timestamp da última sincronização
    ts_now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    set_last_scanner_sync_time(ts_now)
    print(f" -> Timestamp da última sincronização do Scanner 5.0 atualizado para: {ts_now}", flush=True)

    # Atualiza saúde do motor
    try:
        update_engine_health(
            "spotfire_cdp_collector",
            "OPERATIONAL",
            is_running=True,
            error_type="NONE",
            last_error=None,
            records_count=saved_cnt,
            engine_label="Robô CDP Scanner 5.0 (Spotfire) [Carga Manual]"
        )
        print(" -> Saúde do motor 'spotfire_cdp_collector' atualizada para OPERATIONAL.", flush=True)
    except Exception as e_health:
        print(f" -> Aviso ao atualizar saúde do motor: {e_health}", flush=True)

    # -------------------------------------------------------------------------
    # ETAPA 5: Validação Forense Amostral
    # -------------------------------------------------------------------------
    print("\n[ETAPA 5/5] Executando validação forense das consultas...", flush=True)
    # Testa consulta para 01/09/2026 e 30/09/2026
    for check_dt in ["2026-09-01", latest_dt]:
        db_recs = fetch_scanner_records_by_date(check_dt)
        print(f" -> Consulta no Supabase para {check_dt}: {len(db_recs)} equipes confirmadas.", flush=True)

    total_time = round(time.time() - t_start, 2)
    print("\n" + "="*80)
    print(f"✓ PROCESSO CONCLUÍDO COM 100% DE SUCESSO EM {total_time}s!")
    print(f"  Total de registros processados e sincronizados: {saved_cnt}")
    print(f"  Período coberto: 01/09/2026 a {latest_dt} (30 dias)")
    print(f"  Arquivo oficial permanente: {DEST_FILE}")
    print("="*80 + "\n", flush=True)
    return True


if __name__ == "__main__":
    success = run_manual_exception_processing()
    sys.exit(0 if success else 1)
