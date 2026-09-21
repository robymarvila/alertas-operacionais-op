"""
Supabase Client - Conexão e Sincronização Relacional em Nuvem
Suporta persistência granular de sessões de coleta, histórico auditável por equipe (linha a linha)
e consultas relacionais para a tela de Auditoria & Histórico.
"""

import os
import requests
import json
from datetime import datetime, timedelta, timezone

# Fuso Horário Oficial de Operação (Horário de Brasília - UTC-3)
BR_TZ = timezone(timedelta(hours=-3))

def format_datetime_br(val) -> str:
    """Converte com segurança qualquer timestamp (ISO, string ou datetime) para Horário de Brasília."""
    if not val or val == '--':
        return '--'
    if isinstance(val, str):
        if '/' in val and ':' in val:
            return val
        try:
            clean_val = val.replace('Z', '+00:00')
            dt = datetime.fromisoformat(clean_val)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=BR_TZ)
            return dt.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M:%S')
        except Exception:
            return val
    elif isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=BR_TZ)
        return val.astimezone(BR_TZ).strftime('%d/%m/%Y %H:%M:%S')
    return str(val)

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
        from cluster_manager import cluster_manager
        if not cluster_manager.is_feeding_database():
            print(f"[CLUSTER GUARD - BLOQUEADO] Push TRBOnet IGNORADO: Esta maquina ({cluster_manager.node_id}) esta em STANDBY.", flush=True)
            return {"status": "standby_blocked", "message": f"Maquina {cluster_manager.node_id} em Standby"}

        node_host = cluster_manager.config.get("hostname") or "Host"
        sync_source = f"{sync_source} [{cluster_manager.node_id} | {node_host}]"
        summary = consolidated_data.get("summary", {})
        teams = consolidated_data.get("teams", [])
        now = datetime.now(BR_TZ)
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
            if isinstance(date_ref, (list, set, tuple)):
                dates = [str(d).strip() for d in date_ref if str(d).strip()]
            else:
                dates = [str(d).strip() for d in str(date_ref).split(',') if str(d).strip()]
            if len(dates) == 1:
                params.append(f"date_ref=eq.{dates[0]}")
            elif len(dates) > 1:
                params.append(f"date_ref=in.({','.join(dates)})")
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
    Suporta múltiplas datas e bases (separadas por vírgula ou lista).
    """
    try:
        params = ["order=team_code.asc"]
        if date_ref:
            if isinstance(date_ref, (list, set, tuple)):
                dates = [str(d).strip() for d in date_ref if str(d).strip()]
            else:
                dates = [str(d).strip() for d in str(date_ref).split(',') if str(d).strip()]
            if len(dates) == 1:
                params.append(f"date_ref=eq.{dates[0]}")
            elif len(dates) > 1:
                params.append(f"date_ref=in.({','.join(dates)})")

        if base_code and base_code != "ALL":
            if isinstance(base_code, (list, set, tuple)):
                bases = [str(b).strip().upper() for b in base_code if str(b).strip() and str(b).strip().upper() != "ALL"]
            else:
                bases = [str(b).strip().upper() for b in str(base_code).split(',') if str(b).strip() and str(b).strip().upper() != "ALL"]
            if len(bases) == 1:
                params.append(f"base_code=eq.{bases[0]}")
            elif len(bases) > 1:
                params.append(f"base_code=in.({','.join(bases)})")

        query_str = "&".join(params)
        endpoint = f"{BASE_REST_URL}/vw_team_daily_audit?select=*{'&' + query_str if query_str else ''}"
        response = requests.get(endpoint, headers=get_headers(), timeout=10)
        
        if response.status_code == 200:
            return {"status": "success", "data": response.json()}
        else:
            return {"status": "error", "message": response.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def fetch_audit_delivery_marcacoes(date_refs):
    """
    Busca horários de marcação da tabela team_delivery_records para enriquecer a auditoria diária.
    Retorna dicionário {(team_code, date_ref): marcacao} e mapa de contingência {team_code: marcacao}.
    """
    try:
        if not date_refs:
            return {}
        if isinstance(date_refs, (list, set, tuple)):
            dates = [str(d).strip() for d in date_refs if str(d).strip()]
        else:
            dates = [str(d).strip() for d in str(date_refs).split(',') if str(d).strip()]
        if not dates:
            return {}
        
        if len(dates) == 1:
            date_filter = f"date_ref=eq.{dates[0]}"
        else:
            date_filter = f"date_ref=in.({','.join(dates)})"
            
        endpoint = f"{BASE_REST_URL}/team_delivery_records?select=team_code,date_ref,marcacao&{date_filter}&limit=2000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=10)
        marc_map = {}
        if resp.status_code == 200:
            recs = resp.json() or []
            for r in recs:
                tc = (r.get("team_code") or "").strip().upper()
                dr = (r.get("date_ref") or "").strip()
                m = (r.get("marcacao") or "").strip()
                if tc and m and m != "--":
                    marc_map[(tc, dr)] = m
                    marc_map[tc] = m  # Fallback
        return marc_map
    except Exception as e:
        print(f"[SUPABASE FETCH MARCACOES ERROR] {e}")
        return {}

def fetch_team_timeline(team_code, date_ref=None):
    """
    Retorna a linha do tempo completa de coletas de uma equipe específica em um determinado dia.
    Permite verificar exatamente em quais horários o rádio/GPS transmitiu sinal.
    Suporta paginação via cabeçalho Range para evitar truncamento do PostgREST.
    """
    try:
        params = [f"team_code=eq.{team_code.upper()}", "order=captured_at.asc"]
        if date_ref:
            params.append(f"date_ref=eq.{date_ref}")

        query_str = "&".join(params)
        endpoint = f"{BASE_REST_URL}/team_operational_logs?select=*{'&' + query_str if query_str else ''}"
        
        all_rows = []
        page_size = 1000
        for page in range(4): # Até 4000 registros no dia
            start_offset = page * page_size
            end_offset = start_offset + page_size - 1
            headers = get_headers()
            headers["Range"] = f"{start_offset}-{end_offset}"
            response = requests.get(endpoint, headers=headers, timeout=12)
            
            if response.status_code in [200, 206]:
                chunk = response.json() or []
                all_rows.extend(chunk)
                if len(chunk) < page_size:
                    break
            else:
                if page == 0:
                    return {"status": "error", "message": response.text, "data": []}
                break

        return {"status": "success", "data": all_rows}
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
            "created_at": datetime.now(BR_TZ).isoformat(),
            "updated_at": datetime.now(BR_TZ).isoformat()
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
            "updated_at": datetime.now(BR_TZ).isoformat()
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
        from cluster_manager import cluster_manager
        if not cluster_manager.is_feeding_database():
            print(f"[CLUSTER GUARD - BLOQUEADO] Push Entrega Enel IGNORADO: Esta maquina ({cluster_manager.node_id}) esta em STANDBY.", flush=True)
            return {"status": "standby_blocked", "message": f"Maquina {cluster_manager.node_id} em Standby"}

        node_host = cluster_manager.config.get("hostname") or "Host"
        sync_source = f"{sync_source} [{cluster_manager.node_id} | {node_host}]"

        active_teams = delivery_data.get("active_teams") or delivery_data.get("teams") or []
        daily_total = delivery_data.get("daily_total_teams") or []
        summary_active = delivery_data.get("summary_active") or delivery_data.get("summary") or {}
        now = datetime.now(BR_TZ)
        date_today = delivery_data.get("date") or now.strftime("%Y-%m-%d")

        counts_v = summary_active.get("counts_vehicle", {})
        counts_c = summary_active.get("counts_company", {})

        session_payload = {
            "captured_at": now.isoformat(),
            "date_ref": date_today,
            "total_teams": int(summary_active.get("total", len(active_teams))),
            "total_cesto": int(summary_active.get("cesto") or counts_v.get("Cesto Aéreo", 0)),
            "total_veiculo_leve": int(summary_active.get("leve") or counts_v.get("Veículo Leve", 0)),
            "total_moto": int(summary_active.get("moto") or counts_v.get("Moto", 0)),
            "total_munck": int(summary_active.get("munck") or counts_v.get("Munck", 0)),
            "total_linha_viva": int(summary_active.get("linhaviva") or counts_v.get("Linha Viva", 0)),
            "total_alpitel": int(summary_active.get("alpitel") or counts_c.get("Alpitel", 0)),
            "total_propria": int(summary_active.get("propria") or counts_c.get("Própria", 0)),
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
                    "veiculo_portal": str(t.get("veiculo_portal", "--")),
                    "gps_update_str": str(t.get("gps_update_str", "--")),
                    "gps_update_minutes": t.get("gps_update_minutes"),
                    "status_equipes_brasil": str(t.get("status_equipes_brasil", t.get("status", "Logada"))),
                    "data_inicio_descanso": t.get("data_inicio_descanso"),
                    "hora_inicio_descanso": t.get("hora_inicio_descanso"),
                    "ordem_servico": t.get("ordem_servico"),
                    "marcacao": str(t.get("marcacao", "--")),
                    "desvio": str(t.get("desvio", "--")),
                    "desvio_minutos": t.get("desvio_minutos", 0),
                    "order_history": t.get("order_history", []),
                    "plate_clean": str(t.get("plate_clean", "")),
                    "plate_cadastrada": bool(t.get("plate_cadastrada", False)),
                    "situacao_veiculo_cadastrado": str(t.get("situacao_veiculo_cadastrado", "SEM PLACA INFORMADA")),
                    "status_veiculo_cadastrado": str(t.get("status_veiculo_cadastrado", "--")),
                    "is_active": is_act,
                    "sync_source": sync_source
                })

            # Inserção em lotes de 100 com tolerância a cache de schema
            endpoint_records = f"{BASE_REST_URL}/team_delivery_records"
            new_column_keys = {
                "veiculo_portal", "gps_update_str", "gps_update_minutes",
                "status_equipes_brasil", "data_inicio_descanso", "hora_inicio_descanso",
                "ordem_servico", "marcacao", "desvio", "desvio_minutos", "order_history",
                "plate_clean", "plate_cadastrada",
                "situacao_veiculo_cadastrado", "status_veiculo_cadastrado"
            }

            for i in range(0, len(records_payload), 100):
                chunk = records_payload[i:i+100]
                resp_rec = requests.post(endpoint_records, headers=get_headers(), json=chunk, timeout=10)
                if resp_rec.status_code not in [200, 201]:
                    # Caso o Supabase ainda não tenha aplicado o schema_cdp_fleet_v5 / v6, faz fallback para colunas base
                    if resp_rec.status_code == 400 and "Could not find" in resp_rec.text:
                        fallback_chunk = []
                        for item in chunk:
                            base_item = {k: v for k, v in item.items() if k not in new_column_keys}
                            fallback_chunk.append(base_item)
                        requests.post(endpoint_records, headers=get_headers(), json=fallback_chunk, timeout=10)

            # Persistência atômica do histórico de ordens na tabela dedicada team_order_history
            try:
                order_records_payload = []
                for t in teams_to_save:
                    t_code = str(t.get("team_code", "")).upper()
                    hist_items = t.get("order_history") or []
                    for item in hist_items:
                        ordem_val = item.get("ordem")
                        if ordem_val and str(ordem_val).strip() not in ["--", "-", "", "None", "nan"]:
                            order_records_payload.append({
                                "date_ref": date_today,
                                "team_code": t_code,
                                "ordem_servico": str(ordem_val).strip(),
                                "status": item.get("status", "Em atendimento"),
                                "cycles_count": item.get("cycles_count", 1)
                            })
                if order_records_payload:
                    endpoint_orders = f"{BASE_REST_URL}/team_order_history?on_conflict=date_ref,team_code,ordem_servico"
                    headers_upsert = get_headers()
                    headers_upsert["Prefer"] = "resolution=merge-duplicates"
                    for i in range(0, len(order_records_payload), 100):
                        requests.post(endpoint_orders, headers=headers_upsert, json=order_records_payload[i:i+100], timeout=8)
            except Exception:
                pass

        return {"status": "success", "session_id": session_id, "total_records": len(teams_to_save)}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def fetch_team_order_history(team_code: str, date_ref: str = None) -> list:
    """Busca o histórico deduplicado de ordens de serviço de uma equipe no Supabase."""
    try:
        if not date_ref:
            date_ref = datetime.now(BR_TZ).strftime("%Y-%m-%d")
        url = f"{BASE_REST_URL}/team_order_history?team_code=eq.{team_code.upper()}&date_ref=eq.{date_ref}&order=first_seen_at.asc"
        resp = requests.get(url, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []

def fetch_latest_delivery_snapshot_from_supabase() -> dict:
    """Busca estritamente os registros da última sessão de entrega ativa gravada no Supabase."""
    try:
        # 1. Busca as sessões mais recentes que contenham equipes
        endpoint_sess = f"{BASE_REST_URL}/team_delivery_sessions?total_teams=gt.0&order=captured_at.desc&limit=5"
        resp_sess = requests.get(endpoint_sess, headers=get_headers(), timeout=8)
        
        if resp_sess.status_code == 200:
            sessions = resp_sess.json() or []
            for s in sessions:
                s_id = s.get("id")
                s_date = s.get("date_ref")
                s_sync_source = s.get("sync_source")
                s_captured_at = s.get("captured_at")
                if not s_id:
                    continue

                date_filter = f"date_ref=eq.{s_date}&" if s_date else ""
                endpoint_recs = f"{BASE_REST_URL}/team_delivery_records?{date_filter}session_id=eq.{s_id}&order=team_code.asc&limit=1000"
                resp_recs = requests.get(endpoint_recs, headers=get_headers(), timeout=8)
                if resp_recs.status_code == 200:
                    records = resp_recs.json() or []
                    if records:
                        rec_captured = s_captured_at or records[0].get("captured_at")
                        return {
                            "status": "success",
                            "data": records,
                            "session_id": s_id,
                            "captured_at": rec_captured,
                            "date_ref": s_date,
                            "sync_source": s_sync_source
                        }

        # Fallback: busca os últimos registros deduplicando por team_code
        endpoint = f"{BASE_REST_URL}/team_delivery_records?order=captured_at.desc&limit=300"
        resp = requests.get(endpoint, headers=get_headers(), timeout=8)
        if resp.status_code == 200:
            raw_records = resp.json() or []
            seen = set()
            dedup = []
            latest_captured_at = None
            for r in raw_records:
                if not latest_captured_at and r.get("captured_at"):
                    latest_captured_at = r.get("captured_at")
                code = r.get("team_code")
                if code and code not in seen:
                    seen.add(code)
                    dedup.append(r)
            return {"status": "success", "data": dedup, "captured_at": latest_captured_at}
        return {"status": "error", "message": resp.text, "data": []}
    except Exception as e:
        return {"status": "error", "message": str(e), "data": []}

def fetch_delivery_records_by_date(date_str: str) -> list:
    """Busca registros históricos de equipes entregues para uma data específica (YYYY-MM-DD)."""
    try:
        endpoint = f"{BASE_REST_URL}/team_delivery_records?date_ref=eq.{date_str}&order=captured_at.desc&limit=2000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            raw = resp.json() or []
            # Deduplica por equipe preservando o snapshot mais recente/completo
            seen = {}
            for r in raw:
                code = r.get("team_code")
                if code and code not in seen:
                    seen[code] = r
            return list(seen.values())
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

def prune_stale_delivery_snapshots(days_retention: int = 45):
    """
    Remove registros detalhados de coletas anteriores a X dias para prevenir inchaço
    no banco de dados e garantir respostas ultrarrápidas (< 50ms) no Supabase.
    Preserva intactas as tabelas diárias consolidadas.
    """
    try:
        cutoff = (datetime.now(BR_TZ).date() - timedelta(days=days_retention)).isoformat()
        headers = get_headers()
        # Remove linhas antigas de team_delivery_records
        requests.delete(f"{BASE_REST_URL}/team_delivery_records?date_ref=lt.{cutoff}", headers=headers, timeout=15)
        # Remove logs operacionais antigos
        requests.delete(f"{BASE_REST_URL}/team_operational_logs?date_ref=lt.{cutoff}", headers=headers, timeout=15)
        # Remove snapshots JSON antigos
        requests.delete(f"{BASE_REST_URL}/operational_snapshots?created_at=lt.{cutoff}", headers=headers, timeout=15)
        # Remove logs de acesso antigos de usuários
        requests.delete(f"{BASE_REST_URL}/system_user_access_logs?date_ref=lt.{cutoff}", headers=headers, timeout=15)
    except Exception as err:
        print(f"[PRUNE WARN] Erro ao expurgar dados antigos: {err}")

# ==============================================================================
# MÓDULO SPOTFIRE & SCANNER 5.0: PERSISTÊNCIA E CONSULTA DE EXTRAÇÕES (TIBCO)
# ==============================================================================

def push_scanner_records_to_supabase(records_list: list) -> dict:
    """
    Insere ou atualiza (UPSERT) registros analíticos do Scanner 5.0 na tabela 'team_scanner_records'.
    Usa a constraint única (data_referencia, equipe_normalizada) para merge atômico (1 equipe por linha).
    """
    if not records_list:
        return {"status": "success", "count": 0}
    try:
        endpoint = f"{BASE_REST_URL}/team_scanner_records?on_conflict=data_referencia,equipe_normalizada"
        headers = get_headers().copy()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
        
        # Deduplica em memória para garantir atomicidade do ON CONFLICT no Postgres
        seen = {}
        for r in records_list:
            k = (str(r.get("data_referencia")), str(r.get("equipe_normalizada")))
            seen[k] = r
        clean_list = list(seen.values())

        saved_count = 0
        chunk_size = 500
        for i in range(0, len(clean_list), chunk_size):
            chunk = clean_list[i:i+chunk_size]
            resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
            if resp.status_code in [200, 201]:
                saved_count += len(chunk)
            else:
                print(f"[WARN SUPABASE SCANNER UPSERT] Status {resp.status_code}: {resp.text}")
                
        return {"status": "success", "count": saved_count}
    except Exception as e:
        print(f"[ERROR SUPABASE SCANNER PUSH] {e}")
        return {"status": "error", "message": str(e), "count": 0}

def fetch_scanner_records_by_date(date_str: str) -> list:
    """
    Busca registros analíticos do Scanner 5.0 para uma data específica (YYYY-MM-DD).
    """
    try:
        endpoint = f"{BASE_REST_URL}/team_scanner_records?data_referencia=eq.{date_str}&order=equipe_normalizada.asc&limit=2000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[SUPABASE FETCH SCANNER ERROR] {e}")
        return []

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
    Busca registros extraídos para uma data específica (YYYY-MM-DD).
    Prioriza a nova tabela 'team_scanner_records' do Scanner 5.0, com fallback para 'team_spotfire_records'.
    """
    # 1. Prioriza nova tabela Scanner 5.0
    scanner_recs = fetch_scanner_records_by_date(date_str)
    if scanner_recs:
        return scanner_recs

    # 2. Fallback legado
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
                         records_count: int = 0, engine_label: str = None,
                         details_json: dict = None) -> dict:
    """
    Atualiza ou insere o estado de um motor na tabela 'system_engine_health' com fuso de Brasília.
    status: 'OPERATIONAL', 'ERROR_CONNECTION', 'STOPPED', 'WARNING'
    error_type: 'NONE', 'CONNECTION_REFUSED', 'TIMEOUT', 'PROCESS_STOPPED'
    """
    try:
        now_iso = datetime.now(BR_TZ).isoformat()
        payload = {
            "engine_name": engine_name,
            "status": status,
            "is_running": is_running,
            "error_type": error_type,
            "last_heartbeat": now_iso,
            "records_count": records_count
        }
        if engine_label:
            payload["engine_label"] = engine_label
        if details_json is not None:
            payload["details_json"] = details_json

        if status == "OPERATIONAL":
            payload["last_success_sync"] = now_iso
            payload["consecutive_errors"] = 0
            payload["last_error_message"] = None
        else:
            payload["last_error_message"] = str(last_error or "")

        headers = get_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        endpoint = f"{BASE_REST_URL}/system_engine_health"
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=6)
        if resp.status_code in [200, 201, 204]:
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
            "last_heartbeat": datetime.now(BR_TZ).isoformat(),
            "is_active": True
        }

        headers = get_headers()
        headers["Prefer"] = "resolution=merge-duplicates"
        endpoint = f"{BASE_REST_URL}/system_user_sessions?on_conflict=session_id"
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=6)
        if resp.status_code in [200, 201, 204]:
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
            "accessed_at": datetime.now(BR_TZ).isoformat(),
            "date_ref": datetime.now(BR_TZ).strftime("%Y-%m-%d")
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
        now = datetime.now(BR_TZ)
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

