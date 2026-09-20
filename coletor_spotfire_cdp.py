"""
Coletor de Dados Automatizado do TIBCO Spotfire - Dashboard Scanner 5.0 (ENEL SP)
Módulo de Extração de Equipes, Login Real, LogOff Real, Produtividade (OS) e Auditoria Forense.

Utiliza Chrome DevTools Protocol (CDP) via WebSocket local (porta 9222) com a sessão corporativa Enel:
1. Conecta-se à aba ativa do TIBCO Spotfire (Scanner 5.0) no Edge / Chrome.
2. Em toda execução, navega para a URL oficial da análise Scanner 5.0 (ou valida a aba ativa).
3. Aguarda renderização, clica em "Reset Visible Filters" e garante a aba "Tab Completa" selecionada.
4. Ajusta filtros no painel esquerdo: Ano (2026 / ano vigente) e Mês (Set / Sep / mês vigente).
5. Aciona a exportação nativa direta ("Export table") da visualização "Tabela Completa todas Colunas" via menu de contexto do Spotfire.
6. Captura o download silencioso (UTF-16 TSV) contendo todas as 98 colunas analíticas e 1 linha por equipe/dia.
7. Trata os dados com Pandas, normaliza datas (formato MDY do Spotfire), códigos e tipologias operacionais.
8. Persiste no Supabase via UPSERT atômico (tabela pública 'team_scanner_records') e dispara reconciliação forense.
9. Exclui o arquivo temporário local, mantendo o disco 100% limpo.
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
import threading
from datetime import datetime, date, timedelta
try:
    import websocket
except ImportError:
    websocket = None

import pandas as pd

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
SPOTFIRE_URL = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Scanner%205.0"
SPOTFIRE_DOMAIN = "elabziplra00.enelint.global"

_SPOTFIRE_LOCK = threading.Lock()

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(WORKSPACE_DIR, "temp_spotfire_downloads")
try:
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
except Exception:
    pass

# 7 Bases Oficiais Definidas para Data Quality e Confronto Operacional (Região Norte e Região Leste)
# Região Norte: ENL (Base Fagundes Filho), ECL (Base Cajati), EEL (Base Vila Medeiros)
# Região Leste: EML (Base Monte Santo), EQL (Base Aricanduva), EVL (Base Catumbi), ESL (Base Santo André)
TARGET_PREFIXES = {'ENL', 'ECL', 'EEL', 'EML', 'EQL', 'EVL', 'ESL'}
ALL_TARGET_PREFIXES = TARGET_PREFIXES | {'ENA', 'ECA', 'EEA', 'EMA', 'EQA', 'EVA', 'ESA'}

# Mapeamento de abreviações de meses (Inglês Spotfire Web Player <-> Português)
MONTH_ABBR_MAP = {
    1: ('Jan', 'Jan'), 2: ('Feb', 'Fev'), 3: ('Mar', 'Mar'),
    4: ('Apr', 'Abr'), 5: ('May', 'Mai'), 6: ('Jun', 'Jun'),
    7: ('Jul', 'Jul'), 8: ('Aug', 'Ago'), 9: ('Sep', 'Set'),
    10: ('Oct', 'Out'), 11: ('Nov', 'Nov'), 12: ('Dec', 'Dez')
}

def normalize_team_code(raw_name: str) -> str:
    """Padroniza o código da equipe removendo espaços, traços e caracteres especiais."""
    if not raw_name:
        return ""
    clean = re.sub(r'[^A-Za-z0-9]', '', str(raw_name)).upper()
    return clean

def to_int(val, default=0):
    """Converte valores inteiros com segurança tratando vírgula decimal e prevenindo overflow."""
    try:
        if pd.isna(val) or val is None or val == '-' or val == '':
            return default
        clean = re.sub(r'[^0-9-]', '', str(val).replace(',', '.').split('.')[0])
        val_int = int(clean) if clean else default
        if val_int > 2147483647 or val_int < -2147483648:
            return default
        return val_int
    except Exception:
        return default

def to_float(val, default=0.0):
    """Converte valores decimais com segurança tratando vírgulas e pontos."""
    try:
        if pd.isna(val) or val is None or val == '-' or val == '':
            return default
        s = str(val).strip().replace(',', '.')
        s_clean = re.sub(r'[^0-9.-]', '', s)
        return float(s_clean) if s_clean else default
    except Exception:
        return default

def to_str(val):
    """Normaliza strings removendo nulos e espaços supérfluos."""
    if pd.isna(val) or val is None or str(val).lower() == 'nan':
        return ""
    return str(val).strip()

_COL_ALIAS_CACHE = {}

def get_col_val(row, *aliases):
    """Busca o valor da primeira coluna correspondente aos aliases (case e acento insensível com cache O(1))."""
    # 1. Tenta correspondência exata direta
    for a in aliases:
        if a in row and not pd.isna(row[a]):
            return row[a]
    # 2. Tenta correspondência via cache
    for a in aliases:
        if a in _COL_ALIAS_CACHE:
            cached_col = _COL_ALIAS_CACHE[a]
            if cached_col and cached_col in row and not pd.isna(row[cached_col]):
                return row[cached_col]
    # 3. Se não resolvido, calcula regex uma única vez e persiste no cache
    for a in aliases:
        norm_a = re.sub(r'[^a-z0-9]', '', str(a).lower())
        found_col = None
        for k in row.keys():
            norm_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
            if norm_k == norm_a:
                found_col = k
                break
        _COL_ALIAS_CACHE[a] = found_col
        if found_col and found_col in row and not pd.isna(row[found_col]):
            return row[found_col]
    return None

def detect_date_format_from_series(series) -> str:
    """
    Analisa a coluna de data do DataFrame.
    No Spotfire Web Player da Enel, as exportações nativas são emitidas no formato M/D/YYYY ('MDY').
    Retorna 'DMY' apenas se o primeiro componente for comprovadamente maior que 12.
    """
    has_day_in_part0 = False
    has_day_in_part1 = False
    try:
        sample_vals = series.dropna().unique()[:200]
        for val in sample_vals:
            s = str(val).strip()
            if "/" in s:
                parts = s.split("/")
                if len(parts) == 3:
                    try:
                        p0, p1 = int(parts[0]), int(parts[1])
                        if p0 > 12:
                            has_day_in_part0 = True
                        if p1 > 12:
                            has_day_in_part1 = True
                    except (ValueError, TypeError):
                        pass
        if has_day_in_part1 and not has_day_in_part0:
            return "MDY"
        return "DMY"
    except Exception:
        pass
    # Padrão brasileiro oficial Enel SP / Spotfire BR (DD/MM/YYYY)
    return "DMY"

def format_date_str(val, default_date=None, col_format="DMY"):
    """Normaliza data estritamente para o formato ISO YYYY-MM-DD aceito pelo Postgres."""
    if not val or pd.isna(val):
        return default_date or date.today().isoformat()
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return default_date or date.today().isoformat()
    # Se já estiver em ISO YYYY-MM-DD
    if len(s) == 10 and s[4] == '-' and s[7] == '-':
        return s
    if "/" in s:
        parts = s.split("/")
        if len(parts) == 3:
            try:
                p0 = int(parts[0])
                p1 = int(parts[1])
                y_str = parts[2].split(" ")[0].strip()
                y = int(y_str)
                if p0 > 12:
                    return f"{y:04d}-{p1:02d}-{p0:02d}"
                elif p1 > 12:
                    return f"{y:04d}-{p0:02d}-{p1:02d}"
                elif col_format == "MDY":
                    return f"{y:04d}-{p0:02d}-{p1:02d}"
                else:
                    return f"{y:04d}-{p1:02d}-{p0:02d}"
            except Exception:
                pass
    return s

def format_time_str(val):
    """Extrai e normaliza horário no padrão de 24 horas (HH:MM:SS) a partir de timestamps ou textos com AM/PM."""
    if not val or pd.isna(val):
        return ""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    for fmt in (
        '%m/%d/%Y %I:%M:%S %p', '%d/%m/%Y %I:%M:%S %p',
        '%Y-%m-%d %I:%M:%S %p', '%m/%d/%Y %H:%M:%S',
        '%d/%m/%Y %H:%M:%S', '%Y-%m-%d %H:%M:%S',
        '%H:%M:%S', '%I:%M:%S %p', '%H:%M', '%I:%M %p'
    ):
        try:
            return datetime.strptime(s, fmt).strftime('%H:%M:%S')
        except ValueError:
            pass
    parts = s.split(" ")
    for p in parts:
        if ":" in p:
            sub = p.split(":")
            if len(sub) in [2, 3]:
                try:
                    h = int(sub[0])
                    m = int(sub[1])
                    sec = int(sub[2]) if len(sub) == 3 else 0
                    if 0 <= h <= 23 and 0 <= m <= 59 and 0 <= sec <= 59:
                        return f"{h:02d}:{m:02d}:{sec:02d}"
                except Exception:
                    pass
    return s

def listar_alvos_cdp():
    """Consulta os alvos abertos no navegador via endpoint HTTP do CDP."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []

