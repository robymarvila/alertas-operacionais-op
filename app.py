"""
Servidor Flask - Painel Operacional PowerON vs TRBOnet
Fornece rotas web, APIs RESTful para sincronização em tempo real e upload de arquivos.
"""

from flask import Flask, render_template, jsonify, request, send_file, make_response, send_from_directory, redirect
import io
import os
import requests
import csv
import threading
import time
from datetime import datetime
from data_manager import data_manager
from delivery_manager import delivery_manager
from fleet_client import fleet_client
from supabase_client import (
    push_snapshot_to_supabase,
    fetch_latest_snapshot_from_supabase,
    fetch_audit_logs,
    fetch_daily_audit_summary,
    fetch_team_timeline,
    clear_all_supabase_data,
    create_sync_command,
    get_pending_commands,
    update_command_status,
    wait_for_command_completion,
    push_delivery_snapshot_to_supabase,
    fetch_latest_delivery_snapshot_from_supabase
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
    static_url_path='/static'
)
app.config['JSON_SORT_KEYS'] = False

@app.after_request
def add_cors_headers(response):
    """Permite requisições Cross-Origin (CORS) vindas do portal Enel SP."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, DELETE, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization, X-Requested-With, Origin, Accept'
    return response

@app.route('/')
@app.route('/hub')
def index():
    """Renderiza a aplicação principal com design 100% oficial e aprovado."""
    return render_template('index.html')

@app.route('/trbonet')
def view_trbonet():
    """Acesso direto ao Módulo 1: STATUS TRBOnet."""
    return redirect('/#module', code=302)

@app.route('/teams')
@app.route('/delivery')
def view_teams():
    """Acesso direto ao Módulo 2: ENTREGA DE EQUIPES."""
    return redirect('/#delivery', code=302)

@app.route('/static/<path:filename>')
def custom_static(filename):
    """Serve arquivos estáticos com suporte completo ao ambiente Vercel Serverless."""
    return send_from_directory(os.path.join(BASE_DIR, 'static'), filename)

@app.route('/favicon.ico')
def favicon():
    """Retorna favicon sem erro 404 no console."""
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#00f2fe" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.9 19.1C1 15.2 1 8.8 4.9 4.9"/><path d="M7.8 16.2c-2.3-2.3-2.3-6.1 0-8.5"/><circle cx="12" cy="12" r="2"/><path d="M16.2 7.8c2.3 2.3 2.3 6.1 0 8.5"/><path d="M19.1 4.9C23 8.8 23 15.1 19.1 19.1"/></svg>'''
    response = make_response(svg)
    response.headers['Content-Type'] = 'image/svg+xml'
    return response

@app.route('/api/data', methods=['GET'])
def get_data():
    """
    Retorna o estado atual consolidado com equipes, métricas, bases e log de auditoria.
    O Supabase é a fonte mestra da verdade. Se o Supabase for apagado, o painel zera imediatamente.
    """
    try:
        # 1. Consulta o Supabase em tempo real
        cloud_res = fetch_latest_snapshot_from_supabase()
        if cloud_res.get("status") == "success" and cloud_res.get("data"):
            return jsonify({
                "status": "success",
                "source": "supabase_cloud",
                "data": cloud_res["data"]
            })
        elif cloud_res.get("status") == "empty":
            # Se o Supabase foi limpo/apagado, zera a memória local para 0
            empty_data = data_manager.reset_to_baseline()
            return jsonify({
                "status": "success",
                "source": "supabase_empty",
                "data": empty_data
            })

        # 2. Caso ocorra erro de conexão/offline, usa a memória local como contingência
        data = data_manager.consolidate_data()
        return jsonify({
            "status": "success",
            "source": "local_memory",
            "data": data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

from auth_manager import auth_manager, verify_session_token

def get_current_user():
    """Extrai e valida o token de autorização do cabeçalho da requisição."""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    elif request.headers.get("X-Auth-Token"):
        token = request.headers.get("X-Auth-Token").strip()
    elif request.cookies.get("auth_token"):
        token = request.cookies.get("auth_token").strip()

    if not token:
        return None
    return verify_session_token(token)

# ==========================================================================
# ROTAS DE AUTENTICAÇÃO E CONTROLE DE ACESSO (E2EE)
# ==========================================================================

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """Autentica o usuário com Matrícula ou E-mail e Senha."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        login_id = data.get("login") or data.get("email") or data.get("matricula") or ""
        password = data.get("password") or ""
        
        if not login_id or not password:
            return jsonify({"status": "error", "message": "Preencha o usuário/matrícula e a senha."}), 400
            
        result = auth_manager.authenticate(login_id, password)
        status_code = 200 if result.get("status") == "success" else 401
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro interno de autenticação: {str(e)}"}), 500

@app.route('/api/auth/register', methods=['POST'])
def auth_register():
    """Solicita novo acesso para um colaborador com validações estritas."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        nome = data.get("nome", "")
        email = data.get("email", "")
        matricula = data.get("matricula", "")
        password = data.get("password", "")
        role = data.get("role", "operator")

        result = auth_manager.register_user(
            nome=nome,
            email=email,
            matricula=matricula,
            password=password,
            role=role
        )
        status_code = 200 if result.get("status") == "success" else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro no cadastro: {str(e)}"}), 500

@app.route('/api/auth/session', methods=['GET'])
def auth_session():
    """Valida o token da sessão ativa."""
    user = get_current_user()
    if not user:
        return jsonify({"status": "unauthenticated", "authenticated": False}), 200
    return jsonify({
        "status": "success",
        "authenticated": True,
        "user": {
            "id": user.get("sub"),
            "nome": user.get("nome"),
            "email": user.get("email"),
            "matricula": user.get("matricula"),
            "role": user.get("role")
        }
    })

@app.route('/api/auth/users', methods=['GET'])
def auth_list_users():
    """Lista todos os usuários (Apenas Administrador)."""
    user = get_current_user()
    if not user or user.get("role") != "admin":
        return jsonify({"status": "forbidden", "message": "Acesso exclusivo para Administradores."}), 403
    return jsonify({
        "status": "success",
        "users": auth_manager.list_users()
    })

@app.route('/api/auth/approve_user', methods=['POST'])
def auth_approve_user():
    """Aprova ou altera o perfil de um usuário pendente (Apenas Administrador)."""
    user = get_current_user()
    if not user or user.get("role") != "admin":
        return jsonify({"status": "forbidden", "message": "Acesso exclusivo para Administradores."}), 403
    
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    status = data.get("status", "approved")
    role = data.get("role")

    result = auth_manager.update_user_status(user_id, new_status=status, new_role=role)
    status_code = 200 if result.get("status") == "success" else 400
    return jsonify(result), status_code

@app.route('/api/auth/reject_user', methods=['POST'])
def auth_reject_user():
    """Rejeita o acesso de um usuário (Apenas Administrador)."""
    user = get_current_user()
    if not user or user.get("role") != "admin":
        return jsonify({"status": "forbidden", "message": "Acesso exclusivo para Administradores."}), 403
    
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    result = auth_manager.update_user_status(user_id, new_status="rejected")
    return jsonify(result)

@app.route('/api/auth/delete_user', methods=['POST'])
def auth_delete_user():
    """Exclui um usuário do sistema (Apenas Administrador)."""
    user = get_current_user()
    if not user or user.get("role") != "admin":
        return jsonify({"status": "forbidden", "message": "Acesso exclusivo para Administradores."}), 403
    
    data = request.get_json(force=True, silent=True) or {}
    user_id = data.get("user_id")
    result = auth_manager.delete_user(user_id)
    return jsonify(result)

@app.route('/api/reset', methods=['POST'])
def reset_data():
    """Zera e limpa todos os dados operacionais no Supabase e na memória local."""
    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Acesso Restrito: É necessário efetuar login no Cadeado para zerar a base."
        }), 401

    data = data_manager.reset_to_baseline()
    try:
        clear_all_supabase_data()
    except Exception:
        pass
    return jsonify({
        "status": "success",
        "message": "Base de dados zerada com sucesso (Supabase e Local).",
        "data": data
    })

# ==============================================================================
# PAINEL DE CONTROLE ADMINISTRATIVO: SAÚDE DOS MOTORES & TELEMETRIA
# ==============================================================================

def check_port_listening(host="127.0.0.1", port=9222, timeout=1.0) -> bool:
    """Verifica se uma porta de rede local está aberta e aceitando conexões TCP."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False

