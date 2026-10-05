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
import shutil
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
USER_DOWNLOADS_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
try:
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
except Exception:
    pass

def prune_old_user_downloads(prefix="Scanner 5.0", max_keep=3):
    """Remove arquivos antigos de exportação do diretório de Downloads do usuário para economizar espaço em disco."""
    try:
        if not os.path.exists(USER_DOWNLOADS_DIR):
            return
        matches = []
        for f in os.listdir(USER_DOWNLOADS_DIR):
            if (prefix.lower() in f.lower() or 'tabela completa' in f.lower()) and (f.endswith('.csv') or f.endswith('.tsv') or f.endswith('.txt')):
                p = os.path.join(USER_DOWNLOADS_DIR, f)
                try:
                    matches.append((p, os.path.getmtime(p)))
                except Exception:
                    pass
        matches.sort(key=lambda x: x[1], reverse=True)
        for p, _ in matches[max_keep:]:
            try:
                os.remove(p)
            except Exception:
                pass
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

    # 1. Prioriza aba já carregada no Scanner 5.0 (NUNCA capturar o Priorizador!)
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'priorizador' in t_title or 'priorizador' in t_url:
                continue
            if 'scanner' in t_title or 'scanner' in t_url:
                return t

    # 2. Em seguida, busca aba do Spotfire QUE NÃO SEJA O PRIORIZADOR
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'priorizador' in t_title or 'priorizador' in t_url:
                continue
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
def aguardar_spotfire_idle(client, timeout=45, comfort_buffer_seconds=10, step_label="Barreira Idle"):
    """
    Barreira de Estabilização Assíncrona do Spotfire Web Player:
    1. Aguarda ativamente o término de todos os spinners, overlays e indicadores de ocupado do Spotfire.
    2. Aplica o buffer de conforto (+10 segundos) solicitado para garantir 100% de consolidação do render pelo navegador.
    """
    start_t = time.time()
    print(f"[SPOTFIRE CDP] [{step_label}] Aguardando ausência de spinners e ocupado do Spotfire...", flush=True)
    while time.time() - start_t < timeout:
        busy_info = client.evaluate('''(() => {
            if (document.readyState !== 'complete') return { busy: true, reason: "document.readyState != complete" };
            const busySelectors = '.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay, [sf-busy="true"]';
            const busyEls = Array.from(document.querySelectorAll(busySelectors)).filter(el => {
                return (el.offsetWidth > 0 || el.offsetHeight > 0);
            });
            if (busyEls.length > 0) return { busy: true, reason: "spinner ativo", count: busyEls.length };
            return { busy: false };
        })()''')

        if not busy_info or not busy_info.get("busy"):
            break
        time.sleep(1.0)

    if comfort_buffer_seconds > 0:
        print(f"[SPOTFIRE CDP] [{step_label}] Spinners finalizados. Aplicando buffer de conforto de +{comfort_buffer_seconds}s para consolidação total do render...", flush=True)
        time.sleep(comfort_buffer_seconds)
    print(f"[SPOTFIRE CDP OK] [{step_label}] Sistema estabilizado e pronto!", flush=True)