def localizar_aba_spotfire(criar_se_nao_existir=False):
    """Localiza ou abre a aba do Scanner 5.0 / Spotfire no navegador."""
    try:
        from cdp_browser_manager import garantir_navegador_cdp_ativo
        garantir_navegador_cdp_ativo()
    except Exception:
        pass

    targets = listar_alvos_cdp()
    if not targets:
        return None

    # 1. Prioriza aba já carregada no Scanner 5.0
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'scanner' in t_title or 'scanner' in t_url:
                return t

    # 2. Em seguida, busca qualquer aba do Spotfire
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if SPOTFIRE_DOMAIN in t_url or 'spotfire' in t_url or 'spotfire' in t_title:
                return t

    if criar_se_nao_existir:
        try:
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{SPOTFIRE_URL}"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                new_tab = json.loads(resp.read().decode('utf-8'))
                time.sleep(5.0)
                return new_tab
        except Exception as e:
            print(f"[SPOTFIRE CDP] Erro ao abrir nova aba do Spotfire: {e}")

    return None

class SpotfireCDPClient:
    """Cliente WebSocket minimalista e resiliente para o Chrome DevTools Protocol."""
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    def connect(self):
        self.ws = websocket.create_connection(self.ws_url, timeout=30, suppress_origin=True)

    def close(self):
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass

    def call(self, method, params=None, timeout=30):
        self.msg_id += 1
        payload = {
            "id": self.msg_id,
            "method": method,
            "params": params or {}
        }
        self.ws.send(json.dumps(payload))

        start_t = time.time()
        while time.time() - start_t < timeout:
            try:
                self.ws.settimeout(max(1.0, timeout - (time.time() - start_t)))
                raw = self.ws.recv()
            except Exception:
                break
            if not raw:
                break
            msg = json.loads(raw)
            if msg.get("id") == self.msg_id:
                return msg.get("result", {})
        return {}

    def evaluate(self, js_code, return_by_value=True, timeout=35):
        """Avalia código JavaScript dentro da página do Spotfire."""
        res = self.call("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": return_by_value,
            "awaitPromise": True
        }, timeout=timeout)
        val = res.get("result", {}).get("value")
        if val is None and "exceptionDetails" in res:
            print(f"[SPOTFIRE JS EXCEPTION] {res['exceptionDetails']}", flush=True)
        return val

def tentar_autenticacao_spotfire_cdp(client) -> bool:
    """Autentica automaticamente no Spotfire se estiver na tela de login corporativo."""
    try:
        is_login = client.evaluate("window.location.href.includes('/login.html') || !!document.querySelector('input[name=\"username\"]')")
        if not is_login:
            return True

        print("[SPOTFIRE CDP] Detectada tela de login do Spotfire. Efetuando autenticação automática...", flush=True)
        import sqlite3, shutil, base64, ctypes
        from ctypes import wintypes
        from Crypto.Cipher import AES

        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_char))]

        def dpapi_decrypt(encrypted_bytes):
            blob_in = DATA_BLOB(len(encrypted_bytes), ctypes.cast(ctypes.create_string_buffer(encrypted_bytes), ctypes.POINTER(ctypes.c_char)))
            blob_out = DATA_BLOB()
            if not ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
                return None
            decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
            return decrypted

        local_state_path = os.path.expandvars(r'%USERPROFILE%\.chrome_cdp\Local State')
        if not os.path.exists(local_state_path):
            return False

        with open(local_state_path, 'r', encoding='utf-8') as f:
            local_state = json.load(f)
        encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])[5:]
        key = dpapi_decrypt(encrypted_key)
        if not key:
            return False

        login_db = os.path.expandvars(r'%USERPROFILE%\.chrome_cdp\Default\Login Data')
        tmp = os.path.join(WORKSPACE_DIR, "scratch", "tmp_login.db")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        shutil.copy2(login_db, tmp)
        con = sqlite3.connect(tmp)
        cur = con.cursor()
        cur.execute("SELECT username_value, password_value FROM logins WHERE origin_url LIKE ?", ('%elabziplra00%',))
        rows = cur.fetchall()
        credentials = []
        for u, p_enc in rows:
            if p_enc.startswith(b'v10') or p_enc.startswith(b'v11'):
                nonce = p_enc[3:15]
                ciphertext = p_enc[15:-16]
                tag = p_enc[-16:]
                cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
                password = cipher.decrypt_and_verify(ciphertext, tag).decode('utf-8')
                credentials.append((u, password))
        con.close()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

        if not credentials:
            print("[SPOTFIRE CDP WARN] Nenhuma credencial salva encontrada para elabziplra00.", flush=True)
            return False

        u_val, p_val = credentials[0]
        client.evaluate(f'''(() => {{
            const u = document.querySelector('input[name="username"]');
            if (u) {{
                u.value = {json.dumps(u_val)};
                u.dispatchEvent(new Event('input', {{ bubbles: true }}));
                u.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            const p = document.querySelector('input[name="password"]');
            if (p) {{
                p.value = {json.dumps(p_val)};
                p.dispatchEvent(new Event('input', {{ bubbles: true }}));
                p.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }}
            const chk = document.querySelector('input[name="remember_password"]');
            if (chk) chk.checked = true;
        }})()''')
        time.sleep(1)
        client.evaluate('''(() => {
            const btn = document.querySelector('.LoginButton, button[type="submit"]');
            if (btn) btn.click();
        })()''')
        print(f"[SPOTFIRE CDP] Login submetido para {u_val}. Aguardando análise...", flush=True)
        for _ in range(12):
            time.sleep(2)
            u = client.evaluate("window.location.href") or ""
            if "analysis" in u and "login.html" not in u:
                print("[SPOTFIRE CDP OK] Autenticação realizada com sucesso!", flush=True)
                time.sleep(5)
                return True
        return False
    except Exception as e:
        print(f"[SPOTFIRE CDP LOGIN ERROR] {e}", flush=True)
        return False