@app.route('/api/admin/engine_status', methods=['GET'])
def get_engine_status():
    """
    Retorna o status detalhado em tempo real de todos os 4 motores:
    1. Motor TRBOnet One (Rádios & GPS)
    2. Robô CDP Enel SP (Equipes & Turnos - Porta 9222)
    3. Robô CDP Scanner 5.0 (TIBCO Spotfire - Porta 9222)
    4. Sincronizador em Nuvem Supabase
    Discrimina se a falha é de CONEXÃO ou se o PROCESSO PAROU.
    """
    from supabase_client import fetch_all_engine_health, update_engine_health, BASE_REST_URL, get_headers, format_datetime_br, BR_TZ
    from delivery_manager import delivery_manager
    from datetime import datetime, timezone

    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'

    if is_cloud:
        # AMBIENTE NUVEM / VERCEL:
        # Consulta os heartbeats enviados pelo Agente Local Windows.
        engines_from_db = fetch_all_engine_health() or []
        db_map = {e.get("engine_name"): e for e in engines_from_db}

        now_utc = datetime.now(timezone.utc)

        def parse_engine_cloud(eng_key, default_label, default_msg):
            eng = db_map.get(eng_key, {})
            hb_str = eng.get("last_heartbeat")
            is_alive = False
            last_sync_formatted = "--:--:--"

            if hb_str:
                try:
                    hb_dt = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
                    if hb_dt.tzinfo is None:
                        hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                    diff_secs = (now_utc - hb_dt).total_seconds()
                    # Threshold: 40 min para Spotfire (ciclo de 30 min), 6 min para TRBOnet e Enel (ciclo de 2 min)
                    threshold = 2400 if "spotfire" in eng_key else 360
                    is_alive = diff_secs <= threshold
                except Exception:
                    is_alive = False

            succ_str = eng.get("last_success_sync") or hb_str
            if succ_str:
                last_sync_formatted = format_datetime_br(succ_str)

            raw_status = eng.get("status", "STOPPED")
            if is_alive and raw_status in ["OPERATIONAL", "WARNING"]:
                status = raw_status
                msg = eng.get("last_error_message") or default_msg
            elif is_alive:
                status = raw_status
                msg = eng.get("last_error_message") or "Falha de conexão no Agente Local."
            else:
                status = "STOPPED"
                msg = "Agente Local Desconectado: Sem comunicação com o Windows nos últimos minutos."

            return {
                "name": eng_key,
                "label": eng.get("engine_label") or default_label,
                "status": status,
                "is_running": is_alive,
                "error_type": eng.get("error_type", "NONE" if is_alive else "PROCESS_STOPPED"),
                "message": msg,
                "last_sync": last_sync_formatted,
                "records": eng.get("records_count", 0)
            }

        # Teste de conexão Supabase Cloud
        try:
            resp = requests.get(f"{BASE_REST_URL}/system_engine_health?select=engine_name&limit=1", headers=get_headers(), timeout=6)
            cloud_ok = resp.status_code in [200, 206]
        except Exception:
            cloud_ok = False

        cloud_status = "OPERATIONAL" if cloud_ok else "ERROR_CONNECTION"
        cloud_msg = "Operacional: Conexão REST com banco Supabase ativa." if cloud_ok else "Falha de Conexão: Supabase inacessível."

        return jsonify({
            "status": "success",
            "engines": {
                "trbonet": parse_engine_cloud("trbonet_collector", "Motor TRBOnet One (Rádios & GPS)", "Operacional: Rádios e telemetria GPS sendo conciliados a cada 2 min."),
                "enel_cdp": parse_engine_cloud("enel_cdp_collector", "Robô CDP Enel SP (Equipes & Turnos)", "Operacional: Conexão CDP ativa lendo 500 linhas a cada 2 min."),
                "spotfire_cdp": parse_engine_cloud("spotfire_cdp_collector", "Robô CDP Scanner 5.0 (TIBCO Spotfire)", "Operacional: Extração automatizada do Scanner 5.0 a cada 30 min."),
                "bid_cdp": parse_engine_cloud("bid_cdp_collector", "Robô CDP BidTech (Checklist Operacional)", "Operacional: Leitura automatizada da Visão Operacional BidTech a cada 2 min."),
                "cloud_sync": {
                    "name": "cloud_sync_listener",
                    "label": "Banco em Nuvem Supabase",
                    "status": cloud_status,
                    "is_running": True,
                    "error_type": "NONE" if cloud_ok else "CONNECTION_REFUSED",
                    "message": cloud_msg,
                    "last_sync": datetime.now(BR_TZ).strftime("%H:%M:%S"),
                    "records": 0
                }
            }
        })

    # AMBIENTE LOCAL WINDOWS:
    port_9222_open = check_port_listening("127.0.0.1", 9222)
    thread_enel_alive = ENGINE_THREADS.get("enel_cdp") is not None and ENGINE_THREADS["enel_cdp"].is_alive()
    thread_trbo_alive = ENGINE_THREADS.get("trbonet") is not None and ENGINE_THREADS["trbonet"].is_alive()
    thread_spotfire_alive = ENGINE_THREADS.get("spotfire_cdp") is not None and ENGINE_THREADS["spotfire_cdp"].is_alive()
    thread_bid_alive = ENGINE_THREADS.get("bid_cdp") is not None and ENGINE_THREADS["bid_cdp"].is_alive()

    # 1. Motor Enel CDP
    if not thread_enel_alive:
        enel_status = "STOPPED"
        enel_error_type = "PROCESS_STOPPED"
        enel_msg = "Motor Parado: A rotina de segundo plano da Enel foi finalizada ou não iniciou."
    elif not port_9222_open:
        enel_status = "ERROR_CONNECTION"
        enel_error_type = "CONNECTION_REFUSED"
        enel_msg = "Falha de Conexão: O Edge corporativo não está ouvindo na porta 9222. Inicie o Edge com depuração ativada."
    else:
        enel_status = "OPERATIONAL"
        enel_error_type = "NONE"
        enel_msg = "Operacional: Conexão CDP ativa na porta 9222 lendo 500 linhas a cada 2 min."

    update_engine_health("enel_cdp_collector", enel_status, is_running=thread_enel_alive,
                         error_type=enel_error_type, last_error=enel_msg,
                         records_count=len(delivery_manager.active_teams),
                         engine_label="Robô CDP Enel SP (Equipes & Turnos)")

    # 2. Motor TRBOnet One
    if not thread_trbo_alive:
        trbo_status = "STOPPED"
        trbo_error_type = "PROCESS_STOPPED"
        trbo_msg = "Motor Parado: A rotina de auto-captura do TRBOnet está inativa."
    else:
        trbo_status = "OPERATIONAL"
        trbo_error_type = "NONE"
        trbo_msg = "Operacional: Rádios e telemetria GPS sendo conciliados a cada 2 min."

    update_engine_health("trbonet_collector", trbo_status, is_running=thread_trbo_alive,
                         error_type=trbo_error_type, last_error=trbo_msg,
                         records_count=len(data_manager.trbonet_teams),
                         engine_label="Motor TRBOnet One (Rádios & GPS)")

    # 3. Motor Spotfire CDP
    if not thread_spotfire_alive:
        spotfire_status = "STOPPED"
        spotfire_error_type = "PROCESS_STOPPED"
        spotfire_msg = "Motor Parado: A rotina de auto-captura do Scanner 5.0 está inativa."
    elif not port_9222_open:
        spotfire_status = "ERROR_CONNECTION"
        spotfire_error_type = "CONNECTION_REFUSED"
        spotfire_msg = "Falha de Conexão: Porta 9222 fechada no navegador Spotfire."
    else:
        spotfire_status = "OPERATIONAL"
        spotfire_error_type = "NONE"
        spotfire_msg = "Operacional: Extração automatizada do Scanner 5.0 a cada 30 min."

    try:
        from coletor_spotfire_cdp import get_last_scanner_sync_time
        spotfire_sync_time = get_last_scanner_sync_time() or "--:--:--"
    except Exception:
        spotfire_sync_time = "--:--:--"

    update_engine_health("spotfire_cdp_collector", spotfire_status, is_running=thread_spotfire_alive,
                         error_type=spotfire_error_type, last_error=spotfire_msg,
                         records_count=len(delivery_manager.spotfire_cache) if hasattr(delivery_manager, "spotfire_cache") else 0,
                         engine_label="Robô CDP Scanner 5.0 (Spotfire)")

    # 4. Motor BidTech CDP (Visão Operacional)
    if not thread_bid_alive:
        bid_status = "STOPPED"
        bid_error_type = "PROCESS_STOPPED"
        bid_msg = "Motor Parado: A rotina de auto-captura da Visão Operacional BidTech está inativa."
    elif not port_9222_open:
        bid_status = "ERROR_CONNECTION"
        bid_error_type = "CONNECTION_REFUSED"
        bid_msg = "Falha de Conexão: Porta 9222 fechada no navegador BidTech."
    else:
        bid_status = "OPERATIONAL"
        bid_error_type = "NONE"
        bid_msg = "Operacional: Leitura automatizada da Visão Operacional BidTech a cada 2 min."

    bid_records_count = len(delivery_manager.bid_cache) if hasattr(delivery_manager, "bid_cache") else 0
    bid_sync_time = delivery_manager.last_bid_sync or "--:--:--"

    update_engine_health("bid_cdp_collector", bid_status, is_running=thread_bid_alive,
                         error_type=bid_error_type, last_error=bid_msg,
                         records_count=bid_records_count,
                         engine_label="Robô CDP BidTech (Checklist Operacional)")

    # 5. Sincronizador Nuvem Supabase
    try:
        resp = requests.get(f"{BASE_REST_URL}/system_engine_health?select=engine_name&limit=1", headers=get_headers(), timeout=6)
        cloud_ok = resp.status_code in [200, 206]
    except Exception:
        cloud_ok = False

    cloud_status = "OPERATIONAL" if cloud_ok else "ERROR_CONNECTION"
    cloud_msg = "Operacional: Conexão REST com banco Supabase ativa." if cloud_ok else "Falha de Conexão: Supabase inacessível."
    update_engine_health("cloud_sync_listener", cloud_status, is_running=True,
                         error_type="NONE" if cloud_ok else "CONNECTION_REFUSED",
                         last_error=cloud_msg, records_count=0,
                         engine_label="Banco em Nuvem Supabase")

    return jsonify({
        "status": "success",
        "engines": {
            "trbonet": {
                "name": "trbonet_collector",
                "label": "Motor TRBOnet One (Rádios & GPS)",
                "status": trbo_status,
                "is_running": thread_trbo_alive,
                "error_type": trbo_error_type,
                "message": trbo_msg,
                "last_sync": format_datetime_br(data_manager.last_trbonet_sync),
                "records": len(data_manager.trbonet_teams)
            },
            "enel_cdp": {
                "name": "enel_cdp_collector",
                "label": "Robô CDP Enel SP (Equipes & Turnos)",
                "status": enel_status,
                "is_running": thread_enel_alive,
                "error_type": enel_error_type,
                "message": enel_msg,
                "last_sync": format_datetime_br(delivery_manager.last_sync_time),
                "records": len(delivery_manager.active_teams)
            },
            "spotfire_cdp": {
                "name": "spotfire_cdp_collector",
                "label": "Robô CDP Scanner 5.0 (TIBCO Spotfire)",
                "status": spotfire_status,
                "is_running": thread_spotfire_alive,
                "error_type": spotfire_error_type,
                "message": spotfire_msg,
                "last_sync": format_datetime_br(spotfire_sync_time),
                "records": len(delivery_manager.spotfire_cache) if hasattr(delivery_manager, "spotfire_cache") else 0
            },
            "bid_cdp": {
                "name": "bid_cdp_collector",
                "label": "Robô CDP BidTech (Checklist Operacional)",
                "status": bid_status,
                "is_running": thread_bid_alive,
                "error_type": bid_error_type,
                "message": bid_msg,
                "last_sync": bid_sync_time,
                "records": bid_records_count
            },
            "cloud_sync": {
                "name": "cloud_sync_listener",
                "label": "Banco em Nuvem Supabase",
                "status": cloud_status,
                "is_running": True,
                "error_type": "NONE" if cloud_ok else "CONNECTION_REFUSED",
                "message": cloud_msg,
                "last_sync": datetime.now(BR_TZ).strftime("%H:%M:%S"),
                "records": 0
            }
        }
    })

