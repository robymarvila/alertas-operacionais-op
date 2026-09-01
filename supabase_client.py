"""
Supabase Client - Conexão e Sincronização Relacional em Nuvem
Suporta persistência granular de sessões de coleta, histórico auditável por equipe (linha a linha)
e consultas relacionais para a tela de Auditoria & Histórico.
"""

import os
import requests
import json
from datetime import datetime

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xgfawbqllikosyngfvwa.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_uDfIgt5BLYkRJMU540FMcA_LbaubJox")

# Limpa a URL base da API REST
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

def push_snapshot_to_supabase(consolidated_data, sync_source="Sincronização Automática"):
    """
    Persiste a sessão de coleta e todos os registros individuais de equipes (relacional)
    nas tabelas 'operational_sync_sessions' e 'team_operational_logs'.
    """
    try:
        summary = consolidated_data.get("summary", {})
        teams = consolidated_data.get("teams", [])
        now = datetime.now()
        date_today = now.strftime("%Y-%m-%d")

        # 1. Inserir Sessão na tabela 'operational_sync_sessions'
        session_payload = {
            "captured_at": now.isoformat(),
            "date_ref": date_today,
            "sync_source": sync_source,
            "compliance_rate": float(summary.get("compliance_rate", 0)),
            "total_teams": int(summary.get("total_teams", 0)),
            "total_trbonet": int(summary.get("total_trbonet", 0)),
            "total_poweron": int(summary.get("total_poweron", 0)),
            "offline_teams": int(summary.get("offline", 0)),
            "poweron_sync_time": summary.get("last_poweron_login", "--"),
            "trbonet_sync_time": summary.get("last_trbonet_sync", "--")
        }

        endpoint_session = f"{BASE_REST_URL}/operational_sync_sessions"
        resp_session = requests.post(endpoint_session, headers=get_headers(), json=session_payload, timeout=10)
        
        session_id = None
        if resp_session.status_code in [200, 201]:
            session_data = resp_session.json()
            if isinstance(session_data, list) and len(session_data) > 0:
                session_id = session_data[0].get("id")

        # 2. Inserir Linhas Individuais por Equipe na tabela 'team_operational_logs'
        if teams and len(teams) > 0:
            logs_payload = []
            for t in teams:
                team_code = str(t.get("code", "")).strip().upper()
                if not team_code:
                    continue
                logs_payload.append({
                    "session_id": session_id,
                    "captured_at": now.isoformat(),
                    "date_ref": date_today,
                    "team_code": team_code,
                    "base_code": str(t.get("prefix", "")).strip().upper(),
                    "region": str(t.get("region", "Outras Bases")),
                    "in_poweron": bool(t.get("poweron", False)),
                    "in_trbonet": bool(t.get("trbonet", False)),
                    "status": str(t.get("status_category", "OFFLINE")),
                    "has_gps": bool(t.get("gps", False)),
                    "radio_id": str(t.get("radio_id", "--")),
                    "channel": str(t.get("channel", "--")),
                    "last_signal": str(t.get("last_signal", "--")),
                    "poweron_login_time": str(t.get("login_time", "--")),
                    "poweron_vehicle": str(t.get("vehicle", "--"))
                })

            # Inserir em lotes de 100 para alta performance
            endpoint_logs = f"{BASE_REST_URL}/team_operational_logs"
            batch_size = 100
            for i in range(0, len(logs_payload), batch_size):
                batch = logs_payload[i:i + batch_size]
                r_batch = requests.post(endpoint_logs, headers=get_headers(), json=batch, timeout=15)
                if r_batch.status_code not in [200, 201]:
                    print(f"[SUPABASE] Aviso lote de logs: HTTP {r_batch.status_code} - {r_batch.text}")

        # 3. Manter o snapshot em tempo real em 'operational_snapshots' (para carregamento instantâneo)
        try:
            snapshot_payload = {
                "last_trbonet_sync": summary.get("last_trbonet_sync", "--"),
                "last_poweron_login": summary.get("last_poweron_login", "--"),
                "compliance_rate": float(summary.get("compliance_rate", 0)),
                "total_teams": int(summary.get("total_teams", 0)),
                "total_trbonet": int(summary.get("total_trbonet", 0)),
                "total_poweron": int(summary.get("total_poweron", 0)),
                "data_json": consolidated_data
            }
            requests.post(f"{BASE_REST_URL}/operational_snapshots", headers=get_headers(), json=snapshot_payload, timeout=8)
        except Exception:
            pass

        print(f"[SUPABASE] Sessão {session_id} e {len(teams)} logs relacionais gravados com sucesso! ({now.strftime('%H:%M:%S')})")
        return {"status": "success", "session_id": session_id, "teams_logged": len(teams)}
    except Exception as e:
        print(f"[SUPABASE] Erro ao gravar dados relacionais: {e}")
        return {"status": "error", "message": str(e)}

def fetch_latest_snapshot_from_supabase():
    """
    Recupera o snapshot operacional mais recente do Supabase.
    Se as tabelas do Supabase estiverem vazias, retorna status: empty.
    """
    try:
        # 1. Verifica se existem sessões na tabela relacional 'operational_sync_sessions'
        endpoint_sessions = f"{BASE_REST_URL}/operational_sync_sessions?select=id&limit=1"
        resp_sessions = requests.get(endpoint_sessions, headers=get_headers(), timeout=6)
        if resp_sessions.status_code == 200:
            sessions = resp_sessions.json()
            if not sessions or len(sessions) == 0:
                return {"status": "empty", "data": None}

        # 2. Busca o snapshot consolidado mais recente
        endpoint = f"{BASE_REST_URL}/operational_snapshots?select=*&order=created_at.desc&limit=1"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            records = response.json()
            if records and len(records) > 0:
                latest = records[0]
                return {"status": "success", "data": latest.get("data_json", {})}
        return {"status": "empty", "data": None}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": None}