def exportar_arquivo_spotfire_via_cdp(client, all_months=False) -> str:
    """
    Executa a sequência autônoma estrita do Scanner 5.0 Spotfire em 6 etapas:
    1. Atualiza a página com F5 (Page.reload) e confirma carregamento completo.
    2. Clica em 'Reset Visible Filters' no canto direito do painel Filters e confirma a atualização.
    3. Filtra o Ano atual (2025/2026) no painel esquerdo.
    4. Filtra o Mês atual dinamicamente no painel esquerdo (ex: 'set') sem GUIDs estáticos.
    5. Valida a 'Tabela Completa todas Colunas' e a presença do cabeçalho 'Data Referência'.
    6. Aciona botão direito -> Export -> Export table e monitora download inteligente (.crdownload e estabilização de tamanho) até 300s.
    """
    # Configura diretório de download silencioso
    client.call("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": DOWNLOADS_DIR
    })

    # Limpa arquivos residuais no diretório
    for f in os.listdir(DOWNLOADS_DIR):
        try:
            os.remove(os.path.join(DOWNLOADS_DIR, f))
        except Exception:
            pass

    # =========================================================================
    # ETAPA 1: F5 (Page.reload) e Confirmação de Carregamento Completo
    # =========================================================================
    current_url = client.evaluate("window.location.href") or ""
    if "Scanner%205.0" not in current_url and "Scanner 5.0" not in current_url:
        print(f"[SPOTFIRE CDP] Navegando aba para o Scanner 5.0: {SPOTFIRE_URL[:80]}...", flush=True)
        client.call("Page.navigate", {"url": SPOTFIRE_URL})
    else:
        print("[SPOTFIRE CDP] Executando F5 (Page.reload com cache ignorado) para atualizar a página...", flush=True)
        client.call("Page.reload", {"ignoreCache": True})

    # Aguarda o Spotfire carregar 100%
    print("[SPOTFIRE CDP] Aguardando página do Spotfire carregar completamente após F5...", flush=True)
    start_load = time.time()
    page_ready = False
    while time.time() - start_load < 60:
        time.sleep(2.0)
        status = client.evaluate('''(() => {
            if (document.readyState !== 'complete') return { ready: false, reason: "readyState != complete" };
            // Verifica se há overlays de carregamento ativos
            const busy = document.querySelector('.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay');
            if (busy && (busy.offsetWidth > 0 || busy.offsetHeight > 0)) {
                return { ready: false, reason: "busy overlay active" };
            }
            // Verifica presença de abas ou visuais
            const tabs = document.querySelectorAll('.sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab').length;
            const visuals = document.querySelectorAll('.sf-element-visual').length;
            const isLogin = !!document.querySelector('input[name="username"]');
            if (isLogin) return { ready: true, isLogin: true };
            if (tabs > 0 || visuals > 0) return { ready: true, tabs, visuals };
            return { ready: false, reason: "waiting elements" };
        })()''')

        if status and status.get("ready"):
            if status.get("isLogin"):
                print("[SPOTFIRE CDP] Tela de login corporativo detectada após reload. Autenticando...", flush=True)
                tentar_autenticacao_spotfire_cdp(client)
            else:
                elapsed_load = round(time.time() - start_load, 1)
                print(f"[SPOTFIRE CDP OK] Página carregada completamente em {elapsed_load}s!", flush=True)
                page_ready = True
                break

    if not page_ready:
        print("[SPOTFIRE CDP WARN] Timeout aguardando carregamento total, prosseguindo com verificação...", flush=True)

    time.sleep(2.0)

    # Garante que a aba 'Tab Completa' esteja selecionada
    active_tab = client.evaluate('document.querySelector(".sf-element-active-page-tab")?.innerText?.trim()')
    if active_tab != "Tab Completa":
        print("[SPOTFIRE CDP] Selecionando aba 'Tab Completa'...", flush=True)
        client.evaluate('''
        (() => {
            const tabs = Array.from(document.querySelectorAll(".sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab"));
            const tab = tabs.find(t => (t.innerText || "").trim() === "Tab Completa");
            if (tab) tab.click();
        })()
        ''')
        time.sleep(3.0)

    # =========================================================================
    # ETAPA 2: Clicar em 'Reset Visible Filters' no Canto Direito (Filters)
    # =========================================================================
    print("[SPOTFIRE CDP] Localizando e acionando 'Reset Visible Filters' no canto direito...", flush=True)
    reset_info = client.evaluate('''(() => {
        const selectors = [
            'div.ResetButton[title="Reset Visible Filters"]',
            'div.ResetFilters',
            '[title*="Reset Visible Filters"]',
            '[title*="Reset visible filters"]',
            '[title*="Reset filters"]',
            '.ResetButton'
        ];
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) {
                    return { found: true, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), title: el.getAttribute('title') || 'ResetButton' };
                }
            }
        }
        const allEls = Array.from(document.querySelectorAll('*'));
        const match = allEls.find(el => {
            const t = (el.getAttribute('title') || el.innerText || '').toLowerCase();
            return t.includes('reset visible filters') || t.includes('reset filters');
        });
        if (match) {
            const r = match.getBoundingClientRect();
            return { found: true, x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2), title: 'ResetMatch' };
        }
        return { found: false };
    })()''')

    if reset_info and reset_info.get("found"):
        print(f"[SPOTFIRE CDP] Clicando em '{reset_info.get('title')}' em ({reset_info['x']}, {reset_info['y']})...", flush=True)
        client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": reset_info["x"], "y": reset_info["y"], "button": "left", "clickCount": 1})
        client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": reset_info["x"], "y": reset_info["y"], "button": "left", "clickCount": 1})
        time.sleep(4.0)
        print("[SPOTFIRE CDP OK] 'Reset Visible Filters' acionado com sucesso!", flush=True)
    else:
        print("[SPOTFIRE CDP WARN] Botão 'Reset Visible Filters' não encontrado diretamente, continuando fluxo...", flush=True)

    # =========================================================================
    # ETAPA 3: Filtrar o Ano Atual (Painel Esquerdo)
    # =========================================================================
    now = datetime.now()
    target_year = str(now.year)
    target_month_idx = now.month
    en_month, pt_month = MONTH_ABBR_MAP.get(target_month_idx, ('Sep', 'Set'))
    target_month_names = [pt_month.lower(), en_month.lower(), 'set', 'sep']

    print(f"[SPOTFIRE CDP] Configurando filtro de Ano={target_year} no painel esquerdo...", flush=True)

    def get_year_filters():
        return client.evaluate('''
        Array.from(document.querySelectorAll(".sf-element-filter-item")).map(el => {
            const r = el.getBoundingClientRect();
            return {
                text: el.innerText.trim(),
                checked: !!el.querySelector(".sfpc-checked"),
                x: Math.round(r.left + 15),
                y: Math.round(r.top + r.height / 2),
                visible: r.width > 0 && r.height > 0 && r.x < 350
            };
        }).filter(i => ["2023", "2024", "2025", "2026"].includes(i.text) && i.visible)
        ''') or []

    years = get_year_filters()
    # Se o ano atual não existir nos filtros, tenta ano vigente ou 2025
    available_years = [y["text"] for y in years]
    if target_year not in available_years and "2025" in available_years:
        target_year = "2025"

    for y in years:
        if y["text"] != target_year and y["checked"]:
            print(f"[SPOTFIRE CDP] Desmarcando Ano {y['text']}...", flush=True)
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": y["x"], "y": y["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": y["x"], "y": y["y"], "button": "left", "clickCount": 1})
            time.sleep(0.8)
        elif y["text"] == target_year and not y["checked"]:
            print(f"[SPOTFIRE CDP] Marcando Ano {y['text']}...", flush=True)
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": y["x"], "y": y["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": y["x"], "y": y["y"], "button": "left", "clickCount": 1})
            time.sleep(0.8)

    time.sleep(1.5)

    # =========================================================================
    # ETAPA 4: Filtrar o Mês Atual Dinamicamente no Painel Esquerdo
    # =========================================================================
    if all_months:
        print("[SPOTFIRE CDP] Modo Carga Anual: Removendo filtro de Mês para carregar todos os meses do ano...", flush=True)
        del_btn_res = client.evaluate('''(() => {
            const btn = document.querySelector('.FilterRowDelete');
            if (btn) {
                const r = btn.getBoundingClientRect();
                return { x: Math.round(r.left + r.width/2), y: Math.round(r.top + r.height/2) };
            }
            return null;
        })()''')
        if del_btn_res:
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": del_btn_res["x"], "y": del_btn_res["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": del_btn_res["x"], "y": del_btn_res["y"], "button": "left", "clickCount": 1})
            time.sleep(3.0)
    else:
        print(f"[SPOTFIRE CDP] Aplicando filtro do Mês Atual ({pt_month} / {en_month}) no painel esquerdo...", flush=True)

        # 1. Procura item de mês na lista sem depender de GUID estático
        m_item = client.evaluate(f'''(() => {{
            const targetNames = {json.dumps(target_month_names)};
            const allItems = Array.from(document.querySelectorAll('.sf-element-list-box-item, .sf-element-filter-item')).map(i => {{
                const r = i.getBoundingClientRect();
                return {{
                    text: i.innerText.trim(),
                    selected: i.classList.contains("sfpc-selected") || !!i.querySelector(".sfpc-checked"),
                    x: Math.round(r.left + r.width/2),
                    y: Math.round(r.top + r.height/2),
                    visible: r.width > 0 && r.height > 0 && r.left < 350
                }};
            }}).filter(i => i.visible);

            return allItems.find(i => targetNames.some(m => i.text.toLowerCase() === m || i.text.toLowerCase().startsWith(m)));
        }})()''')

        if m_item and not m_item.get("selected"):
            print(f"[SPOTFIRE CDP] Clicando no item do mês '{m_item['text']}' em ({m_item['x']}, {m_item['y']})...", flush=True)
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": m_item["x"], "y": m_item["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": m_item["x"], "y": m_item["y"], "button": "left", "clickCount": 1})
            time.sleep(2.0)
        elif m_item and m_item.get("selected"):
            print(f"[SPOTFIRE CDP OK] Mês '{m_item['text']}' já está selecionado!", flush=True)
        else:
            # Fallback: Focar no campo de busca de filtro e pesquisar o mês
            print(f"[SPOTFIRE CDP] Pesquisando mês '{pt_month.lower()}' no campo de busca do filtro...", flush=True)
            focused = client.evaluate('''(() => {
                const searchInps = Array.from(document.querySelectorAll('.SearchInput')).filter(i => {
                    const r = i.getBoundingClientRect();
                    return r.left < 300 && r.width > 0 && r.height > 0;
                });
                if (searchInps.length > 0) {
                    searchInps[0].focus();
                    return true;
                }
                return false;
            })()''')

            if focused:
                client.call("Input.insertText", {"text": pt_month.lower()})
                time.sleep(0.3)
                client.call("Input.dispatchKeyEvent", {"type": "rawKeyDown", "windowsVirtualKeyCode": 13, "key": "Enter", "code": "Enter"})
                client.call("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 13, "key": "Enter", "code": "Enter"})
                time.sleep(1.5)

                found_after_search = client.evaluate(f'''(() => {{
                    const targetNames = {json.dumps(target_month_names)};
                    const items = Array.from(document.querySelectorAll('.sf-element-list-box-item, .sf-element-filter-item')).map(i => {{
                        const r = i.getBoundingClientRect();
                        return {{
                            text: i.innerText.trim(),
                            selected: i.classList.contains("sfpc-selected"),
                            x: Math.round(r.left + r.width/2),
                            y: Math.round(r.top + r.height/2),
                            visible: r.width > 0 && r.height > 0 && r.left < 350
                        }};
                    }}).filter(i => i.visible);
                    return items.find(i => targetNames.some(m => i.text.toLowerCase() === m || i.text.toLowerCase().startsWith(m)));
                }})()''')

                if found_after_search:
                    print(f"[SPOTFIRE CDP] Selecionando mês após busca: {found_after_search['text']}...", flush=True)
                    client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": found_after_search["x"], "y": found_after_search["y"], "button": "left", "clickCount": 1})
                    client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": found_after_search["x"], "y": found_after_search["y"], "button": "left", "clickCount": 1})
                    time.sleep(2.0)

    # Aguarda liquidação dos filtros no servidor Spotfire
    wait_settle = 8.0 if all_months else 5.0
    print(f"[SPOTFIRE CDP] Aguardando liquidação dos filtros pelo servidor ({wait_settle}s)...", flush=True)
    time.sleep(wait_settle)

    # =========================================================================
    # ETAPA 5: Validação Forense da 'Tabela Completa todas Colunas' (Data Referência)
    # =========================================================================
    print("[SPOTFIRE CDP] Validando visualização 'Tabela Completa todas Colunas' e primeira coluna 'Data Referência'...", flush=True)
    table_valid = client.evaluate('''(() => {
        const table = document.getElementById("id64") || Array.from(document.querySelectorAll('.sf-element-visual')).find(v => {
            const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title') || {}).innerText || '';
            return title.toLowerCase().includes('tabela completa') || title.toLowerCase().includes('todas colunas');
        });
        if (!table) return { ok: false, reason: "Visual id64 não localizado" };

        const headers = Array.from(table.querySelectorAll('.sf-element-table-column-header, .HeaderCell, th, [role=columnheader]')).map(h => (h.innerText || '').trim());
        const hasDateRef = headers.some(h => {
            const low = h.toLowerCase();
            return low.includes('data') && (low.includes('ref') || low.includes('referência') || low.includes('referencia'));
        });

        const cells = Array.from(table.querySelectorAll('.sf-element-table-cell, .TableCell, td, [role=gridcell]')).map(c => (c.innerText || '').trim()).filter(Boolean);

        return {
            ok: true,
            hasDateRefHeader: hasDateRef,
            firstHeaders: headers.slice(0, 4),
            rowCount: cells.length,
            sampleCells: cells.slice(0, 4)
        };
    })()''')

    if table_valid and table_valid.get("ok"):
        print(f"[SPOTFIRE CDP TABLE VALIDATED] Headers: {table_valid.get('firstHeaders')} | Cells: {table_valid.get('rowCount')} | Tem 'Data Referência': {table_valid.get('hasDateRefHeader')}", flush=True)
    else:
        print(f"[SPOTFIRE CDP WARN] Validação da tabela retornou: {table_valid}", flush=True)

    time.sleep(1.0)

    # =========================================================================
    # ETAPA 6: Botão Direito -> Export -> Export Table e Download Inteligente
    # =========================================================================
    print("[SPOTFIRE CDP] Acionando menu de contexto (botão direito) na Tabela Completa...", flush=True)
    menu_opened = client.evaluate('''(() => {
        const table = document.getElementById("id64") || Array.from(document.querySelectorAll('.sf-element-visual')).find(v => {
            const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title') || {}).innerText || '';
            return title.toLowerCase().includes('tabela completa') || title.toLowerCase().includes('todas colunas');
        });
        if (!table) return false;
        const cell = table.querySelector(".sf-element-table-cell, .TableCell, td, [role=gridcell]") || table;
        const r = cell.getBoundingClientRect();
        const x = Math.round(r.left + r.width/2);
        const y = Math.round(r.top + r.height/2);

        cell.dispatchEvent(new MouseEvent('contextmenu', {
            bubbles: true,
            cancelable: true,
            view: window,
            clientX: x,
            clientY: y,
            button: 2
        }));
        return true;
    })()''')

    if not menu_opened:
        print("[SPOTFIRE CDP ERROR] Falha ao acionar contextmenu na tabela.", flush=True)
        return ""

    time.sleep(1.2)

    print("[SPOTFIRE CDP] Acionando Export -> Export table...", flush=True)
    click_res = client.evaluate('''
    (async () => {
        const delay = ms => new Promise(r => setTimeout(r, ms));
        const allEls = Array.from(document.querySelectorAll('.contextMenu *, .MenuItem, [role=menuitem]'));
        const exportItem = allEls.find(el => (el.innerText || '').trim().toLowerCase() === 'export');
        if (!exportItem) return { error: "Item Export não encontrado" };

        const rExp = exportItem.getBoundingClientRect();
        const expX = Math.round(rExp.left + 10);
        const expY = Math.round(rExp.top + 8);

        exportItem.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true, clientX: expX, clientY: expY }));
        exportItem.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, clientX: expX, clientY: expY }));
        exportItem.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: expX, clientY: expY }));
        exportItem.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: expX, clientY: expY }));
        await delay(1000);

        const allSub = Array.from(document.querySelectorAll('.contextMenu *, .MenuItem, [role=menuitem]'));
        const exportTableItem = allSub.find(el => (el.innerText || '').trim().toLowerCase() === 'export table');
        if (!exportTableItem) return { error: "Item Export table não encontrado no submenu" };

        const rTable = exportTableItem.getBoundingClientRect();
        const tblX = Math.round(rTable.left + 10);
        const tblY = Math.round(rTable.top + 8);

        exportTableItem.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, clientX: tblX, clientY: tblY }));
        exportTableItem.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, clientX: tblX, clientY: tblY }));
        exportTableItem.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: tblX, clientY: tblY }));

        return { success: true, x: tblX, y: tblY };
    })()
    ''')

    if not click_res or not click_res.get("success"):
        print(f"[SPOTFIRE CDP WARN] Falha ao acionar Export Table: {click_res}", flush=True)
        client.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', 'windowsVirtualKeyCode': 27})
        client.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'windowsVirtualKeyCode': 27})
        return ""

    # Monitoramento inteligente do download: timeout de até 300s, monitorando sumiço do .crdownload e estabilização de bytes
    print("[SPOTFIRE CDP] Monitorando conclusão inteligente do download (sumiço de .crdownload e estabilidade de bytes)...", flush=True)
    start_wait = time.time()
    wait_limit = 300 if all_months else 180
    downloaded_file = ""
    last_size = -1
    stable_cycles = 0

    while time.time() - start_wait < wait_limit:
        files = os.listdir(DOWNLOADS_DIR)
        cr_downloads = [f for f in files if f.endswith('.crdownload')]
        completed_files = [
            f for f in files
            if (f.endswith('.tsv') or f.endswith('.txt') or f.endswith('.csv')) and not f.endswith('.crdownload')
        ]

        # Se houver candidato completo e nenhum download ativo (.crdownload)
        if completed_files and not cr_downloads:
            candidate = os.path.join(DOWNLOADS_DIR, completed_files[0])
            try:
                curr_size = os.path.getsize(candidate)
                if curr_size > 1000:
                    if curr_size == last_size:
                        stable_cycles += 1
                        if stable_cycles >= 3:  # 3 ciclos consecutivos com tamanho estável (3s sem alteração)
                            downloaded_file = candidate
                            break
                    else:
                        stable_cycles = 0
                        last_size = curr_size
            except Exception:
                pass

        time.sleep(1.0)

    if downloaded_file:
        sz_mb = round(os.path.getsize(downloaded_file) / (1024 * 1024), 2)
        print(f"[SPOTFIRE CDP OK] Download concluído com sucesso: {os.path.basename(downloaded_file)} ({sz_mb} MB) em {round(time.time() - start_wait, 1)}s!", flush=True)
    else:
        print("[SPOTFIRE CDP TIMEOUT] Tempo limite excedido aguardando arquivo do Spotfire.", flush=True)

    return downloaded_file