@app.route('/api/admin/engine_details/<engine_key>', methods=['GET'])
def get_engine_details(engine_key):
    """
    Retorna o resumo detalhado e métricas analíticas aprofundadas do motor selecionado:
    - trbonet
    - enel_cdp
    - spotfire_cdp
    - cloud_sync
    """
    from supabase_client import fetch_all_engine_health, format_datetime_br, BR_TZ
    from delivery_manager import delivery_manager
    from datetime import datetime

    engines_db = {e.get("engine_name"): e for e in (fetch_all_engine_health() or [])}

    if engine_key in ["trbonet", "trbonet_collector"]:
        db_rec = engines_db.get("trbonet_collector", {})
        last_sync = format_datetime_br(db_rec.get("last_success_sync") or data_manager.last_trbonet_sync)
        summary = data_manager.consolidate_data().get("summary", {})
        sample_teams = []
        for t_code, t_data in list(data_manager.trbonet_teams.items())[:12]:
            sample_teams.append({
                "code": t_code,
                "radio_id": t_data.get("radio_id") or "--",
                "status": t_data.get("status") or "Online",
                "has_gps": bool(t_data.get("latitude") and t_data.get("longitude")),
                "speed": t_data.get("speed") or "0 km/h"
            })
        return jsonify({
            "status": "success",
            "engine_key": "trbonet",
            "name": "trbonet_collector",
            "label": "Motor TRBOnet One (Rádios & GPS)",
            "icon": "radio",
            "last_sync": last_sync,
            "engine_status": db_rec.get("status", "OPERATIONAL"),
            "is_running": db_rec.get("is_running", True),
            "summary": {
                "total_radios": len(data_manager.trbonet_teams),
                "online_with_gps": summary.get("online_with_gps", 0),
                "online_without_gps": summary.get("online_without_gps", 0),
                "compliance_rate": summary.get("compliance_rate", 0),
                "gps_rate": summary.get("gps_rate", 0),
                "total_poweron": summary.get("total_poweron", 0)
            },
            "sample_records": sample_teams,
            "action_command": "CAPTURE_TRBONET",
            "action_label": "Disparar Leitura TRBOnet Agora"
        })

    elif engine_key in ["enel_cdp", "enel_cdp_collector"]:
        db_rec = engines_db.get("enel_cdp_collector", {})
        last_sync = format_datetime_br(db_rec.get("last_success_sync") or delivery_manager.last_sync_time)
        active_teams = delivery_manager.active_teams or []
        norte_count = sum(1 for t in active_teams if "NORTE" in str(t.get("region", "")).upper() or "NORTE" in str(t.get("ut", "")).upper())
        leste_count = sum(1 for t in active_teams if "LESTE" in str(t.get("region", "")).upper() or "LESTE" in str(t.get("ut", "")).upper())
        cesto_count = sum(1 for t in active_teams if "CESTO" in str(t.get("vehicle_type", "")).upper())
        leve_count = sum(1 for t in active_teams if "LEVE" in str(t.get("vehicle_type", "")).upper())
        munck_count = sum(1 for t in active_teams if "MUNCK" in str(t.get("vehicle_type", "")).upper())
        plate_ok = sum(1 for t in active_teams if t.get("plate_cadastrada"))

        sample_teams = []
        for t in active_teams[:12]:
            sample_teams.append({
                "code": t.get("team_code"),
                "base": t.get("base_name"),
                "ut": t.get("ut"),
                "filial": t.get("company"),
                "driver": t.get("driver"),
                "plate": t.get("plate"),
                "plate_status": t.get("situacao_veiculo_cadastrado", "NÃO CADASTRADO"),
                "status_op": t.get("status_equipes_brasil", "Logada")
            })

        return jsonify({
            "status": "success",
            "engine_key": "enel_cdp",
            "name": "enel_cdp_collector",
            "label": "Robô CDP Enel SP (Equipes & Turnos)",
            "icon": "users",
            "last_sync": last_sync,
            "engine_status": db_rec.get("status", "OPERATIONAL"),
            "is_running": db_rec.get("is_running", True),
            "summary": {
                "total_teams": len(active_teams),
                "norte_count": norte_count,
                "leste_count": leste_count,
                "cesto_count": cesto_count,
                "leve_count": leve_count,
                "munck_count": munck_count,
                "plate_matched_count": plate_ok,
                "sync_source": delivery_manager.sync_source
            },
            "sample_records": sample_teams,
            "action_command": "CAPTURE_ENEL",
            "action_label": "Disparar Coleta CDP Enel SP Agora"
        })

    elif engine_key in ["spotfire_cdp", "spotfire_cdp_collector"]:
        db_rec = engines_db.get("spotfire_cdp_collector", {})
        try:
            from coletor_spotfire_cdp import get_last_scanner_sync_time
            last_sync_raw = get_last_scanner_sync_time()
        except Exception:
            last_sync_raw = None
        last_sync = format_datetime_br(db_rec.get("last_success_sync") or last_sync_raw)

        return jsonify({
            "status": "success",
            "engine_key": "spotfire_cdp",
            "name": "spotfire_cdp_collector",
            "label": "Robô CDP Scanner 5.0 (TIBCO Spotfire)",
            "icon": "bar-chart-2",
            "last_sync": last_sync,
            "engine_status": db_rec.get("status", "OPERATIONAL"),
            "is_running": db_rec.get("is_running", True),
            "summary": {
                "total_records": db_rec.get("records_count", 0),
                "protocol": "Chrome DevTools Protocol (CDP)",
                "target": "TIBCO Spotfire Scanner 5.0 (Tab Completa)",
                "interval": "30 minutos (1800s)",
                "output_table": "public.team_scanner_records"
            },
            "sample_records": [],
            "action_command": "CAPTURE_SPOTFIRE",
            "action_label": "Disparar Extração Spotfire Scanner 5.0 Agora"
        })

    elif engine_key in ["bid_cdp", "bid_cdp_collector"]:
        db_rec = engines_db.get("bid_cdp_collector", {})
        last_sync = db_rec.get("last_success_sync") or delivery_manager.last_bid_sync or "--:--:--"
        if last_sync and "-" in str(last_sync) and "T" in str(last_sync):
            last_sync = format_datetime_br(last_sync)

        bid_records = list(delivery_manager.bid_cache.values()) if hasattr(delivery_manager, "bid_cache") and delivery_manager.bid_cache else []
        if not bid_records:
            try:
                from supabase_client import fetch_bid_records_by_date
                bid_records = fetch_bid_records_by_date() or []
            except Exception:
                bid_records = []

        def norm_st(s):
            up = str(s or "").upper()
            if "OPERA" in up: return "Em Operação"
            if "CHECKLIST" in up: return "Em Checklist"
            if "PLANEJAD" in up: return "Planejada"
            if "RETORNAD" in up: return "Retornada"
            if "BLOQUEAD" in up: return "Bloqueada"
            return str(s)

        total_teams = len(bid_records)
        em_operacao = sum(1 for r in bid_records if norm_st(r.get("status_bid")) == "Em Operação")
        em_checklist = sum(1 for r in bid_records if norm_st(r.get("status_bid")) == "Em Checklist")
        planejadas = sum(1 for r in bid_records if norm_st(r.get("status_bid")) == "Planejada")
        bloqueadas = sum(1 for r in bid_records if norm_st(r.get("status_bid")) in ["Bloqueada", "Retornada"])

        sample_teams = []
        for r in bid_records[:15]:
            sample_teams.append({
                "code": r.get("team_code", "--"),
                "status_bid": norm_st(r.get("status_bid", "--")),
                "base": r.get("base", "--"),
                "driver": r.get("driver", "--"),
                "plate": r.get("plate", "--"),
                "tipo_operacional": r.get("tipo_operacional", "--"),
                "turno": r.get("turno", "--"),
                "timer_value": r.get("timer_value", "--")
            })

        return jsonify({
            "status": "success",
            "engine_key": "bid_cdp",
            "name": "bid_cdp_collector",
            "label": "Robô CDP BidTech (Checklist Operacional)",
            "icon": "clipboard-check",
            "last_sync": last_sync,
            "engine_status": db_rec.get("status", "OPERATIONAL"),
            "is_running": db_rec.get("is_running", True),
            "summary": {
                "total_teams": total_teams,
                "em_operacao": em_operacao,
                "em_checklist": em_checklist,
                "planejadas": planejadas,
                "bloqueadas": bloqueadas,
                "protocol": "Chrome DevTools Protocol (CDP)",
                "target": "suite360.bidtech.com.br (Visão Operacional)",
                "interval": "2 minutos (120s)"
            },
            "sample_records": sample_teams,
            "action_command": "CAPTURE_BID",
            "action_label": "Disparar Sincronização BidTech (CDP) Agora"
        })

    elif engine_key in ["cloud_sync", "cloud_sync_listener"]:
        db_rec = engines_db.get("cloud_sync_listener", {})
        return jsonify({
            "status": "success",
            "engine_key": "cloud_sync",
            "name": "cloud_sync_listener",
            "label": "Banco em Nuvem Supabase",
            "icon": "database",
            "last_sync": datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S"),
            "engine_status": "OPERATIONAL",
            "is_running": True,
            "summary": {
                "provider": "Supabase PostgreSQL 15 (AWS Cloud)",
                "realtime_ws": "Ativo (wss://xgfawbqllikosyngfvwa.supabase.co)",
                "security": "Row Level Security (RLS) habilitado",
                "tables": ["team_delivery_records", "team_delivery_sessions", "team_scanner_records", "system_engine_health", "system_commands"]
            },
            "sample_records": [],
            "action_command": "TEST_CLOUD",
            "action_label": "Testar Conexão Supabase"
        })

    return jsonify({"status": "error", "message": "Motor não encontrado."}), 404

@app.route('/api/admin/restart_engines', methods=['POST'])
def restart_engines():
    """
    Reinicia os motores autônomos locais sem derrubar o servidor web.
    Se estiver na nuvem (Vercel), envia comando remoto para a máquina Windows executar.
    """
    try:
        user = get_current_user()
        is_local = request.remote_addr in ['127.0.0.1', 'localhost', '::1']
        if not user and not is_local:
            return jsonify({"status": "unauthorized", "message": "Acesso Restrito: Faça login para reiniciar motores."}), 401

        is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'
        if is_cloud:
            from supabase_client import create_sync_command, wait_for_command_completion
            user_name = (user.get("nome") if user else "Admin")
            cmd_res = create_sync_command("RESTART_ENGINES", {"requested_by": user_name})
            cmd_id = cmd_res.get("command_id")
            if cmd_id:
                finished = wait_for_command_completion(cmd_id, timeout_seconds=8)
                if finished.get("status") == "COMPLETED":
                    return jsonify({
                        "status": "success",
                        "message": "Motores locais reiniciados com sucesso pelo Agente Windows!"
                    })
                else:
                    return jsonify({
                        "status": "success",
                        "message": "Ordem de reinício enviada ao Agente Windows! Os motores estão reiniciando em segundo plano."
                    })
            return jsonify({"status": "error", "message": "Falha ao enfileirar comando no Supabase."}), 500

        print("[ADMIN] Reiniciando motores locais de segundo plano a pedido do usuário...", flush=True)
        start_background_jobs(force_restart=True)
        return jsonify({
            "status": "success",
            "message": "Motores locais (TRBOnet One, Robô CDP Enel SP, Robô CDP Spotfire e Robô CDP BidTech) reiniciados com sucesso!"
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro ao reiniciar motores: {str(e)}"}), 500

@app.route('/api/telemetry/heartbeat', methods=['POST'])
def telemetry_heartbeat():
    """Registra ou atualiza o heartbeat de uma sessão de usuário e loga no Supabase."""
    try:
        from supabase_client import upsert_user_session, log_user_access
        payload = request.get_json(force=True, silent=True) or {}
        
        # IP real do cliente
        forwarded = request.headers.get("X-Forwarded-For")
        ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "127.0.0.1")
        payload["ip_address"] = ip

        # Se houver usuário autenticado no token JWT
        user = get_current_user()
        if user:
            payload["username"] = user.get("nome") or user.get("email") or "Administrador"
            payload["user_id"] = user.get("sub")

        upsert_user_session(payload)
        log_user_access(payload)
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/admin/telemetry_metrics', methods=['GET'])
def get_telemetry_metrics():
    """Retorna estatísticas consolidadas de usuários ativos agora, hoje, semana e mês."""
    from supabase_client import fetch_session_telemetry_metrics
    data = fetch_session_telemetry_metrics()
    return jsonify(data)

def execute_trbonet_sync(source_label="Captura ao Vivo (TRBOnet One)"):
    """
    Executa a leitura direta do TRBOnet One via UIAutomation (quando em Windows Local)
    ou sincroniza com a nuvem Supabase (quando em ambiente Vercel / Cloud).
    """
    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'

    # Se estiver na Vercel (servidor na nuvem sem GUI Windows), despacha comando remoto para o Agente Local
    if is_cloud:
        cmd_res = create_sync_command("CAPTURE_TRBONET", {"source": source_label})
        if cmd_res.get("status") == "success" and cmd_res.get("command_id"):
            cmd_id = cmd_res["command_id"]
            finished_cmd = wait_for_command_completion(cmd_id, timeout_seconds=9)
            if finished_cmd.get("status") == "COMPLETED":
                latest_cloud = fetch_latest_snapshot_from_supabase()
                if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                    data_manager.load_from_snapshot(latest_cloud["data"])
                    total_rads = latest_cloud["data"].get("summary", {}).get("total_trbonet", 0)
                    return {
                        "status": "success",
                        "message": f"Agente Local Windows executou a captura com sucesso ({total_rads} rádios no TRBOnet One)!",
                        "data": latest_cloud["data"]
                    }

        # Fallback: se o agente local não respondeu a tempo, exibe o último snapshot disponível
        latest_cloud = fetch_latest_snapshot_from_supabase()
        if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
            data_manager.load_from_snapshot(latest_cloud["data"])
            return {
                "status": "warning",
                "message": "Solicitação enviada. Exibindo último snapshot em nuvem (mantenha o servidor local ativo no Windows).",
                "data": latest_cloud["data"]
            }
        else:
            return {
                "status": "warning",
                "message": "Ambiente Nuvem Vercel: Aguardando inicialização do servidor local no Windows.",
                "data": data_manager.consolidate_data()
            }

    # Ambiente Local Windows: Executa a leitura da tela do TRBOnet One via UIAutomation
    try:
        # 1. Hidrata PowerON da nuvem se não estiver em memória local
        if not data_manager.poweron_teams:
            latest_cloud = fetch_latest_snapshot_from_supabase()
            if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                data_manager.load_from_snapshot(latest_cloud["data"])

        from coletar_trbonet_completo import extrair_dados_trbonet
        radios = extrair_dados_trbonet()
        if not radios:
            return {
                "status": "warning",
                "message": "Nenhum rádio encontrado ou janela do TRBOnet One fechada no Windows.",
                "data": data_manager.consolidate_data()
            }

        updated_data = data_manager.update_data(
            trbonet_dict=radios,
            source_label=source_label
        )

        # Envia automaticamente o snapshot consolidado para o Supabase
        try:
            push_snapshot_to_supabase(updated_data)
        except Exception as err:
            print(f"[WARN] Falha ao enviar snapshot para o Supabase: {err}")

        try:
            from supabase_client import update_engine_health
            update_engine_health("trbonet_collector", "OPERATIONAL", is_running=True,
                                 error_type="NONE", last_error=None,
                                 records_count=len(radios),
                                 engine_label="Motor TRBOnet One (Rádios & GPS)")
        except Exception:
            pass

        timestamp_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{timestamp_str}] [TRBONET SYNC] {len(radios)} rádios sincronizados ({source_label}).")
        return {
            "status": "success",
            "message": f"Capturados {len(radios)} rádios ao vivo do TRBOnet One!",
            "data": updated_data
        }
    except Exception as e:
        print(f"[TRBONET SYNC ERROR] {e}")
        try:
            from supabase_client import update_engine_health
            update_engine_health("trbonet_collector", "ERROR_CONNECTION", is_running=True,
                                 error_type="CONNECTION_REFUSED", last_error=str(e),
                                 engine_label="Motor TRBOnet One (Rádios & GPS)")
        except Exception:
            pass
        return {
            "status": "error",
            "message": f"Erro na captura do TRBOnet: {str(e)}"
        }