def fetch_audit_logs(date_ref=None, team_code=None, base_code=None, status=None, limit=200):
    """
    Consulta o histórico relacional de coletas na tabela 'team_operational_logs'.
    Permite filtrar por data, equipe, base e status.
    """
    try:
        params = [f"limit={limit}", "order=captured_at.desc"]
        if date_ref:
            params.append(f"date_ref=eq.{date_ref}")
        if team_code:
            params.append(f"team_code=ilike.*{team_code}*")
        if base_code and base_code != "ALL":
            params.append(f"base_code=eq.{base_code}")
        if status and status != "ALL":
            params.append(f"status=eq.{status}")

        query_str = "&".join(params)
        endpoint = f"{BASE_REST_URL}/team_operational_logs?select=*{'&' + query_str if query_str else ''}"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "message": response.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def clear_all_supabase_data():
    """
    Limpa todas as tabelas operacionais no Supabase (logs, sessões e snapshots).
    """
    try:
        zero_uuid = "00000000-0000-0000-0000-000000000000"
        requests.delete(f"{BASE_REST_URL}/team_operational_logs?id=gte.0", headers=get_headers(), timeout=10)
        requests.delete(f"{BASE_REST_URL}/operational_sync_sessions?id=neq.{zero_uuid}", headers=get_headers(), timeout=10)
        requests.delete(f"{BASE_REST_URL}/operational_snapshots?created_at=gt.1970-01-01", headers=get_headers(), timeout=10)
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def fetch_daily_audit_summary(date_ref=None, base_code=None):
    """
    Consulta a View 'vw_team_daily_audit' para obter o consolidado de auditoria por equipe no dia.
    Responde se a equipe conectou no TRBOnet em algum momento do dia, quantas vezes e uptime.
    """
    try:
        params = ["order=team_code.asc"]
        if date_ref:
            params.append(f"date_ref=eq.{date_ref}")
        if base_code and base_code != "ALL":
            params.append(f"base_code=eq.{base_code}")

        query_str = "&".join(params)
        endpoint = f"{BASE_REST_URL}/vw_team_daily_audit?select=*{'&' + query_str if query_str else ''}"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "message": response.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def fetch_team_timeline(team_code, date_ref=None):
    """
    Retorna a linha do tempo completa de coletas de uma equipe específica em um determinado dia.
    Permite verificar exatamente em quais horários o rádio/GPS transmitiu sinal.
    """
    try:
        params = [f"team_code=eq.{team_code.upper()}", "order=captured_at.asc"]
        if date_ref:
            params.append(f"date_ref=eq.{date_ref}")

        query_str = "&".join(params)
        endpoint = f"{BASE_REST_URL}/team_operational_logs?select=*{'&' + query_str if query_str else ''}"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "message": response.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

# ==============================================================================
# FILA DE COMANDOS REMOTOS (CLOUD -> AGENTE LOCAL WINDOWS)
# ==============================================================================

def create_sync_command(command_name: str, payload: dict = None) -> dict:
    """Insere um comando na tabela 'system_commands' para ser executado pelo agente local Windows."""
    try:
        body = {
            "command": command_name,
            "status": "PENDING",
            "payload": payload or {},
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        endpoint = f"{BASE_REST_URL}/system_commands"
        resp = requests.post(endpoint, headers=get_headers(), json=body, timeout=5)
        if resp.status_code in [200, 201]:
            data = resp.json()
            cmd_id = data[0].get("id") if isinstance(data, list) and data else None
            return {"status": "success", "command_id": cmd_id}
        return {"status": "error", "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_pending_commands() -> list:
    """Busca comandos pendentes aguardando execução pelo robô local."""
    try:
        endpoint = f"{BASE_REST_URL}/system_commands?status=eq.PENDING&order=created_at.asc&limit=5"
        resp = requests.get(endpoint, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception:
        return []

def update_command_status(command_id: str, status: str, result: dict = None) -> bool:
    """Atualiza o status de um comando (PROCESSING, COMPLETED, ERROR)."""
    try:
        body = {
            "status": status,
            "result": result or {},
            "updated_at": datetime.now().isoformat()
        }
        endpoint = f"{BASE_REST_URL}/system_commands?id=eq.{command_id}"
        resp = requests.patch(endpoint, headers=get_headers(), json=body, timeout=5)
        return resp.status_code in [200, 204]
    except Exception:
        return False

def wait_for_command_completion(command_id: str, timeout_seconds: int = 10) -> dict:
    """Aguarda até que o agente local execute o comando e grave o resultado no Supabase."""
    import time
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            endpoint = f"{BASE_REST_URL}/system_commands?id=eq.{command_id}&select=*"
            resp = requests.get(endpoint, headers=get_headers(), timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                if data and isinstance(data, list):
                    cmd = data[0]
                    if cmd.get("status") in ["COMPLETED", "ERROR"]:
                        return cmd
        except Exception:
            pass
        time.sleep(0.8)
    return {"status": "TIMEOUT", "message": "O Agente Local não respondeu a tempo."}