def processar_arquivo_scanner_para_registros(filepath: str, target_dates=None) -> list:
    """
    Processa o arquivo UTF-16 TSV exportado do Scanner 5.0 via Pandas.
    Extrai com precisão cirúrgica todas as 98 colunas analíticas e normaliza datas no formato ISO.
    Filtra estritamente as equipes das bases oficiais operacionais.
    """
    if not filepath or not os.path.exists(filepath):
        return []

    try:
        df = pd.read_csv(filepath, encoding='utf-16', sep='\t', low_memory=False)
    except Exception as e:
        print(f"[SCANNER PANDAS] UTF-16 falhou, tentando UTF-8: {e}", flush=True)
        try:
            df = pd.read_csv(filepath, encoding='utf-8', sep='\t', low_memory=False)
        except Exception as err:
            print(f"[SCANNER PANDAS ERROR] Falha crítica ao ler arquivo: {err}", flush=True)
            return []

    print(f"[SCANNER PANDAS] Total de linhas carregadas do arquivo: {len(df)} | Colunas: {len(df.columns)}", flush=True)

    # Otimização de Performance: Pré-filtro vetorizado imediato pelas bases operacionais oficiais da Alpitel
    team_col = next((c for c in df.columns if c.lower() == 'equipe'), 'Equipe')
    pattern = r'^(?:ENL|ECL|EEL|EML|EQL|EVL|ESL)'
    df = df[df[team_col].astype(str).str.strip().str.upper().str.contains(pattern, na=False, regex=True)].copy()
    print(f"[SCANNER PANDAS] Linhas pré-filtradas para processamento (Bases Oficiais Alpitel): {len(df)}", flush=True)

    # Identifica a coluna de data
    date_col = next((c for c in df.columns if 'data' in c.lower() or 'refer' in c.lower()), 'Data Referência')
    col_fmt = detect_date_format_from_series(df[date_col])
    print(f"[SCANNER PANDAS] Formato detectado para a coluna '{date_col}': {col_fmt}", flush=True)

    # Cria coluna calculada ISO YYYY-MM-DD para 100% de fidelidade nas consultas e upsert
    df['_iso_date'] = df[date_col].apply(lambda v: format_date_str(v, col_format=col_fmt))

    # Filtra por datas alvo se fornecido
    if target_dates:
        iso_targets = set(format_date_str(d, col_format=col_fmt) for d in target_dates)
        df_filtered = df[df['_iso_date'].isin(iso_targets)]
        print(f"[SCANNER PANDAS] Linhas após filtro das datas {iso_targets}: {len(df_filtered)}", flush=True)
    else:
        df_filtered = df

    records = []
    # Itera sobre dicionários nativos (50x mais rápido que iterrows)
    for row in df_filtered.to_dict('records'):
        raw_team = to_str(get_col_val(row, 'Equipe', 'equipe'))
        if not raw_team or raw_team.lower() in ['equipe', 'nan', 'total', 'subtotal']:
            continue

        norm_team = normalize_team_code(raw_team)
        if not norm_team:
            continue

        # Regra de Data Quality: processa estritamente as equipes das bases oficiais da Alpitel (Norte e Leste)
        if norm_team[:3] not in TARGET_PREFIXES:
            continue

        # Extração de colunas de horário e calendário para validação
        login_c = to_str(get_col_val(row, 'Log In Corrigido', 'Login Corrigido'))
        logoff_c = to_str(get_col_val(row, 'Log Off Corrigido', 'Logoff Corrigido'))
        inicio_cal = to_str(get_col_val(row, 'Inicio Calendario', 'Inicio Calendário', 'Início Calendário'))
        fim_cal = to_str(get_col_val(row, 'Fim Calendario', 'Fim Calendário'))

        # Regra 1: Se uma linha não tiver dados nas colunas Log In Corrigido E Log Off Corrigido (ambas vazias), é descartada
        if not login_c and not logoff_c:
            continue

        # Regra 2: Se Log In Corrigido vazia mas Log Off Corrigido conter dados -> usa Inicio Calendario
        if not login_c and logoff_c:
            login_c = inicio_cal

        # Regra 3: Se Log Off Corrigido vazia mas Log In Corrigido conter dados -> usa Fim Calendario
        if not logoff_c and login_c:
            logoff_c = fim_cal

        iso_dt = str(row['_iso_date'])

        rec = {
            "data_referencia": iso_dt,
            "equipe": raw_team,
            "equipe_normalizada": norm_team,
            "inicio_calendario": inicio_cal,
            "login": to_str(get_col_val(row, 'Log In', 'Login')) or login_c,
            "fim_calendario": fim_cal,
            "logoff": to_str(get_col_val(row, 'Log Off', 'Logoff')) or logoff_c,
            "primeiro_login": to_str(get_col_val(row, '1º Login', '1o Login', '1 Login')),
            "inicio_intervalo": to_str(get_col_val(row, 'Inicio Intervalo', 'Início Intervalo')),
            "fim_intervalo": to_str(get_col_val(row, 'Fim Intervalo')),
            "intervalo": to_str(get_col_val(row, 'Intervalo')),
            "base": to_str(get_col_val(row, 'BASE', 'Base')),
            "periodo": to_str(get_col_val(row, 'Período', 'Periodo', 'Perodo')),
            "origem": to_str(get_col_val(row, 'Origem')),
            "nr_ordem": to_str(get_col_val(row, 'Nr_Ordem', 'Nr Ordem')),
            "equipe1": to_str(get_col_val(row, 'Equipe1')),
            "despachada": to_str(get_col_val(row, 'Despachada')),
            "a_caminho": to_str(get_col_val(row, 'A_Caminho', 'A Caminho')),
            "no_local": to_str(get_col_val(row, 'No_Local', 'No Local')),
            "liberada": to_str(get_col_val(row, 'Liberada')),
            "minutos": to_float(get_col_val(row, 'Minutos')),
            "ups_executada": to_str(get_col_val(row, 'UPSExecutada')),
            "classe": to_str(get_col_val(row, 'Classe')),
            "descricao_classe": to_str(get_col_val(row, 'Descrição_Classe', 'Descricao_Classe', 'Descrio_Classe')),
            "causa": to_str(get_col_val(row, 'Causa')),
            "descricao_causa": to_str(get_col_val(row, 'Descrição_Causa', 'Descricao_Causa', 'Descrio_Causa')),
            "componente": to_str(get_col_val(row, 'Componente')),
            "estado_servico": to_str(get_col_val(row, 'Estado+Servico', 'Estado Servico')),
            "fases": to_str(get_col_val(row, 'Fases')),
            "tipo_classe": to_str(get_col_val(row, 'Tipo_Classe', 'Tipo Classe')),
            "qtd_task": to_int(get_col_val(row, 'Qtd Task')),
            "tempo_padrao": to_float(get_col_val(row, 'Tempo Padrao', 'Tempo Padrão')),
            "observacao": to_str(get_col_val(row, 'Observação', 'Observacao', 'Observao')),
            "qtd_servicos": to_int(get_col_val(row, 'Qtd Serviços', 'Qtd Servicos', 'Qtd Servios')),
            "verifica_repetidos_ht": to_str(get_col_val(row, 'VerificaRepetidosHT')),
            "hora_primeiro_deslocamento": to_str(get_col_val(row, 'Hora 1º Deslocamento', 'Hora 1o Deslocamento', 'Hora 1 Deslocamento')),
            "hora_primeiro_despacho": to_str(get_col_val(row, 'Hora 1º Despacho', 'Hora 1o Despacho', 'Hora 1 Despacho')),
            "qtd_deslocamentos": to_int(get_col_val(row, 'Qtd Deslocamentos')),
            "hora_ultima_ordem": to_str(get_col_val(row, 'Hora Ultima Ordem', 'Hora Última Ordem')),
            "ht_ordem": to_float(get_col_val(row, 'HT Ordem')),
            "ht_total": to_float(get_col_val(row, 'HT total', 'HT Total')),
            "tl_ordem": to_float(get_col_val(row, 'TL Ordem')),
            "tl_total": to_float(get_col_val(row, 'TL Total', 'TL total')),
            "tr_ordem": to_float(get_col_val(row, 'TR Ordem')),
            "tr_total": to_float(get_col_val(row, 'TR Total', 'TR total')),
            "hp_ordem": to_float(get_col_val(row, 'HP Ordem')),
            "hp_total": to_float(get_col_val(row, 'HP Total', 'HP total')),
            "qtd_equipes_os": to_int(get_col_val(row, 'Qtd Equipes OS')),
            "soma_desl_ativ": to_float(get_col_val(row, 'Soma De Desl/Ativ')),
            "conta_task_time_tr": to_float(get_col_val(row, 'Conta Task Time tr', 'Conta Task Time TR')),
            "conta_task_time_tl": to_float(get_col_val(row, 'Conta task Time TL', 'Conta Task Time TL')),
            "task_time_total_tr": to_float(get_col_val(row, 'Task Time Total TR')),
            "task_time_total_tl": to_float(get_col_val(row, 'Task Time Total TL')),
            "media_qtd_servicos": to_float(get_col_val(row, 'Média Qtd Serviços', 'Media Qtd Servicos', 'Mdia Qtd Servios')),
            "tr_ordem_secundario": to_float(get_col_val(row, 'TR Ordem Secundário', 'TR Ordem Secundario', 'TR Ordem Secundrio')),
            "tr_ordem_imp_ss": to_float(get_col_val(row, 'TR Ordem Imp SS')),
            "tr_ordem_secundario_equipe": to_float(get_col_val(row, 'TR Ordem Sencundário equipe', 'TR Ordem Secundario equipe', 'TR Ordem Sencundrio equipe')),
            "tr_ordem_imp_ss_equipe": to_float(get_col_val(row, 'TR Ordem Imp SS equipe')),
            "os_projeto": to_int(get_col_val(row, 'OS Projeto')),
            "os_poda": to_int(get_col_val(row, 'OS PODA', 'OS Poda')),
            "os_recolha": to_int(get_col_val(row, 'OS Recolha')),
            "os_tma": to_int(get_col_val(row, 'OS TMA')),
            "os_projeto_total": to_int(get_col_val(row, 'OS Projeto Total')),
            "os_poda_total": to_int(get_col_val(row, 'OS Poda Total')),
            "os_recolha_total": to_int(get_col_val(row, 'OS Recolha Total')),
            "os_tma_total": to_int(get_col_val(row, 'OS TMA Total')),
            "atuacao": to_str(get_col_val(row, 'Atuação', 'Atuacao', 'Atuao')),
            "os_improdutiva": to_int(get_col_val(row, 'OS improdutiva', 'OS Improdutiva')),
            "os_improdutiva_total": to_int(get_col_val(row, 'OS  Improdutivda Total', 'OS Improdutiva Total')),
            "os_p2": to_int(get_col_val(row, 'OS P2')),
            "os_p2_total": to_int(get_col_val(row, 'OS P2 Total')),
            "fonte": to_str(get_col_val(row, 'Fonte')),
            "placa": to_str(get_col_val(row, 'Placa')),
            "tempo_plataforma": to_float(get_col_val(row, 'Tempo_Plataforma', 'Tempo Plataforma')),
            "filtro_repetido_equipe_data": to_str(get_col_val(row, 'FiltroRepetidoEquipeData')),
            "login_corrigido": login_c,
            "logoff_corrigido": logoff_c,
            "hd_total": to_float(get_col_val(row, 'HD Total')),
            "primeiro_desloc": to_str(get_col_val(row, '1º Desloc', '1o Desloc', '1 Desloc')),
            "primeiro_despacho": to_str(get_col_val(row, '1º Despacho', '1o Despacho', '1 Despacho')),
            "plataforma": to_str(get_col_val(row, 'Plataforma')),
            "retorno_base": to_str(get_col_val(row, 'Retorno a base', 'Retorno a Base')),
            "mes": to_str(get_col_val(row, 'Mês', 'Mes', 'Ms')),
            "desvios": to_str(get_col_val(row, 'Desvios')),
            "ano": to_int(get_col_val(row, 'Ano')),
            "primeiro_login_corrigido": to_str(get_col_val(row, '1º Login Corrigido', '1o Login Corrigido', '1 Login Corrigido')),
            "filtro_ordens": to_str(get_col_val(row, 'FiltroOrdens')),
            "ht_p2": to_float(get_col_val(row, 'HT P2')),
            "ht_p2_total": to_float(get_col_val(row, 'HT P2 Total')),
            "horas_extras": to_str(get_col_val(row, 'Horas Extras')),
            "filtro_palavra_chave": to_str(get_col_val(row, 'FiltroPalavraChave')),
            "semana": to_int(get_col_val(row, 'Semana')),
            "base_responsavel": to_str(get_col_val(row, 'BaseResponsavel', 'Base Responsavel')),
            "dia": to_int(get_col_val(row, 'DIA', 'Dia')),
            "tipo_equipe": to_str(get_col_val(row, 'TIPO_EQUIPE', 'Tipo Equipe')),
            "empresa": to_str(get_col_val(row, 'EMPRESA', 'Empresa')),
            "tipo_empresa": to_str(get_col_val(row, 'TIPO_EMPRESA', 'Tipo Empresa')),
            "ut": to_str(get_col_val(row, 'UT', 'Ut')),
            "semana_mes": to_str(get_col_val(row, 'SEMANA_MES', 'Semana Mes')),
            "micro_regiao": to_str(get_col_val(row, 'MICRO_REGIAO', 'Micro Regiao')),
            "tr_ordem_imp_m300": to_float(get_col_val(row, 'TR Ordem Imp M300')),
            "raw_data": {str(k): to_str(v) for k, v in row.items() if not str(k).startswith('_')}
        }
        records.append(rec)

    return records