@app.route('/api/sync/unified', methods=['POST', 'GET'])
def sync_unified_operational():
    """
    Sincroniza simultaneamente o Equipes Brasil (Portal Enel via CDP) e o TRBOnet One (UIAutomation),
    garantindo que ambas as fontes estejam 100% atualizadas em tempo real.
    Se estiver na nuvem (Vercel), despacha a ordem para o Agente Local Windows via Supabase.
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Acesso Restrito: É necessário efetuar login no Cadeado para sincronizar."
        }), 401

    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'
    if is_cloud:
        from supabase_client import create_sync_command, wait_for_command_completion, fetch_latest_snapshot_from_supabase
        cmd_res = create_sync_command("SYNC_UNIFIED", {"source": "Painel Web (Nuvem)"})
        cmd_id = cmd_res.get("command_id")
        if cmd_id:
            finished = wait_for_command_completion(cmd_id, timeout_seconds=9)
            if finished.get("status") == "COMPLETED":
                latest_cloud = fetch_latest_snapshot_from_supabase()
                if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                    data_manager.load_from_snapshot(latest_cloud["data"])
                return jsonify({
                    "status": "success",
                    "message": "Agente Local Windows executou a sincronização unificada com sucesso!",
                    "data": data_manager.consolidate_data()
                }), 200
            else:
                return jsonify({
                    "status": "queued",
                    "command_id": cmd_id,
                    "message": "Ordem de sincronização enviada ao Robô Local! Processando em segundo plano.",
                    "data": data_manager.consolidate_data()
                }), 202
        return jsonify({"status": "error", "message": "Falha ao enfileirar comando unificado no Supabase."}), 500

    enel_status = "ok"
    enel_msg = ""
    try:
        from coletor_enel_cdp import executar_ciclo_sincronizacao_enel
        res_enel = executar_ciclo_sincronizacao_enel(source_label="Sincronização Unificada")
        enel_msg = res_enel.get("message", "")
    except Exception as e_err:
        enel_status = "warn"
        enel_msg = str(e_err)
        print(f"[UNIFIED SYNC] Erro ao sincronizar Enel: {e_err}")

    # Executa a captura ao vivo do TRBOnet
    trbo_res = execute_trbonet_sync(source_label="Sincronização Unificada")
    
    # Consolida os dados mais recentes de ambas as fontes
    consolidated = data_manager.consolidate_data()
    try:
        push_snapshot_to_supabase(consolidated)
    except Exception:
        pass

    msg = f"Sincronização Unificada Concluída! {enel_msg} {trbo_res.get('message', '')}".strip()
    return jsonify({
        "status": "success",
        "message": msg,
        "data": consolidated
    }), 200

@app.route('/api/capture/trbonet', methods=['POST', 'GET'])
def capture_trbonet_live():
    """
    Executa a leitura direta da tela do TRBOnet One via UIAutomation
    e atualiza o estado do painel e do Supabase imediatamente preservando equipes do PowerON.
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Acesso Restrito: É necessário efetuar login no Cadeado para ler o TRBOnet One."
        }), 401

    res = execute_trbonet_sync(source_label="Captura Manual (Usuário)")
    status_code = 200 if res.get("status") in ["success", "warning"] else 500
    return jsonify(res), status_code

@app.route('/api/capture/enel/direct', methods=['POST', 'GET'])
def capture_enel_live():
    """
    Executa a leitura direta do portal Enel SP via Chrome DevTools Protocol (CDP)
    selecionando 500 linhas e sincronizando com o Supabase e com o delivery_manager.
    """
    from coletor_enel_cdp import executar_ciclo_sincronizacao_enel
    res = executar_ciclo_sincronizacao_enel(source_label="Captura Manual CDP (Usuário)")
    status_code = 200 if res.get("status") in ["success", "warning"] else 500
    return jsonify(res), status_code

