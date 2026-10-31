# -*- coding: utf-8 -*-
"""
Script de Revisao do Banco de Dados para Outubro/2026:
Atualiza os 25 codigos fixos de equipes de apoio TMA para 'STC Leste' em:
1. team_delivery_records (Supabase) via Primary Key IDs em lote de 400 com 3 workers
2. team_scanner_records (Supabase)
3. delivery_daily_cache.json (Cache Diario Local)
4. Invalidacao e Recalculo da Auditoria Mensal 10/2026
"""

import os
import sys
import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from supabase_client import BASE_REST_URL, get_headers
from delivery_manager import delivery_manager, STC_LESTE_CODES, ALL_STC_LESTE_CODES

def processar_equipe_delivery(code):
    """Atualiza todos os registros de uma equipe em team_delivery_records para Outubro/2026."""
    h_get = get_headers().copy()
    h_patch = get_headers().copy()
    h_patch["Prefer"] = "return=minimal"
    
    payload = {
        "vehicle_type": "STC Leste",
        "unified_group": "STC Leste",
        "vehicle_category": "STC Leste"
    }

    t0 = time.time()
    total_updated = 0
    consecutive_errors = 0

    while True:
        url_ids = (
            f"{BASE_REST_URL}/team_delivery_records?"
            f"team_code=eq.{code}&"
            f"date_ref=gte.2026-10-01&date_ref=lte.2026-10-31&"
            f"vehicle_type=neq.STC%20Leste&"
            f"select=id&limit=400"
        )
        try:
            r_ids = requests.get(url_ids, headers=h_get, timeout=15)
            if r_ids.status_code != 200:
                consecutive_errors += 1
                if consecutive_errors > 3:
                    break
                time.sleep(1)
                continue

            rows = r_ids.json()
            if not rows:
                break

            ids = [str(x["id"]) for x in rows if "id" in x]
            if not ids:
                break

            url_patch = f"{BASE_REST_URL}/team_delivery_records?id=in.({','.join(ids)})"
            r_patch = requests.patch(url_patch, json=payload, headers=h_patch, timeout=15)
            if r_patch.status_code in (200, 204):
                total_updated += len(ids)
                consecutive_errors = 0
            else:
                consecutive_errors += 1
                if consecutive_errors > 3:
                    break
                time.sleep(1)
        except Exception:
            consecutive_errors += 1
            if consecutive_errors > 3:
                break
            time.sleep(1)

    elapsed = time.time() - t0
    return code, total_updated, elapsed

