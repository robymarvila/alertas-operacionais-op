"""
Supabase Client - Conexão e Sincronização Relacional em Nuvem
Suporta persistência granular de sessões de coleta, histórico auditável por equipe (linha a linha)
e consultas relacionais para a tela de Auditoria & Histórico.
"""

import os
import requests
import json
from datetime import datetime, timedelta

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

# ==============================================================================
# PERSISTÊNCIA RELACIONAL DO MÓDULO DE ENTREGA DE EQUIPES (ENEL)
# ==============================================================================

def push_delivery_snapshot_to_supabase(delivery_data: dict, sync_source="Portal Enel SP") -> dict:
    """Grava o cabeçalho da sessão de entrega e as linhas individuais no Supabase (ativas + acumuladas do dia)."""
    try:
        active_teams = delivery_data.get("active_teams") or delivery_data.get("teams") or []
        daily_total = delivery_data.get("daily_total_teams") or []
        summary_active = delivery_data.get("summary_active") or delivery_data.get("summary") or {}
        now = datetime.now()
        date_today = delivery_data.get("date") or now.strftime("%Y-%m-%d")

        counts_v = summary_active.get("counts_vehicle", {})
        counts_c = summary_active.get("counts_company", {})

        session_payload = {
            "captured_at": now.isoformat(),
            "date_ref": date_today,
            "total_teams": int(summary_active.get("total", len(active_teams))),
            "total_cesto": int(counts_v.get("Cesto Aéreo", 0)),
            "total_veiculo_leve": int(counts_v.get("Veículo Leve", 0)),
            "total_moto": int(counts_v.get("Moto", 0)),
            "total_munck": int(counts_v.get("Munck", 0)),
            "total_linha_viva": int(counts_v.get("Linha Viva", 0)),
            "total_alpitel": int(counts_c.get("Alpitel", 0)),
            "total_propria": int(counts_c.get("Própria", 0)),
            "sync_source": sync_source
        }

        endpoint_session = f"{BASE_REST_URL}/team_delivery_sessions"
        resp_session = requests.post(endpoint_session, headers=get_headers(), json=session_payload, timeout=10)
        
        session_id = None
        if resp_session.status_code in [200, 201]:
            s_data = resp_session.json()
            if isinstance(s_data, list) and s_data:
                session_id = s_data[0].get("id")

        # Persiste o universo completo do dia nesta sessão: equipes ativas (is_active=True) e concluídas (is_active=False)
        teams_to_save = daily_total if daily_total and len(daily_total) >= len(active_teams) else active_teams

        if teams_to_save and len(teams_to_save) > 0:
            records_payload = []
            for t in teams_to_save:
                is_act = bool(t.get("is_active", True))
                records_payload.append({
                    "session_id": session_id,
                    "captured_at": now.isoformat(),
                    "date_ref": date_today,
                    "team_code": str(t.get("team_code", "")).upper(),
                    "base_code": str(t.get("base_code", "")).upper(),
                    "base_name": str(t.get("base_name", "")),
                    "base_display": str(t.get("base_display") or t.get("base_name", "")),
                    "region": str(t.get("region", "Outras Bases")),
                    "company": str(t.get("company", "Outros")),
                    "vehicle_type": str(t.get("vehicle_type", "Outros")),
                    "vehicle_category": str(t.get("vehicle_category", "Pesado")),
                    "unified_group": str(t.get("unified_group", "Cesto Aéreo")),
                    "login_time": str(t.get("login_time", "--")),
                    "logoff_time": str(t.get("logoff_time", "--")),
                    "shift_slot": str(t.get("shift_slot", "Turno 08:00")),
                    "shift_code": str(t.get("shift_code", "08:00")),
                    "status": str(t.get("status", "Logada")),
                    "driver": str(t.get("driver", "--")),
                    "plate": str(t.get("plate", "--")),
                    "ut": str(t.get("ut", "--")),
                    "filial": str(t.get("filial", "--")),
                    "is_active": is_act,
                    "sync_source": sync_source
                })

            # Inserção em lotes de 100
            endpoint_records = f"{BASE_REST_URL}/team_delivery_records"
            for i in range(0, len(records_payload), 100):
                chunk = records_payload[i:i+100]
                requests.post(endpoint_records, headers=get_headers(), json=chunk, timeout=10)

        return {"status": "success", "session_id": session_id, "total_records": len(teams_to_save)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def fetch_latest_delivery_snapshot_from_supabase() -> dict:
    """Busca estritamente os registros da última sessão de entrega ativa gravada no Supabase."""
    try:
        # 1. Busca a sessão mais recente que contenha registros (total_teams > 0)
        endpoint_sess = f"{BASE_REST_URL}/team_delivery_sessions?total_teams=gt.0&order=captured_at.desc&limit=1"
        resp_sess = requests.get(endpoint_sess, headers=get_headers(), timeout=10)
        
        latest_session_id = None
        if resp_sess.status_code == 200:
            sessions = resp_sess.json() or []
            if sessions:
                latest_session_id = sessions[0].get("id")

        if latest_session_id:
            endpoint_recs = f"{BASE_REST_URL}/team_delivery_records?session_id=eq.{latest_session_id}&order=team_code.asc&limit=1000"
            resp_recs = requests.get(endpoint_recs, headers=get_headers(), timeout=10)
            if resp_recs.status_code == 200:
                records = resp_recs.json() or []
                if records:
                    return {"status": "success", "data": records, "session_id": latest_session_id}

        # Fallback: busca os últimos registros deduplicando por team_code
        endpoint = f"{BASE_REST_URL}/team_delivery_records?order=captured_at.desc&limit=300"
        resp = requests.get(endpoint, headers=get_headers(), timeout=10)
        if resp.status_code == 200:
            raw_records = resp.json() or []
            seen = set()
            dedup = []
            for r in raw_records:
                code = r.get("team_code")
                if code and code not in seen:
                    seen.add(code)
                    dedup.append(r)
            return {"status": "success", "data": dedup}
        return {"status": "error", "message": resp.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def fetch_delivery_records_by_date(date_str: str) -> list:
    """Busca registros históricos de equipes entregues para uma data específica (YYYY-MM-DD)."""
    try:
        endpoint = f"{BASE_REST_URL}/team_delivery_records?date_ref=eq.{date_str}&order=team_code.asc&limit=1000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[SUPABASE FETCH DATE ERROR] {e}")
        return []

def fetch_delivery_sessions_by_month(month_str: str) -> list:
    """Busca cabeçalhos de sessões de entrega de um determinado mês (YYYY-MM)."""
    try:
        endpoint = f"{BASE_REST_URL}/team_delivery_sessions?date_ref=gte.{month_str}-01&date_ref=lte.{month_str}-31&order=date_ref.asc&limit=1000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[SUPABASE FETCH MONTH ERROR] {e}")
        return []