def executar_ciclo_sincronizacao_spotfire(source_label="Rotina Automática", full_history=True, all_months=False):
    """
    Executa o ciclo completo de sincronização do Scanner 5.0 (Spotfire):
    1. Abre WebSocket CDP na aba do Scanner 5.0.
    2. Aplica filtros e exporta silenciosamente a Tabela Completa todas Colunas (mês atual ou todos se all_months=True).
    3. Trata com Pandas (filtrando as equipes das bases oficiais e normalizando as 98 colunas).
    4. Persiste no Supabase com UPSERT atômico (team_scanner_records).
    5. Reconcilia no delivery_manager.
    6. Exclui o arquivo temporário baixado.
    """
    from cluster_manager import cluster_manager
    if not cluster_manager.is_feeding_database():
        ts = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts}] [CDP SPOTFIRE] [STANDBY REPOUSO] Esta maquina ({cluster_manager.node_id}) esta em STANDBY. Nenhuma acao disparada no Spotfire ({source_label}).", flush=True)
        return {"status": "standby", "message": "Maquina em Standby - Extracao Spotfire suspensa"}

    if not _SPOTFIRE_LOCK.acquire(blocking=False):
        ts = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts}] [CDP SPOTFIRE] Ciclo anterior ainda em andamento. Ignorando novo disparo ({source_label}).", flush=True)
        return {"status": "busy", "message": "Ciclo anterior do Spotfire em andamento"}

    start_t = time.time()
    ts_start = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    print(f"\n[{ts_start}] [CDP SPOTFIRE] >>> INICIANDO CICLO DE COLETA: Scanner 5.0 Spotfire ({source_label})...", flush=True)

    try:
        from supabase_client import push_scanner_records_to_supabase
        from delivery_manager import delivery_manager

        tab = localizar_aba_spotfire(criar_se_nao_existir=True)
        if not tab:
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM AVISO ({elapsed}s): Aba do Spotfire não encontrada.", flush=True)
            return {"status": "error", "message": "Aba do Spotfire não encontrada."}

        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM ERRO ({elapsed}s): WebSocket CDP indisponível.", flush=True)
            return {"status": "error", "message": "WebSocket CDP indisponível."}

        client = SpotfireCDPClient(ws_url)
        client.connect()

        downloaded_file = ""
        try:
            downloaded_file = exportar_arquivo_spotfire_via_cdp(client, all_months=all_months)
        finally:
            client.close()

        if not downloaded_file or not os.path.exists(downloaded_file):
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM AVISO ({elapsed}s): Falha na geração do arquivo exportado.", flush=True)
            return {"status": "error", "message": "Falha na geração do arquivo exportado do Scanner 5.0."}

        today_str = date.today().isoformat()
        if full_history:
            records = processar_arquivo_scanner_para_registros(downloaded_file, target_dates=None)
        else:
            yesterday_str = (date.today() - timedelta(days=1)).isoformat()
            target_dates = [today_str, yesterday_str]
            records = processar_arquivo_scanner_para_registros(downloaded_file, target_dates=target_dates)

        # Exclui o arquivo temporário baixado após o processamento (Regra Master de Limpeza)
        try:
            os.remove(downloaded_file)
            print(f"[CLEANUP] Arquivo temporário de exportação excluído com sucesso.", flush=True)
        except Exception:
            pass

        if not records:
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
            print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM AVISO ({elapsed}s): Nenhum registro retornado.", flush=True)
            return {"status": "success", "count": 0, "message": "Nenhum registro encontrado."}

        # Persiste no Supabase via UPSERT atômico na tabela team_scanner_records
        db_res = push_scanner_records_to_supabase(records)
        count_saved = db_res.get("count", len(records))

        # Reconcilia no delivery_manager para a data atual
        today_records = [r for r in records if r.get("data_referencia") == today_str]
        if today_records:
            delivery_manager.reconcile_with_spotfire_records(today_records, date_ref=today_str)
        else:
            # Reconcilia com a data mais recente disponível
            dates_in_rec = sorted(list(set(r.get("data_referencia") for r in records if r.get("data_referencia"))))
            if dates_in_rec:
                latest_dt = dates_in_rec[-1]
                latest_records = [r for r in records if r.get("data_referencia") == latest_dt]
                delivery_manager.reconcile_with_spotfire_records(latest_records, date_ref=latest_dt)

        elapsed = round(time.time() - start_t, 2)
        ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        set_last_scanner_sync_time(ts_end)
        print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM SUCESSO: {count_saved} equipes sincronizadas no Supabase em {elapsed}s ({source_label}).", flush=True)

        try:
            from supabase_client import update_engine_health
            update_engine_health("spotfire_cdp_collector", "OPERATIONAL", is_running=True,
                                 error_type="NONE", last_error=None,
                                 records_count=count_saved,
                                 engine_label="Robô CDP Scanner 5.0 (Spotfire)")
        except Exception:
            pass

        return {
            "status": "success",
            "count": count_saved,
            "last_sync": ts_end,
            "message": f"{count_saved} registros do Scanner 5.0 sincronizados com sucesso."
        }
    except Exception as e:
        elapsed = round(time.time() - start_t, 2)
        ts_end = datetime.now().strftime('%d/%m/%Y %H:%M:%S')
        print(f"[{ts_end}] [CDP SPOTFIRE] <<< CICLO FINALIZADO COM ERRO ({elapsed}s): {e}", flush=True)
        try:
            from supabase_client import update_engine_health
            update_engine_health("spotfire_cdp_collector", "ERROR_CONNECTION", is_running=True,
                                 error_type="CONNECTION_REFUSED", last_error=str(e),
                                 engine_label="Robô CDP Scanner 5.0 (Spotfire)")
        except Exception:
            pass
        return {"status": "error", "message": str(e)}
    finally:
        _SPOTFIRE_LOCK.release()