def revisar_banco_outubro():
    print("\n" + "=" * 80)
    print(">>> INICIANDO REVISAO DO BANCO DE DADOS - MES 10/2026 (STC LESTE)")
    print("=" * 80, flush=True)

    # 1. Atualizar team_delivery_records no Supabase para Outubro/2026
    print("\n[ETAPA 1/4] Atualizando 'team_delivery_records' no Supabase para 10/2026 (3 workers paralelos)...", flush=True)
    t0_deliv = time.time()
    total_deliv_updated = 0
    all_codes = sorted(ALL_STC_LESTE_CODES)

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_code = {executor.submit(processar_equipe_delivery, c): c for c in all_codes}
        completed_count = 0
        for future in as_completed(future_to_code):
            code, cnt, el = future.result()
            completed_count += 1
            total_deliv_updated += cnt
            print(f"  [{completed_count:02d}/25] Equipe {code}: {cnt} registros atualizados ({el:.1f}s)", flush=True)

    print(f" -> Total em team_delivery_records atualizado: {total_deliv_updated} registros em {time.time() - t0_deliv:.1f}s.", flush=True)

    # 2. Atualizar team_scanner_records no Supabase para Outubro/2026
    print("\n[ETAPA 2/4] Atualizando 'team_scanner_records' no Supabase para 10/2026...", flush=True)
    headers = get_headers().copy()
    headers["Prefer"] = "return=minimal"
    patch_payload_scan = {
        "tipo_equipe": "STC LESTE"
    }

    total_scan_updated = 0
    for code in all_codes:
        url = f"{BASE_REST_URL}/team_scanner_records?equipe_normalizada=eq.{code}&data_referencia=gte.2026-10-01&data_referencia=lte.2026-10-31"
        try:
            r = requests.patch(url, json=patch_payload_scan, headers=headers, timeout=15)
            if r.status_code in (200, 204):
                total_scan_updated += 1
        except Exception as e:
            print(f"  [WARN] {code} scanner patch: {e}", flush=True)

    print(f" -> team_scanner_records processado com sucesso ({total_scan_updated}/25).", flush=True)

    # 3. Atualizar delivery_daily_cache.json
    print("\n[ETAPA 3/4] Atualizando 'delivery_daily_cache.json'...", flush=True)
    cache_path = os.path.join(ROOT_DIR, "delivery_daily_cache.json")
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            d_cache = json.load(f)
        teams = d_cache.get("accumulated_teams", {})
        c_upd = 0
        for code, t in teams.items():
            c_up = str(code).strip().upper()
            if c_up in ALL_STC_LESTE_CODES:
                t["vehicle_type"] = "STC Leste"
                t["unified_group"] = "STC Leste"
                t["vehicle_category"] = "STC Leste"
                t["vehicle_badge_class"] = "badge-vehicle-stc-leste"
                t["vehicle_pill_class"] = "pill-stc-leste"
                c_upd += 1
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(d_cache, f, ensure_ascii=False, indent=2)
        print(f" -> {c_upd} equipes atualizadas no cache diario local.", flush=True)

    # 4. Invalidacao de Cache e Teste de get_monthly_audit_data('2026-10')
    print("\n[ETAPA 4/4] Limpando caches e recalculando auditoria de 10/2026...", flush=True)
    delivery_manager.clear_audit_cache("2026-10")
    delivery_manager.clear_audit_cache()
    
    disk_cache = os.path.join(ROOT_DIR, "data", "monthly_audit_2026-10.json")
    if os.path.exists(disk_cache):
        try:
            os.remove(disk_cache)
            print(f" -> Cache em disco {disk_cache} removido.", flush=True)
        except Exception as e:
            print(f" -> Aviso ao remover cache em disco: {e}", flush=True)

    audit_res = delivery_manager.get_monthly_audit_data("2026-10")
    raw_cnt = len(audit_res.get("raw_records", []))
    stc_cnt = sum(1 for r in audit_res.get("raw_records", []) if r.get("vehicle_type") == "STC Leste")
    ramal_cnt = sum(1 for r in audit_res.get("raw_records", []) if r.get("vehicle_type") == "Projeto Ramal")
    leve_cnt = sum(1 for r in audit_res.get("raw_records", []) if r.get("vehicle_type") == "Veículo Leve")
    
    print("\n" + "=" * 80)
    print("REVISAO CONCLUIDA COM SUCESSO!")
    print(f"  Mes: {audit_res.get('month')}")
    print(f"  Total de registros analisados: {raw_cnt}")
    print(f"  Dias operacionais: {audit_res.get('operating_days')}")
    print(f"  Media Diaria Total: {audit_res.get('avg_total')}")
    print(f"  Media STC Leste: {audit_res.get('avg_stc_leste')} (Total no mes: {stc_cnt})")
    print(f"  Media Projeto Ramal: {audit_res.get('avg_ramal')} (Total no mes: {ramal_cnt})")
    print(f"  Media Veiculo Leve: {audit_res.get('avg_leve')} (Total no mes: {leve_cnt})")
    print(f"  Dimensoes de veiculos: {audit_res.get('unique_dimensions', {}).get('vehicles', [])}")
    print("=" * 80 + "\n", flush=True)

if __name__ == "__main__":
    revisar_banco_outubro()
