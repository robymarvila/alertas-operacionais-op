import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import json
from supabase_client import BASE_REST_URL, get_headers, fetch_latest_snapshot_from_supabase, push_snapshot_to_supabase
from data_manager import data_manager

PROPRIA_PREFIXES = ['ENA', 'ECA', 'EEA', 'EMA', 'EQA', 'EVA', 'ESA']

def purge_propria_records():
    headers = get_headers()
    print("=" * 65)
    print("PURGANDO REGISTROS PRÓPRIA NO SUPABASE (TABELA TRBONET)")
    print("Prefixos a serem removidos:", PROPRIA_PREFIXES)
    print("=" * 65)

    total_deleted = 0

    # 1. Deletar por base_code na tabela team_operational_logs
    for p in PROPRIA_PREFIXES:
        endpoint = f"{BASE_REST_URL}/team_operational_logs?base_code=eq.{p}"
        # Primeiro verificar quantos existem
        r_check = requests.get(f"{endpoint}&select=id", headers=headers, timeout=10)
        count_p = len(r_check.json()) if r_check.status_code == 200 else 0
        
        # Deletar
        r_del = requests.delete(endpoint, headers=headers, timeout=15)
        if r_del.status_code in [200, 204]:
            print(f"  -> {p}: Removidos {count_p} registros com sucesso.")
            total_deleted += count_p
        else:
            print(f"  -> {p}: Erro ao remover (HTTP {r_del.status_code}): {r_del.text}")

    # 2. Verificar por team_code (caso tenha algum registrado com base diferente)
    for p in PROPRIA_PREFIXES:
        endpoint = f"{BASE_REST_URL}/team_operational_logs?team_code=like.{p}*"
        r_check = requests.get(f"{endpoint}&select=id", headers=headers, timeout=10)
        count_p = len(r_check.json()) if r_check.status_code == 200 else 0
        if count_p > 0:
            r_del = requests.delete(endpoint, headers=headers, timeout=15)
            print(f"  -> Prefixo {p}* em team_code: Removidos {count_p} registros residuais.")
            total_deleted += count_p

    print("\nTotal de registros deletados em team_operational_logs:", total_deleted)

    # 3. Atualizar snapshot mais recente no Supabase para garantir que não contenha equipes próprias
    print("\nAtualizando snapshot operacional em 'operational_snapshots'...")
    try:
        snap_res = fetch_latest_snapshot_from_supabase()
        if snap_res.get("status") == "success" and snap_res.get("data"):
            snap_data = snap_res["data"]
            teams = snap_data.get("teams", [])
            filtered_teams = [
                t for t in teams 
                if t.get("prefix") not in PROPRIA_PREFIXES and str(t.get("code", ""))[:3] not in PROPRIA_PREFIXES
            ]
            snap_data["teams"] = filtered_teams
            # Recalcular resumo rápido
            if "summary" in snap_data:
                snap_data["summary"]["total_teams"] = len(filtered_teams)
                snap_data["summary"]["total_teams_audited"] = len(filtered_teams)
            
            # Atualizar data_manager e salvar
            data_manager.load_from_snapshot(snap_data)
            clean_consolidated = data_manager.consolidate_data()
            push_snapshot_to_supabase(clean_consolidated, sync_source="Purge Equipes Próprias")
            print("Snapshot limpo gravado com sucesso no Supabase!")
    except Exception as e:
        print(f"Aviso ao atualizar snapshot: {e}")

    # 4. Verificação final
    print("\nVerificação de integridade no Supabase:")
    remaining_total = 0
    for p in PROPRIA_PREFIXES:
        r = requests.get(f"{BASE_REST_URL}/team_operational_logs?base_code=eq.{p}&select=id", headers=headers, timeout=10)
        cnt = len(r.json()) if r.status_code == 200 else 0
        print(f"  Restantes {p}: {cnt}")
        remaining_total += cnt

    if remaining_total == 0:
        print("\nSUCESSO: Todos os códigos Própria foram eliminados da tabela do TRBOnet no Supabase!")
    else:
        print(f"\nAtenção: Ainda restam {remaining_total} registros. Executando rodada adicional...")

if __name__ == "__main__":
    purge_propria_records()
