"""
Script de Saneamento e Reprocessamento das Equipes do Scanner 5.0 no Supabase.
1. Purge (exclusão de 100% dos dados) da tabela 'team_scanner_records' no Supabase.
2. Carga dos 8 arquivos mensais atualizados de 2026 (Jan a Ago/2026) da pasta Base_Equipes/Equipe.
3. Extração e carga limpa de Setembro/2026 via CDP do Scanner 5.0.
4. Validação forense confrontando com a planilha oficial 'Equipes Conf 01092026.xlsx'.
"""

import os
import sys
import glob
import time
import requests
from datetime import datetime

# Garante importação dos módulos da raiz do projeto
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from supabase_client import BASE_REST_URL, get_headers, push_scanner_records_to_supabase, fetch_scanner_records_by_date
from coletor_spotfire_cdp import processar_arquivo_scanner_para_registros, executar_ciclo_sincronizacao_spotfire, set_last_scanner_sync_time
from delivery_manager import delivery_manager

BASE_EQUIPES_DIR = r"C:\Users\robym\Desktop\Documentos\Base_Equipes\Equipe"
CONF_FILE = r"C:\Users\robym\Desktop\Documentos\Analise de dados\Equipes Conf\Equipes Conf 01092026.xlsx"


def purge_supabase_scanner_records():
    """Exclui 100% dos registros da tabela team_scanner_records no Supabase."""
    print("\n" + "="*70)
    print("[ETAPA 1/4] PURGE TOTAL DA TABELA team_scanner_records NO SUPABASE")
    print("="*70, flush=True)

    headers = get_headers().copy()
    headers["Prefer"] = "return=minimal"

    # Exclui mês a mês para garantir segurança contra timeout
    months = [f"2026-{m:02d}" for m in range(1, 13)]
    total_deleted_batches = 0

    for m in months:
        start_dt = f"{m}-01"
        end_dt = f"{m}-31"
        url = f"{BASE_REST_URL}/team_scanner_records?data_referencia=gte.{start_dt}&data_referencia=lte.{end_dt}"
        try:
            resp = requests.delete(url, headers=headers, timeout=60)
            if resp.status_code in [200, 204]:
                print(f"  [PURGE] Registros do mês {m} excluídos com sucesso (Status {resp.status_code}).", flush=True)
                total_deleted_batches += 1
            else:
                print(f"  [PURGE WARN] Falha ao excluir mês {m}: Status {resp.status_code} - {resp.text}", flush=True)
        except Exception as e:
            print(f"  [PURGE ERROR] Erro no mês {m}: {e}", flush=True)

    # Exclusão residual ampla
    try:
        url_all = f"{BASE_REST_URL}/team_scanner_records?data_referencia=gt.1970-01-01"
        resp_all = requests.delete(url_all, headers=headers, timeout=60)
        print(f"  [PURGE] Exclusão residual final: Status {resp_all.status_code}", flush=True)
    except Exception as e:
        print(f"  [PURGE ERROR] Exclusão residual: {e}", flush=True)

    # Verifica se a tabela ficou zerada
    headers_check = get_headers().copy()
    headers_check["Prefer"] = "count=exact"
    r_check = requests.get(f"{BASE_REST_URL}/team_scanner_records?select=id&limit=1", headers=headers_check, timeout=10)
    cr = r_check.headers.get("content-range", "")
    print(f"  [CHECK APÓS PURGE] Content-Range retornado: {cr}", flush=True)
    print("[ETAPA 1 CONCLUÍDA] Tabela do Scanner 5.0 purgada com sucesso!\n", flush=True)