@app.route('/api/sync/poweron', methods=['POST', 'GET'])
def sync_poweron_calendar():
    """
    Sincroniza automaticamente a escala do PowerON lendo o Arquivo Calendário mais recente
    e atualiza a nuvem Supabase preservando rádios do TRBOnet.
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Acesso Restrito: É necessário efetuar login no Cadeado para sincronizar o PowerON."
        }), 401

    try:
        # 1. Hidrata TRBOnet da nuvem se não estiver em memória
        if not data_manager.trbonet_teams:
            latest_cloud = fetch_latest_snapshot_from_supabase()
            if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                data_manager.load_from_snapshot(latest_cloud["data"])

        res = data_manager.carregar_arquivo_calendario_poweron()
        if res.get("status") == "success":
            consolidated = data_manager.consolidate_data()
            try:
                push_snapshot_to_supabase(consolidated)
            except Exception as err:
                print(f"[WARN] Falha ao enviar para o Supabase: {err}")
            res["data"] = consolidated
            return jsonify(res)
        else:
            return jsonify(res), 400
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro ao sincronizar PowerON: {str(e)}"}), 500

@app.route('/api/sync/supabase', methods=['GET', 'POST'])
def sync_supabase_endpoint():
    """
    Força o envio ou recuperação manual do Supabase.
    """
    action = request.args.get("action", "push")
    if action == "pull":
        res = fetch_latest_snapshot_from_supabase()
        return jsonify(res)
    else:
        data = data_manager.consolidate_data()
        res = push_snapshot_to_supabase(data)
        return jsonify(res)

@app.route('/api/audit/logs', methods=['GET'])
def get_audit_logs():
    """
    Retorna histórico relacional de coletas filtrado por data, equipe, base e status.
    """
    date_ref = request.args.get("date")
    team_code = request.args.get("team")
    base_code = request.args.get("base")
    status = request.args.get("status")
    limit = int(request.args.get("limit", 300))
    res = fetch_audit_logs(date_ref=date_ref, team_code=team_code, base_code=base_code, status=status, limit=limit)
    return jsonify(res)

@app.route('/api/audit/daily_summary', methods=['GET'])
def get_daily_audit_summary():
    """
    Retorna o consolidado de auditoria diária (se a equipe conectou no dia, uptime, total coletas).
    """
    date_ref = request.args.get("date")
    base_code = request.args.get("base")
    res = fetch_daily_audit_summary(date_ref=date_ref, base_code=base_code)
    return jsonify(res)

@app.route('/api/audit/team_timeline', methods=['GET'])
def get_team_timeline():
    """
    Retorna a linha do tempo detalhada de coletas de uma equipe em um determinado dia.
    """
    team_code = request.args.get("team")
    date_ref = request.args.get("date")
    if not team_code:
        return jsonify({"status": "error", "message": "Parâmetro 'team' é obrigatório"}), 400
    res = fetch_team_timeline(team_code=team_code, date_ref=date_ref)
    return jsonify(res)

@app.route('/api/delivery/team_details/<team_code>', methods=['GET'])
@app.route('/api/delivery/team-details/<team_code>', methods=['GET'])
def get_delivery_team_details(team_code):
    """
    Retorna os detalhes completos da equipe entregue no dia:
    - Informações cadastrais do portal EquipesBrasil (UT, Base, Filial, Turno, etc.)
    - Marcação e Desvio de escala
    - Histórico deduplicado de Ordens de Serviço (OS) do dia
    - Status de conexão em tempo real no TRBOnet One (rádio ID, repetidora, último sinal, GPS)
    - Situação do veículo no inventário de frotas Alpitel
    - Status do checklist na Visão Operacional BidTech (em operação, em checklist, planejada, etc.)
    - Alertas operacionais forenses consolidados
    """
    try:
        code = str(team_code).strip().upper()
        details = delivery_manager.get_team_details(code)
        team_data = details.get("team_data", {})
        order_hist = details.get("order_history", [])
        bid_info = details.get("bid_info", {})

        # Se não houver histórico em memória (ex: reinício), busca do Supabase como contingência
        if not order_hist:
            try:
                from supabase_client import fetch_team_order_history
                cloud_hist = fetch_team_order_history(code)
                if cloud_hist:
                    order_hist = [
                        {
                            "ordem": o.get("ordem_servico"),
                            "first_seen": (o.get("first_seen_at") or "")[-8:],
                            "last_seen": (o.get("last_seen_at") or "")[-8:],
                            "status": o.get("status", "Em atendimento"),
                            "cycles_count": o.get("cycles_count", 1)
                        }
                        for o in cloud_hist
                    ]
            except Exception:
                pass

        # 2. Checagem em tempo real no TRBOnet One
        trbo_teams = getattr(data_manager, "trbonet_teams", {})
        in_trbonet = code in trbo_teams
        trbo_info = trbo_teams.get(code, {}) if in_trbonet else {}
        has_gps = bool(trbo_info.get("gps", False)) if in_trbonet else False
        last_signal = trbo_info.get("last_signal", "--:--:--") if in_trbonet else None
        radio_id = trbo_info.get("radio_id", "N/A") if in_trbonet else None
        channel = trbo_info.get("channel", "N/A") if in_trbonet else None

        if in_trbonet:
            if has_gps:
                trbo_status_label = "Conectado com GPS Ativo"
                trbo_status_code = "CONNECTED_GPS"
                trbo_details = "Rádio comunicando normalmente com coordenadas GPS transmitidas em tempo real."
            else:
                trbo_status_label = "Conectado sem Sinal GPS"
                trbo_status_code = "CONNECTED_NO_GPS"
                trbo_details = "Rádio ativo no TRBOnet, porém sem fixação de coordenadas de satélite no momento."
        else:
            trbo_status_label = "Desconectado / Sem Sinal de Rádio"
            trbo_status_code = "DISCONNECTED"
            trbo_details = "Equipe sem transmissão de sinal ou rádio desligado/fora de área no TRBOnet One."

        # 3. Cruzamento de Frota
        plate = team_data.get("plate", "--")
        fleet_match = fleet_client.cross_reference_plate(plate)

        # 4. Alertas Operacionais Forenses
        alerts = []
        is_active = team_data.get("is_active", True)

        # 4.1 Alertas do BID (Visão Operacional)
        if is_active:
            bid_st = bid_info.get("status_bid")
            if not bid_info:
                alerts.append({
                    "type": "danger",
                    "title": "Alerta Gravíssimo: Não Encontrada no BID",
                    "message": "Equipe ativa no Equipes Brasil sem nenhum card na Visão Operacional BidTech."
                })
            elif bid_st == "Planejada":
                alerts.append({
                    "type": "danger",
                    "title": "Alerta Grave: Sem Checklist Iniciado",
                    "message": "Equipe logada no Equipes Brasil mas ainda consta como 'Planejada' no BID (checklist pendente)."
                })
            elif bid_st == "Em Checklist":
                alerts.append({
                    "type": "warning",
                    "title": "Alerta Crítico: Checklist em Andamento",
                    "message": "Equipe logada no Equipes Brasil enquanto o checklist ainda está sendo preenchido no BID."
                })
            elif bid_st in ["Bloqueada", "Retornada"]:
                alerts.append({
                    "type": "danger",
                    "title": f"Alerta Impeditivo: Status BID {bid_st.upper()}",
                    "message": f"Equipe logada no Equipes Brasil mas com status impeditivo '{bid_st}' na plataforma BID."
                })

        # 4.2 Alertas de TRBOnet
        if is_active and not in_trbonet:
            alerts.append({
                "type": "danger",
                "title": "Alerta de Rádio TRBOnet",
                "message": "Equipe ativa no EquipesBrasil mas SEM conexão no TRBOnet One!"
            })
        elif in_trbonet and not has_gps:
            alerts.append({
                "type": "warning",
                "title": "Alerta de GPS TRBOnet",
                "message": "Rádio conectado no TRBOnet One, porém sem transmissão de sinal GPS."
            })

        # 4.3 Alertas de Frota
        situacao_frota = str(fleet_match.get("situacao_veiculo_cadastrado", "")).upper()
        if not fleet_match.get("plate_cadastrada", False) and plate not in ["--", "", "Sem placa", "SEM PLACA"]:
            alerts.append({
                "type": "danger",
                "title": "Veículo Não Cadastrado",
                "message": f"Placa {plate} não consta no inventário oficial de frotas da Alpitel."
            })
        elif situacao_frota in ["PARADO", "MANUTENÇÃO", "MANUTENCAO"]:
            alerts.append({
                "type": "danger",
                "title": "Restrição de Frota",
                "message": f"Veículo placa {plate} está registrado na frota como {situacao_frota}!"
            })

        # 4.4 Alertas de Desvio
        desvio_min = team_data.get("desvio_minutos", 0)
        if desvio_min is not None and abs(desvio_min) > 30:
            alerts.append({
                "type": "warning",
                "title": "Desvio Elevado de Escala",
                "message": f"A equipe registrou marcação com desvio de {team_data.get('desvio', '')} em relação ao turno programado."
            })

        return jsonify({
            "status": "success",
            "team_code": code,
            "found": details.get("found", False),
            "delivery": team_data,
            "order_history": order_hist,
            "bid_info": bid_info,
            "trbonet": {
                "connected": in_trbonet,
                "status_code": trbo_status_code,
                "status_label": trbo_status_label,
                "details": trbo_details,
                "radio_id": radio_id,
                "channel": channel,
                "last_signal": last_signal,
                "has_gps": has_gps
            },
            "fleet": fleet_match,
            "alerts": alerts
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/update_data', methods=['POST'])
def update_data():
    """
    Endpoint para receber dados atualizados de scripts de extração / rotinas agendadas.
    """
    payload = request.get_json(silent=True) or {}
    poweron_teams = payload.get("poweron_teams")
    trbonet_teams = payload.get("trbonet_teams")
    source = payload.get("source", "API Externa")

    if poweron_teams is None and trbonet_teams is None:
        return jsonify({
            "status": "error",
            "message": "Nenhum dado de 'poweron_teams' ou 'trbonet_teams' foi enviado."
        }), 400

    try:
        updated_data = data_manager.update_data(
            poweron_list=poweron_teams,
            trbonet_dict=trbonet_teams,
            source_label=source
        )
        try:
            push_snapshot_to_supabase(updated_data)
        except Exception:
            pass

        return jsonify({
            "status": "success",
            "message": f"Dados atualizados com sucesso via {source}!",
            "data": updated_data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Falha ao atualizar dados: {str(e)}"
        }), 500

def read_uploaded_dataframe(file_storage):
    """
    Lê um arquivo enviado via upload suportando UTF-16, UTF-8 com BOM, Latin1, TSV, CSV e Excel (.xlsx/.xls).
    Inclui fallback seguro em Python puro caso bibliotecas externas falhem.
    """
    filename = (file_storage.filename or '').lower()
    file_storage.seek(0)
    content = file_storage.read()
    
    # 1. Tenta leitura de arquivos Excel
    if filename.endswith(('.xlsx', '.xls')):
        try:
            import pandas as pd
            return pd.read_excel(io.BytesIO(content))
        except Exception as e:
            print(f"[WARN] Falha ao ler Excel com pandas: {e}")

    # 2. Tenta leitura de arquivos de texto / CSV / TSV com pandas
    try:
        import pandas as pd
        for enc in ['utf-16', 'utf-8-sig', 'utf-8', 'latin1', 'cp1252', 'iso-8859-1']:
            for sep in ['\t', ';', ',', None]:
                try:
                    bio = io.BytesIO(content)
                    if sep is None:
                        df = pd.read_csv(bio, sep=None, engine='python', encoding=enc, on_bad_lines='skip')
                    else:
                        df = pd.read_csv(bio, sep=sep, encoding=enc, on_bad_lines='skip')
                    if df is not None and len(df.columns) >= 1:
                        return df
                except Exception:
                    pass
    except Exception as err_pd:
        print(f"[WARN] Pandas indisponível ou com erro: {err_pd}")

    # 3. Fallback em Python Puro (sem dependência de pandas)
    text_content = None
    for enc in ['utf-16', 'utf-8-sig', 'utf-8', 'latin1', 'cp1252', 'iso-8859-1']:
        try:
            text_content = content.decode(enc)
            break
        except Exception:
            continue

    if not text_content:
        text_content = content.decode('latin1', errors='ignore')

    lines = [line.strip() for line in text_content.splitlines() if line.strip()]
    if not lines:
        raise ValueError("Arquivo de texto vazio.")

    # Detectar delimitador (tab, ponto-e-vírgula ou vírgula)
    first_line = lines[0]
    sep = '\t' if '\t' in first_line else (';' if ';' in first_line else ',')
    
    import csv
    reader = csv.reader(lines, delimiter=sep)
    rows = list(reader)
    if not rows:
        raise ValueError("Nenhum registro encontrado no arquivo.")

    headers = [str(h).strip() for h in rows[0]]
    data_rows = rows[1:]

    # Converte para DataFrame se pandas estiver disponível, senão constrói dicionário
    try:
        import pandas as pd
        return pd.DataFrame(data_rows, columns=headers)
    except Exception:
        # Mini wrapper com suporte a .columns, iterrows() e indexação
        class SimpleDF:
            def __init__(self, data, columns):
                self.columns = columns
                self._data = data
            def iterrows(self):
                for idx, row in enumerate(self._data):
                    row_dict = {col: (row[i] if i < len(row) else '') for i, col in enumerate(self.columns)}
                    yield idx, row_dict
            def __getitem__(self, col):
                if col in self.columns:
                    col_idx = self.columns.index(col)
                    return SimpleSeries([r[col_idx] if col_idx < len(r) else '' for r in self._data])
                return SimpleSeries([])

        class SimpleSeries:
            def __init__(self, items):
                self._items = items
            def dropna(self):
                return self
            def astype(self, _):
                return self
            @property
            def str(self):
                return self
            def strip(self):
                return self
            def upper(self):
                return self
            def unique(self):
                return self
            def tolist(self):
                return [str(x).strip().upper() for x in self._items if str(x).strip()]

        return SimpleDF(data_rows, headers)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """
    Endpoint para importar planilhas Excel (.xlsx) ou CSV com as equipes.
    Permite atualizar via interface com arrastar e soltar e aplica regras de negócio CCO das 14 bases oficiais.
    """
    user = get_current_user()
    if not user:
        return jsonify({
            "status": "unauthorized",
            "message": "Acesso Restrito: É necessário efetuar login no Cadeado para importar planilhas."
        }), 401

    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado."}), 400

    file = request.files['file']
    dataset_type = request.form.get('type', 'poweron') # 'poweron' ou 'trbonet'

    if not file or file.filename == '':
        return jsonify({"status": "error", "message": "Nome de arquivo vazio."}), 400

    try:
        df = read_uploaded_dataframe(file)

        if dataset_type == 'poweron':
            # Hidrata TRBOnet se necessário
            if not data_manager.trbonet_teams:
                latest_cloud = fetch_latest_snapshot_from_supabase()
                if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                    data_manager.load_from_snapshot(latest_cloud["data"])

            # Localiza coluna de equipes
            col_equipe = [c for c in df.columns if any(term in str(c).lower().strip() for term in ['equipe', 'equipes', 'team', 'recurso'])]
            eq_col = col_equipe[0] if col_equipe else df.columns[0]

            # Regra 1: Somente equipes com LOGOFF vazio / nulo (ainda logadas)
            col_logoff = [c for c in df.columns if str(c).strip().upper() == 'LOGOFF']
            col_login = [c for c in df.columns if str(c).strip().upper() == 'LOGIN']

            raw_teams = []
            max_login_dt = None

            for _, row in df.iterrows():
                # Validação de LOGOFF
                if col_logoff:
                    val_lo = str(row.get(col_logoff[0], '')).strip().lower()
                    if val_lo not in ['', 'nan', 'nat', 'none', '-', '0']:
                        continue # Equipe já deslogou

                # Extração do maior LOGIN
                if col_login:
                    val_li = str(row.get(col_login[0], '')).strip()
                    if val_li and val_li.lower() not in ['', 'nan', 'nat', 'none', '-']:
                        try:
                            dt = datetime.strptime(val_li, '%d/%m/%Y %H:%M:%S')
                            if not max_login_dt or dt > max_login_dt:
                                max_login_dt = dt
                        except Exception:
                            try:
                                dt = datetime.strptime(val_li, '%Y-%m-%d %H:%M:%S')
                                if not max_login_dt or dt > max_login_dt:
                                    max_login_dt = dt
                            except Exception:
                                pass

                team_val = str(row.get(eq_col, '')).strip().upper()
                if team_val and team_val != 'NAN':
                    raw_teams.append(team_val)

            if max_login_dt:
                data_manager.last_poweron_login = max_login_dt.strftime("%d/%m/%Y %H:%M:%S")

            extracted_teams = sorted(list(set(raw_teams)))
            # Regra 3: Filtrar ESTRITAMENTE as 14 bases oficiais
            extracted_teams = [
                t for t in extracted_teams 
                if len(t) >= 4 and t[:3] in data_manager.official_bases
            ]

            data_manager.update_data(
                poweron_list=extracted_teams, 
                source_label=f"Upload Arquivo: {file.filename} (PowerON)"
            )
        else:
            # Hidrata PowerON se necessário
            if not data_manager.poweron_teams:
                latest_cloud = fetch_latest_snapshot_from_supabase()
                if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
                    data_manager.load_from_snapshot(latest_cloud["data"])

            col_equipe = [c for c in df.columns if any(term in str(c).lower().strip() for term in ['equipe', 'equipes', 'team', 'recurso', 'radio', 'id'])]
            eq_col = col_equipe[0] if col_equipe else df.columns[0]

            gps_col = None
            for col in df.columns:
                col_str = str(col).lower().strip()
                if 'gps' in col_str or 'satelite' in col_str:
                    gps_col = col
                    break
            
            trbo_dict = {}
            for _, row in df.iterrows():
                code = str(row.get(eq_col, '')).strip().upper()
                if len(code) >= 4 and code[:3] in data_manager.official_bases:
                    has_gps = True
                    if gps_col:
                        val = str(row.get(gps_col, '')).lower().strip()
                        has_gps = val in ['true', '1', 'sim', 's', 'yes', 'y', 'ok']
                    trbo_dict[code] = {
                        "id": str(row.get('id', code)),
                        "name": code,
                        "gps": has_gps,
                        "channel": str(row.get('channel', 'Canal Principal')),
                        "last_signal": datetime.now().strftime("%H:%M:%S")
                    }
            extracted_teams = list(trbo_dict.keys())
            data_manager.update_data(
                trbonet_dict=trbo_dict,
                source_label=f"Upload Arquivo: {file.filename} (TRBOnet)"
            )

        consolidated = data_manager.consolidate_data()
        try:
            push_snapshot_to_supabase(consolidated)
        except Exception as err:
            print(f"[WARN] Falha ao enviar para o Supabase: {err}")

        return jsonify({
            "status": "success",
            "message": f"Carregadas {len(extracted_teams)} equipes válidas das 14 bases oficiais ({file.filename})!",
            "total_equipes": len(extracted_teams),
            "data": consolidated
        })
    except Exception as e:
        print(f"[UPLOAD ERROR] {e}")
        return jsonify({"status": "error", "message": f"Erro no processamento do arquivo: {str(e)}"}), 500

@app.route('/api/export/excel', methods=['GET'])
def export_excel():
    """Gera e faz download de planilha nativa Excel (.xlsx) com 100% das equipes cruzadas."""
    if not data_manager.poweron_teams or not data_manager.trbonet_teams:
        latest_cloud = fetch_latest_snapshot_from_supabase()
        if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
            data_manager.load_from_snapshot(latest_cloud["data"])

    data = data_manager.consolidate_data()
    teams = data.get("teams", [])
    summary = data.get("summary", {})

    rows = []
    for t in teams:
        rows.append({
            "Código Equipe": t.get("code", ""),
            "Base Operacional": t.get("base", ""),
            "Sigla Base": t.get("prefix", ""),
            "Região / Empresa": t.get("region", ""),
            "Status de Conformidade": t.get("status_label") or t.get("status_code", ""),
            "Escala PowerON": "SIM (ESCALADA)" if t.get("poweron") else "NÃO (FORA DA ESCALA)",
            "Conexão TRBOnet": "ONLINE (CONECTADO)" if t.get("trbonet") else "DESCONECTADO",
            "Sinal GPS": "COM SINAL GPS" if t.get("gps") else "SEM SINAL GPS",
            "ID do Rádio": t.get("radio_id") or "--",
            "Canal TRBOnet": t.get("channel") or "--",
            "Último Sinal Registrado": t.get("last_signal") or "--",
            "Horário Login PowerON": t.get("login_time") or summary.get("last_poweron_login") or "--",
            "Diagnóstico CCO": t.get("details_text", "")
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Painel_Operacional_CCO')

    output.seek(0)
    filename = f"Alertas_Operacionais_PowerON_vs_TRBOnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/export/audit_excel', methods=['GET'])
def export_audit_excel():
    """Gera e faz download de planilha nativa Excel (.xlsx) da auditoria."""
    date_ref = request.args.get("date")
    base_code = request.args.get("base")
    mode = request.args.get("mode", "daily")

    if mode == "daily":
        res = fetch_daily_audit_summary(date_ref=date_ref, base_code=base_code)
        data_list = res.get("data", []) if res.get("status") == "success" else []
        rows = []
        for i in data_list:
            rows.append({
                "Data": i.get("date_ref", date_ref or "Hoje"),
                "Equipe": i.get("team_code", ""),
                "Base": i.get("base_code", ""),
                "Região": i.get("region", ""),
                "Escala PowerON": "SIM" if i.get("was_in_poweron") else "NÃO",
                "Conectou TRBOnet": "SIM" if i.get("was_online_trbonet") else "NÃO",
                "Coletas Online": i.get("times_seen_online", 0),
                "Total Coletas": i.get("total_sync_checks", 0),
                "Uptime (%)": f"{i.get('uptime_percentage', 0)}%",
                "Primeiro Sinal": i.get("first_seen_online", "--"),
                "Último Sinal": i.get("last_seen_online", "--")
            })
    else:
        res = fetch_audit_logs(date_ref=date_ref, base_code=base_code, limit=5000)
        data_list = res.get("data", []) if res.get("status") == "success" else []
        rows = []
        for i in data_list:
            rows.append({
                "Data e Hora Coleta": i.get("captured_at", ""),
                "Data Ref": i.get("date_ref", ""),
                "Equipe": i.get("team_code", ""),
                "Base": i.get("base_code", ""),
                "Região": i.get("region", ""),
                "Status": i.get("status", ""),
                "PowerON": "SIM" if i.get("in_poweron") else "NÃO",
                "TRBOnet": "SIM" if i.get("in_trbonet") else "NÃO",
                "GPS": "SIM" if i.get("has_gps") else "NÃO",
                "ID Rádio": i.get("radio_id", ""),
                "Canal": i.get("channel", ""),
                "Último Sinal": i.get("last_signal", "")
            })

    import pandas as pd
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Auditoria_CCO')

    output.seek(0)
    filename = f"Auditoria_TRBOnet_PowerON_{(date_ref or 'Hoje')}_{mode}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Gera e faz download de relatório consolidado em CSV com 100% das equipes cruzadas."""
    # Hidrata da nuvem se necessário
    if not data_manager.poweron_teams or not data_manager.trbonet_teams:
        latest_cloud = fetch_latest_snapshot_from_supabase()
        if latest_cloud.get("status") == "success" and latest_cloud.get("data"):
            data_manager.load_from_snapshot(latest_cloud["data"])

    data = data_manager.consolidate_data()
    teams = data.get("teams", [])
    summary = data.get("summary", {})

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Código Equipe", "Base Operacional", "Sigla Base", "Região / Empresa",
        "Status de Conformidade", "Escala PowerON", "Conexão TRBOnet", "Sinal GPS", 
        "ID do Rádio", "Canal TRBOnet", "Último Sinal Registrado", "Horário Login PowerON", "Diagnóstico CCO"
    ])

    for t in teams:
        writer.writerow([
            t.get("code", ""),
            t.get("base", ""),
            t.get("prefix", ""),
            t.get("region", ""),
            t.get("status_label") or t.get("status_code", ""),
            "SIM (ESCALADA)" if t.get("poweron") else "NÃO (FORA DA ESCALA)",
            "ONLINE (CONECTADO)" if t.get("trbonet") else "DESCONECTADO",
            "COM SINAL GPS" if t.get("gps") else "SEM SINAL GPS",
            t.get("radio_id") or "--",
            t.get("channel") or "--",
            t.get("last_signal") or "--",
            t.get("login_time") or summary.get("last_poweron_login") or "--",
            t.get("details_text", "")
        ])

    response = make_response(output.getvalue().encode('utf-8-sig'))
    response.headers["Content-Disposition"] = f"attachment; filename=Alertas_Operacionais_PowerON_vs_TRBOnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response

