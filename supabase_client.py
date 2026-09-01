"""
Supabase Client - Conexão e Sincronização em Nuvem
Permite enviar snapshots operacionais locais para o Supabase e recuperar dados na Web (Vercel).
"""

import os
import requests
import json
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xgfawbqllikosyngfvwa.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_uDfIgt5BLYkRJMU540FMcA_LbaubJox")

# Limpa a URL se terminar com /rest/v1 ou /
BASE_REST_URL = SUPABASE_URL.rstrip('/')
if not BASE_REST_URL.endswith('/rest/v1'):
    BASE_REST_URL = f"{BASE_REST_URL}/rest/v1"

def get_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def push_snapshot_to_supabase(consolidated_data):
    """
    Envia o estado operacional consolidado para a tabela 'operational_snapshots' no Supabase.
    """
    try:
        summary = consolidated_data.get("summary", {})
        payload = {
            "last_trbonet_sync": summary.get("last_trbonet_sync", "--"),
            "last_poweron_login": summary.get("last_poweron_login", "--"),
            "compliance_rate": float(summary.get("compliance_rate", 0)),
            "total_teams": int(summary.get("total_teams", 0)),
            "total_trbonet": int(summary.get("total_trbonet", 0)),
            "total_poweron": int(summary.get("total_poweron", 0)),
            "data_json": consolidated_data
        }

        endpoint = f"{BASE_REST_URL}/operational_snapshots"
        response = requests.post(endpoint, headers=get_headers(), json=payload, timeout=10)
        
        if response.status_code in [200, 201]:
            print(f"[SUPABASE] Snapshot sincronizado com sucesso na nuvem! ({datetime.now().strftime('%H:%M:%S')})")
            return {"status": "success", "response": response.json()}
        else:
            print(f"[SUPABASE] Aviso ao enviar: HTTP {response.status_code} - {response.text}")
            return {"status": "error", "message": response.text}
    except Exception as e:
        print(f"[SUPABASE] Erro de conexão com a nuvem: {e}")
        return {"status": "error", "message": str(e)}

def fetch_latest_snapshot_from_supabase():
    """
    Recupera o snapshot operacional mais recente do Supabase.
    """
    try:
        endpoint = f"{BASE_REST_URL}/operational_snapshots?select=*&order=created_at.desc&limit=1"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            records = response.json()
            if records and len(records) > 0:
                latest = records[0]
                data_json = latest.get("data_json", {})
                return {"status": "success", "data": data_json}
        return {"status": "empty", "data": None}
    except Exception as e:
        print(f"[SUPABASE] Erro ao buscar snapshot: {e}")
        return {"status": "error", "message": str(e), "data": None}