# ==============================================================================
# MÓDULO SPOTFIRE: PERSISTÊNCIA E CONSULTA DE EXTRAÇÕES (TIBCO SPOTFIRE ENEL)
# ==============================================================================

def push_spotfire_records_to_supabase(records_list: list) -> dict:
    """
    Insere ou atualiza (UPSERT) registros extraídos do Spotfire na tabela 'team_spotfire_records'.
    Usa a constraint única (data_referencia, equipe_normalizada) para merge atômico.
    """
    if not records_list:
        return {"status": "success", "count": 0}
    try:
        endpoint = f"{BASE_REST_URL}/team_spotfire_records?on_conflict=data_referencia,equipe_normalizada"
        headers = get_headers().copy()
        headers["Prefer"] = "resolution=merge-duplicates,return=representation"
        
        saved_count = 0
        for i in range(0, len(records_list), 100):
            chunk = records_list[i:i+100]
            resp = requests.post(endpoint, headers=headers, json=chunk, timeout=15)
            if resp.status_code in [200, 201]:
                saved_count += len(chunk)
            else:
                print(f"[WARN SUPABASE SPOTFIRE UPSERT] Status {resp.status_code}: {resp.text}")
                
        return {"status": "success", "count": saved_count}
    except Exception as e:
        print(f"[ERROR SUPABASE SPOTFIRE PUSH] {e}")
        return {"status": "error", "message": str(e), "count": 0}

