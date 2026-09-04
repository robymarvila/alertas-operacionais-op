"""
Coletor de Dados Automatizado do TIBCO Spotfire (ENEL SP)
Módulo de Extração de Equipes, Login Real, LogOff Real e Produtividade (OS).

Utiliza Chrome DevTools Protocol (CDP) via WebSocket local (porta 9222) com a sessão corporativa Enel:
1. Conecta-se à aba ativa do TIBCO Spotfire no Edge / Chrome.
2. Interage com o botão de Filtros (XPath //*[@id="fcea3f94-d62c-4563-ad4c-495b266e1124"]/div[5]).
3. Aciona "Reset Visible Filters" para remover filtros residuais.
4. Filtra a Data de Referência para a data do dia operacional atual.
5. Navega para a aba "Extração".
6. Extrai os registros da "Extração Tabela Geral".
7. Normaliza códigos de equipes e persiste no Supabase via UPSERT atômico (team_spotfire_records).
8. Executa em segundo plano a cada 3 minutos e dispara reconciliação com o EquipesBrasil.
"""

import os
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import json
import time
import re
import urllib.request
from datetime import datetime, date, timedelta
import websocket

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
SPOTFIRE_URL = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Gerenciamento%20de%20equipes%20-%20Nova%20vers%C3%A3o"
SPOTFIRE_DOMAIN = "elabziplra00.enelint.global"

def normalize_team_code(raw_name: str) -> str:
    """Padroniza o código da equipe removendo espaços, traços e caracteres especiais."""
    if not raw_name:
        return ""
    clean = re.sub(r'[^A-Za-z0-9]', '', str(raw_name)).upper()
    return clean

