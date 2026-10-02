"""
Coletor de Dados Automatizado do TIBCO Spotfire - Análise Priorizador (ENEL SP)
Módulo de Extração de Ordens Críticas de Grande Interrupção (Aba ANALISTAS).

Utiliza Chrome DevTools Protocol (CDP) via WebSocket local (porta 9222):
1. Conecta-se à aba ativa do Priorizador no Edge / Chrome corporativo.
2. Navega para a URL oficial da análise /SP/COD/Priorizador.
3. Aguarda renderização e ausência total de spinners/overlays.
4. Garante a seleção da aba 'ANALISTAS'.
5. Localiza a visualização 'GRANDES INTERRUPÇÕES (utilize os filtros de CI e tempo):'.
6. Aciona exportação nativa via menu de contexto ('Export table') sem alterar filtros.
7. Lê os dados brutos com Pandas (25 colunas), normaliza e envia para priorizador_manager.
8. Limpa o arquivo temporário baixado no disco.
"""

import os
import sys
import json
import time
import re
import urllib.request
import threading
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

try:
    import websocket
except ImportError:
    websocket = None

import pandas as pd

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
PRIORIZADOR_URL = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Priorizador&waid=imNNdJ3J-0O6OSAz4Fszo-240327d640x8wg&wavid=0"
PRIORIZADOR_BASE_URL = "http://elabziplra00.enelint.global:8090/spotfire/wp/analysis?file=/SP/COD/Priorizador"
SPOTFIRE_DOMAIN = "elabziplra00.enelint.global"