# ==============================================================================
# MÓDULO DE PLANEJAMENTO E METAS OPERACIONAIS (ENTREGA DE EQUIPES)
# ==============================================================================

PLANNING_TARGETS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "delivery_planning_targets.json")

def fetch_delivery_planning_targets(month_str: str = None) -> dict:
    """
    Retorna as metas operacionais de entrega de equipes (Norte, Leste e Geral).
    Tenta consultar do Supabase (team_delivery_planning_targets) e faz fallback para JSON local.
    """
    targets = None
    if os.path.exists(PLANNING_TARGETS_FILE):
        try:
            with open(PLANNING_TARGETS_FILE, "r", encoding="utf-8") as f:
                targets = json.load(f)
        except Exception:
            pass

    # Tenta enriquecer com dados do Supabase
    try:
        m_filter = month_str or "DEFAULT"
        endpoint = f"{BASE_REST_URL}/team_delivery_planning_targets?target_month=in.({m_filter},DEFAULT)&order=updated_at.desc"
        resp = requests.get(endpoint, headers=get_headers(), timeout=6)
        if resp.status_code == 200:
            rows = resp.json() or []
            if rows:
                if not targets:
                    targets = {"daily_meta": 226, "Norte": {"bases": {}, "turno": {}, "veiculo": {}}, "Leste": {"bases": {}, "turno": {}, "veiculo": {}}}
                for r in rows:
                    reg = r.get("region")
                    cat = r.get("category_type")
                    key = r.get("item_key")
                    val = int(r.get("target_val", 0))
                    if reg in ["Norte", "Leste"]:
                        if cat in ["base", "bases"]:
                            targets[reg]["bases"][key] = val
                        elif cat in ["turno", "turnos"]:
                            targets[reg]["turno"][key] = val
                        elif cat in ["veiculo", "veiculos"]:
                            targets[reg]["veiculo"][key] = val
                    elif cat == "daily_total" or key == "daily_meta":
                        targets["daily_meta"] = val
    except Exception as e:
        print(f"[WARN FETCH PLANNING TARGETS] {e}")

    return targets or {
        "daily_meta": 226,
        "Norte": {
            "bases": {"Fagundes Filho": 42, "Cajati": 24, "Vila Medeiros": 28, "LV": 10, "Munk": 5},
            "turno": {"Manhã": 54, "Tarde": 42, "Noite": 13},
            "veiculo": {"Cesto Aéreo": 68, "Veículo Leve": 13, "Moto": 13, "LV": 10, "Munk": 5}
        },
        "Leste": {
            "bases": {"Monte Santo": 33, "Catumbi": 21, "Aricanduva": 34, "Santo André": 7, "LV": 0, "Munk": 0},
            "turno": {"Manhã": 35, "Tarde": 35, "Noite": 25},
            "veiculo": {"Cesto Aéreo": 75, "Veículo Leve": 15, "Moto": 5, "LV": 0, "Munk": 0}
        }
    }

