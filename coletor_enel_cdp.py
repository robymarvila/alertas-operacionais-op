"""
Coletor de Dados Automatizado da Enel SP (Portal Equipes Brasil)
Utiliza Chrome DevTools Protocol (CDP) via WebSocket local (porta 9222).
Executa 100% em segundo plano a cada 2 minutos:
1. Conecta-se à aba ativa da Enel SP no Microsoft Edge / Chrome.
2. Atualiza a página (F5) para buscar os dados mais recentes da Enel.
3. Localiza o elemento <select onchange="setPageSize(this.value)"> e seleciona 500 linhas.
4. Extrai a tabela de equipes (UT, Base, Veículo, Equipe, Motorista, Turno, Status, Placa).
5. Consolida no delivery_manager e sincroniza automaticamente com o Supabase.
"""

import os
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import json
import time
import urllib.request
from datetime import datetime
import websocket

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
ENEL_DOMAIN_KEYWORD = "equipesbrasil.enelint.global"

def listar_alvos_cdp():
    """Consulta os alvos abertos no navegador via endpoint HTTP do CDP."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception as err:
        return []

def localizar_aba_enel(criar_se_nao_existir=False):
    """Localiza a aba do portal da Enel SP no Edge/Chrome."""
    targets = listar_alvos_cdp()
    if not targets:
        return None

    # Procura aba com URL ou Título da Enel
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'equipesbrasil' in t_url or ENEL_DOMAIN_KEYWORD in t_url or 'equipes' in t_title or 'enel' in t_title:
                return t

    if criar_se_nao_existir:
        try:
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?https://equipesbrasil.enelint.global/"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                new_tab = json.loads(resp.read().decode('utf-8'))
                time.sleep(3.5)
                return new_tab
        except Exception as e:
            print(f"[CDP] Erro ao abrir nova aba Enel: {e}")

    return None

class CDPClient:
    """Cliente WebSocket minimalista para o Chrome DevTools Protocol."""
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.ws_url, timeout=10, suppress_origin=True)

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def call(self, method, params=None, timeout=15):
        self.msg_id += 1
        payload = {
            "id": self.msg_id,
            "method": method,
            "params": params or {}
        }
        self.ws.send(json.dumps(payload))

        start_t = time.time()
        while time.time() - start_t < timeout:
            raw = self.ws.recv()
            if not raw:
                break
            msg = json.loads(raw)
            if msg.get("id") == self.msg_id:
                return msg.get("result", {})
        return {}

    def evaluate(self, js_code, return_by_value=True):
        """Avalia código JavaScript dentro da página e retorna o resultado."""
        res = self.call("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": return_by_value,
            "awaitPromise": True
        })
        return res.get("result", {}).get("value")

def extrair_dados_enel_via_cdp():
    """
    Executa o fluxo autônomo completo de extração via CDP:
    1. Localiza aba (ou abre automaticamente se não existir)
    2. Recarrega página
    3. Altera para 500 linhas
    4. Extrai a tabela
    """
    tab = localizar_aba_enel(criar_se_nao_existir=True)
    if not tab:
        return {
            "status": "warning",
            "message": "Aba do portal da Enel SP (equipesbrasil.enelint.global) não encontrada e não pôde ser aberta."
        }

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "status": "error",
            "message": "URL de depuração da aba Enel não disponível."
        }

    client = CDPClient(ws_url)
    try:
        client.connect()
        current_url = str(client.evaluate("location.href") or "")
        current_title = str(client.evaluate("document.title") or "")

        if "login.microsoftonline.com" in current_url or "entrar em sua conta" in current_title.lower():
            client.close()
            return {
                "status": "warning",
                "message": "Aba da Enel aguardando autenticação Microsoft SSO. Conclua o login na aba do Edge."
            }

        # 1. Garante que está na página do Filtro Avançado (/teams-list) e recarrega os dados
        if "teams-list" not in current_url.lower():
            client.evaluate("location.href = '/teams-list';")
            time.sleep(4.5)
        else:
            client.evaluate("location.reload();")
            time.sleep(3.5)

        # 2. Aguarda o DOM estar pronto
        for _ in range(12):
            ready_state = client.evaluate("document.readyState;")
            if ready_state == "complete":
                break
            time.sleep(0.5)

        # 3. Força a paginação para 500 linhas no select
        js_set_500 = """
        (() => {
            const sel = document.querySelector('select[onchange*="setPageSize"]') || document.querySelector('select');
            if (sel) {
                if (sel.value !== "500") {
                    sel.value = "500";
                    if (typeof window.setPageSize === 'function') {
                        window.setPageSize("500");
                    } else {
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                    return "PAGINATION_CHANGED_TO_500";
                }
                return "PAGINATION_ALREADY_500";
            }
            return "PAGINATION_SELECT_NOT_FOUND";
        })()
        """
        pag_status = client.evaluate(js_set_500)
        
        # Se alterou a paginação, aguarda carregar até 500 linhas
        if pag_status == "PAGINATION_CHANGED_TO_500":
            time.sleep(3.0)
        else:
            time.sleep(1.0)

        # 4. Extrai todas as linhas da tabela
        js_extract = """
        (() => {
            const rows = Array.from(document.querySelectorAll('table tbody tr, [role="row"]'));
            const headers = Array.from(document.querySelectorAll('table thead th, [role="columnheader"]')).map(h => h.innerText.trim());
            const results = [];

            rows.forEach(r => {
                const cells = Array.from(r.querySelectorAll('td, [role="cell"]')).map(c => c.innerText.trim());
                if (cells.length >= 8) {
                    const obj = {};
                    headers.forEach((h, idx) => {
                        if (h) obj[h] = cells[idx] || '';
                    });
                    // Mapeamento posicional oficial
                    obj['UT'] = cells[0] || '';
                    obj['BASE'] = cells[1] || '';
                    obj['FILIAL'] = cells[2] || '';
                    obj['VEÍCULO'] = cells[3] || '';
                    obj['EQUIPE'] = cells[4] || '';
                    obj['TIPO'] = cells[5] || '';
                    obj['MOTORISTA'] = cells[6] || '';
                    obj['TURNO'] = cells[7] || '';
                    obj['STATUS'] = cells[9] || 'Logada';
                    obj['PLACA'] = cells[11] || '--';
                    results.push(obj);
                }
            });

            return {
                count: results.length,
                headers: headers,
                data: results
            };
        })()
        """
        extracted = client.evaluate(js_extract)
        client.close()

        if not extracted or not extracted.get('data'):
            return {
                "status": "warning",
                "message": "Nenhuma linha encontrada na tabela da Enel."
            }

        records = extracted['data']
        return {
            "status": "success",
            "message": f"{len(records)} equipes capturadas via CDP (500 linhas).",
            "records": records
        }

    except Exception as err:
        client.close()
        return {
            "status": "error",
            "message": f"Erro durante a extração via CDP: {str(err)}"
        }

def executar_ciclo_sincronizacao_enel(source_label="Rotina Automática CDP (2 min)"):
    """
    Executa a extração, consolidação no delivery_manager e push para o Supabase.
    """
    try:
        from delivery_manager import delivery_manager
        from supabase_client import push_delivery_snapshot_to_supabase

        res = extrair_dados_enel_via_cdp()
        if res.get("status") != "success":
            return res

        records = res.get("records", [])
        if not records:
            return res

        # Consolida no delivery_manager
        consolidated = delivery_manager.process_raw_enel_records(records, source_label=source_label)

        # Persiste no Supabase
        try:
            push_delivery_snapshot_to_supabase(consolidated, sync_source=source_label)
        except Exception as err:
            print(f"[WARN] Falha ao enviar dados da Enel para o Supabase: {err}")

        timestamp_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{timestamp_str}] [ENEL SYNC CDP] {len(records)} equipes sincronizadas ({source_label}).", flush=True)

        return {
            "status": "success",
            "message": f"{len(records)} equipes sincronizadas com sucesso!",
            "data": consolidated
        }
    except Exception as e:
        print(f"[ENEL SYNC ERROR] {e}", flush=True)
        return {
            "status": "error",
            "message": str(e)
        }

def enel_background_worker(interval_seconds=120):
    """
    Worker executado em thread contínua a cada 2 minutos (120s),
    exatamente no mesmo padrão do TRBOnet.
    """
    print(f"[BACKGROUND WORKER] Rotina de auto-captura da Enel SP iniciada (intervalo: {interval_seconds}s).", flush=True)
    # Aguarda 10s para inicialização do servidor
    time.sleep(10)

    while True:
        try:
            executar_ciclo_sincronizacao_enel(source_label="Rotina Automática (2 min)")
        except Exception as err:
            print(f"[ENEL WORKER EXCEPTION] {err}", flush=True)
        time.sleep(interval_seconds)

if __name__ == "__main__":
    print("Testando extração imediata via CDP...")
    result = executar_ciclo_sincronizacao_enel(source_label="Teste Manual CDP")
    print(json.dumps({k: v for k, v in result.items() if k != 'data'}, indent=2, ensure_ascii=False))