_PRIORIZADOR_LOCK = threading.Lock()

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOADS_DIR = os.path.join(WORKSPACE_DIR, "temp_spotfire_downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


def listar_alvos_cdp():
    """Consulta os alvos abertos no navegador via endpoint HTTP do CDP."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except Exception:
        return []


def localizar_aba_priorizador(criar_se_nao_existir=True):
    """Localiza ou abre a aba do Priorizador no navegador."""
    try:
        from cdp_browser_manager import garantir_navegador_cdp_ativo
        garantir_navegador_cdp_ativo()
    except Exception:
        pass

    targets = listar_alvos_cdp()
    if not targets:
        return None

    # 1. Prioriza aba que já contenha 'priorizador' no título ou URL
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if 'priorizador' in t_title or 'priorizador' in t_url:
                return t

    # 2. Em seguida, busca qualquer aba do Spotfire
    for t in targets:
        if t.get('type') == 'page':
            t_url = (t.get('url') or '').lower()
            t_title = (t.get('title') or '').lower()
            if SPOTFIRE_DOMAIN in t_url or 'spotfire' in t_url:
                return t

    # 3. Cria nova aba se solicitado
    if criar_se_nao_existir:
        try:
            target_open_url = urllib.parse.quote(PRIORIZADOR_URL, safe=':/?=&')
            create_url = f"http://{CDP_HOST}:{CDP_PORT}/json/new?{target_open_url}"
            req = urllib.request.Request(create_url, method='PUT')
            with urllib.request.urlopen(req, timeout=5) as resp:
                new_tab = json.loads(resp.read().decode('utf-8'))
                time.sleep(4.0)
                return new_tab
        except Exception as e:
            print(f"[PRIORIZADOR CDP] Erro ao abrir nova aba do Priorizador: {e}", flush=True)

    return None


class PriorizadorCDPClient:
    """Cliente WebSocket minimalista e resiliente para o Chrome DevTools Protocol."""
    def __init__(self, ws_url):
        self.ws_url = ws_url
        self.ws = None
        self.msg_id = 0

    def connect(self):
        if websocket is None:
            raise RuntimeError("Módulo 'websocket-client' não instalado.")
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
        """Executa código JavaScript dentro do contexto da página."""
        res = self.call("Runtime.evaluate", {
            "expression": js_code,
            "returnByValue": return_by_value,
            "awaitPromise": True
        }, timeout=timeout)
        val = res.get("result", {}).get("value")
        if val is None and "exceptionDetails" in res:
            print(f"[PRIORIZADOR JS EXCEPTION] {res['exceptionDetails']}", flush=True)
        return val


def tentar_autenticacao_spotfire(client) -> bool:
    """Reutiliza autenticação automática Enel DPAPI caso caia na tela corporativa de login."""
    try:
        is_login = client.evaluate("window.location.href.includes('/login.html') || !!document.querySelector('input[name=\"username\"]')")
        if not is_login:
            return True

        print("[PRIORIZADOR CDP] Tela de login do Spotfire detectada. Autenticando com credenciais corporativas salvas...", flush=True)
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
        tmp = os.path.join(WORKSPACE_DIR, "scratch", "tmp_login_prio.db")
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

        for _ in range(12):
            time.sleep(2)
            u = client.evaluate("window.location.href") or ""
            if "analysis" in u and "login.html" not in u:
                print("[PRIORIZADOR CDP OK] Autenticação realizada com sucesso!", flush=True)
                time.sleep(4)
                return True
        return False
    except Exception as e:
        print(f"[PRIORIZADOR CDP LOGIN ERROR] {e}", flush=True)
        return False


def aguardar_spotfire_idle(client, timeout=45, comfort_buffer_seconds=6, step_label="Barreira Idle"):
    """Aguarda ausência de spinners, indicadores de ocupado e consolidação do DOM."""
    start_t = time.time()
    while time.time() - start_t < timeout:
        busy_info = client.evaluate('''(() => {
            if (document.readyState !== 'complete') return { busy: true, reason: "document.readyState != complete" };
            const busySelectors = '.sf-element-busy, .sfc-busy-indicator, .sfc-loading-spinner, .spotfire-busy, .sf-busy, .ProgressOverlay, [sf-busy="true"]';
            const busyEls = Array.from(document.querySelectorAll(busySelectors)).filter(el => (el.offsetWidth > 0 || el.offsetHeight > 0));
            if (busyEls.length > 0) return { busy: true, count: busyEls.length };
            return { busy: false };
        })()''')

        if not busy_info or not busy_info.get("busy"):
            break
        time.sleep(1.0)

    if comfort_buffer_seconds > 0:
        time.sleep(comfort_buffer_seconds)


def extrair_arquivo_priorizador_via_cdp(client) -> str:
    """
    Executa a sequência de extração da tabela 'GRANDES INTERRUPÇÕES' na aba 'ANALISTAS':
    1. Garante que a página do Priorizador esteja ativa e renderizada.
    2. Clica na aba 'ANALISTAS'.
    3. Aguarda renderização da tabela 'GRANDES INTERRUPÇÕES (utilize os filtros de CI e tempo):'.
    4. Aciona botão direito -> Export -> Export table.
    5. Monitora download inteligente no diretório temp_spotfire_downloads.
    """
    # 1. Configura diretório de download silencioso
    client.call("Page.setDownloadBehavior", {
        "behavior": "allow",
        "downloadPath": DOWNLOADS_DIR
    })

    # Limpa arquivos prévios
    for f in os.listdir(DOWNLOADS_DIR):
        try:
            os.remove(os.path.join(DOWNLOADS_DIR, f))
        except Exception:
            pass

    # 2. Verifica se a análise está pronta na aba ativa ou navega
    is_ready_now = client.evaluate('''(() => {
        const title = (document.title || '').toLowerCase();
        const url = (window.location.href || '').toLowerCase();
        const hasTabs = document.querySelectorAll('.sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab, [role="tab"]').length > 0;
        const hasVisuals = document.querySelectorAll('.sf-element-visual').length > 0;
        const isPriorizador = title.includes('priorizador') || url.includes('priorizador');
        return (hasTabs || hasVisuals) && isPriorizador;
    })()''')

    if not is_ready_now:
        print(f"[PRIORIZADOR CDP] Navegando aba para URL oficial do Priorizador...", flush=True)
        client.call("Page.navigate", {"url": PRIORIZADOR_URL})
        time.sleep(5.0)

    # Aguarda carregamento completo
    start_load = time.time()
    while time.time() - start_load < 60:
        time.sleep(2.0)
        status = client.evaluate('''(() => {
            if (document.readyState !== 'complete') return { ready: false };
            const isLogin = !!document.querySelector('input[name="username"]');
            if (isLogin) return { ready: true, isLogin: true };
            const tabs = document.querySelectorAll('.sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab, [role="tab"]').length;
            const visuals = document.querySelectorAll('.sf-element-visual').length;
            if (tabs > 0 || visuals > 0) return { ready: true };
            return { ready: false };
        })()''')

        if status and status.get("ready"):
            if status.get("isLogin"):
                tentar_autenticacao_spotfire(client)
            else:
                break

    aguardar_spotfire_idle(client, timeout=40, comfort_buffer_seconds=5, step_label="Carregamento Inicial")

    # 3. Garante que a aba 'ANALISTAS' esteja selecionada
    print("[PRIORIZADOR CDP] Selecionando aba 'ANALISTAS'...", flush=True)
    tab_click_res = client.evaluate('''(() => {
        const tabs = Array.from(document.querySelectorAll('.sf-element-page-tab, .sfx_page-tab, .sfc-navigation-tab, [role="tab"]'));
        const tab = tabs.find(t => (t.innerText || '').trim().toUpperCase() === 'ANALISTAS');
        if (tab) {
            tab.click();
            return { success: true, text: tab.innerText.trim() };
        }
        return { success: false, availableTabs: tabs.map(t => (t.innerText || '').trim()) };
    })()''')

    if tab_click_res and tab_click_res.get("success"):
        print(f"[PRIORIZADOR CDP OK] Aba '{tab_click_res['text']}' selecionada com sucesso!", flush=True)
    else:
        print(f"[PRIORIZADOR CDP WARN] Aba 'ANALISTAS' não localizada diretamente. Tabs disponíveis: {tab_click_res.get('availableTabs') if tab_click_res else 'Nenhuma'}", flush=True)

    aguardar_spotfire_idle(client, timeout=30, comfort_buffer_seconds=5, step_label="Pós Seleção Aba ANALISTAS")

    # 4. Localiza a visualização 'GRANDES INTERRUPÇÕES'
    print("[PRIORIZADOR CDP] Localizando visualização 'GRANDES INTERRUPÇÕES'...", flush=True)
    target_visual = client.evaluate('''(() => {
        const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
        const target = visuals.find(v => {
            const titleEl = v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title');
            const t = (titleEl ? titleEl.innerText : v.innerText || '').toLowerCase();
            return t.includes('grandes interrup') || t.includes('grandes interrupções');
        });

        if (!target) return null;

        const tabular = target.querySelector('.sf-element-tabular-content') || target;
        const r = tabular.getBoundingClientRect();
        return {
            title: (target.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title') || {}).innerText || 'GRANDES INTERRUPÇÕES',
            x: Math.round(r.left + Math.min(180, r.width / 2)),
            y: Math.round(r.top + Math.min(60, r.height / 2))
        };
    })()''')

    if not target_visual:
        print("[PRIORIZADOR CDP ERROR] Visualização 'GRANDES INTERRUPÇÕES' não encontrada na aba ANALISTAS.", flush=True)
        return ""

    print(f"[PRIORIZADOR CDP OK] Visual localizado: '{target_visual['title']}' em ({target_visual['x']}, {target_visual['y']})", flush=True)

    # 5. Aciona botão direito (contextmenu) na tabela
    client.call('Input.dispatchKeyEvent', {'type': 'rawKeyDown', 'windowsVirtualKeyCode': 27})
    client.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'windowsVirtualKeyCode': 27})
    time.sleep(0.4)

    print("[PRIORIZADOR CDP] Disparando menu de contexto (botão direito) na tabela de Grandes Interrupções...", flush=True)
    client.evaluate(f'''(() => {{
        const visuals = Array.from(document.querySelectorAll('.sf-element-visual'));
        const target = visuals.find(v => {{
            const titleEl = v.querySelector('.sfc-visual-header, .sf-element-visual-title, .title, .Title');
            const t = (titleEl ? titleEl.innerText : v.innerText || '').toLowerCase();
            return t.includes('grandes interrup');
        }});
        if (!target) return;
        const tabular = target.querySelector('.sf-element-tabular-content') || target;
        const r = tabular.getBoundingClientRect();
        const clientX = {target_visual['x']};
        const clientY = {target_visual['y']};
        const $ = window.jQuery || window.$;
        if ($) {{
            $(tabular).trigger($.Event('contextmenu', {{ clientX, clientY, pageX: clientX, pageY: clientY }}));
        }} else {{
            tabular.dispatchEvent(new MouseEvent('contextmenu', {{ bubbles: true, cancelable: true, view: window, clientX, clientY, button: 2 }}));
        }}
    }})()''')

    time.sleep(0.8)

    # Fallback via CDP se menu não abriu
    menu_open = client.evaluate('''(() => {
        const allEls = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
        return allEls.some(el => (el.innerText || '').trim().toLowerCase() === 'export');
    })()''')

    if not menu_open:
        print("[PRIORIZADOR CDP RETRY] Disparando clique físico com botão direito via CDP...", flush=True)
        client.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": target_visual["x"], "y": target_visual["y"], "button": "right", "clickCount": 1})
        client.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": target_visual["x"], "y": target_visual["y"], "button": "right", "clickCount": 1})
        time.sleep(0.8)

    # 6. Clica em Export -> Export table
    print("[PRIORIZADOR CDP] Clicando em Export -> Export table...", flush=True)
    click_export_res = client.evaluate('''
    (async () => {
        const delay = ms => new Promise(r => setTimeout(r, ms));
        const allEls = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
        const exportItem = allEls.find(el => (el.innerText || '').trim().toLowerCase() === 'export');
        if (!exportItem) return { error: "Item Export não encontrado" };

        const rExp = exportItem.getBoundingClientRect();
        const opts = { bubbles: true, cancelable: true, view: window, clientX: Math.round(rExp.left + rExp.width / 2), clientY: Math.round(rExp.top + rExp.height / 2), button: 0 };
        exportItem.dispatchEvent(new MouseEvent('mouseenter', opts));
        exportItem.dispatchEvent(new MouseEvent('mouseover', opts));
        exportItem.dispatchEvent(new MouseEvent('click', opts));
        await delay(500);

        const subItems = Array.from(document.querySelectorAll('.contextMenuItem, .contextMenuItemLabel, .contextMenu *'));
        const tableItem = subItems.find(el => {
            const txt = (el.innerText || '').trim().toLowerCase();
            return txt === 'export table' || txt.includes('table');
        });

        if (!tableItem) return { error: "Opção Export table não encontrada no submenu" };

        const rTbl = tableItem.getBoundingClientRect();
        const optsTbl = { bubbles: true, cancelable: true, view: window, clientX: Math.round(rTbl.left + rTbl.width / 2), clientY: Math.round(rTbl.top + rTbl.height / 2), button: 0 };
        tableItem.dispatchEvent(new MouseEvent('mouseenter', optsTbl));
        tableItem.dispatchEvent(new MouseEvent('mouseover', optsTbl));
        tableItem.dispatchEvent(new MouseEvent('click', optsTbl));

        return { success: true };
    })()''')

    if not click_export_res or not click_export_res.get("success"):
        print(f"[PRIORIZADOR CDP WARN] Falha no acionamento do submenu de exportação: {click_export_res}", flush=True)

    # 7. Monitoramento Inteligente do Download
    print(f"[PRIORIZADOR CDP] Monitorando chegada do download na pasta '{DOWNLOADS_DIR}'...", flush=True)
    start_dl = time.time()
    downloaded_file = None

    while time.time() - start_dl < 45:
        time.sleep(1.0)
        files = os.listdir(DOWNLOADS_DIR)
        valid_files = [f for f in files if not f.endswith('.crdownload') and not f.endswith('.tmp') and os.path.getsize(os.path.join(DOWNLOADS_DIR, f)) > 0]
        if valid_files:
            # Garante que o tamanho estabilizou
            cand = os.path.join(DOWNLOADS_DIR, valid_files[0])
            size1 = os.path.getsize(cand)
            time.sleep(1.0)
            size2 = os.path.getsize(cand)
            if size1 == size2 and size1 > 50:
                downloaded_file = cand
                print(f"[PRIORIZADOR CDP OK] Download concluído com sucesso: {os.path.basename(downloaded_file)} ({size1:,} bytes)!", flush=True)
                break

    return downloaded_file or ""


def ler_arquivo_exportado(file_path: str) -> pd.DataFrame:
    """Lê o arquivo TSV/CSV/XLSX exportado do Spotfire tratando codificação UTF-16/UTF-8."""
    if not file_path or not os.path.exists(file_path):
        return pd.DataFrame()

    try:
        # Padrão Spotfire: TSV UTF-16
        return pd.read_csv(file_path, sep='\t', encoding='utf-16', dtype=str, on_bad_lines='skip')
    except Exception:
        pass

    try:
        # Fallback UTF-8 Tab
        return pd.read_csv(file_path, sep='\t', encoding='utf-8', dtype=str, on_bad_lines='skip')
    except Exception:
        pass

    try:
        # Fallback Latin-1 Tab
        return pd.read_csv(file_path, sep='\t', encoding='latin-1', dtype=str, on_bad_lines='skip')
    except Exception:
        pass

    try:
        # Fallback CSV vírgula/ponto-e-vírgula
        return pd.read_csv(file_path, sep=None, engine='python', dtype=str, on_bad_lines='skip')
    except Exception as e:
        print(f"[PRIORIZADOR PANDAS ERROR] Não foi possível ler o arquivo: {e}", flush=True)
        return pd.DataFrame()


def executar_ciclo_sincronizacao_priorizador(source_label="Robô CDP Automático") -> Dict[str, Any]:
    """
    Executa o ciclo completo de extração do Priorizador:
    1. Conecta ao Spotfire via CDP.
    2. Baixa a tabela GRANDES INTERRUPÇÕES da aba ANALISTAS.
    3. Normaliza e persiste através do priorizador_manager.
    4. Exclui o arquivo temporário.
    """
    if not _PRIORIZADOR_LOCK.acquire(blocking=False):
        print("[PRIORIZADOR CDP SKIPPED] Ciclo já em andamento. Ignorando requisição concorrente.", flush=True)
        return {"status": "warning", "message": "Ciclo de coleta já em andamento."}

    from priorizador_manager import priorizador_manager
    priorizador_manager.is_collecting = True

    downloaded_path = ""
    client = None
    try:
        tab = localizar_aba_priorizador(criar_se_nao_existir=True)
        if not tab:
            priorizador_manager.last_collect_status = "ERROR"
            return {"status": "error", "message": "Navegador com porta 9222 não acessível ou aba não encontrada."}

        ws_url = tab.get("webSocketDebuggerUrl")
        if not ws_url:
            priorizador_manager.last_collect_status = "ERROR"
            return {"status": "error", "message": "Aba encontrada não possui endpoint WebSocketDebuggerUrl."}

        client = PriorizadorCDPClient(ws_url)
        client.connect()

        downloaded_path = extrair_arquivo_priorizador_via_cdp(client)
        if not downloaded_path or not os.path.exists(downloaded_path):
            priorizador_manager.last_collect_status = "ERROR"
            return {"status": "error", "message": "Falha ao baixar arquivo da tabela 'GRANDES INTERRUPÇÕES'."}

        df = ler_arquivo_exportado(downloaded_path)
        print(f"[PRIORIZADOR CDP] Tabela carregada com {len(df)} linhas e {len(df.columns)} colunas.", flush=True)

        res = priorizador_manager.processar_dataframe_spotfire(df, source_label=source_label)
        return res

    except Exception as e:
        print(f"[PRIORIZADOR CDP EXCEPTION] {e}", flush=True)
        priorizador_manager.last_collect_status = "ERROR"
        return {"status": "error", "message": str(e)}

    finally:
        if downloaded_path and os.path.exists(downloaded_path):
            try:
                os.remove(downloaded_path)
            except Exception:
                pass
        if client:
            client.close()
        priorizador_manager.is_collecting = False
        _PRIORIZADOR_LOCK.release()


def priorizador_background_worker(interval_seconds=120, stop_event: Optional[threading.Event] = None):
    """
    Worker que roda em segundo plano a cada 2 a 3 minutos (padrão: 120s)
    para manter o painel de Ordens Críticas sempre atualizado.
    """
    if os.name != 'nt' or os.environ.get("VERCEL"):
        return

    print(f"[PRIORIZADOR WORKER] Motor de auto-captura do Priorizador Spotfire ATIVO (intervalo: {interval_seconds}s).", flush=True)

    # Espera 10 segundos antes do primeiro ciclo para estabilizar inicialização do servidor
    time.sleep(10.0)

    while True:
        if stop_event and stop_event.is_set():
            break

        try:
            from cluster_manager import cluster_manager
            if cluster_manager.is_feeding_database():
                print(f"[PRIORIZADOR WORKER] Disparando ciclo autônomo de Ordens Críticas...", flush=True)
                executar_ciclo_sincronizacao_priorizador(source_label="Auto-Worker Periódico CDP (120s)")
            else:
                print(f"[PRIORIZADOR WORKER SKIPPED] Máquina em STANDBY. Ciclo ignorado.", flush=True)
        except Exception as e:
            print(f"[PRIORIZADOR WORKER ERROR] {e}", flush=True)

        # Aguarda o intervalo respeitando stop_event
        sleep_elapsed = 0
        while sleep_elapsed < interval_seconds:
            if stop_event and stop_event.is_set():
                break
            time.sleep(2.0)
            sleep_elapsed += 2
