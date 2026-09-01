"""
Servidor Flask - Painel Operacional PowerON vs TRBOnet
Fornece rotas web, APIs RESTful para sincronização em tempo real e upload de arquivos.
"""

from flask import Flask, render_template, jsonify, request, send_file, make_response
import io
import os
import csv
from datetime import datetime
from data_manager import data_manager
from supabase_client import push_snapshot_to_supabase, fetch_latest_snapshot_from_supabase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static'),
    static_url_path='/static'
)
app.config['JSON_SORT_KEYS'] = False

@app.route('/')
def index():
    """Renderiza a página principal do dashboard."""
    return render_template('index.html')

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
    No Vercel (ou em nuvem), tenta carregar o snapshot mais recente do Supabase.
    """
    try:
        # Se estiver em ambiente Vercel/Cloud ou requisitado explicitamente, busca do Supabase
        if os.environ.get("VERCEL") or request.args.get("source") == "supabase":
            cloud_res = fetch_latest_snapshot_from_supabase()
            if cloud_res.get("status") == "success" and cloud_res.get("data"):
                return jsonify({
                    "status": "success",
                    "source": "supabase_cloud",
                    "data": cloud_res["data"]
                })

        # Caso local ou fallback
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

@app.route('/api/reset', methods=['POST'])
def reset_data():
    """Restaura o dataset de referência inicial."""
    data = data_manager.reset_to_baseline()
    try:
        push_snapshot_to_supabase(data)
    except Exception:
        pass
    return jsonify({
        "status": "success",
        "message": "Base de dados restaurada para o estado de referência original.",
        "data": data
    })

@app.route('/api/capture/trbonet', methods=['POST', 'GET'])
def capture_trbonet_live():
    """
    Executa a leitura direta da tela do TRBOnet One via UIAutomation
    e atualiza o estado do painel e do Supabase imediatamente.
    """
    try:
        from coletar_trbonet_completo import extrair_dados_trbonet
        radios = extrair_dados_trbonet()
        if not radios:
            return jsonify({
                "status": "warning",
                "message": "Nenhum rádio encontrado ou TRBOnet One fechado.",
                "data": data_manager.consolidate_data()
            })
        
        updated_data = data_manager.update_data(
            trbonet_dict=radios,
            source_label="Captura ao Vivo (TRBOnet One)"
        )
        
        # Envia automaticamente o snapshot consolidado para o Supabase
        try:
            push_snapshot_to_supabase(updated_data)
        except Exception as err:
            print(f"[WARN] Falha ao enviar para o Supabase: {err}")

        return jsonify({
            "status": "success",
            "message": f"Capturados {len(radios)} rádios ao vivo do TRBOnet One!",
            "data": updated_data
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Erro na captura do TRBOnet: {str(e)}"
        }), 500

@app.route('/api/sync/poweron', methods=['POST', 'GET'])
def sync_poweron_calendar():
    """
    Sincroniza automaticamente a escala do PowerON lendo o Arquivo Calendário mais recente
    e atualiza a nuvem Supabase.
    """
    try:
        res = data_manager.carregar_arquivo_calendario_poweron()
        if res.get("status") == "success":
            try:
                push_snapshot_to_supabase(data_manager.consolidate_data())
            except Exception as err:
                print(f"[WARN] Falha ao enviar para o Supabase: {err}")
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
    Lê um arquivo enviado via upload suportando UTF-16, UTF-8 com BOM, Latin1, TSV, CSV e Excel.
    """
    import pandas as pd
    filename = file_storage.filename.lower()
    content = file_storage.read()
    
    if filename.endswith('.xlsx') or filename.endswith('.xls'):
        return pd.read_excel(io.BytesIO(content))
    
    # Tentar múltiplos encodings e separadores para CSV / TSV
    for enc in ['utf-16', 'utf-8-sig', 'utf-8', 'latin1', 'cp1252']:
        for sep in ['\t', ';', ',', None]:
            try:
                bio = io.BytesIO(content)
                if sep is None:
                    df = pd.read_csv(bio, sep=None, engine='python', encoding=enc)
                else:
                    df = pd.read_csv(bio, sep=sep, encoding=enc)
                if len(df.columns) >= 1:
                    return df
            except Exception:
                pass
                
    return pd.read_csv(io.BytesIO(content), sep=None, engine='python', encoding='latin1')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """
    Endpoint para importar planilhas Excel (.xlsx) ou CSV com as equipes.
    Permite atualizar via interface com arrastar e soltar e aplica regras de negócio CCO.
    """
    if 'file' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo enviado."}), 400

    file = request.files['file']
    dataset_type = request.form.get('type', 'poweron') # 'poweron' ou 'trbonet'

    if file.filename == '':
        return jsonify({"status": "error", "message": "Nome de arquivo vazio."}), 400

    try:
        df = read_uploaded_dataframe(file)

        if dataset_type == 'poweron':
            # Localiza coluna de equipes
            col_equipe = [c for c in df.columns if any(term in str(c).lower().strip() for term in ['equipe', 'equipes', 'team', 'recurso'])]
            eq_col = col_equipe[0] if col_equipe else df.columns[0]

            # Regra 1: Desconsiderar equipes que começam com CML
            df_val = df[~df[eq_col].astype(str).str.strip().str.upper().str.startswith('CML')].copy()

            # Regra 2: Somente equipes com LOGOFF vazio / nulo (ainda logadas)
            col_logoff = [c for c in df_val.columns if str(c).strip().upper() == 'LOGOFF']
            if col_logoff:
                lo_col = col_logoff[0]
                df_logadas = df_val[
                    df_val[lo_col].isna() | 
                    df_val[lo_col].astype(str).str.strip().isin(['', 'nan', 'NaT', 'None', '-'])
                ]
            else:
                df_logadas = df_val

            # Regra 3: Obter data e hora da última equipe logada na coluna LOGIN
            col_login = [c for c in df_logadas.columns if str(c).strip().upper() == 'LOGIN']
            if col_login and not df_logadas[col_login[0]].dropna().empty:
                logins_list = [str(x).strip() for x in df_logadas[col_login[0]].dropna().tolist() if str(x).strip() not in ['', 'nan', 'NaT', 'None', '-']]
                if logins_list:
                    data_manager.last_poweron_login = sorted(logins_list)[-1]

            extracted_teams = sorted(df_logadas[eq_col].dropna().astype(str).str.strip().str.upper().unique().tolist())
            extracted_teams = [t for t in extracted_teams if len(t) >= 4 and t != 'NAN']

            data_manager.update_data(
                poweron_list=extracted_teams, 
                source_label=f"Upload Arquivo: {file.filename} (PowerON)"
            )
        else:
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
                code = str(row[eq_col]).strip().upper()
                if len(code) >= 4 and code != 'NAN':
                    has_gps = True
                    if gps_col:
                        val = str(row[gps_col]).lower().strip()
                        has_gps = val in ['true', '1', 'sim', 's', 'yes', 'y', 'ok']
                    trbo_dict[code] = {
                        "gps": has_gps,
                        "last_signal": datetime.now().strftime("%H:%M:%S")
                    }
            extracted_teams = list(trbo_dict.keys())
            data_manager.update_data(
                trbonet_dict=trbo_dict, 
                source_label=f"Upload Arquivo: {file.filename} (TRBOnet)"
            )

        return jsonify({
            "status": "success",
            "message": f"Arquivo '{file.filename}' processado com sucesso. {len(extracted_teams)} equipes ativas carregadas!",
            "data": data_manager.consolidate_data()
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro ao processar arquivo: {str(e)}"}), 500

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Gera e faz download de relatório consolidado em CSV."""
    data = data_manager.consolidate_data()
    teams = data["teams"]

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "Código Equipe", "Base Operacional", "Sigla Base", 
        "Escala PowerON", "Conexão TRBOnet", "Sinal GPS", 
        "Status de Conformidade", "Último Sinal", "Diagnóstico"
    ])

    for t in teams:
        writer.writerow([
            t["code"],
            t["base"],
            t["prefix"],
            "LOGADA" if t["poweron"] else "NÃO LOGADA",
            "ONLINE" if t["trbonet"] else "DESCONECTADO",
            "SIM" if t["gps"] else "NÃO",
            t["status_label"],
            t.get("last_signal") or "N/A",
            t["details_text"]
        ])

    response = make_response(output.getvalue().encode('utf-8-sig'))
    response.headers["Content-Disposition"] = f"attachment; filename=Auditoria_PowerON_vs_TRBOnet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    response.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    return response

@app.route('/api/health', methods=['GET'])
def health():
    return jsonify({
        "status": "online",
        "service": "alertas-operacionais-op",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == '__main__':
    import sys
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print("\n" + "="*70)
    print("[INICIANDO] ALERTAS OPERACIONAIS OP: POWERON vs TRBONET")
    print("[OK] Servidor Local Ativo em: http://127.0.0.1:5000")
    print("="*70 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)