def save_delivery_planning_targets(targets_payload: dict, user_email: str = "admin@alpitelbrasil.com.br") -> dict:
    """
    Grava as metas operacionais atualizadas no cache em disco e no Supabase.
    """
    try:
        now_iso = datetime.now(BR_TZ).isoformat()
        targets_payload["updated_at"] = now_iso
        targets_payload["updated_by"] = user_email
        with open(PLANNING_TARGETS_FILE, "w", encoding="utf-8") as f:
            json.dump(targets_payload, f, ensure_ascii=False, indent=2)

        # Monta payload relacional para o Supabase
        rows_to_save = []
        # Meta diária
        rows_to_save.append({
            "target_month": "DEFAULT",
            "region": "Geral",
            "category_type": "daily_total",
            "item_key": "daily_meta",
            "target_val": int(targets_payload.get("daily_meta", 226)),
            "updated_by": user_email,
            "updated_at": now_iso
        })

        for reg in ["Norte", "Leste"]:
            r_data = targets_payload.get(reg, {})
            for b_name, b_val in r_data.get("bases", {}).items():
                rows_to_save.append({
                    "target_month": "DEFAULT",
                    "region": reg,
                    "category_type": "base",
                    "item_key": b_name,
                    "target_val": int(b_val),
                    "updated_by": user_email,
                    "updated_at": now_iso
                })
            for s_name, s_val in r_data.get("turno", {}).items():
                rows_to_save.append({
                    "target_month": "DEFAULT",
                    "region": reg,
                    "category_type": "turno",
                    "item_key": s_name,
                    "target_val": int(s_val),
                    "updated_by": user_email,
                    "updated_at": now_iso
                })
            for v_name, v_val in r_data.get("veiculo", {}).items():
                rows_to_save.append({
                    "target_month": "DEFAULT",
                    "region": reg,
                    "category_type": "veiculo",
                    "item_key": v_name,
                    "target_val": int(v_val),
                    "updated_by": user_email,
                    "updated_at": now_iso
                })

        try:
            endpoint = f"{BASE_REST_URL}/team_delivery_planning_targets?on_conflict=target_month,region,category_type,item_key"
            headers = get_headers().copy()
            headers["Prefer"] = "resolution=merge-duplicates"
            requests.post(endpoint, headers=headers, json=rows_to_save, timeout=8)
        except Exception as e:
            print(f"[WARN SUPABASE TARGETS SAVE] {e}")

        return {"status": "success", "message": "Metas salvas com sucesso."}
    except Exception as err:
        return {"status": "error", "message": str(err)}


