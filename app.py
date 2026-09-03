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
    Retorna o status detalhado em tempo real de todos os motores:
    1. Motor TRBOnet One (Rádios & GPS)
    2. Robô CDP Enel SP (Equipes & Turnos - Porta 9222)
    3. Sincronizador em Nuvem Supabase
    Discrimina se a falha é de CONEXÃO ou se o PROCESSO PAROU.
    """
    from supabase_client import fetch_all_engine_health, update_engine_health, BASE_REST_URL, get_headers
    from delivery_manager import delivery_manager

    # 1. Motor Enel CDP
    port_9222_open = check_port_listening("127.0.0.1", 9222)
    thread_enel_alive = ENGINE_THREADS.get("enel_cdp") is not None and ENGINE_THREADS["enel_cdp"].is_alive()

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
                         records_count=len(delivery_manager.active_teams))

    # 2. Motor TRBOnet One
    thread_trbo_alive = ENGINE_THREADS.get("trbonet") is not None and ENGINE_THREADS["trbonet"].is_alive()
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
                         records_count=len(data_manager.trbonet_teams))

    # 3. Sincronizador Nuvem Supabase
    try:
        resp = requests.get(f"{BASE_REST_URL}/system_engine_health?select=engine_name&limit=1", headers=get_headers(), timeout=6)
        cloud_ok = resp.status_code in [200, 206]
    except Exception as exc:
        print(f"[ENGINE_STATUS ERROR] Supabase check failed: {exc}")
        cloud_ok = False

    cloud_status = "OPERATIONAL" if cloud_ok else "ERROR_CONNECTION"
    cloud_msg = "Operacional: Conexão REST com banco Supabase ativa." if cloud_ok else "Falha de Conexão: Supabase inacessível ou sem internet."
    update_engine_health("cloud_sync_listener", cloud_status, is_running=True,
                         error_type="NONE" if cloud_ok else "CONNECTION_REFUSED",
                         last_error=cloud_msg, records_count=0)

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
                "last_sync": data_manager.last_trbonet_sync,
                "records": len(data_manager.trbonet_teams)
            },
            "enel_cdp": {
                "name": "enel_cdp_collector",
                "label": "Robô CDP Enel SP (Equipes & Turnos)",
                "status": enel_status,
                "is_running": thread_enel_alive,
                "error_type": enel_error_type,
                "message": enel_msg,
                "last_sync": delivery_manager.last_sync_time,
                "records": len(delivery_manager.active_teams)
            },
            "cloud_sync": {
                "name": "cloud_sync_listener",
                "label": "Sincronizador Nuvem Supabase",
                "status": cloud_status,
                "is_running": True,
                "error_type": "NONE" if cloud_ok else "CONNECTION_REFUSED",
                "message": cloud_msg,
                "last_sync": datetime.now().strftime("%H:%M:%S"),
                "records": 0
            }
        }
    })

@app.route('/api/admin/restart_engines', methods=['POST'])
def restart_engines():
    """
    Reinicia os motores autônomos locais sem derrubar o servidor web.
    """
    try:
        user = get_current_user()
        if not user:
            return jsonify({"status": "unauthorized", "message": "Acesso Restrito: Faça login para reiniciar motores."}), 401

        print("[ADMIN] Reiniciando motores locais de segundo plano a pedido do usuário...")
        start_background_jobs(force_restart=True)
        return jsonify({
            "status": "success",
            "message": "Motores locais (TRBOnet One e Robô CDP Enel SP) reiniciados com sucesso!"
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

        timestamp_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{timestamp_str}] [TRBONET SYNC] {len(radios)} rádios sincronizados ({source_label}).")
        return {
            "status": "success",
            "message": f"Capturados {len(radios)} rádios ao vivo do TRBOnet One!",
            "data": updated_data
        }
    except Exception as e:
        print(f"[TRBONET SYNC ERROR] {e}")
        return {
            "status": "error",
            "message": f"Erro na captura do TRBOnet: {str(e)}"
        }

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

@app.route('/api/capture/enel', methods=['POST', 'GET'])
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
            delivery_manager.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase")

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

@app.route('/api/delivery/monthly', methods=['GET'])
def get_delivery_monthly_audit():
    """Retorna consolidação e média diária de equipes entregues no mês (YYYY-MM)."""
    from datetime import date
    month_str = request.args.get('month') or date.today().strftime('%Y-%m')
    return jsonify(delivery_manager.get_monthly_audit_data(month_str))

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
            delivery_manager.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase")

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
            "Status Operacional": t.get("status", ""),
            "Tipo Operação": t.get("tipo_operacional", ""),
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
    "cloud_listener": None
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
        except Exception:
            pass
        time.sleep(poll_interval)

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
            if force_restart or ENGINE_THREADS["enel_cdp"] is None or not ENGINE_THREADS["enel_cdp"].is_alive():
                bg_enel = threading.Thread(target=enel_background_worker, args=(120,), daemon=True)
                bg_enel.start()
                ENGINE_THREADS["enel_cdp"] = bg_enel
        except Exception as err:
            print(f"[WARN] Falha ao iniciar worker Enel CDP: {err}")

if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("\n" + "="*70)
    print("[INICIANDO] ALERTAS OPERACIONAIS OP: POWERON vs TRBONET")
    print("[OK] Servidor Local Ativo em: http://127.0.0.1:5000")
    print("[ROUTINE] Rotina de Atualização Automática do TRBOnet One (2 min) ATIVA")
    print("[ROUTINE] Rotina de Atualização Automática da Enel SP CDP (2 min) ATIVA")
    print("="*70 + "\n")
    
    start_background_jobs()
    app.run(host='0.0.0.0', port=5000, debug=False)