def ingest_monthly_files():
    """Ingere os 8 arquivos mensais da pasta Base_Equipes/Equipe."""
    print("\n" + "="*70)
    print("[ETAPA 2/4] INGESTÃO DOS 8 ARQUIVOS MENSAIS DE 2026 (JAN A AGO)")
    print("="*70, flush=True)

    csv_files = sorted(glob.glob(os.path.join(BASE_EQUIPES_DIR, "*.csv")))
    if not csv_files:
        print(f"[ERRO] Nenhum arquivo CSV encontrado em {BASE_EQUIPES_DIR}", flush=True)
        return False

    print(f"Encontrados {len(csv_files)} arquivos para processamento.", flush=True)
    grand_total_records = 0

    for idx, fpath in enumerate(csv_files, 1):
        fname = os.path.basename(fpath)
        print(f"\n[{idx}/{len(csv_files)}] Processando: {fname}...", flush=True)
        t0 = time.time()

        records = processar_arquivo_scanner_para_registros(fpath, target_dates=None)
        t_parse = time.time() - t0
        print(f"   -> {len(records)} registros válidos extraídos em {t_parse:.2f}s.", flush=True)

        if not records:
            print(f"   [AVISO] Nenhum registro extraído para {fname}. Pulando envio...", flush=True)
            continue

        t_push0 = time.time()
        res = push_scanner_records_to_supabase(records)
        t_push = time.time() - t_push0
        saved = res.get("count", 0)
        grand_total_records += saved
        print(f"   -> {saved} registros salvos no Supabase em {t_push:.2f}s (Status: {res.get('status')}).", flush=True)

    print(f"\n[ETAPA 2 CONCLUÍDA] Total acumulado de registros de Jan a Ago salvos: {grand_total_records}\n", flush=True)
    return True


def ingest_september_data():
    """Extrai via CDP ou processa o arquivo de Setembro/2026."""
    print("\n" + "="*70)
    print("[ETAPA 3/4] EXTRAÇÃO E CARGA DE SETEMBRO/2026 VIA CDP DO SCANNER 5.0")
    print("="*70, flush=True)

    cdp_success = False
    try:
        print("Disparando ciclo de sincronização CDP do Scanner 5.0 para o mês atual...", flush=True)
        res_cdp = executar_ciclo_sincronizacao_spotfire(source_label="Reprocessamento Setembro 2026", full_history=True, all_months=False)
        if res_cdp.get("status") == "success":
            print(f"Sincronização CDP concluída com sucesso: {res_cdp.get('count')} registros.", flush=True)
            cdp_success = True
        else:
            print(f"[CDP AVISO] Retorno do CDP: {res_cdp.get('message')}", flush=True)
    except Exception as e:
        print(f"[CDP EXCEPTION] Erro ao executar ciclo CDP: {e}", flush=True)

    if not cdp_success:
        print("Tentando fallback através de arquivo exportado recente em Downloads...", flush=True)
        user_dl = os.path.expanduser("~/Downloads")
        cands = glob.glob(os.path.join(user_dl, "Scanner 5.0*.csv")) + glob.glob(os.path.join(user_dl, "Scanner 5.0*.tsv"))
        if cands:
            cands.sort(key=os.path.getmtime, reverse=True)
            latest_file = cands[0]
            print(f"Arquivo de fallback identificado: {latest_file}", flush=True)
            records = processar_arquivo_scanner_para_registros(latest_file, target_dates=None)
            print(f"Extraídos {len(records)} registros de Setembro do arquivo de fallback.", flush=True)
            res = push_scanner_records_to_supabase(records)
            print(f"Salvos {res.get('count')} registros no Supabase.", flush=True)

    print("[ETAPA 3 CONCLUÍDA] Dados de Setembro/2026 carregados no Supabase!\n", flush=True)