def cdp_press_enter(client):
    """
    Envia o evento de teclado físico da tecla Enter (VK_RETURN / código 13) via Chrome DevTools Protocol.
    Garante que todos os ouvintes nativos do navegador e bibliotecas JavaScript registrem a submissão.
    """
    client.call("Input.dispatchKeyEvent", {
        "type": "rawKeyDown",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
        "macCharCode": 13,
        "key": "Enter",
        "code": "Enter",
        "unmodifiedText": "\r",
        "text": "\r"
    })
    client.call("Input.dispatchKeyEvent", {
        "type": "char",
        "key": "Enter",
        "code": "Enter",
        "unmodifiedText": "\r",
        "text": "\r"
    })
    client.call("Input.dispatchKeyEvent", {
        "type": "keyUp",
        "windowsVirtualKeyCode": 13,
        "nativeVirtualKeyCode": 13,
        "macCharCode": 13,
        "key": "Enter",
        "code": "Enter"
    })

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
    # Configura diretório de download silencioso via Browser e Page domains
    for method in ["Browser.setDownloadBehavior", "Page.setDownloadBehavior"]:
        try:
            client.call(method, {
                "behavior": "allow",
                "downloadPath": DOWNLOADS_DIR,
                "eventsEnabled": True
            })
        except Exception:
            pass

    # Limpa arquivos residuais no diretório
    for f in os.listdir(DOWNLOADS_DIR):
        try:
            os.remove(os.path.join(DOWNLOADS_DIR, f))
        except Exception:
            pass

    # =========================================================================
    # ETAPA 1: F5 (Page.reload) e Confirmação de Carregamento Completo
    # =========================================================================
    current_check = client.evaluate('''(() => {
        const title = (document.title || '').toLowerCase();
        const url = (window.location.href || '').toLowerCase();
        return {
            isPriorizador: title.includes('priorizador') || url.includes('priorizador'),
            isScanner: title.includes('scanner') || url.includes('scanner')
        };
    })()''')

    if current_check and current_check.get("isPriorizador"):
        raise RuntimeError("Conflito evitado: a aba conectada pertence ao Priorizador! O Scanner 5.0 utilizará apenas sua própria aba dedicada.")

    current_url = client.evaluate("window.location.href") or ""
    is_ready_now = client.evaluate('''(() => {
        const visuals = document.querySelectorAll('.sf-element-visual').length;
        const tabs = document.querySelectorAll('.sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab').length;
        const title = (document.title || '').toLowerCase();
        const url = window.location.href.toLowerCase();
        const isScanner = title.includes('scanner') || url.includes('scanner');
        return (visuals > 0 || tabs > 0) && isScanner;
    })()''')

    if not is_ready_now:
        print(f"[SPOTFIRE CDP] Navegando aba para URL limpa do Scanner 5.0: {SPOTFIRE_URL[:80]}...", flush=True)
        client.call("Page.navigate", {"url": SPOTFIRE_URL})
    else:
        print("[SPOTFIRE CDP OK] Página do Scanner 5.0 já carregada e pronta na aba ativa!", flush=True)

    # Aguarda o Spotfire carregar 100%
    print("[SPOTFIRE CDP] Aguardando página do Spotfire carregar completamente após F5...", flush=True)
    start_load = time.time()
    page_ready = False
    while time.time() - start_load < 60:
        time.sleep(2.0)
        status = client.evaluate('''(() => {
            if (document.readyState !== 'complete') return { ready: false, reason: "readyState != complete" };
            // Verifica se há overlays de carregamento ativos
            const busy = document.querySelector('.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay, .sfx_progress-dialog_1130');
            if (busy && (busy.offsetWidth > 0 || busy.offsetHeight > 0)) {
                const cancelBtn = document.querySelector('.sfx_progress-dialog_1130 [title="Cancel"], .sfx_centralizer_1131 [title="Cancel"]');
                if (cancelBtn) cancelBtn.click();
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
        # Aguarda Tabela Completa e Filtros renderizarem na aba 'Tab Completa'
        for _ in range(20):
            time.sleep(1.0)
            ready_tab = client.evaluate('''(() => {
                const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
                const hasTabela = visuals.some(v => {
                    const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || '';
                    return title.toLowerCase().includes('tabela completa');
                });
                const hasFilters = visuals.some(v => {
                    const r = v.getBoundingClientRect();
                    return r.left < 250 && r.height > 400;
                });
                const busy = document.querySelectorAll('.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay');
                return (hasTabela && hasFilters && busy.length === 0);
            })()''')
            if ready_tab:
                break

    # =========================================================================
    # ETAPA 2: Clicar em 'Reset Visible Filters' no Canto Direito (Filters)
    # =========================================================================
    print("[SPOTFIRE CDP] Localizando e acionando 'Reset Visible Filters' no canto direito...", flush=True)
    reset_clicked = client.evaluate('''(() => {
        const candidates = Array.from(document.querySelectorAll('.ResetButton, .ResetFilters, [title*="Reset Visible Filters"], [title*="Reset visible filters"]'));
        for (const el of candidates) {
            const r = el.getBoundingClientRect();
            // Garante que é um botão pequeno no painel de filtros (direita, r.left > 1500)
            if (r.width > 0 && r.width < 50 && r.height > 0 && r.height < 50 && r.left > 1500) {
                const x = Math.round(r.left + r.width / 2);
                const y = Math.round(r.top + r.height / 2);
                const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 };
                el.dispatchEvent(new MouseEvent('pointerdown', opts));
                el.dispatchEvent(new MouseEvent('mousedown', opts));
                el.dispatchEvent(new MouseEvent('pointerup', opts));
                el.dispatchEvent(new MouseEvent('mouseup', opts));
                el.dispatchEvent(new MouseEvent('click', opts));
                return { success: true, title: el.getAttribute('title') || 'ResetButton', x, y };
            }
        }
        return { success: false };
    })()''')

    if reset_clicked and reset_clicked.get("success"):
        print(f"[SPOTFIRE CDP OK] 'Reset Visible Filters' acionado com sucesso em ({reset_clicked['x']}, {reset_clicked['y']})!", flush=True)
        # Barreira de estabilização pós-reset com buffer de conforto (+10s)
        aguardar_spotfire_idle(client, timeout=45, comfort_buffer_seconds=10, step_label="Etapa 2 - Pós Reset")
    else:
        print("[SPOTFIRE CDP WARN] Botão 'Reset Visible Filters' não localizado no painel direito, prosseguindo...", flush=True)

    # =========================================================================
    # ETAPA 3: Filtrar o Ano Atual (Painel Esquerdo)
    # =========================================================================
    now = datetime.now()
    target_year = str(now.year)
    target_month_idx = now.month
    en_month, pt_month = MONTH_ABBR_MAP.get(target_month_idx, ('Sep', 'Set'))
    target_month_names = [pt_month.lower(), en_month.lower(), 'set', 'sep']

    print(f"[SPOTFIRE CDP] Configurando filtro de Ano={target_year} no painel esquerdo...", flush=True)

    def adjust_year_filter():
        return client.evaluate(f'''(() => {{
            const target = "{target_year}";
            const items = Array.from(document.querySelectorAll(".sf-element-filter-item")).filter(el => {{
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && r.left < 300 && r.top < 160;
            }});

            const adjusted = [];
            for (const el of items) {{
                const text = el.innerText.trim();
                const chk = el.querySelector(".sf-element-check-box");
                const isChecked = chk ? chk.classList.contains("sfpc-checked") : false;
                const isTarget = (text === target);

                if ((isTarget && !isChecked) || (!isTarget && isChecked && ["2023", "2024", "2025", "2026"].includes(text))) {{
                    const txt = el.querySelector(".sf-element-text-box") || el;
                    const r = txt.getBoundingClientRect();
                    const x = Math.round(r.left + r.width / 2);
                    const y = Math.round(r.top + r.height / 2);
                    const opts = {{ bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 }};
                    txt.dispatchEvent(new PointerEvent('pointerdown', opts));
                    txt.dispatchEvent(new MouseEvent('mousedown', opts));
                    txt.dispatchEvent(new PointerEvent('pointerup', opts));
                    txt.dispatchEvent(new MouseEvent('mouseup', opts));
                    txt.dispatchEvent(new MouseEvent('click', opts));
                    adjusted.push(text);
                }}
            }}
            return adjusted;
        }})()''')

    adjusted_years = adjust_year_filter()
    if adjusted_years:
        print(f"[SPOTFIRE CDP] Anos ajustados no filtro: {adjusted_years}", flush=True)
        # Barreira de estabilização pós-ajuste de ano com buffer de conforto (+10s)
        aguardar_spotfire_idle(client, timeout=45, comfort_buffer_seconds=10, step_label="Etapa 3 - Pós Ano")
    else:
        time.sleep(2.0)

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
            aguardar_spotfire_idle(client, timeout=45, comfort_buffer_seconds=10, step_label="Etapa 4 - Pós Remoção Filtro Mês")
    else:
        print(f"[SPOTFIRE CDP] Aplicando filtro estrito do Mês Atual ({pt_month} / {en_month} - Mês {target_month_idx:02d}) no painel esquerdo...", flush=True)

        month_text = pt_month.lower()

        # 1. Localiza, foca e clica fisicamente no SearchInput do Mês
        print(f"[SPOTFIRE CDP] [Etapa 4] Focando SearchInput do Mês e digitando '{month_text}'...", flush=True)
        inp_coords = client.evaluate('''(() => {
            const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {
                const r = el.getBoundingClientRect();
                return r.left < 250 && r.height > 400;
            }) || document.body;
            const inps = Array.from(v.querySelectorAll('input.SearchInput, input')).filter(i => {
                const r = i.getBoundingClientRect();
                return r.left < 300 && r.top > 150 && r.top < 300;
            });
            if (inps.length === 0) return null;
            const inp = inps[0];
            const r = inp.getBoundingClientRect();
            inp.focus();
            return {
                x: Math.round(r.left + r.width / 2),
                y: Math.round(r.top + r.height / 2)
            };
        })()''')

        if inp_coords:
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": inp_coords["x"], "y": inp_coords["y"], "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": inp_coords["x"], "y": inp_coords["y"], "button": "left", "clickCount": 1})
            time.sleep(0.3)

        # Preenche o texto 'set' mantendo o foco no SearchInput
        client.evaluate(f'''(() => {{
            const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                const r = el.getBoundingClientRect();
                return r.left < 250 && r.height > 400;
            }}) || document.body;
            const inps = Array.from(v.querySelectorAll('input.SearchInput, input')).filter(i => {{
                const r = i.getBoundingClientRect();
                return r.left < 300 && r.top > 150 && r.top < 300;
            }});
            if (inps.length === 0) return;
            const inp = inps[0];
            inp.focus();

            const $ = window.jQuery || window.$;
            if ($) {{
                const $inp = $(inp);
                $inp.val("").trigger("input");
                $inp.val("{month_text}").trigger("input").trigger("change");
                $inp.trigger($.Event('keydown', {{ which: 13, keyCode: 13 }}));
                $inp.trigger($.Event('keypress', {{ which: 13, keyCode: 13, charCode: 13 }}));
                $inp.trigger($.Event('keyup', {{ which: 13, keyCode: 13 }}));
            }} else {{
                inp.value = "{month_text}";
                inp.dispatchEvent(new Event('input', {{ bubbles: true }}));
                inp.dispatchEvent(new Event('change', {{ bubbles: true }}));
                inp.dispatchEvent(new KeyboardEvent('keydown', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                inp.dispatchEvent(new KeyboardEvent('keypress', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
                inp.dispatchEvent(new KeyboardEvent('keyup', {{ key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true }}));
            }}
            inp.focus();
        }})()''')

        # DISPARO FÍSICO MANDATÓRIO DO "ENTER" VIA CDP COM FOCO NO SEARCHINPUT
        print("[SPOTFIRE CDP] [Etapa 4] Pressionando tecla física 'Enter' (código 13) via CDP no SearchInput...", flush=True)
        time.sleep(0.2)
        cdp_press_enter(client)
        time.sleep(0.5)

        # 2. Barreira de Espera de Renderização: 4 Ciclos de 30 Segundos
        # Regra do Usuário:
        # - Estabelecer um tempo de 30 segundos DEPOIS que escreve 'set' e pressiona Enter para verificar se foi renderizado e selecionar o set no filtro.
        # - Quando der os 30 segundos de espera, o CDP verifica se no selectBox do mês apareceu 'set' para aí sim selecionar.
        # - Caso não tenha aparecido, aguarda mais 30 segundos.
        # - Faz esse ciclo 4 vezes (total de até 120s).
        # - Caso não apareça após os 4 ciclos, considera como falha e reinicia o processo (sem travar outros CDPs).
        max_render_cycles = 4
        render_cycle_wait = 30  # exatamente 30 segundos por ciclo
        item_found = None

        print(f"[SPOTFIRE CDP] [Etapa 4] Enter pressionado. Iniciando monitoramento da selectBox do Mês ({max_render_cycles} ciclos de {render_cycle_wait}s)...", flush=True)

        for cycle in range(1, max_render_cycles + 1):
            print(f"[SPOTFIRE CDP] [Etapa 4 - Ciclo {cycle}/{max_render_cycles}] Aguardando {render_cycle_wait}s após Enter para verificar se '{month_text}' foi renderizado no selectBox...", flush=True)
            time.sleep(render_cycle_wait)

            # Quando der os 30 segundos de espera, o CDP verifica se no selectBox do mês apareceu 'set'
            check_res = client.evaluate(f'''(() => {{
                const targetNames = {json.dumps(target_month_names)};
                const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                    const r = el.getBoundingClientRect();
                    return r.left < 250 && r.height > 400;
                }}) || document.body;
                const items = Array.from(v.querySelectorAll('.sf-element-list-box-item, [role="listitem"], .ListBoxItem')).filter(it => {{
                    const r = it.getBoundingClientRect();
                    return r.left < 300 && r.top > 150 && r.top < 450 && r.width > 0 && r.height > 0;
                }});

                const match = items.find(i => targetNames.some(m => {{
                    const t = (i.innerText || '').trim().toLowerCase();
                    const title = (i.getAttribute('title') || '').trim().toLowerCase();
                    return t === m || t.startsWith(m) || title === m || title.startsWith(m);
                }}));

                if (!match) {{
                    return {{
                        found: false,
                        itemsCount: items.length,
                        sampleItems: items.slice(0, 5).map(i => (i.innerText || i.getAttribute('title') || '').trim())
                    }};
                }}

                const r = match.getBoundingClientRect();
                return {{
                    found: true,
                    text: (match.innerText || match.getAttribute('title') || '').trim(),
                    alreadySelected: match.classList.contains("sfpc-selected") || !!match.querySelector(".sfpc-checked"),
                    x: Math.round(r.left + r.width / 2),
                    y: Math.round(r.top + r.height / 2)
                }};
            }})()''')

            if check_res and check_res.get("found"):
                item_found = check_res
                print(f"[SPOTFIRE CDP OK] [Etapa 4 - Ciclo {cycle}/{max_render_cycles}] Item '{item_found.get('text', month_text)}' apareceu na selectBox do mês!", flush=True)
                break
            else:
                items_cnt = check_res.get("itemsCount", 0) if check_res else 0
                sample = check_res.get("sampleItems", []) if check_res else []
                print(f"[SPOTFIRE CDP] [Etapa 4 - Ciclo {cycle}/{max_render_cycles}] Item '{month_text}' ainda não apareceu na selectBox após {cycle * render_cycle_wait}s (itens visíveis: {items_cnt}, amostra: {sample}).", flush=True)
                if cycle < max_render_cycles:
                    print(f"[SPOTFIRE CDP] [Etapa 4] Reaplicando foco e Enter no SearchInput para o próximo ciclo de {render_cycle_wait}s...", flush=True)
                    client.evaluate(f'''(() => {{
                        const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                            const r = el.getBoundingClientRect();
                            return r.left < 250 && r.height > 400;
                        }}) || document.body;
                        const inps = Array.from(v.querySelectorAll('input.SearchInput, input')).filter(i => {{
                            const r = i.getBoundingClientRect();
                            return r.left < 300 && r.top > 150 && r.top < 300;
                        }});
                        if (inps.length > 0) {{
                            const inp = inps[0];
                            inp.focus();
                            const $ = window.jQuery || window.$;
                            if ($) $(inp).val("{month_text}").trigger("input").trigger($.Event('keypress', {{ which: 13, keyCode: 13 }}));
                        }}
                    }})()''')
                    cdp_press_enter(client)

        if not item_found:
            print(f"[SPOTFIRE CDP ERROR] FALHA NA RENDERIZAÇÃO: Mês '{month_text}' não apareceu na selectBox após {max_render_cycles * render_cycle_wait}s ({max_render_cycles} ciclos de {render_cycle_wait}s).", flush=True)
            print("[SPOTFIRE CDP ERROR] Reiniciando processo para não impactar outras rotinas e ciclos...", flush=True)
            return ""

        match_text = item_found.get("text", month_text)

        # 3. Agora sim seleciona o item 'set' no filtro
        print(f"[SPOTFIRE CDP] [Etapa 4] Renderização confirmada! Agora selecionando '{match_text}' na selectBox do mês...", flush=True)
        if not item_found.get("alreadySelected"):
            client.evaluate(f'''(() => {{
                const targetNames = {json.dumps(target_month_names)};
                const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                    const r = el.getBoundingClientRect();
                    return r.left < 250 && r.height > 400;
                }}) || document.body;
                const items = Array.from(v.querySelectorAll('.sf-element-list-box-item, [role="listitem"], .ListBoxItem')).filter(it => {{
                    const r = it.getBoundingClientRect();
                    return r.left < 300 && r.top > 150 && r.top < 450 && r.width > 0 && r.height > 0;
                }});
                const match = items.find(i => targetNames.some(m => {{
                    const t = (i.innerText || '').trim().toLowerCase();
                    const title = (i.getAttribute('title') || '').trim().toLowerCase();
                    return t === m || t.startsWith(m) || title === m || title.startsWith(m);
                }}));
                if (!match) return;

                const $ = window.jQuery || window.$;
                if ($) {{
                    const $item = $(match);
                    const $scrollArea = $item.closest('.ScrollArea');
                    const offset = $item.offset();
                    const pageY = offset.top + ($item.height() / 2);
                    const pageX = offset.left + ($item.width() / 2);
                    $scrollArea.trigger($.Event('mousedown', {{ which: 1, pageX, pageY }}));
                    $(document.body).trigger($.Event('mouseup', {{ which: 1, pageX, pageY }}));
                }} else {{
                    const r = match.getBoundingClientRect();
                    const x = Math.round(r.left + r.width / 2);
                    const y = Math.round(r.top + r.height / 2);
                    const opts = {{ bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, button: 0 }};
                    match.dispatchEvent(new PointerEvent('pointerdown', opts));
                    match.dispatchEvent(new MouseEvent('mousedown', opts));
                    match.dispatchEvent(new PointerEvent('pointerup', opts));
                    match.dispatchEvent(new MouseEvent('mouseup', opts));
                    match.dispatchEvent(new MouseEvent('click', opts));
                }}
            }})()''')

            # Disparo físico adicional via CDP no elemento do mês
            x, y = item_found["x"], item_found["y"]
            client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": x, "y": y, "button": "left", "clickCount": 1})
            client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": x, "y": y, "button": "left", "clickCount": 1})
            time.sleep(1.0)

        # 4. Confirmação obrigatória do estado sfpc-selected
        is_sel = False
        for _ in range(15):
            is_sel = client.evaluate(f'''(() => {{
                const targetNames = {json.dumps(target_month_names)};
                const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                    const r = el.getBoundingClientRect();
                    return r.left < 250 && r.height > 400;
                }}) || document.body;
                const items = Array.from(v.querySelectorAll('.sf-element-list-box-item, [role="listitem"], .ListBoxItem'));
                const match = items.find(i => targetNames.some(m => {{
                    const t = (i.innerText || '').trim().toLowerCase();
                    const title = (i.getAttribute('title') || '').trim().toLowerCase();
                    return t === m || t.startsWith(m) || title === m || title.startsWith(m);
                }}));
                return match ? (match.classList.contains("sfpc-selected") || !!match.querySelector(".sfpc-checked")) : false;
            }})()''')
            if is_sel:
                break
            time.sleep(1.0)

        if not is_sel and not item_found.get("alreadySelected"):
            print(f"[SPOTFIRE CDP ERROR] BLOQUEIO PREVENTIVO: Mês '{match_text}' clicado mas NÃO adquiriu estado 'sfpc-selected'. Reiniciando processo!", flush=True)
            return ""

        print(f"[SPOTFIRE CDP OK] Mês '{match_text}' confirmado selecionado no filtro (sfpc-selected)!", flush=True)

        # 5. Barreira de Estabilização Pós-Seleção do Mês: AGUARDA O RECÁLCULO COMPLETO DA ANÁLISE E TABELA
        print("[SPOTFIRE CDP] Mês selecionado com sucesso. Aguardando 10s para o Spotfire registrar e iniciar recálculo da Tabela Completa...", flush=True)
        time.sleep(10.0)
        aguardar_spotfire_idle(client, timeout=60, comfort_buffer_seconds=10, step_label="Etapa 4 -> 5 - Recálculo Tabela Completa")

    # =========================================================================
    # ETAPA 5: Validação Forense Mandatória da 'Tabela Completa todas Colunas' (Data Referência)
    # =========================================================================
    # Regra Fundamental de Performance e Qualidade:
    # A tabela 'Tabela Completa todas Colunas' DEVE exibir exclusivamente datas do Mês e Ano filtrados.
    # Se a tabela ainda exibir datas de anos anteriores ou outros meses por lentidão de recálculo do Spotfire,
    # aguardamos em loop até 90s. Se persistir errado, o download é BLOQUEADO para não sobrecarregar o sistema.
    print(f"[SPOTFIRE CDP] Iniciando validação forense da coluna 'Data Referência' na visualização 'Tabela Completa todas Colunas'...", flush=True)

    table_data_valid = False
    start_table_check = time.time()
    max_wait_table = 90.0

    while time.time() - start_table_check < max_wait_table:
        # 1. Verifica se há indicadores de ocupado / spinner ativo
        busy_status = client.evaluate('''(() => {
            const busy = document.querySelector('.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay');
            return !!busy && (busy.offsetWidth > 0 || busy.offsetHeight > 0);
        })()''')

        if busy_status:
            print("[SPOTFIRE CDP] Spotfire recalculando dados da análise (spinner ativo)...", flush=True)
            time.sleep(2.0)
            continue

        # 2. Avalia a estrutura de células e datas da Tabela Completa todas Colunas
        table_eval = client.evaluate(f'''(() => {{
            const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
            const table = visuals.find(v => {{
                const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {{}}).innerText || '';
                const low = title.toLowerCase();
                return low.includes('tabela completa') || low.includes('todas colunas');
            }});
            if (!table) return {{ ok: false, reason: "Visual 'Tabela Completa todas Colunas' não localizado" }};

            const cells = Array.from(table.querySelectorAll('.sf-element-table-cell, .TableCell, td, [role=gridcell]')).map(c => {{
                const r = c.getBoundingClientRect();
                return {{
                    text: (c.innerText || '').trim(),
                    left: Math.round(r.left),
                    top: Math.round(r.top)
                }};
            }});

            if (cells.length === 0) return {{ ok: false, reason: "Células da tabela ainda não renderizadas" }};

            const rowMap = {{}};
            cells.forEach(c => {{
                if (!rowMap[c.top]) rowMap[c.top] = [];
                rowMap[c.top].push(c);
            }});

            const sortedTops = Object.keys(rowMap).map(Number).sort((a, b) => a - b);
            if (sortedTops.length < 2) return {{ ok: false, reason: "Apenas 1 linha encontrada (possível apenas cabeçalho)" }};

            // Linha de cabeçalho
            const headerCells = rowMap[sortedTops[0]].sort((a, b) => a.left - b.left);
            const headers = headerCells.map(c => c.text);

            let dateColIdx = headers.findIndex(h => {{
                const low = h.toLowerCase();
                return low.includes('data') && (low.includes('ref') || low.includes('referência') || low.includes('referencia'));
            }});
            if (dateColIdx === -1) dateColIdx = 0;

            // Extrai datas das linhas de dados
            const dataRows = sortedTops.slice(1);
            const rawDates = [];
            for (const top of dataRows) {{
                const rowCells = rowMap[top].sort((a, b) => a.left - b.left);
                if (rowCells[dateColIdx]) {{
                    const val = rowCells[dateColIdx].text;
                    if (val) rawDates.push(val);
                }}
            }}

            const targetMonth = {target_month_idx};
            const targetYear = {int(target_year)};

            function parseMonthYear(dateStr) {{
                if (!dateStr) return null;
                const clean = dateStr.trim();
                if (clean.includes('/')) {{
                    const parts = clean.split(' ')[0].split('/');
                    if (parts.length === 3) {{
                        const p0 = parseInt(parts[0], 10);
                        const p1 = parseInt(parts[1], 10);
                        const yr = parseInt(parts[2], 10);
                        // Reconhece padrão DD/MM/YYYY (oficial Enel SP) e MM/DD/YYYY
                        let isMonthMatch = false;
                        if (p1 === targetMonth && p0 <= 31) {{
                            isMonthMatch = true;
                        }} else if (p0 === targetMonth && p1 <= 31) {{
                            isMonthMatch = true;
                        }}
                        const isYearMatch = (yr === targetYear);
                        return {{
                            month: (p1 <= 12) ? p1 : p0,
                            year: yr,
                            isMatch: isMonthMatch && isYearMatch,
                            isYearMatch: isYearMatch,
                            raw: dateStr
                        }};
                    }}
                }} else if (clean.includes('-')) {{
                    const parts = clean.split(' ')[0].split('-');
                    if (parts.length === 3) {{
                        const yr = parseInt(parts[0], 10);
                        const mo = parseInt(parts[1], 10);
                        return {{
                            month: mo,
                            year: yr,
                            isMatch: (mo === targetMonth && yr === targetYear),
                            isYearMatch: (yr === targetYear),
                            raw: dateStr
                        }};
                    }}
                }}
                return null;
            }}

            const parsedDates = rawDates.map(parseMonthYear).filter(Boolean);

            const matchingDates = parsedDates.filter(d => d.isMatch);
            const mismatchedDates = parsedDates.filter(d => !d.isMatch);
            const yearMatchingDates = parsedDates.filter(d => d.isYearMatch);
            const yearMismatchedDates = parsedDates.filter(d => !d.isYearMatch);

            return {{
                ok: true,
                headers,
                dateColIdx,
                dataRowsCount: dataRows.length,
                rawDatesSample: rawDates.slice(0, 5),
                parsedCount: parsedDates.length,
                matchingCount: matchingDates.length,
                mismatchedCount: mismatchedDates.length,
                yearMatchingCount: yearMatchingDates.length,
                yearMismatchedCount: yearMismatchedDates.length,
                mismatchedSample: mismatchedDates.slice(0, 3).map(d => d.raw)
            }};
        }})()''')

        if table_eval and table_eval.get("ok"):
            data_rows = table_eval.get("dataRowsCount", 0)
            matching = table_eval.get("matchingCount", 0)
            mismatched = table_eval.get("mismatchedCount", 0)
            year_matching = table_eval.get("yearMatchingCount", 0)
            year_mismatched = table_eval.get("yearMismatchedCount", 0)
            sample_dates = table_eval.get("rawDatesSample", [])

            # Modo Carga Anual: valida apenas se o ano corresponde ao target_year
            if all_months:
                if data_rows > 0 and year_mismatched == 0 and year_matching > 0:
                    print(f"[SPOTFIRE CDP TABLE VALIDATED] Carga Anual validada! {year_matching} linhas visíveis para o ano {target_year}. Amostra: {sample_dates[:3]}", flush=True)
                    print(f"[SPOTFIRE CDP] Aplicando buffer de conforto de +10s antes do export...", flush=True)
                    time.sleep(10.0)
                    table_data_valid = True
                    break
            else:
                # Validação Estrita do Mês Atual:
                # DEVE haver pelo menos 1 linha, TODAS as linhas visíveis devem pertencer ao mês e ano alvo, e ZERO divergências!
                if data_rows > 0 and matching > 0 and mismatched == 0:
                    print(f"[SPOTFIRE CDP TABLE VALIDATED] Tabela 'Tabela Completa todas Colunas' validada com sucesso!", flush=True)
                    print(f"   -> Mês/Ano esperado: {pt_month}/{target_year} ({target_month_idx:02d}/{target_year})", flush=True)
                    print(f"   -> Linhas visíveis verificadas: {matching} | Amostra de datas: {sample_dates[:4]}", flush=True)
                    print(f"[SPOTFIRE CDP] Tabela 100% validada! Aplicando buffer de conforto de +10s antes do export...", flush=True)
                    time.sleep(10.0)
                    table_data_valid = True
                    break
                else:
                    elapsed = round(time.time() - start_table_check, 1)
                    mismatches = table_eval.get("mismatchedSample", [])
                    print(f"[SPOTFIRE CDP TABLE WAITING] Aguardando atualização dos dados da tabela ({elapsed}s)... (Correspondentes: {matching}/{data_rows} | Divergentes: {mismatched} - Amostra: {mismatches})", flush=True)

                    # Se após 25 segundos ainda apresentar datas divergentes, reaplica busca e clique no filtro do mês
                    if elapsed > 25.0 and elapsed % 15.0 < 2.5 and not all_months:
                        print(f"[SPOTFIRE CDP RETRY] Reaplicando clique no filtro do mês '{pt_month}' para forçar atualização do servidor...", flush=True)
                        client.evaluate(f'''(() => {{
                            const targetNames = {json.dumps(target_month_names)};
                            const v = Array.from(document.querySelectorAll('.sf-element-visual')).find(el => {{
                                const r = el.getBoundingClientRect();
                                return r.left < 250 && r.height > 400;
                            }}) || document.body;
                            const items = Array.from(v.querySelectorAll('.sf-element-list-box-item')).filter(it => {{
                                const r = it.getBoundingClientRect();
                                return r.left < 300 && r.top > 150 && r.top < 350;
                            }});
                            const match = items.find(i => targetNames.some(m => {{
                                const t = (i.innerText || '').trim().toLowerCase();
                                const title = (i.getAttribute('title') || '').trim().toLowerCase();
                                return t === m || t.startsWith(m) || title === m || title.startsWith(m);
                            }}));
                            if (match) {{
                                const $ = window.jQuery || window.$;
                                if ($) {{
                                    const $item = $(match);
                                    const $scrollArea = $item.closest('.ScrollArea');
                                    const offset = $item.offset();
                                    const pageY = offset.top + ($item.height() / 2);
                                    const pageX = offset.left + ($item.width() / 2);
                                    $scrollArea.trigger($.Event('mousedown', {{ which: 1, pageX, pageY }}));
                                    $(document.body).trigger($.Event('mouseup', {{ which: 1, pageX, pageY }}));
                                }}
                            }}
                        }})()''')

        time.sleep(2.0)

    if not table_data_valid:
        print(f"[SPOTFIRE CDP ERROR] BLOQUEIO PREVENTIVO DE DOWNLOAD: A 'Tabela Completa todas Colunas' não atualizou para o mês/ano filtrado ({pt_month}/{target_year}) após {max_wait_table}s!", flush=True)
        print(f"[SPOTFIRE CDP ERROR] Operação cancelada para evitar sobrecarga do servidor Spotfire e download de arquivos com múltiplos anos.", flush=True)
        return ""

    time.sleep(1.0)

    # =========================================================================
    # ETAPA 6: Botão Direito -> Export -> Export Table e Monitoramento em Duas Fases
    # =========================================================================
    print("[SPOTFIRE CDP] Acionando menu de contexto (botão direito) na Tabela Completa...", flush=True)
    target_data_cell = client.evaluate('''(() => {
        const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
        const table = visuals.find(v => {
            const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || '';
            const low = title.toLowerCase();
            return low.includes('tabela completa') || low.includes('todas colunas');
        });
        if (!table) return null;
        const cells = Array.from(table.querySelectorAll('.sf-element-table-cell, .TableCell, td, [role=gridcell]'));
        // Seleciona uma célula de dados (a partir da linha 1, índice >= 10 ou com texto de equipe/data)
        const cell = cells[11] || cells.find(c => (c.innerText || '').trim().length > 3) || cells[0];
        if (!cell) return null;
        const r = cell.getBoundingClientRect();
        return {
            tableId: table.id,
            tableTitle: (table.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || '',
            x: Math.round(r.left + r.width / 2),
            y: Math.round(r.top + r.height / 2),
            text: (cell.innerText || '').trim()
        };
    })()''')

    if not target_data_cell:
        print("[SPOTFIRE CDP ERROR] Falha ao localizar visual ou células da 'Tabela Completa todas Colunas'.", flush=True)
        return ""

    print(f"[SPOTFIRE CDP] Visual alvo identificado: '{target_data_cell.get('tableTitle')}' (ID: {target_data_cell.get('tableId')})", flush=True)

    # Garante que nenhum popup, tooltip ou menu anterior esteja aberto
    client.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', 'windowsVirtualKeyCode': 27})
    client.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'windowsVirtualKeyCode': 27})
    time.sleep(0.4)

    # Dispara o menu de contexto diretamente no container tabular da Tabela Completa
    print("[SPOTFIRE CDP] Acionando menu de contexto na Tabela Completa...", flush=True)
    menu_open = False
    for attempt in range(1, 4):
        trigger_res = client.evaluate('''(() => {
            const $ = window.jQuery || window.$;
            const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
            const table = visuals.find(v => {
                const title = (v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || '';
                const low = title.toLowerCase();
                return low.includes('tabela completa') || low.includes('todas colunas');
            });
            if (!table) return { success: false, reason: "Tabela Completa não encontrada" };

            const tabularContent = table.querySelector('.sf-element-tabular-content') || table;
            const r = tabularContent.getBoundingClientRect();
            const clientX = Math.round(r.left + Math.min(150, r.width / 2));
            const clientY = Math.round(r.top + Math.min(50, r.height / 2));

            if ($) {
                $(tabularContent).trigger($.Event('contextmenu', { clientX, clientY, pageX: clientX, pageY: clientY }));
            } else {
                tabularContent.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, view: window, clientX, clientY, button: 2 }));
            }
            return {
                success: true,
                tableId: table.id,
                tableTitle: (table.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || '',
                tabularId: tabularContent.id,
                x: clientX,
                y: clientY
            };
        })()''')

        if trigger_res and trigger_res.get("success"):
            print(f"[SPOTFIRE CDP] Menu disparado na visualização '{trigger_res.get('tableTitle')}' (ID: {trigger_res.get('tableId')}, Tabular: {trigger_res.get('tabularId')}) em ({trigger_res.get('x')}, {trigger_res.get('y')})", flush=True)

        time.sleep(0.8)

        menu_open = client.evaluate('''(() => {
            const allEls = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
            return allEls.some(el => (el.innerText || '').trim().toLowerCase() === 'export');
        })()''')

        if menu_open:
            print("[SPOTFIRE CDP OK] Menu de contexto aberto com opção 'Export' confirmada na Tabela Completa!", flush=True)
            break

        # Fallback nativo CDP na célula exata da Tabela Completa se necessário
        print(f"[SPOTFIRE CDP RETRY] Menu não abriu na tentativa {attempt}. Disparando clique físico com botão direito via CDP na célula da Tabela Completa...", flush=True)
        client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": target_data_cell["x"], "y": target_data_cell["y"], "button": "right", "clickCount": 1})
        client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": target_data_cell["x"], "y": target_data_cell["y"], "button": "right", "clickCount": 1})
        time.sleep(0.8)

    # Re-aplica permissões de download imediatamente antes do clique de exportação
    for method in ["Browser.setDownloadBehavior", "Page.setDownloadBehavior"]:
        try:
            client.call(method, {
                "behavior": "allow",
                "downloadPath": DOWNLOADS_DIR,
                "eventsEnabled": True
            })
        except Exception:
            pass

    print("[SPOTFIRE CDP] Acionando Export -> Export table...", flush=True)
    click_res = client.evaluate('''
    (async () => {
        const delay = ms => new Promise(r => setTimeout(r, ms));
        const allEls = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
        const exportItem = allEls.find(el => (el.innerText || '').trim().toLowerCase() === 'export');
        if (!exportItem) return { error: "Item Export não encontrado no menu de contexto" };

        const rExp = exportItem.getBoundingClientRect();
        const expX = Math.round(rExp.left + rExp.width / 2);
        const expY = Math.round(rExp.top + rExp.height / 2);

        const opts = { bubbles: true, cancelable: true, view: window, clientX: expX, clientY: expY, button: 0 };
        exportItem.dispatchEvent(new MouseEvent('mouseenter', opts));
        exportItem.dispatchEvent(new MouseEvent('mouseover', opts));
        exportItem.dispatchEvent(new MouseEvent('mousedown', opts));
        exportItem.dispatchEvent(new MouseEvent('mouseup', opts));
        exportItem.dispatchEvent(new MouseEvent('click', opts));
        await delay(1200);

        const allSub = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
        const exportTableItem = allSub.find(el => (el.innerText || '').trim().toLowerCase() === 'export table');
        if (!exportTableItem) return { error: "Item Export table não encontrado no submenu" };

        const rTable = exportTableItem.getBoundingClientRect();
        const tblX = Math.round(rTable.left + rTable.width / 2);
        const tblY = Math.round(rTable.top + rTable.height / 2);

        const subOpts = { bubbles: true, cancelable: true, view: window, clientX: tblX, clientY: tblY, button: 0 };
        exportTableItem.dispatchEvent(new MouseEvent('mouseenter', subOpts));
        exportTableItem.dispatchEvent(new MouseEvent('mouseover', subOpts));
        exportTableItem.dispatchEvent(new MouseEvent('mousedown', subOpts));
        exportTableItem.dispatchEvent(new MouseEvent('mouseup', subOpts));
        exportTableItem.dispatchEvent(new MouseEvent('click', subOpts));

        return { success: true, x: tblX, y: tblY };
    })()
    ''')

    if not click_res or not click_res.get("success"):
        print(f"[SPOTFIRE CDP WARN] Falha ao acionar Export Table: {click_res}", flush=True)
        client.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', 'windowsVirtualKeyCode': 27})
        client.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'windowsVirtualKeyCode': 27})
        return ""

    # =========================================================================
    # MONITORAMENTO EM DUAS FASES:
    # FASE 1: Acompanhar o Modal do Spotfire ('Exporting data...', 'Exporting rows...')
    # FASE 2: Acompanhar a gravação do arquivo pelo navegador (.crdownload e estabilidade)
    # =========================================================================
    print("[SPOTFIRE CDP] Iniciando monitoramento em duas fases da exportação nativa do Spotfire...", flush=True)
    start_wait = time.time()
    last_activity_time = time.time()
    last_reported_rows = -1
    modal_seen = False
    downloaded_file = ""
    last_size = -1
    stable_cycles = 0

    max_inactivity_timeout = 90.0  # Timeout apenas se ficar 90s sem qualquer sinal de progresso
    overall_timeout = 360.0 if all_months else 240.0

    while time.time() - start_wait < overall_timeout:
        # FASE 1: Checa se o modal de exportação do Spotfire está ativo na tela
        modal_status = client.evaluate(r'''(() => {
            const dialog = document.querySelector('.sfx_progress-dialog_1130, .sfx_centralizer_1131, [class*="progress-dialog"]');
            if (dialog) {
                const text = (dialog.innerText || '');
                const match = text.match(/([\d\.,]+)\s+rows\s+exported/i);
                const rawRows = match ? match[1].replace(/\./g, '').replace(/,/g, '') : "0";
                const rows = parseInt(rawRows, 10) || 0;
                const shortText = match ? match[0] : 'Exporting rows...';
                return { active: true, text: shortText, rows };
            }
            return { active: false };
        })()''')

        if modal_status and modal_status.get("active"):
            modal_seen = True
            rows_now = modal_status.get("rows", 0)
            if rows_now != last_reported_rows or (int(time.time() - start_wait) % 5 == 0):
                print(f"[SPOTFIRE CDP EXPORT MODAL] {modal_status.get('text', 'Exporting...')} ({rows_now} linhas geradas no servidor)", flush=True)
                last_reported_rows = rows_now
            # Reseta o temporizador de inatividade enquanto o servidor do Spotfire estiver ativamente trabalhando
            last_activity_time = time.time()
        else:
            if modal_seen and last_reported_rows >= 0:
                print(f"[SPOTFIRE CDP EXPORT MODAL] Modal de exportação do Spotfire concluído! Servidor liberou o arquivo ({last_reported_rows} linhas). Aguardando download...", flush=True)
                last_reported_rows = -2  # Marcador para não repetir o log

        # FASE 2: Checa se há arquivos em DOWNLOADS_DIR ou na pasta Downloads do Usuário
        cr_downloads = []
        completed_candidates = []

        # 1. Pasta dedicada local
        if os.path.exists(DOWNLOADS_DIR):
            for f in os.listdir(DOWNLOADS_DIR):
                p = os.path.join(DOWNLOADS_DIR, f)
                if f.endswith('.crdownload'):
                    cr_downloads.append(p)
                elif f.endswith('.tsv') or f.endswith('.txt') or f.endswith('.csv'):
                    completed_candidates.append(p)

        # 2. Pasta Downloads do Usuário (onde o Chrome grava por padrão no Windows)
        if os.path.exists(USER_DOWNLOADS_DIR):
            for f in os.listdir(USER_DOWNLOADS_DIR):
                f_low = f.lower()
                if not ('scanner' in f_low or 'tabela completa' in f_low):
                    continue
                p = os.path.join(USER_DOWNLOADS_DIR, f)
                try:
                    mtime = os.path.getmtime(p)
                except Exception:
                    continue
                # Apenas arquivos criados ou modificados neste ciclo (com margem de 15 segundos)
                if mtime < start_wait - 15:
                    continue

                if f.endswith('.crdownload'):
                    cr_downloads.append(p)
                elif f.endswith('.tsv') or f.endswith('.txt') or f.endswith('.csv'):
                    completed_candidates.append(p)

        if cr_downloads:
            # Download do navegador em andamento ativo
            cr_path = cr_downloads[0]
            try:
                cr_sz = round(os.path.getsize(cr_path) / 1024, 1)
                last_activity_time = time.time()
                if int(time.time() - start_wait) % 3 == 0:
                    print(f"[SPOTFIRE CDP DOWNLOAD] Transferindo arquivo pelo navegador ({os.path.basename(cr_path)}: {cr_sz} KB)...", flush=True)
            except Exception:
                pass

        if completed_candidates and not cr_downloads:
            # Ordena pelo mtime mais recente
            completed_candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
            candidate = completed_candidates[0]
            try:
                curr_size = os.path.getsize(candidate)
                if curr_size > 1000:
                    if curr_size == last_size:
                        stable_cycles += 1
                        if stable_cycles >= 3:  # 3 ciclos consecutivos de estabilidade (3 segundos sem alteração de bytes)
                            # Se o arquivo foi capturado na pasta Downloads do Usuário, transfere para DOWNLOADS_DIR
                            if os.path.dirname(os.path.abspath(candidate)) == os.path.abspath(USER_DOWNLOADS_DIR):
                                dest_path = os.path.join(DOWNLOADS_DIR, os.path.basename(candidate))
                                shutil.copy2(candidate, dest_path)
                                print(f"[SPOTFIRE CDP DOWNLOAD] Arquivo capturado da pasta Downloads do usuário e transferido para workspace: {os.path.basename(candidate)}", flush=True)
                                try:
                                    os.remove(candidate)
                                except Exception:
                                    pass
                                downloaded_file = dest_path
                            else:
                                downloaded_file = candidate
                            break
                    else:
                        stable_cycles = 0
                        last_size = curr_size
                        last_activity_time = time.time()
            except Exception:
                pass

        # Verificação de timeout por inatividade
        if time.time() - last_activity_time > max_inactivity_timeout:
            print(f"[SPOTFIRE CDP TIMEOUT] Inatividade excedida ({max_inactivity_timeout}s sem respostas do modal ou download).", flush=True)
            break

        time.sleep(1.0)

    if downloaded_file:
        sz_mb = round(os.path.getsize(downloaded_file) / (1024 * 1024), 2)
        elapsed_total = round(time.time() - start_wait, 1)
        print(f"[SPOTFIRE CDP OK] Download concluído com sucesso: {os.path.basename(downloaded_file)} ({sz_mb} MB) em {elapsed_total}s!", flush=True)

        # Validação pós-download da Tabela Completa (rejeita com bloqueio arquivos incorretos como 'Deslocamentos')
        try:
            filename = os.path.basename(downloaded_file)
            sample_df = pd.read_csv(downloaded_file, encoding='utf-16', sep='\t', nrows=50, low_memory=False)
            cols = [str(c).strip() for c in sample_df.columns]
            cols_lower = [c.lower() for c in cols]

            # A Tabela Completa DEVE conter a coluna 'Equipe', 'Data Referência' e ter mais de 20 colunas (~98 colunas)
            is_deslocamentos = "deslocamento" in filename.lower() or any("deslocamento" in c for c in cols_lower[:5])
            has_equipe = any("equipe" in c for c in cols_lower)
            has_data_ref = any("data" in c for c in cols_lower)

            if is_deslocamentos or len(cols) < 20 or not has_equipe:
                print(f"[SPOTFIRE CDP ERROR] BLOQUEIO CRÍTICO: Arquivo baixado incorreto '{filename}' com {len(cols)} colunas! Esperado 'Tabela Completa todas Colunas' com ~98 colunas. Amostra de colunas: {cols[:5]}", flush=True)
                try:
                    os.remove(downloaded_file)
                except Exception:
                    pass
                return ""

            print(f"[SPOTFIRE CDP OK] Arquivo validado com sucesso como 'Tabela Completa todas Colunas' ({len(cols)} colunas identificadas)!", flush=True)

            date_col = next((c for c in sample_df.columns if 'data' in c.lower() or 'refer' in c.lower()), sample_df.columns[0])
            sample_dates = sample_df[date_col].dropna().unique().tolist()
            print(f"[SPOTFIRE CDP POST-CHECK] Amostra de datas no arquivo exportado ({date_col}): {sample_dates[:5]}", flush=True)
            if not all_months and sample_dates:
                for sd in sample_dates[:10]:
                    fmt = detect_date_format_from_series(pd.Series([sd]))
                    iso_d = format_date_str(sd, col_format=fmt)
                    if iso_d and len(iso_d) == 10:
                        y_val, m_val = int(iso_d[:4]), int(iso_d[5:7])
                        if y_val != int(target_year) or m_val != target_month_idx:
                            print(f"[SPOTFIRE CDP POST-CHECK WARN] Data divergente detectada no arquivo: {sd} (ISO: {iso_d}), esperado {target_month_idx:02d}/{target_year}", flush=True)
        except Exception as check_err:
            print(f"[SPOTFIRE CDP POST-CHECK WARN] Leitura preliminar de verificação: {check_err}", flush=True)
    else:
        print("[SPOTFIRE CDP TIMEOUT] Tempo limite excedido aguardando conclusão do arquivo do Spotfire.", flush=True)

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
        prune_old_user_downloads("Scanner 5.0", max_keep=3)

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