# ==============================================================================
# MÓDULO 2: ENTREGA DE EQUIPES (ENEL SP - PADRÃO TEAMS)
# ==============================================================================

@app.route('/api/teams/data', methods=['GET'])
@app.route('/api/delivery/data', methods=['GET'])
def get_teams_data():
    """Retorna o estado consolidado das equipes entregues hoje (Ativas vs Total Acumulado)."""
    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'

    # Em ambiente de nuvem (Vercel) ou se a memória local estiver vazia, hidrata sempre do Supabase
    if is_cloud or (not delivery_manager.active_teams and not delivery_manager.daily_accumulated_teams):
        cloud_snap = fetch_latest_delivery_snapshot_from_supabase()
        if cloud_snap.get("status") == "success" and cloud_snap.get("data"):
            delivery_manager.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase", captured_at=cloud_snap.get("captured_at"))

        try:
            from supabase_client import fetch_delivery_records_by_date
            op_date = delivery_manager.get_operational_date()
            today_recs = fetch_delivery_records_by_date(op_date)
            if today_recs:
                for r in today_recs:
                    t_code = r.get("team_code")
                    if t_code and t_code not in delivery_manager.daily_accumulated_teams:
                        delivery_manager.daily_accumulated_teams[t_code] = r
        except Exception:
            pass

    return jsonify(delivery_manager.get_consolidated_state())

@app.route('/api/delivery/history', methods=['GET'])
def get_delivery_history_by_date():
    """Retorna a auditoria forense de entrega para uma data específica (YYYY-MM-DD)."""
    from datetime import date
    date_str = request.args.get('date') or date.today().isoformat()
    return jsonify(delivery_manager.get_daily_audit_data(date_str))

@app.route('/api/delivery/available-dates', methods=['GET'])
def get_delivery_available_dates():
    """Retorna datas e meses com dados disponíveis no Supabase para o calendário e seletores."""
    return jsonify(delivery_manager.get_available_audit_dates())

@app.route('/api/commands/<cmd_id>', methods=['GET'])
def get_command_status_route(cmd_id):
    """Consulta o status de um comando assíncrono (PENDING, PROCESSING, COMPLETED, ERROR)."""
    try:
        from supabase_client import BASE_REST_URL, get_headers
        import requests
        endpoint = f"{BASE_REST_URL}/system_commands?id=eq.{cmd_id}&select=*"
        resp = requests.get(endpoint, headers=get_headers(), timeout=4)
        if resp.status_code == 200:
            data = resp.json()
            if data and isinstance(data, list):
                return jsonify(data[0])
        return jsonify({"status": "NOT_FOUND"}), 404
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500

@app.route('/api/capture/enel', methods=['GET', 'POST'])
def trigger_enel_capture():
    """Dispara a captura autônoma de equipes do portal Enel SP via robô CDP."""
    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'
    if is_cloud:
        from supabase_client import create_sync_command, wait_for_command_completion
        cmd_res = create_sync_command("CAPTURE_ENEL", {"source": "Painel Web"})
        cmd_id = cmd_res.get("command_id")
        if cmd_id:
            # Aguarda até 5 segundos para conclusão imediata
            result = wait_for_command_completion(cmd_id, timeout_seconds=5)
            if result.get("status") == "COMPLETED":
                return jsonify({"status": "success", "command_id": cmd_id, "message": "Coleta da Enel concluída com sucesso pelo Agente Local!"}), 200
            elif result.get("status") == "ERROR":
                return jsonify({"status": "error", "command_id": cmd_id, "message": result.get("message", "Falha reportada pelo Agente Local.")}), 500
            else:
                # Retorna 202 Accepted sem estourar o timeout de 10s da Vercel!
                return jsonify({
                    "status": "queued",
                    "command_id": cmd_id,
                    "message": "Comando enviado com sucesso ao Robô Local! Coleta em andamento em segundo plano."
                }), 202
        return jsonify({"status": "error", "message": "Falha ao enfileirar comando no Supabase."}), 500
    else:
        try:
            from coletor_enel_cdp import executar_ciclo_sincronizacao_enel
            res = executar_ciclo_sincronizacao_enel(source_label="Disparo Manual Web")
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delivery/history/monthly', methods=['GET'])
@app.route('/api/delivery/monthly', methods=['GET'])
def get_delivery_monthly_audit():
    """Retorna consolidação e média diária de equipes entregues no mês (YYYY-MM)."""
    from datetime import date
    month_str = request.args.get('month') or date.today().strftime('%Y-%m')
    return jsonify(delivery_manager.get_monthly_audit_data(month_str))

@app.route('/api/delivery/spotfire/sync', methods=['GET', 'POST'])
def trigger_spotfire_sync():
    """Dispara ciclo imediato de extração do TIBCO Spotfire Scanner 5.0 via CDP."""
    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'
    if is_cloud:
        from supabase_client import create_sync_command, wait_for_command_completion
        cmd_res = create_sync_command("CAPTURE_SPOTFIRE", {"source": "Painel Web"})
        cmd_id = cmd_res.get("command_id")
        if cmd_id:
            result = wait_for_command_completion(cmd_id, timeout_seconds=60)
            if result.get("status") == "COMPLETED":
                return jsonify({"status": "success", "message": "Extração do Scanner 5.0 concluída com sucesso pelo Agente Local!"})
            else:
                return jsonify({"status": "error", "message": result.get("message", "Timeout aguardando Agente Local.")}), 500
        return jsonify({"status": "error", "message": "Falha ao enfileirar comando."}), 500
    else:
        try:
            from coletor_spotfire_cdp import executar_ciclo_sincronizacao_spotfire
            res = executar_ciclo_sincronizacao_spotfire(source_label="Disparo Manual API")
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/delivery/integrity-check', methods=['GET'])
def get_integrity_check():
    """Retorna a auditoria forense de integridade confrontando EquipesBrasil com Spotfire."""
    from datetime import datetime, timedelta
    date_str = request.args.get('date')
    if not date_str:
        date_str = (datetime.now().date() - timedelta(days=1)).isoformat()
    return jsonify(delivery_manager.get_daily_audit_data(date_str))

@app.route('/api/delivery/targets-audit', methods=['GET'])
def get_targets_audit():
    """Retorna o comparativo oficial entre Metas Planejadas (PLAN), Entregas Efetivas (REAL) e Desvios (GAP)."""
    try:
        from datetime import date
        date_str = request.args.get('date') or date.today().isoformat()
        region = request.args.get('region') or 'Norte'
        return jsonify(delivery_manager.get_comparative_targets_audit(date_str, region))
    except Exception as e:
        print(f"[ERROR TARGETS AUDIT] {e}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "date": request.args.get('date') or "",
            "region": request.args.get('region') or "Norte",
            "tables": {"bases": [], "turno": [], "veiculo": []},
            "fleet_cards": {}
        }), 200