# ==============================================================================
# MÓDULO BIDTECH - VISÃO OPERACIONAL (CHECKLISTS & RECONCILIAÇÃO)
# ==============================================================================

def push_bid_records_to_supabase(records_list: list, date_ref: str = None) -> dict:
    """
    Insere ou atualiza (UPSERT) registros extraídos da Visão Operacional BidTech na tabela 'bid_visao_operacional_records'.
    Usa a constraint única (date_ref, team_code) para merge atômico (1 registro por equipe no dia operacional).
    """
    if not records_list:
        return {"status": "success", "count": 0}
    try:
        now_iso = datetime.now(BR_TZ).isoformat()
        if not date_ref:
            from delivery_manager import delivery_manager
            date_ref = delivery_manager.get_operational_date()

        endpoint = f"{BASE_REST_URL}/bid_visao_operacional_records?on_conflict=date_ref,team_code"
        headers = get_headers().copy()
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"

        # Deduplica em memória para garantir unicidade estrita por (date_ref, team_code)
        seen = {}
        for r in records_list:
            t_code = str(r.get("team_code", "")).strip().upper()
            if not t_code:
                continue
            d_ref = str(r.get("date_ref") or date_ref)
            raw_st = str(r.get("status_bid") or "Planejada").strip()
            up_st = raw_st.upper()
            if "OPERA" in up_st:
                norm_st = "Em Operação"
            elif "CHECKLIST" in up_st:
                norm_st = "Em Checklist"
            elif "PLANEJAD" in up_st:
                norm_st = "Planejada"
            elif "RETORNAD" in up_st:
                norm_st = "Retornada"
            elif "BLOQUEAD" in up_st:
                norm_st = "Bloqueada"
            else:
                norm_st = raw_st or "Planejada"

            payload_item = {
                "date_ref": d_ref,
                "captured_at": r.get("captured_at") or now_iso,
                "team_code": t_code,
                "status_bid": norm_st,
                "col_title": str(r.get("col_title") or ""),
                "base": str(r.get("base") or "--"),
                "tipo_operacional": str(r.get("tipo_operacional") or "--"),
                "turno": str(r.get("turno") or "--"),
                "phone": str(r.get("phone") or "--"),
                "driver": str(r.get("driver") or "--"),
                "plate": str(r.get("plate") or "--"),
                "vehicle_type": str(r.get("vehicle_type") or "--"),
                "members": r.get("members") if isinstance(r.get("members"), list) else [],
                "timer_label": str(r.get("timer_label") or ""),
                "timer_value": str(r.get("timer_value") or "--"),
                "updated_at": now_iso
            }
            seen[(d_ref, t_code)] = payload_item

        clean_list = list(seen.values())
        saved_count = 0
        chunk_size = 200

        for i in range(0, len(clean_list), chunk_size):
            chunk = clean_list[i:i + chunk_size]
            resp = requests.post(endpoint, headers=headers, json=chunk, timeout=20)
            if resp.status_code in [200, 201]:
                saved_count += len(chunk)
            else:
                print(f"[WARN SUPABASE BID UPSERT] Status {resp.status_code}: {resp.text}")

        return {"status": "success", "count": saved_count}
    except Exception as e:
        print(f"[ERROR SUPABASE BID PUSH] {e}")
        return {"status": "error", "message": str(e), "count": 0}