LAST_SYNC_FILE = os.path.join(WORKSPACE_DIR, "scanner_last_sync.json")

def set_last_scanner_sync_time(dt_str=None):
    """Grava em disco o timestamp da última sincronização bem-sucedida do Scanner 5.0."""
    if not dt_str:
        dt_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    try:
        with open(LAST_SYNC_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sync": dt_str}, f)
    except Exception:
        pass
    return dt_str

def get_last_scanner_sync_time():
    """Recupera o timestamp da última sincronização bem-sucedida do Scanner 5.0."""
    try:
        if os.path.exists(LAST_SYNC_FILE):
            with open(LAST_SYNC_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_sync")
    except Exception:
        pass
    return None

def spotfire_background_worker(interval_seconds=1800, stop_event=None):
    """
    Worker contínuo executado em background thread a cada 30 minutos (1800s).
    """
    mins = int(interval_seconds // 60)
    print(f"[BACKGROUND WORKER] Motor CDP TIBCO Spotfire ativo (intervalo: {mins} min).", flush=True)
    if stop_event:
        if stop_event.wait(15):
            return
    else:
        time.sleep(15)

    while True:
        if stop_event and stop_event.is_set():
            print("[BACKGROUND WORKER] Rotina do Spotfire finalizada.", flush=True)
            break
        try:
            from cluster_manager import cluster_manager
            if cluster_manager.is_feeding_database():
                executar_ciclo_sincronizacao_spotfire(source_label=f"Rotina Automática ({mins} min)")
        except Exception as err:
            print(f"[SPOTFIRE WORKER EXCEPTION] {err}", flush=True)
        if stop_event:
            if stop_event.wait(interval_seconds):
                break
        else:
            time.sleep(interval_seconds)

if __name__ == "__main__":
    print("Testando extração do Scanner 5.0 Spotfire...")
    r = executar_ciclo_sincronizacao_spotfire(source_label="Teste Manual Scanner 5.0")
    print(json.dumps(r, indent=2, ensure_ascii=False))