@app.route('/api/delivery/planning/targets', methods=['GET'])
def get_planning_targets():
    """Retorna as metas operacionais configuradas para o mês solicitado."""
    from datetime import date
    from supabase_client import fetch_delivery_planning_targets
    month_str = request.args.get('month') or date.today().strftime('%Y-%m')
    return jsonify(fetch_delivery_planning_targets(month_str))

@app.route('/api/delivery/planning/save', methods=['POST'])
def save_planning_targets_endpoint():
    """Salva novas metas operacionais após verificação de autenticação master."""
    from supabase_client import save_delivery_planning_targets
    payload = request.get_json(silent=True) or {}
    password = str(payload.get('master_password', '')).strip()
    user_email = str(payload.get('user_email', 'admin@alpitelbrasil.com.br')).strip()
    targets = payload.get('targets')

    # Validação Master
    if password not in ['Tim@3021', 'admin3021', 'master3021']:
        return jsonify({"status": "error", "message": "Senha Master inválida. Acesso não autorizado."}), 403

    if not targets or not isinstance(targets, dict):
        return jsonify({"status": "error", "message": "Dados de metas inválidos."}), 400

    res = save_delivery_planning_targets(targets, user_email=user_email)
    return jsonify(res)



@app.route('/api/teams/sync', methods=['POST', 'OPTIONS'])
@app.route('/api/delivery/sync', methods=['POST', 'OPTIONS'])
def sync_teams_records():
    """Recebe lote de registros extraídos do portal Enel e persiste no Supabase."""
    if request.method == 'OPTIONS':
        return jsonify({"status": "ok"}), 200
    try:
        payload = request.get_json(force=True, silent=True) or {}
        records = payload.get("records") or payload.get("data") or []
        source = payload.get("source", "Extrator Web Enel SP")

        if not records or not isinstance(records, list):
            return jsonify({"status": "error", "message": "Nenhum registro enviado."}), 400

        result = delivery_manager.process_raw_enel_records(records, source_label=source)

        try:
            push_delivery_snapshot_to_supabase(result, sync_source=source)
        except Exception as err:
            print(f"[WARN] Falha ao enviar entrega para o Supabase: {err}")

        return jsonify({
            "status": "success",
            "message": f"Processadas e consolidadas {len(result.get('teams', []))} equipes entregues!",
            "data": result
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/teams/export_excel', methods=['GET'])
@app.route('/api/delivery/export_excel', methods=['GET'])
def export_teams_excel():
    """Gera e faz download de planilha Excel (.xlsx) das equipes entregues."""
    if not delivery_manager.active_teams and not delivery_manager.daily_accumulated_teams:
        cloud_snap = fetch_latest_delivery_snapshot_from_supabase()
        if cloud_snap.get("status") == "success" and cloud_snap.get("data"):
            delivery_manager.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase", captured_at=cloud_snap.get("captured_at"))

    teams = list(delivery_manager.daily_accumulated_teams.values()) if delivery_manager.daily_accumulated_teams else delivery_manager.active_teams
    rows = []
    for t in teams:
        rows.append({
            "Código Equipe": t.get("team_code", ""),
            "Base Operacional": t.get("base_name", ""),
            "Sigla Base": t.get("base_code", ""),
            "Região": t.get("region", ""),
            "Empresa": t.get("company", ""),
            "Tipo de Frota": t.get("vehicle_type", ""),
            "Categoria Veículo": t.get("vehicle_category", ""),
            "Horário Login": t.get("login_time", ""),
            "Horário Logoff": t.get("logoff_time", ""),
            "Turno Operacional": t.get("shift_slot", ""),
            "Motorista / Responsável": t.get("driver", ""),
            "Placa": t.get("plate", ""),
            "Placa Normalizada": t.get("plate_clean", ""),
            "Placa Cadastrada na Frota": "Sim" if t.get("plate_cadastrada") else "Não",
            "Situação Frota": t.get("situacao_veiculo_cadastrado", "--"),
            "Status Frota": t.get("status_veiculo_cadastrado", "--"),
            "Status Equipes Brasil": t.get("status_equipes_brasil", t.get("status", "")),
            "Tempo Atualização GPS": t.get("gps_update_str", "--"),
            "GPS (minutos)": t.get("gps_update_minutes") if t.get("gps_update_minutes") is not None else "--",
            "Data Início Descanso": t.get("data_inicio_descanso", "--"),
            "Hora Início Descanso": t.get("hora_inicio_descanso", "--"),
            "Ordem de Serviço": t.get("ordem_servico", "--"),
            "Tipo Operação": t.get("tipo_operacional", ""),
            "Status BID": t.get("status_bid", "--"),
            "UT": t.get("ut", ""),
            "Filial": t.get("filial", "")
        })

    import pandas as pd
    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Entrega_Equipes_Enel')

    output.seek(0)
    filename = f"Entrega_Equipes_Enel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@app.route('/api/bid/data', methods=['GET'])
def get_bid_reconciliation_data():
    """Retorna o estado da reconciliação forense ONLINE x BID (Equipes Brasil vs BidTech)."""
    date_str = request.args.get('date') or delivery_manager.current_date_str
    return jsonify(delivery_manager.get_online_x_bid_state(date_str))

@app.route('/api/capture/bid/direct', methods=['POST', 'GET'])
def trigger_bid_capture_direct():
    """Dispara a extração imediata do portal BidTech (Visão Operacional) via robô CDP."""
    is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'
    if is_cloud:
        from supabase_client import create_sync_command, wait_for_command_completion
        cmd_res = create_sync_command("CAPTURE_BID", {"source": "Painel Web"})
        cmd_id = cmd_res.get("command_id")
        if cmd_id:
            result = wait_for_command_completion(cmd_id, timeout_seconds=15)
            if result.get("status") == "COMPLETED":
                return jsonify({"status": "success", "message": "Coleta do BidTech concluída com sucesso pelo Agente Local!"})
            else:
                return jsonify({"status": "queued", "command_id": cmd_id, "message": "Coleta do BidTech disparada em segundo plano."}), 202
        return jsonify({"status": "error", "message": "Falha ao enfileirar comando de captura do BID."}), 500
    else:
        try:
            from coletor_bid_cdp import executar_ciclo_sincronizacao_bid
            res = executar_ciclo_sincronizacao_bid()
            return jsonify(res)
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/bid/export_excel', methods=['GET'])
def export_bid_reconciliation_excel():
    """Gera e faz download de planilha Excel (.xlsx) da reconciliação forense ONLINE x BID."""
    date_str = request.args.get('date') or delivery_manager.current_date_str
    state = delivery_manager.get_online_x_bid_state(date_str)
    rows = state.get("rows", [])

    excel_rows = []
    for r in rows:
        excel_rows.append({
            "Código Equipe": r.get("team_code", ""),
            "Status Cruzado": r.get("cross_status", ""),
            "Diagnóstico / Regra": r.get("cross_desc", ""),
            "Base Operacional": r.get("base_display", ""),
            "Região": r.get("geo", ""),
            "Turno": r.get("turno", ""),
            "Status Equipes Brasil": r.get("status_eb", ""),
            "Status Visão Operacional BID": r.get("status_bid", ""),
            "Tempo no Status BID": r.get("bid_timer_value", "--"),
            "Motorista": r.get("driver", ""),
            "Placa": r.get("plate", ""),
            "Tipo Veículo": r.get("vehicle_type", ""),
            "Telefone": r.get("bid_phone", "--"),
            "Tipo Operacional": r.get("bid_tipo_operacional", "--"),
            "Horário Login EB": r.get("login_time_eb", "--"),
            "Marcação Ponto": r.get("marcacao_eb", "--"),
            "Ordem de Serviço Atual": r.get("ordem_servico", "--")
        })

    import pandas as pd
    df = pd.DataFrame(excel_rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Online_x_BID')

    output.seek(0)
    filename = f"Reconciliacao_Online_x_BID_{date_str}_{datetime.now().strftime('%H%M%S')}.xlsx"
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

# ==============================================================================
# APIS DO SISTEMA DE CONTROLE OPERACIONAL (FROTAS / SIST-OPERACAO-NORTE)
# ==============================================================================

@app.route('/api/fleet/sync', methods=['POST', 'GET'])
def api_fleet_sync():
    """Força sincronização do inventário de veículos com o Controle Operacional."""
    res = fleet_client.sync_fleet_inventory()
    return jsonify(res)

@app.route('/api/fleet/vehicles', methods=['GET'])
def api_fleet_vehicles():
    """Retorna lista completa dos veículos cadastrados na frota."""
    vehicles = fleet_client.get_all_vehicles()
    return jsonify({
        "status": "success",
        "total": len(vehicles),
        "vehicles": vehicles
    })

@app.route('/api/fleet/summary', methods=['GET'])
def api_fleet_summary():
    """Retorna resumo estatístico do inventário de veículos da empresa."""
    return jsonify({
        "status": "success",
        "data": fleet_client.get_summary()
    })

@app.route('/api/fleet/audit-plates', methods=['GET'])
def api_fleet_audit_plates():
    """
    Cruza as equipes do Equipes Brasil com o cadastro de veículos da frota
    e categoriza inconsistências para a tela de Alertas e Atenção.
    """
    teams = delivery_manager.active_teams or list(delivery_manager.daily_accumulated_teams.values())
    if not teams:
        cloud_snap = fetch_latest_delivery_snapshot_from_supabase()
        if cloud_snap.get("status") == "success" and cloud_snap.get("data"):
            delivery_manager.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase", captured_at=cloud_snap.get("captured_at"))
            teams = delivery_manager.active_teams

    matched_ok = []
    discrepancy_nao_cadastrada = []
    discrepancy_parado_manutencao = []
    sem_placa = []

    for t in teams:
        plate = t.get("plate", "--")
        cadastrada = t.get("plate_cadastrada", False)
        situacao = str(t.get("situacao_veiculo_cadastrado", "")).upper()
        status_v = str(t.get("status_veiculo_cadastrado", "")).upper()

        item = {
            "team_code": t.get("team_code"),
            "base_code": t.get("base_code"),
            "base_name": t.get("base_name"),
            "region": t.get("region"),
            "driver": t.get("driver"),
            "plate": plate,
            "plate_clean": t.get("plate_clean"),
            "plate_cadastrada": cadastrada,
            "situacao_veiculo": situacao,
            "status_veiculo": status_v,
            "status_equipe": t.get("status_equipes_brasil", t.get("status")),
            "ordem_servico": t.get("ordem_servico"),
            "gps_update_str": t.get("gps_update_str"),
            "data_inicio_descanso": t.get("data_inicio_descanso"),
            "hora_inicio_descanso": t.get("hora_inicio_descanso")
        }

        if not plate or plate in ['--', '-', 'SEM PLACA']:
            sem_placa.append(item)
        elif not cadastrada:
            discrepancy_nao_cadastrada.append(item)
        elif situacao == 'PARADO' or 'MANUTEN' in status_v:
            discrepancy_parado_manutencao.append(item)
        else:
            matched_ok.append(item)

    return jsonify({
        "status": "success",
        "total_teams": len(teams),
        "summary": {
            "matched_ok": len(matched_ok),
            "placas_nao_cadastradas": len(discrepancy_nao_cadastrada),
            "veiculos_parados_ou_manutencao": len(discrepancy_parado_manutencao),
            "sem_placa": len(sem_placa)
        },
        "discrepancies": {
            "placas_nao_cadastradas": discrepancy_nao_cadastrada,
            "veiculos_parados_ou_manutencao": discrepancy_parado_manutencao,
            "sem_placa": sem_placa
        },
        "matched_ok": matched_ok
    })

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "online",
        "service": "alertas-operacionais-op",
        "timestamp": datetime.now().isoformat()
    })

ENGINE_THREADS = {
    "trbonet": None,
    "enel_cdp": None,
    "spotfire_cdp": None,
    "bid_cdp": None,
    "daily_10am_audit": None,
    "cloud_listener": None
}

ENGINE_STOP_EVENTS = {
    "enel_cdp": None,
    "spotfire_cdp": None,
    "bid_cdp": None
}

def trbonet_background_worker(interval_seconds=120):
    """
    Worker em segundo plano que executa a captura automática silenciosa
    do TRBOnet One a cada 2 minutos (120 segundos).
    """
    print(f"[BACKGROUND WORKER] Rotina de auto-captura do TRBOnet One iniciada (intervalo: {interval_seconds}s).")
    time.sleep(6)
    while True:
        try:
            execute_trbonet_sync(source_label="Rotina Automática (2 min)")
        except Exception as err:
            print(f"[BACKGROUND WORKER EXCEPTION] {err}")
        time.sleep(interval_seconds)

def remote_command_listener_worker(poll_interval=2.5):
    """
    Worker que escuta a tabela 'system_commands' no Supabase.
    Ao receber comandos de disparo da Nuvem Vercel (ex: 'CAPTURE_TRBONET'),
    executa a captura do TRBOnet One imediatamente na tela local do Windows
    e responde para a nuvem.
    """
    if os.name != 'nt' or os.environ.get("VERCEL"):
        return

    print(f"[REMOTE LISTENER] Escutando comandos remotos da nuvem a cada {poll_interval}s...")
    time.sleep(5)
    while True:
        try:
            pending = get_pending_commands()
            for cmd in pending:
                cmd_id = cmd.get("id")
                cmd_name = cmd.get("command")
                print(f"[REMOTE COMMAND RECEIVED] Executando comando {cmd_name} ({cmd_id})...")
                update_command_status(cmd_id, "PROCESSING")

                if cmd_name == "CAPTURE_TRBONET":
                    res = execute_trbonet_sync(source_label="Disparo Remoto Solicitado na Nuvem")
                    status = "COMPLETED" if res.get("status") == "success" else "ERROR"
                    update_command_status(cmd_id, status, res)
                elif cmd_name == "SYNC_POWERON":
                    res = data_manager.carregar_arquivo_calendario_poweron()
                    consolidated = data_manager.consolidate_data()
                    try:
                        push_snapshot_to_supabase(consolidated)
                    except Exception:
                        pass
                elif cmd_name in ["CAPTURE_ENEL", "SYNC_ENEL", "COLETAR_ENEL"]:
                    from coletor_enel_cdp import executar_ciclo_sincronizacao_enel
                    res = executar_ciclo_sincronizacao_enel(source_label="Disparo Remoto Solicitado na Nuvem")
                    status = "COMPLETED" if res.get("status") == "success" else "ERROR"
                    update_command_status(cmd_id, status, res)
                elif cmd_name in ["CAPTURE_SPOTFIRE", "SYNC_SPOTFIRE", "COLETAR_SPOTFIRE"]:
                    from coletor_spotfire_cdp import executar_ciclo_sincronizacao_spotfire
                    res = executar_ciclo_sincronizacao_spotfire(source_label="Disparo Remoto Solicitado na Nuvem")
                    status = "COMPLETED" if res.get("status") == "success" else "ERROR"
                    update_command_status(cmd_id, status, res)
                elif cmd_name in ["CAPTURE_BID", "SYNC_BID", "COLETAR_BID"]:
                    from coletor_bid_cdp import executar_ciclo_sincronizacao_bid
                    res = executar_ciclo_sincronizacao_bid()
                    status = "COMPLETED" if res.get("status") == "success" else "ERROR"
                    update_command_status(cmd_id, status, res)
                elif cmd_name in ["RESTART_ENGINES", "REINICIAR_MOTORES"]:
                    print("[REMOTE COMMAND] Reiniciando motores locais em segundo plano no Windows...", flush=True)
                    start_background_jobs(force_restart=True)
                    update_command_status(cmd_id, "COMPLETED", {"message": "Motores locais reiniciados com sucesso no Windows!"})
                elif cmd_name in ["SYNC_UNIFIED", "UNIFIED_SYNC"]:
                    print("[REMOTE COMMAND] Executando Sincronização Unificada no Windows...", flush=True)
                    try:
                        from coletor_enel_cdp import executar_ciclo_sincronizacao_enel
                        executar_ciclo_sincronizacao_enel(source_label="Disparo Remoto Unificado")
                    except Exception as e_enel:
                        print(f"[REMOTE UNIFIED ENEL WARN] {e_enel}")
                    trbo_res = execute_trbonet_sync(source_label="Disparo Remoto Unificado")
                    status = "COMPLETED" if trbo_res.get("status") in ["success", "warning"] else "ERROR"
                    update_command_status(cmd_id, status, {"message": "Sincronização unificada concluída no Windows!"})
        except Exception:
            pass
        time.sleep(poll_interval)

def daily_10am_integrity_worker():
    """
    Worker que monitora o relógio e, pontualmente às 10:00 da manhã,
    executa a conferência forense de integridade entre as equipes captadas no
    EquipesBrasil e as equipes consolidadas no TIBCO Spotfire para o dia anterior (D-1).
    Não apaga nenhum dado; apenas apura 100% da integridade e assertividade.
    """
    if os.name != 'nt' or os.environ.get("VERCEL"):
        return
    print("[INTEGRITY WORKER] Agendador de conferência diária das 10:00 ATIVO.", flush=True)
    last_run_date = None
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            # Executa na faixa das 10:00 se ainda não executou no dia de hoje
            if now.hour == 10 and last_run_date != today_str:
                d_yesterday = (now.date() - timedelta(days=1)).isoformat()
                print(f"[INTEGRITY AUDIT 10:00] Iniciando conferência forense de integridade para a data {d_yesterday}...", flush=True)
                audit_result = delivery_manager.get_daily_audit_data(d_yesterday)
                reconcil = audit_result.get("reconciliation", {})
                rate = reconcil.get("assertiveness_rate", 0)
                tot_eb = reconcil.get("total_equipes_brasil", 0)
                tot_sp = reconcil.get("total_spotfire", 0)
                tot_logoff = reconcil.get("total_with_logoff", 0)
                print(f"[INTEGRITY AUDIT 10:00 OK] Data: {d_yesterday} | EquipesBrasil: {tot_eb} | Spotfire: {tot_sp} | Com Logoff: {tot_logoff} | Assertividade: {rate}%", flush=True)
                last_run_date = today_str
        except Exception as err:
            print(f"[INTEGRITY WORKER EXCEPTION] {err}", flush=True)
        time.sleep(60)

def start_background_jobs(force_restart=False):
    """Inicia threads de captura periódica e escuta de comandos remotos da nuvem."""
    if os.name == 'nt' and not os.environ.get("VERCEL"):
        # 1. Rotina de auto-captura do TRBOnet One (120s)
        if force_restart or ENGINE_THREADS["trbonet"] is None or not ENGINE_THREADS["trbonet"].is_alive():
            bg_sync = threading.Thread(target=trbonet_background_worker, args=(120,), daemon=True)
            bg_sync.start()
            ENGINE_THREADS["trbonet"] = bg_sync

        # 2. Escuta de comandos remotos da nuvem Supabase (2.5s)
        if force_restart or ENGINE_THREADS["cloud_listener"] is None or not ENGINE_THREADS["cloud_listener"].is_alive():
            bg_listener = threading.Thread(target=remote_command_listener_worker, args=(2.5,), daemon=True)
            bg_listener.start()
            ENGINE_THREADS["cloud_listener"] = bg_listener

        # 3. Rotina de auto-captura autônoma da Enel SP via CDP (120s)
        try:
            from coletor_enel_cdp import enel_background_worker
            if force_restart and ENGINE_STOP_EVENTS.get("enel_cdp") is not None:
                ENGINE_STOP_EVENTS["enel_cdp"].set()
            if force_restart or ENGINE_THREADS["enel_cdp"] is None or not ENGINE_THREADS["enel_cdp"].is_alive():
                stop_evt_enel = threading.Event()
                ENGINE_STOP_EVENTS["enel_cdp"] = stop_evt_enel
                bg_enel = threading.Thread(target=enel_background_worker, args=(120, stop_evt_enel), daemon=True)
                bg_enel.start()
                ENGINE_THREADS["enel_cdp"] = bg_enel
        except Exception as err:
            print(f"[WARN] Falha ao iniciar worker Enel CDP: {err}", flush=True)

        # 4. Rotina de auto-captura autônoma do TIBCO Spotfire via CDP (1800s)
        try:
            from coletor_spotfire_cdp import spotfire_background_worker
            if force_restart and ENGINE_STOP_EVENTS.get("spotfire_cdp") is not None:
                ENGINE_STOP_EVENTS["spotfire_cdp"].set()
            if force_restart or ENGINE_THREADS["spotfire_cdp"] is None or not ENGINE_THREADS["spotfire_cdp"].is_alive():
                stop_evt_spotfire = threading.Event()
                ENGINE_STOP_EVENTS["spotfire_cdp"] = stop_evt_spotfire
                bg_spotfire = threading.Thread(target=spotfire_background_worker, args=(1800, stop_evt_spotfire), daemon=True)
                bg_spotfire.start()
                ENGINE_THREADS["spotfire_cdp"] = bg_spotfire
        except Exception as err:
            print(f"[WARN] Falha ao iniciar worker Spotfire CDP: {err}", flush=True)

        # 5. Rotina de auto-captura autônoma do portal BidTech (Visão Operacional) via CDP (120s)
        try:
            from coletor_bid_cdp import bid_background_worker
            if force_restart and ENGINE_STOP_EVENTS.get("bid_cdp") is not None:
                ENGINE_STOP_EVENTS["bid_cdp"].set()
            if force_restart or ENGINE_THREADS["bid_cdp"] is None or not ENGINE_THREADS["bid_cdp"].is_alive():
                stop_evt_bid = threading.Event()
                ENGINE_STOP_EVENTS["bid_cdp"] = stop_evt_bid
                bg_bid = threading.Thread(target=bid_background_worker, args=(120, stop_evt_bid), daemon=True)
                bg_bid.start()
                ENGINE_THREADS["bid_cdp"] = bg_bid
        except Exception as err:
            print(f"[WARN] Falha ao iniciar worker BidTech CDP: {err}", flush=True)

        # 6. Agendador da conferência forense diária das 10:00
        if force_restart or ENGINE_THREADS["daily_10am_audit"] is None or not ENGINE_THREADS["daily_10am_audit"].is_alive():
            bg_10am = threading.Thread(target=daily_10am_integrity_worker, daemon=True)
            bg_10am.start()
            ENGINE_THREADS["daily_10am_audit"] = bg_10am

        # 7. Sincronização do Inventário de Frotas (Controle Operacional / sist-operacao-norte)
        try:
            bg_fleet = threading.Thread(target=fleet_client.sync_fleet_inventory, daemon=True)
            bg_fleet.start()
        except Exception as err:
            print(f"[WARN] Falha ao disparar sincronização inicial de frotas: {err}", flush=True)

if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("\n" + "="*70)
    print("[INICIANDO] ALERTAS OPERACIONAIS OP: STATUS TRBONET & EQUIPES BRASIL")
    print("[OK] Servidor Local Ativo em: http://127.0.0.1:5000")
    print("[ROUTINE] Rotina de Atualização Automática do TRBOnet One (2 min) ATIVA")
    print("[ROUTINE] Rotina de Atualização Automática da Enel SP CDP (2 min) ATIVA")
    print("[ROUTINE] Rotina de Atualização Automática do TIBCO Spotfire Scanner 5.0 (30 min) ATIVA")
    print("[ROUTINE] Rotina de Atualização Automática do BidTech Visão Operacional (2 min) ATIVA")
    print("[ROUTINE] Sincronização e Auditoria de Frotas (Controle Operacional) ATIVA")
    print("[ROUTINE] Agendador de Conferência Forense Diária (10:00 AM) ATIVO")
    print("="*70 + "\n")
    
    start_background_jobs()
    app.run(host='0.0.0.0', port=5000, debug=False)