def fetch_bid_records_by_date(date_str: str = None) -> list:
    """
    Busca registros da Visão Operacional BidTech para uma data específica (YYYY-MM-DD).
    """
    try:
        if not date_str:
            from delivery_manager import delivery_manager
            date_str = delivery_manager.get_operational_date()

        endpoint = f"{BASE_REST_URL}/bid_visao_operacional_records?date_ref=eq.{date_str}&order=team_code.asc&limit=2000"
        resp = requests.get(endpoint, headers=get_headers(), timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        return []
    except Exception as e:
        print(f"[SUPABASE FETCH BID ERROR] {e}")
        return []


def prune_stale_bid_records(date_ref: str, valid_team_codes: list) -> dict:
    """
    Remove registros da tabela 'bid_visao_operacional_records' para a data especificada
    que não estejam na lista de equipes válidas ativas extraídas do portal (ex: cards zumbis residuais).
    """
    if not date_ref or not valid_team_codes:
        return {"status": "skipped", "deleted": 0}
    try:
        current = fetch_bid_records_by_date(date_ref)
        if not current:
            return {"status": "success", "deleted": 0}

        valid_set = set(str(t).strip().upper() for t in valid_team_codes if t)
        to_delete = [r for r in current if str(r.get("team_code", "")).strip().upper() not in valid_set]

        if not to_delete:
            return {"status": "success", "deleted": 0}

        print(f"[SUPABASE BID PRUNE] Identificados {len(to_delete)} registros fantasmas para date_ref={date_ref}. Removendo...", flush=True)
        delete_headers = get_headers().copy()

        del_count = 0
        to_delete_codes = [r.get("team_code") for r in to_delete if r.get("team_code")]
        chunk_size = 50
        for i in range(0, len(to_delete_codes), chunk_size):
            chunk = to_delete_codes[i:i + chunk_size]
            codes_in = ",".join(chunk)
            del_url = f"{BASE_REST_URL}/bid_visao_operacional_records?date_ref=eq.{date_ref}&team_code=in.({codes_in})"
            r_del = requests.delete(del_url, headers=delete_headers, timeout=12)
            if r_del.status_code in [200, 204]:
                del_count += len(chunk)
            else:
                print(f"[WARN SUPABASE BID PRUNE BATCH] Status {r_del.status_code}: {r_del.text}")

        print(f"[SUPABASE BID PRUNE] {del_count} registros fantasmas removidos com sucesso.", flush=True)
        return {"status": "success", "deleted": del_count}
    except Exception as e:
        print(f"[SUPABASE BID PRUNE ERROR] {e}")
        return {"status": "error", "message": str(e), "deleted": 0}


# ==============================================================================
# AUDITORIA FORENSE MENSAL POR EQUIPE (CALENDÁRIO TRBONET x LOGIN)
# ==============================================================================

MONTHLY_CALENDAR_CACHE = {}

def fetch_team_monthly_calendar_audit(team_code: str, year_month: str = None) -> dict:
    """
    Busca o consolidado mensal de conexões no rádio (com e sem GPS) e logins no sistema
    para uma equipe específica no formato adequado para o calendário interativo.
    Utiliza RPC server-side no Supabase (alta performance) com fallback automático
    robusto e resolução precisa de horários de login e veículos para cada dia do mês.
    """
    if not team_code:
        return {"status": "error", "message": "Código da equipe é obrigatório", "data": None}

    clean_team = str(team_code).strip().upper()
    now_br = datetime.now(BR_TZ)
    if not year_month:
        year_month = now_br.strftime("%Y-%m")
    
    # 1. Verifica cache em memória (TTL: 60s para mês corrente, 1h para meses passados)
    cache_key = f"{clean_team}:{year_month}"
    current_ym = now_br.strftime("%Y-%m")
    ttl_seconds = 60 if year_month == current_ym else 3600
    
    cached_entry = MONTHLY_CALENDAR_CACHE.get(cache_key)
    if cached_entry:
        entry_time, entry_data = cached_entry
        if (now_br.timestamp() - entry_time) < ttl_seconds:
            return {"status": "success", "data": entry_data, "source": "memory_cache"}

    try:
        # Extrai ano e mês para calcular datas limites
        year_int, month_int = map(int, year_month.split("-"))
        if month_int == 12:
            next_ym = f"{year_int + 1}-01-01"
        else:
            next_ym = f"{year_int}-{month_int + 1:02d}-01"
        
        start_date = f"{year_month}-01"
        from calendar import monthrange
        _, last_day = monthrange(year_int, month_int)
        end_date = f"{year_month}-{last_day:02d}"

        records = []
        used_rpc = False

        # 2. Tenta invocar a função RPC do Supabase (get_team_monthly_audit)
        try:
            rpc_url = f"{BASE_REST_URL}/rpc/get_team_monthly_audit"
            payload = {"p_team_code": clean_team, "p_month": year_month}
            resp_rpc = requests.post(rpc_url, headers=get_headers(), json=payload, timeout=8)
            if resp_rpc.status_code == 200:
                rpc_data = resp_rpc.json()
                if isinstance(rpc_data, list) and len(rpc_data) > 0:
                    records = rpc_data
                    used_rpc = True
        except Exception as rpc_err:
            print(f"[WARN RPC MONTHLY AUDIT] Falha ao chamar RPC: {rpc_err}")

        # 3. Fallback inteligente: se o RPC não existir ou retornar erro, consulta views/tabelas agregadas
        if not used_rpc:
            # 3.1 Consulta a view diária consolidada (1 linha por dia ativo)
            ep_daily = (
                f"{BASE_REST_URL}/vw_team_daily_audit"
                f"?team_code=eq.{clean_team}&date_ref=gte.{start_date}&date_ref=lte.{end_date}&order=date_ref.asc"
            )
            resp_daily = requests.get(ep_daily, headers=get_headers(), timeout=10)
            daily_rows = resp_daily.json() if resp_daily.status_code == 200 and isinstance(resp_daily.json(), list) else []

            # 3.2 Consulta registros de entrega filtrando logins válidos (mais recentes primeiro)
            ep_deliv = (
                f"{BASE_REST_URL}/team_delivery_records"
                f"?team_code=eq.{clean_team}&date_ref=gte.{start_date}&date_ref=lte.{end_date}&login_time=neq.--&login_time=neq.--:--&select=date_ref,login_time,vehicle_type,driver,status&order=captured_at.desc&limit=1000"
            )
            resp_deliv = requests.get(ep_deliv, headers=get_headers(), timeout=8)
            deliv_rows = resp_deliv.json() if resp_deliv.status_code == 200 and isinstance(resp_deliv.json(), list) else []
            deliv_map = {}
            for d in deliv_rows:
                dr = d.get("date_ref")
                lt = d.get("login_time")
                if dr and lt and lt not in ("--", "--:--") and dr not in deliv_map:
                    deliv_map[dr] = d

            # 3.3 Consulta login e veículo diretamente em team_operational_logs (fonte de alta granularidade)
            ep_logs_login = (
                f"{BASE_REST_URL}/team_operational_logs"
                f"?team_code=eq.{clean_team}&date_ref=gte.{start_date}&date_ref=lte.{end_date}&poweron_login_time=neq.--&poweron_login_time=neq.--:--&select=date_ref,poweron_login_time,poweron_vehicle&order=captured_at.desc&limit=1000"
            )
            resp_logs_login = requests.get(ep_logs_login, headers=get_headers(), timeout=8)
            logs_login_rows = resp_logs_login.json() if resp_logs_login.status_code == 200 and isinstance(resp_logs_login.json(), list) else []
            logs_login_map = {}
            for l in logs_login_rows:
                dr = l.get("date_ref")
                plt = l.get("poweron_login_time")
                if dr and plt and plt not in ("--", "--:--") and dr not in logs_login_map:
                    logs_login_map[dr] = l

            # 3.4 Para datas marcadas como escaladas/login que não foram capturadas nas 1000 linhas mais recentes, busca granular rápida
            from concurrent.futures import ThreadPoolExecutor
            missing_poweron_dates = [
                r.get("date_ref") for r in daily_rows 
                if r.get("was_in_poweron") and r.get("date_ref") not in deliv_map and r.get("date_ref") not in logs_login_map
            ]
            if missing_poweron_dates:
                def fetch_missing_date_login(target_date):
                    try:
                        ep = f"{BASE_REST_URL}/team_delivery_records?team_code=eq.{clean_team}&date_ref=eq.{target_date}&login_time=neq.--&login_time=neq.--:--&select=login_time,vehicle_type&order=captured_at.desc&limit=1"
                        r = requests.get(ep, headers=get_headers(), timeout=5).json()
                        if r and len(r) > 0 and r[0].get("login_time") not in ("--", "--:--", None):
                            return target_date, r[0].get("login_time"), r[0].get("vehicle_type", "--")
                    except Exception:
                        pass
                    return target_date, None, None

                with ThreadPoolExecutor(max_workers=min(6, len(missing_poweron_dates))) as ex:
                    for res_date, res_login, res_veh in ex.map(fetch_missing_date_login, missing_poweron_dates):
                        if res_login:
                            deliv_map[res_date] = {"login_time": res_login, "vehicle_type": res_veh or "--"}

            # 3.5 Consulta seletiva de GPS nos logs com paginação automática (até 4.000 linhas)
            ep_gps = (
                f"{BASE_REST_URL}/team_operational_logs"
                f"?team_code=eq.{clean_team}&date_ref=gte.{start_date}&date_ref=lte.{end_date}&in_trbonet=eq.true&select=date_ref,has_gps"
            )
            gps_rows = []
            offset = 0
            chunk_size = 1000
            for _ in range(4):
                h = get_headers()
                h['Range'] = f"{offset}-{offset + chunk_size - 1}"
                resp_gps = requests.get(ep_gps, headers=h, timeout=8)
                page_rows = resp_gps.json() if resp_gps.status_code in [200, 206] and isinstance(resp_gps.json(), list) else []
                if not page_rows:
                    break
                gps_rows.extend(page_rows)
                if len(page_rows) < chunk_size:
                    break
                offset += chunk_size

            gps_counts = {}
            for g in gps_rows:
                dr = g.get("date_ref")
                if dr not in gps_counts:
                    gps_counts[dr] = {"with_gps": 0, "without_gps": 0}
                if g.get("has_gps"):
                    gps_counts[dr]["with_gps"] += 1
                else:
                    gps_counts[dr]["without_gps"] += 1

            # 3.6 Unifica os dados no padrão
            all_dates = set([r.get("date_ref") for r in daily_rows] + list(deliv_map.keys()) + list(logs_login_map.keys()))
            for dr in sorted(all_dates):
                daily = next((r for r in daily_rows if r.get("date_ref") == dr), None)
                deliv = deliv_map.get(dr, {})
                log_l = logs_login_map.get(dr, {})
                gps_info = gps_counts.get(dr, {"with_gps": 0, "without_gps": 0})

                was_trbo = bool(daily.get("was_online_trbonet")) if daily else False
                
                # Resolução inteligente de login_time e veículo
                resolved_login = deliv.get("login_time") or log_l.get("poweron_login_time") or "--"
                if resolved_login in ("--:--", None):
                    resolved_login = "--"

                resolved_vehicle = deliv.get("vehicle_type") or log_l.get("poweron_vehicle") or "--"
                if resolved_vehicle in (None, ""):
                    resolved_vehicle = "--"

                was_power = bool(daily.get("was_in_poweron")) if daily else (resolved_login != "--")
                if resolved_login != "--":
                    was_power = True

                times_online = int(daily.get("times_seen_online", 0)) if daily else 0
                w_gps = gps_info["with_gps"]
                wo_gps = gps_info["without_gps"]
                if times_online > 0 and (w_gps + wo_gps) == 0:
                    wo_gps = times_online
                    w_gps = 0

                records.append({
                    "date_ref": dr,
                    "was_in_poweron": was_power,
                    "was_online_trbonet": was_trbo,
                    "times_seen_online": times_online,
                    "times_with_gps": w_gps,
                    "times_without_gps": wo_gps,
                    "total_sync_checks": int(daily.get("total_sync_checks", 0)) if daily else 0,
                    "uptime_percentage": float(daily.get("uptime_percentage", 0.0)) if daily else 0.0,
                    "first_seen_online": daily.get("first_seen_online") if daily else None,
                    "last_seen_online": daily.get("last_seen_online") if daily else None,
                    "poweron_login_time": resolved_login,
                    "poweron_vehicle": resolved_vehicle,
                    "base_code": daily.get("base_code", "--") if daily else "--",
                    "region": daily.get("region", "--") if daily else "--"
                })

        # 4. Mapeamento indexado por dia do mês (1 a last_day) para preenchimento garantido do calendário
        days_map = {r.get("date_ref"): r for r in records if r.get("date_ref")}
        calendar_days = []
        base_code_detected = clean_team[:3]
        region_detected = "--"

        total_days_connected = 0
        total_days_logged = 0
        total_days_both = 0
        total_checks_online = 0
        total_checks_with_gps = 0
        total_checks_without_gps = 0

        for d in range(1, last_day + 1):
            d_str = f"{year_month}-{d:02d}"
            rec = days_map.get(d_str)

            if rec:
                was_conn = bool(rec.get("was_online_trbonet"))
                was_log = bool(rec.get("was_in_poweron")) or (rec.get("poweron_login_time") and rec.get("poweron_login_time") not in ("--", "--:--"))
                checks_on = int(rec.get("times_seen_online") or 0)
                checks_gps = int(rec.get("times_with_gps") or 0)
                checks_nogps = int(rec.get("times_without_gps") or 0)

                # Valida integridade: checks_gps + checks_nogps deve bater com checks_on
                if checks_on > 0 and (checks_gps + checks_nogps) == 0:
                    checks_nogps = checks_on

                if was_conn:
                    total_days_connected += 1
                if was_log:
                    total_days_logged += 1
                if was_conn and was_log:
                    total_days_both += 1

                total_checks_online += checks_on
                total_checks_with_gps += checks_gps
                total_checks_without_gps += checks_nogps

                if rec.get("base_code") and rec.get("base_code") != "--":
                    base_code_detected = rec.get("base_code")
                if rec.get("region") and rec.get("region") != "--":
                    region_detected = rec.get("region")

                first_sig = format_datetime_br(rec.get("first_seen_online"))
                last_sig = format_datetime_br(rec.get("last_seen_online"))
                if first_sig != '--' and ' ' in first_sig:
                    first_sig = first_sig.split(' ')[1]
                if last_sig != '--' and ' ' in last_sig:
                    last_sig = last_sig.split(' ')[1]

                calendar_days.append({
                    "day": d,
                    "date": d_str,
                    "has_data": True,
                    "connected": was_conn,
                    "logged": was_log,
                    "checks_online": checks_on,
                    "checks_gps": checks_gps,
                    "checks_without_gps": checks_nogps,
                    "total_sync_checks": int(rec.get("total_sync_checks") or 0),
                    "uptime_pct": float(rec.get("uptime_percentage") or 0.0),
                    "first_signal": first_sig,
                    "last_signal": last_sig,
                    "login_time": rec.get("poweron_login_time") or "--",
                    "vehicle": rec.get("poweron_vehicle") or "--",
                    "status_label": "CONFORME" if (was_conn and was_log and checks_gps > 0) else ("SEM GPS" if (was_conn and checks_nogps > 0 and checks_gps == 0) else ("SEM RÁDIO" if was_log else ("SEM LOGIN" if was_conn else "SEM REGISTRO")))
                })
            else:
                calendar_days.append({
                    "day": d,
                    "date": d_str,
                    "has_data": False,
                    "connected": False,
                    "logged": False,
                    "checks_online": 0,
                    "checks_gps": 0,
                    "checks_without_gps": 0,
                    "total_sync_checks": 0,
                    "uptime_pct": 0.0,
                    "first_signal": "--",
                    "last_signal": "--",
                    "login_time": "--",
                    "vehicle": "--",
                    "status_label": "FOLGA / SEM DADOS"
                })

        # 5. Cálculo consolidado de KPIs executivos do mês
        gps_ratio = round((total_checks_with_gps / total_checks_online * 100), 1) if total_checks_online > 0 else 0.0
        adherence_pct = round((total_days_both / total_days_logged * 100), 1) if total_days_logged > 0 else (100.0 if total_days_connected > 0 else 0.0)
        avg_daily_checks = round(total_checks_online / total_days_connected, 1) if total_days_connected > 0 else 0.0

        result_payload = {
            "team_code": clean_team,
            "base_code": base_code_detected,
            "region": region_detected,
            "month": year_month,
            "days_in_month": last_day,
            "kpis": {
                "days_connected": total_days_connected,
                "days_logged": total_days_logged,
                "days_both": total_days_both,
                "total_checks_online": total_checks_online,
                "total_checks_with_gps": total_checks_with_gps,
                "total_checks_without_gps": total_checks_without_gps,
                "gps_ratio_pct": gps_ratio,
                "adherence_pct": adherence_pct,
                "avg_daily_checks": avg_daily_checks
            },
            "days": calendar_days,
            "server_timestamp": now_br.isoformat()
        }

        # Armazena em cache
        MONTHLY_CALENDAR_CACHE[cache_key] = (now_br.timestamp(), result_payload)

        return {
            "status": "success",
            "data": result_payload,
            "source": "supabase_rpc" if used_rpc else "supabase_direct_aggregate"
        }

    except Exception as e:
        print(f"[FETCH TEAM MONTHLY CALENDAR ERROR] {e}")
        return {"status": "error", "message": f"Erro ao processar auditoria mensal: {str(e)}", "data": None}


def fetch_active_teams_list() -> list:
    """
    Retorna lista única e ordenada de equipes conhecidas no sistema para autocomplete.
    Busca em memória (delivery_manager) ou via Supabase.
    """
    try:
        from delivery_manager import delivery_manager
        current_teams = list(delivery_manager.current_delivery.keys())
        if current_teams:
            return sorted(list(set(current_teams)))
    except Exception:
        pass
    
    try:
        ep = f"{BASE_REST_URL}/vw_team_daily_audit?select=team_code&limit=500"
        resp = requests.get(ep, headers=get_headers(), timeout=5)
        if resp.status_code == 200:
            codes = [r.get("team_code") for r in resp.json() if r.get("team_code")]
            return sorted(list(set(codes)))
    except Exception:
        pass
    return []