def fetch_spotfire_records_by_date(date_str: str) -> list:
    """
    Busca registros extraídos do Spotfire para uma data específica (YYYY-MM-DD).
    """
    try:
        endpoint = f"{BASE_REST_URL}/team_spotfire_records?data_referencia=eq.{date_str}&order=equipe_normalizada.asc&limit=2000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[SUPABASE FETCH SPOTFIRE ERROR] {e}")
        return []


# ==============================================================================
# MONITORAMENTO DE SAÚDE DOS MOTORES (ENGINE HEALTH)
# ==============================================================================

def update_engine_health(engine_name: str, status: str, is_running: bool = True,
                         error_type: str = "NONE", last_error: str = None,
                         records_count: int = 0) -> dict:
    """
    Atualiza o estado de um motor na tabela 'system_engine_health'.
    status: 'OPERATIONAL', 'ERROR_CONNECTION', 'STOPPED', 'WARNING'
    error_type: 'NONE', 'CONNECTION_REFUSED', 'TIMEOUT', 'PROCESS_STOPPED'
    """
    try:
        payload = {
            "status": status,
            "is_running": is_running,
            "error_type": error_type,
            "last_heartbeat": datetime.now().isoformat(),
            "records_count": records_count
        }
        if status == "OPERATIONAL":
            payload["last_success_sync"] = datetime.now().isoformat()
            payload["consecutive_errors"] = 0
            payload["last_error_message"] = None
        else:
            payload["last_error_message"] = str(last_error or "")

        headers = get_headers()
        headers["Prefer"] = "return=representation"
        endpoint = f"{BASE_REST_URL}/system_engine_health?engine_name=eq.{engine_name}"
        resp = requests.patch(endpoint, headers=headers, json=payload, timeout=6)
        if resp.status_code in [200, 204]:
            return {"status": "success"}
        return {"status": "error", "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def fetch_all_engine_health() -> list:
    """Busca o status em tempo real de todos os motores cadastrados no Supabase."""
    try:
        endpoint = f"{BASE_REST_URL}/system_engine_health?order=engine_name.asc"
        resp = requests.get(endpoint, headers=get_headers(), timeout=6)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[FETCH ENGINE HEALTH ERROR] {e}")
        return []

# ==============================================================================
# TELEMETRIA DE SESSÕES E AUDITORIA DE USUÁRIOS
# ==============================================================================

def upsert_user_session(session_data: dict) -> dict:
    """
    Registra ou atualiza o heartbeat de uma sessão de usuário no Supabase.
    Armazena Fingerprint, IP, Geolocalização, Dispositivo e Navegador.
    """
    try:
        session_id = session_data.get("session_id")
        if not session_id:
            return {"status": "error", "message": "session_id é obrigatório"}

        payload = {
            "session_id": session_id,
            "username": session_data.get("username", "Colaborador"),
            "fingerprint": session_data.get("fingerprint", "desconhecido"),
            "ip_address": session_data.get("ip_address", "127.0.0.1"),
            "device_type": session_data.get("device_type", "Desktop"),
            "device_brand": session_data.get("device_brand", ""),
            "os_name": session_data.get("os_name", "Windows"),
            "browser_name": session_data.get("browser_name", "Navegador"),
            "geo_city": session_data.get("geo_city", "São Paulo"),
            "geo_region": session_data.get("geo_region", "SP"),
            "geo_country": session_data.get("geo_country", "Brasil"),
            "last_heartbeat": datetime.now().isoformat(),
            "is_active": True
        }

        headers = get_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        endpoint = f"{BASE_REST_URL}/system_user_sessions"
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=6)
        if resp.status_code in [200, 201]:
            return {"status": "success"}
        return {"status": "error", "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def log_user_access(access_data: dict) -> dict:
    """Grava uma entrada de log na tabela de auditoria temporal 'system_user_access_logs'."""
    try:
        payload = {
            "session_id": access_data.get("session_id"),
            "fingerprint": access_data.get("fingerprint", ""),
            "username": access_data.get("username", "Colaborador"),
            "ip_address": access_data.get("ip_address", "127.0.0.1"),
            "device_type": access_data.get("device_type", "Desktop"),
            "os_name": access_data.get("os_name", "Windows"),
            "browser_name": access_data.get("browser_name", "Navegador"),
            "geo_city": access_data.get("geo_city", "São Paulo"),
            "endpoint": access_data.get("endpoint", "/"),
            "accessed_at": datetime.now().isoformat(),
            "date_ref": datetime.now().strftime("%Y-%m-%d")
        }
        endpoint = f"{BASE_REST_URL}/system_user_access_logs"
        resp = requests.post(endpoint, headers=get_headers(), json=payload, timeout=6)
        if resp.status_code in [200, 201]:
            return {"status": "success"}
        return {"status": "error", "message": resp.text}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def fetch_session_telemetry_metrics() -> dict:
    """
    Retorna métricas consolidadas de usuários ativos agora, hoje, semana e mês,
    além da lista forense de sessões auditadas.
    """
    try:
        now = datetime.now()
        date_today = now.strftime("%Y-%m-%d")
        
        # 1. Sessões com heartbeat nos últimos 5 minutos (Ativos Agora)
        five_min_ago = (now - timedelta(minutes=5)).isoformat()
        ep_active = f"{BASE_REST_URL}/system_user_sessions?last_heartbeat=gte.{five_min_ago}&order=last_heartbeat.desc"
        resp_act = requests.get(ep_active, headers=get_headers(), timeout=6)
        active_sessions = resp_act.json() if resp_act.status_code == 200 else []
        active_count = len(active_sessions)

        # 2. Todas as sessões recentes (até 100)
        ep_all = f"{BASE_REST_URL}/system_user_sessions?order=last_heartbeat.desc&limit=100"
        resp_all = requests.get(ep_all, headers=get_headers(), timeout=6)
        recent_sessions = resp_all.json() if resp_all.status_code == 200 else []

        # 3. Contagem de acessos Hoje
        ep_today = f"{BASE_REST_URL}/system_user_access_logs?date_ref=eq.{date_today}&select=id,fingerprint"
        resp_today = requests.get(ep_today, headers=get_headers(), timeout=6)
        logs_today = resp_today.json() if resp_today.status_code == 200 else []
        unique_today = len(set(l.get("fingerprint") for l in logs_today if l.get("fingerprint"))) or len(logs_today)

        # 4. Contagem de acessos Semana (últimos 7 dias)
        seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        ep_week = f"{BASE_REST_URL}/system_user_access_logs?date_ref=gte.{seven_days_ago}&select=id,fingerprint"
        resp_week = requests.get(ep_week, headers=get_headers(), timeout=6)
        logs_week = resp_week.json() if resp_week.status_code == 200 else []
        unique_week = len(set(l.get("fingerprint") for l in logs_week if l.get("fingerprint"))) or len(logs_week)

        # 5. Contagem de acessos Mês (últimos 30 dias)
        thirty_days_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        ep_month = f"{BASE_REST_URL}/system_user_access_logs?date_ref=gte.{thirty_days_ago}&select=id,fingerprint"
        resp_month = requests.get(ep_month, headers=get_headers(), timeout=6)
        logs_month = resp_month.json() if resp_month.status_code == 200 else []
        unique_month = len(set(l.get("fingerprint") for l in logs_month if l.get("fingerprint"))) or len(logs_month)

        return {
            "status": "success",
            "active_now": active_count,
            "today_unique": unique_today,
            "week_unique": unique_week,
            "month_unique": unique_month,
            "active_sessions": active_sessions,
            "recent_sessions": recent_sessions
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "active_now": 0,
            "today_unique": 0,
            "week_unique": 0,
            "month_unique": 0,
            "active_sessions": [],
            "recent_sessions": []
        }