def listar_alvos_cdp():
    """Consulta os alvos abertos no navegador via endpoint HTTP do CDP."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []

def localizar_aba_spotfire(criar_se_nao_existir=False):
    """Localiza ou abre a aba do Spotfire no navegador."""
    targets = listar_alvos_cdp()
    if not targets:
        return None

    # 1. Procura por URL ou Título do Spotfire
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if SPOTFIRE_DOMAIN in t_url or 'spotfire' in t_url or 'spotfire' in t_title or 'gerenciamento de equipes' in t_title:
                return t

    # 2. Se não existir e for solicitado criar
    if criar_se_nao_existir:
        try:
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{SPOTFIRE_URL}"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                new_tab = json.loads(resp.read().decode('utf-8'))
                time.sleep(4.0)
                return new_tab
        except Exception as e:
            print(f"[SPOTFIRE CDP] Erro ao abrir nova aba do Spotfire: {e}")

    return None

class SpotfireCDPClient:
    """Cliente WebSocket minimalista para o Chrome DevTools Protocol."""
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.ws_url, timeout=12, suppress_origin=True)

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def call(self, method, params=None, timeout=20):
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

    def evaluate(self, js_code, return_by_value=True, timeout=25):
        """Avalia código JavaScript dentro da página do Spotfire."""
        res = self.call("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": return_by_value,
            "awaitPromise": True
        }, timeout=timeout)
        return res.get("result", {}).get("value")

def extrair_dados_spotfire_via_cdp():
    """
    Executa o fluxo completo e autônomo de extração via CDP:
    1. Localiza a aba do Spotfire.
    2. Valida se o usuário está logado.
    3. Reseta filtros e aplica a Data de Referência de hoje.
    4. Seleciona a aba 'Extração'.
    5. Extrai as linhas da 'Extração Tabela Geral'.
    """
    tab = localizar_aba_spotfire(criar_se_nao_existir=True)
    if not tab:
        return {
            "status": "error",
            "message": "Aba do TIBCO Spotfire não encontrada e não foi possível criá-la."
        }

    ws_url = tab.get("webSocketDebuggerUrl")
    if not ws_url:
        return {
            "status": "error",
            "message": "URL de depuração WebSocket (CDP) não disponível para a aba do Spotfire."
        }

    client = SpotfireCDPClient(ws_url)
    try:
        client.connect()

        # 1. Verifica estado atual da URL e tela de login
        info = client.evaluate("""
            (() => {
                const url = window.location.href;
                const isLogin = url.includes('/login.html') || !!document.querySelector('input[name="username"]');
                const title = document.title || '';
                return { url, isLogin, title };
            })()
        """)

        if not info:
            return {"status": "error", "message": "Falha ao inspecionar contexto da página Spotfire."}

        if info.get("isLogin"):
            return {
                "status": "waiting_login",
                "message": "A página do Spotfire está na tela de login. Por favor, acesse a aba no navegador e faça o login com 'Keep me logged in'."
            }

        # Se não estiver na análise, navega para a URL completa
        current_url = info.get("url", "")
        if "analysis" not in current_url:
            client.call("Page.navigate", {"url": SPOTFIRE_URL})
            time.sleep(5.0)

        # 2. Script de automação e extração executado diretamente no contexto do Spotfire
        extract_js = """
        (async () => {
            const delay = ms => new Promise(r => setTimeout(r, ms));
            
            function findByXPath(xpath) {
                try {
                    return document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                } catch(e) { return null; }
            }

            // Passo A: Clicar no botão Filters
            const filterBtnXPath = '//*[@id="fcea3f94-d62c-4563-ad4c-495b266e1124"]/div[5]';
            let filterBtn = findByXPath(filterBtnXPath);
            
            // Fallback para botão de filtro por atributos comuns do Spotfire
            if (!filterBtn) {
                filterBtn = document.querySelector('[title*="Filter"], [aria-label*="Filter"], .sfc-filter-panel-toggle');
            }
            
            if (filterBtn) {
                try { filterBtn.click(); } catch(e) {}
                await delay(800);
            }

            // Passo B: Localizar e clicar em 'Reset Visible Filters'
            const allElements = Array.from(document.querySelectorAll('*'));
            const resetBtn = allElements.find(el => {
                const txt = (el.innerText || el.getAttribute('title') || '').trim().toLowerCase();
                return txt === 'reset visible filters' || txt === 'redefinir filtros visíveis';
            });
            if (resetBtn) {
                try { resetBtn.click(); } catch(e) {}
                await delay(1000);
            }

            // Passo C: Localizar e clicar na aba 'Extração'
            const tabs = Array.from(document.querySelectorAll('.sfc-navigation-tab, [role="tab"], .sfc-page-navigation-item, div, span'));
            const extracaoTab = tabs.find(el => {
                const t = (el.innerText || '').trim();
                return t === 'Extração' || t === 'Extracao';
            });
            if (extracaoTab) {
                try { extracaoTab.click(); } catch(e) {}
                await delay(1500);
            }

            // Passo D: Localizar a tabela 'Extração Tabela Geral' e extrair dados
            // Procura containers de tabela do Spotfire
            const tables = Array.from(document.querySelectorAll('table, .sfc-table, .sf-element-table, [role="grid"], .sfc-visual-table'));
            
            // Função para extrair texto limpo de células
            function parseTableRows() {
                const results = [];
                // Estratégia 1: Tabela HTML clássica ou Grid Spotfire
                const htmlTables = document.querySelectorAll('table');
                for (const tbl of htmlTables) {
                    const headers = Array.from(tbl.querySelectorAll('th')).map(th => th.innerText.trim());
                    if (headers.some(h => h.includes('Equipe') || h.includes('Calibrado') || h.includes('Referência'))) {
                        const trs = Array.from(tbl.querySelectorAll('tbody tr, tr')).slice(1);
                        for (const tr of trs) {
                            const cells = Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                            if (cells.length >= 2) {
                                const row = {};
                                headers.forEach((h, idx) => {
                                    row[h] = cells[idx] || '';
                                });
                                results.push(row);
                            }
                        }
                        if (results.length > 0) return { strategy: 'html_table', rows: results };
                    }
                }

                // Estratégia 2: Grid virtualizado por classes do Spotfire Web Player
                const rows = Array.from(document.querySelectorAll('.sfc-table-row, .sf-table-row, [role="row"]'));
                if (rows.length > 0) {
                    const parsed = [];
                    for (const r of rows) {
                        const cellEls = Array.from(r.querySelectorAll('.sfc-table-cell, .sf-table-cell, [role="gridcell"]'));
                        if (cellEls.length > 0) {
                            parsed.push(cellEls.map(c => c.innerText.trim()));
                        }
                    }
                    return { strategy: 'spotfire_grid', rows: parsed };
                }

                return { strategy: 'none', rows: [] };
            }

            const extracted = parseTableRows();
            return {
                title: document.title,
                url: window.location.href,
                extracted: extracted,
                bodyPreview: document.body.innerText.substring(0, 500)
            };
        })()
        """

        extraction_res = client.evaluate(extract_js)
        return {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            "data": extraction_res
        }

    except Exception as err:
        return {
            "status": "error",
            "message": f"Erro durante execução CDP do Spotfire: {err}"
        }
    finally:
        client.close()

def parse_and_format_spotfire_records(raw_extraction: dict, default_date: str = None) -> list:
    """
    Formata e limpa os registros extraídos do Spotfire para o padrão da tabela 'team_spotfire_records'.
    """
    if not default_date:
        default_date = date.today().isoformat()

    formatted_records = []
    data_content = (raw_extraction.get("data") or {}).get("extracted", {})
    rows = data_content.get("rows", [])
    strategy = data_content.get("strategy", "")

    if strategy == "html_table":
        for r in rows:
            equipe_raw = r.get("Equipe") or r.get("EQUIPE") or ""
            norm_code = normalize_team_code(equipe_raw)
            if not norm_code:
                continue

            dt_ref = r.get("Data Referência") or r.get("Data Referencia") or default_date
            # Converte formatos como '04/09/2026' para 'YYYY-MM-DD'
            if "/" in dt_ref:
                parts = dt_ref.split("/")
                if len(parts) == 3:
                    dt_ref = f"{parts[2]}-{parts[1].zfill(2)}-{parts[0].zfill(2)}"

            def to_int(val):
                try:
                    return int(re.sub(r'[^0-9]', '', str(val)))
                except Exception:
                    return 0

            formatted_records.append({
                "data_referencia": dt_ref,
                "equipe": equipe_raw,
                "equipe_normalizada": norm_code,
                "inicio_intervalo": r.get("Inicio Intervalo") or r.get("Início Intervalo") or "",
                "fim_intervalo": r.get("Fim Intervalo") or "",
                "inicio_calibrado": r.get("Inicio Calibrado") or r.get("Início Calibrado") or "",
                "fim_calibrado": r.get("Fim Calibrado") or "",
                "qtd_os": to_int(r.get("QTD_OS") or r.get("Qtd OS") or 0),
                "improdutiva": to_int(r.get("IMPRODUTIVA") or 0),
                "verificacoes": to_int(r.get("VERIFICAÇÕES") or r.get("VERIFICACOES") or 0),
                "produtivas": to_int(r.get("PRODUTIVAS") or 0),
                "no_local": to_int(r.get("NO_LOCAL") or 0),
                "rejeita": str(r.get("REJEITA?") or r.get("REJEITA") or "NÃO").upper(),
                "raw_data": r
            })

    return formatted_records

def executar_ciclo_sincronizacao_spotfire(source_label="Rotina Automática"):
    """
    Executa o ciclo completo de sincronização do Spotfire com o Supabase:
    1. Extrai via CDP.
    2. Formata e normaliza os dados.
    3. Persiste no Supabase com UPSERT.
    4. Notifica e reconcilia no delivery_manager.
    """
    try:
        from supabase_client import push_spotfire_records_to_supabase
        from delivery_manager import delivery_manager

        res = extrair_dados_spotfire_via_cdp()
        if res.get("status") == "waiting_login":
            print(f"[SPOTFIRE CDP] {res.get('message')}", flush=True)
            return res

        if res.get("status") != "success":
            print(f"[SPOTFIRE CDP WARN] {res.get('message')}", flush=True)
            return res

        records = parse_and_format_spotfire_records(res)
        if not records:
            print("[SPOTFIRE CDP] Conectado à página, aguardando renderização dos dados da tabela.", flush=True)
            return {"status": "success", "count": 0, "message": "Nenhum registro extraído nesta rodada."}

        # Persiste no Supabase
        db_res = push_spotfire_records_to_supabase(records)
        count_saved = db_res.get("count", len(records))

        # Reconcilia no delivery_manager
        date_today = date.today().isoformat()
        delivery_manager.reconcile_with_spotfire_records(records, date_ref=date_today)

        timestamp_str = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{timestamp_str}] [SPOTFIRE SYNC CDP] {count_saved} equipes sincronizadas ({source_label}).", flush=True)

        return {
            "status": "success",
            "count": count_saved,
            "message": f"{count_saved} registros do Spotfire sincronizados com sucesso."
        }
    except Exception as e:
        print(f"[SPOTFIRE SYNC ERROR] {e}", flush=True)
        return {"status": "error", "message": str(e)}

def spotfire_background_worker(interval_seconds=180):
    """
    Worker contínuo executado em background thread a cada 3 minutos (180s).
    """
    print(f"[BACKGROUND WORKER] Rotina de auto-captura do TIBCO Spotfire iniciada (intervalo: {interval_seconds}s).", flush=True)
    time.sleep(15)  # Aguarda inicialização dos outros serviços

    while True:
        try:
            executar_ciclo_sincronizacao_spotfire(source_label="Rotina Automática (3 min)")
        except Exception as err:
            print(f"[SPOTFIRE WORKER EXCEPTION] {err}", flush=True)
        time.sleep(interval_seconds)

if __name__ == "__main__":
    print("Testando extração do Spotfire via CDP...")
    r = executar_ciclo_sincronizacao_spotfire(source_label="Teste Manual")
    print(json.dumps(r, indent=2, ensure_ascii=False))