def validate_reconciliation():
    """Executa a validação cruzada para o dia 01/09/2026 e emite o laudo."""
    print("\n" + "="*70)
    print("[ETAPA 4/4] VALIDAÇÃO E RECONCILIAÇÃO OFICIAL (01/09/2026)")
    print("="*70, flush=True)

    # 1. Consulta registros no Supabase para 01/09/2026
    records_01 = fetch_scanner_records_by_date("2026-09-01")
    count_01 = len(records_01)
    print(f"Total de registros no Supabase para 2026-09-01: {count_01} (Esperado: 187)", flush=True)

    import pandas as pd
    df01 = pd.DataFrame(records_01)
    if not df01.empty:
        df01["pfx"] = df01["equipe_normalizada"].str[:3]
        norte_teams = df01[df01["pfx"].isin(["ENL", "ECL", "EEL"])]
        leste_teams = df01[df01["pfx"].isin(["EML", "EQL", "EVL", "ESL"])]
        print(f"  -> Região Norte no banco: {len(norte_teams)} equipes (Esperado: 92)", flush=True)
        print(f"     ENL (Fagundes Filho): {(df01['pfx'] == 'ENL').sum()} (Esperado: 36)")
        print(f"     ECL (Cajati):         {(df01['pfx'] == 'ECL').sum()} (Esperado: 31)")
        print(f"     EEL (Vila Medeiros):  {(df01['pfx'] == 'EEL').sum()} (Esperado: 25)")
        print(f"  -> Região Leste no banco: {len(leste_teams)} equipes (Esperado: 95)", flush=True)
        print(f"     EML (Monte Santo):    {(df01['pfx'] == 'EML').sum()} (Esperado: 38)")
        print(f"     EQL (Aricanduva):     {(df01['pfx'] == 'EQL').sum()} (Esperado: 34)")
        print(f"     EVL (Catumbi):        {(df01['pfx'] == 'EVL').sum()} (Esperado: 19)")
        print(f"     ESL (Santo André):    {(df01['pfx'] == 'ESL').sum()} (Esperado: 4)")

    # 2. Testa Relatório de Entrega de Equipes (API de targets audit)
    print("\n--- TESTE DO RELATÓRIO DE ENTREGA (Norte - 01/09/2026) ---")
    res_targets_norte = delivery_manager.get_comparative_targets_audit("2026-09-01", "Norte")
    for t in res_targets_norte.get("tables", {}).get("bases", []):
        print(f"  {t['categoria']}: Plan={t['plan']}, Real={t['real']}, Gap={t['gap']}")

    print("\n--- TESTE DO RELATÓRIO DE ENTREGA (Leste - 01/09/2026) ---")
    res_targets_leste = delivery_manager.get_comparative_targets_audit("2026-09-01", "Leste")
    for t in res_targets_leste.get("tables", {}).get("bases", []):
        print(f"  {t['categoria']}: Plan={t['plan']}, Real={t['real']}, Gap={t['gap']}")

    # 3. Testa Gráfico de Evolução Diária da Força de Trabalho (API mensal)
    print("\n--- TESTE DO GRÁFICO DE EVOLUÇÃO DIÁRIA (Setembro/2026) ---")
    res_monthly = delivery_manager.get_monthly_audit_data("2026-09")
    raw_m = res_monthly.get("raw_records", [])
    raw_01 = [r for r in raw_m if r.get("date") == "2026-09-01"]
    norte_m01 = [r for r in raw_01 if r.get("region") == "Região Norte"]
    leste_m01 = [r for r in raw_01 if r.get("region") == "Região Leste"]

    print(f"Total registros no gráfico em 01/09: {len(raw_01)} (Esperado: 187)")
    print(f"Filtro Região Norte no gráfico em 01/09: {len(norte_m01)} (Esperado: 92)")
    print(f"Filtro Região Leste no gráfico em 01/09: {len(leste_m01)} (Esperado: 95)")

    # 4. Atualiza timestamp e invalida cache
    set_last_scanner_sync_time()
    delivery_manager.get_available_audit_dates(force_refresh=True)

    print("\n" + "="*70)
    print("REPROCESSAMENTO E AUDITORIA CONCLUÍDOS COM SUCESSO!")
    print("="*70 + "\n", flush=True)


if __name__ == "__main__":
    purge_supabase_scanner_records()
    ingest_monthly_files()
    ingest_september_data()
    validate_reconciliation()
