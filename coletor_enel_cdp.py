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
import threading
import urllib.request
from datetime import datetime
import websocket

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
ENEL_DOMAIN_KEYWORD = "equipesbrasil.enelint.global"

_ENEL_LOCK = threading.Lock()

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
    try:
        from cdp_browser_manager import garantir_navegador_cdp_ativo
        garantir_navegador_cdp_ativo()
    except Exception:
        pass

    targets = listar_alvos_cdp()
    if not targets:
        return None

    # Procura aba estritamente do portal EquipesBrasil (nunca capturar o Spotfire)
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'spotfire' in t_url or 'spotfire' in t_title or 'elabziplra00' in t_url:
                continue
            if 'equipesbrasil.enelint.global' in t_url or 'filtro avançado' in t_title or 'login.microsoftonline.com' in t_url or 'entrar em sua conta' in t_title:
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

        # 4. Extrai todas as linhas da tabela (14 colunas oficiais com Marcação e Desvio)
        js_extract = """
        (() => {
            const rows = Array.from(document.querySelectorAll('table tbody tr, [role="row"]'));
            const headers = Array.from(document.querySelectorAll('table thead th, [role="columnheader"]')).map(h => h.innerText.trim());
            const results = [];

            // Mapeamento dinâmico de cabeçalhos
            const colMap = {};
            headers.forEach((h, idx) => {
                const cleanH = h.toUpperCase().normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
                if (cleanH.includes('UT') && colMap['ut'] === undefined) colMap['ut'] = idx;
                else if (cleanH.includes('BASE') && colMap['base'] === undefined) colMap['base'] = idx;
                else if (cleanH.includes('FILIAL') && colMap['filial'] === undefined) colMap['filial'] = idx;
                else if (cleanH.includes('VEIC') && colMap['veiculo'] === undefined) colMap['veiculo'] = idx;
                else if (cleanH.includes('EQUIPE') && colMap['equipe'] === undefined) colMap['equipe'] = idx;
                else if (cleanH.includes('TIPO') && colMap['tipo'] === undefined) colMap['tipo'] = idx;
                else if (cleanH.includes('MOTORISTA') && colMap['motorista'] === undefined) colMap['motorista'] = idx;
                else if (cleanH.includes('TURNO') && colMap['turno'] === undefined) colMap['turno'] = idx;
                else if (cleanH.includes('MARCA') && colMap['marcacao'] === undefined) colMap['marcacao'] = idx;
                else if (cleanH.includes('DESVIO') && colMap['desvio'] === undefined) colMap['desvio'] = idx;
                else if (cleanH.includes('GPS') && colMap['gps'] === undefined) colMap['gps'] = idx;
                else if (cleanH.includes('STATUS') && colMap['status'] === undefined) colMap['status'] = idx;
                else if (cleanH.includes('PLACA') && colMap['placa'] === undefined) colMap['placa'] = idx;
                else if (cleanH.includes('DESCANSO') && colMap['descanso'] === undefined) colMap['descanso'] = idx;
                else if (cleanH.includes('ORDEM') && colMap['ordem'] === undefined) colMap['ordem'] = idx;
            });

            rows.forEach(r => {
                const cells = Array.from(r.querySelectorAll('td, [role="cell"]')).map(c => c.innerText.trim());
                if (cells.length >= 8) {
                    const getVal = (key, fallbackIdx) => {
                        if (colMap[key] !== undefined && colMap[key] < cells.length && cells[colMap[key]]) {
                            return cells[colMap[key]];
                        }
                        return (fallbackIdx !== undefined && fallbackIdx < cells.length) ? cells[fallbackIdx] : '';
                    };

                    const obj = {};
                    headers.forEach((h, idx) => {
                        if (h && idx < cells.length) obj[h] = cells[idx] || '';
                    });

                    // Extração estruturada das 14 colunas oficiais
                    obj['UT'] = getVal('ut', 0);
                    obj['BASE'] = getVal('base', 1);
                    obj['FILIAL'] = getVal('filial', 2);
                    obj['VEÍCULO'] = getVal('veiculo', 3);
                    obj['EQUIPE'] = getVal('equipe', 4);
                    obj['TIPO'] = getVal('tipo', 5);
                    obj['MOTORISTA'] = getVal('motorista', 6);
                    obj['TURNO'] = getVal('turno', 7);

                    // Coluna Marcação e Desvio
                    const rawMarcacao = getVal('marcacao', 8);
                    let horaMarcacao = rawMarcacao;
                    let desvioStr = getVal('desvio', -1);

                    // Se marcação contiver desvio embutido (ex: '07:31 (+32min)')
                    if (rawMarcacao && rawMarcacao.includes('(')) {
                        const parts = rawMarcacao.split('(');
                        horaMarcacao = parts[0].trim();
                        if (!desvioStr) {
                            desvioStr = '(' + parts.slice(1).join('(').trim();
                            desvioStr = desvioStr.replace(/^[()]+|[()]+$/g, '').trim();
                        }
                    }

                    obj['MARCACAO'] = horaMarcacao || '--';
                    obj['DESVIO'] = desvioStr || '--';
                    obj['RAW_MARCACAO'] = rawMarcacao || '--';

                    obj['GPS'] = getVal('gps', 9);
                    obj['STATUS'] = getVal('status', 10) || 'Logada';
                    obj['PLACA'] = getVal('placa', 11);
                    obj['INICIO_DESCANSO'] = getVal('descanso', 12);
                    obj['ORDEM'] = getVal('ordem', 13);

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
    if not _ENEL_LOCK.acquire(blocking=False):
        ts = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts}] [CDP ENEL] Ciclo anterior ainda em andamento. Ignorando novo disparo ({source_label}).", flush=True)
        return {"status": "busy", "message": "Ciclo anterior da Enel em andamento"}

    start_t = time.time()
    ts_start = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    print(f"\n[{ts_start}] [CDP ENEL] >>> INICIANDO CICLO DE COLETA: EquipesBrasil ENEL SP ({source_label})...", flush=True)

    try:
        from delivery_manager import delivery_manager
        from supabase_client import push_delivery_snapshot_to_supabase

        res = extrair_dados_enel_via_cdp()
        if res.get("status") != "success":
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            msg = res.get('message', 'Aba não encontrada ou CDP inativo')
            print(f"[{ts_end}] [CDP ENEL] <<< CICLO FINALIZADO COM AVISO ({elapsed}s): {msg}", flush=True)
            return res

        records = res.get("records", [])
        if not records:
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            print(f"[{ts_end}] [CDP ENEL] <<< CICLO FINALIZADO: Nenhuma equipe retornada na tabela ({elapsed}s).", flush=True)
            return res

        # Consolida no delivery_manager
        consolidated = delivery_manager.process_raw_enel_records(records, source_label=source_label)

        # Persiste no Supabase
        try:
            push_delivery_snapshot_to_supabase(consolidated, sync_source=source_label)
        except Exception as err:
            print(f"[WARN] Falha ao enviar dados da Enel para o Supabase: {err}")

        elapsed = round(time.time() - start_t, 2)
        ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts_end}] [CDP ENEL] <<< CICLO FINALIZADO COM SUCESSO: {len(records)} equipes sincronizadas no Supabase em {elapsed}s ({source_label}).", flush=True)

        try:
            from supabase_client import update_engine_health
            update_engine_health("enel_cdp_collector", "OPERATIONAL", is_running=True,
                                 error_type="NONE", last_error=None,
                                 records_count=len(records),
                                 engine_label="Robô CDP Enel SP (Equipes & Turnos)")
        except Exception:
            pass

        # Dispara a sincronização sequencial do CDP BidTech Visão Operacional logo após Equipes Brasil
        try:
            from coletor_bid_cdp import executar_ciclo_sincronizacao_bid
            threading.Thread(target=executar_ciclo_sincronizacao_bid, kwargs={"source_label": "Gatilho Pós-EquipesBrasil"}, daemon=True).start()
        except Exception as b_err:
            print(f"[BID CDP AUTO TRIGGER ERROR] {b_err}", flush=True)

        return {
            "status": "success",
            "message": f"{len(records)} equipes sincronizadas com sucesso!",
            "data": consolidated
        }
    except Exception as e:
        elapsed = round(time.time() - start_t, 2)
        ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts_end}] [CDP ENEL] <<< CICLO FINALIZADO COM ERRO ({elapsed}s): {e}", flush=True)
        try:
            from supabase_client import update_engine_health
            update_engine_health("enel_cdp_collector", "ERROR_CONNECTION", is_running=True,
                                 error_type="CONNECTION_REFUSED", last_error=str(e),
                                 engine_label="Robô CDP Enel SP (Equipes & Turnos)")
        except Exception:
            pass
        return {
            "status": "error",
            "message": str(e)
        }
    finally:
        _ENEL_LOCK.release()

def enel_background_worker(interval_seconds=120, stop_event=None):
    """
    Worker executado em thread contínua a cada 2 minutos (120s),
    exatamente no mesmo padrão do TRBOnet.
    """
    print(f"[BACKGROUND WORKER] Motor CDP Enel SP ativo (intervalo: {interval_seconds}s).", flush=True)
    if stop_event:
        if stop_event.wait(5):
            return
    else:
        time.sleep(5)

    while True:
        if stop_event and stop_event.is_set():
            print("[BACKGROUND WORKER] Rotina da Enel SP finalizada.", flush=True)
            break
        try:
            executar_ciclo_sincronizacao_enel(source_label="Rotina Automática (2 min)")
        except Exception as err:
            print(f"[ENEL WORKER EXCEPTION] {err}", flush=True)
        if stop_event:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)

if __name__ == "__main__":
    print("Testando extração imediata via CDP...")
    result = executar_ciclo_sincronizacao_enel(source_label="Teste Manual CDP")
    print(json.dumps({k: v for k, v in result.items() if k != 'data'}, indent=2, ensure_ascii=False))
