"""
Coletor de Dados Automatizado do Portal BidTech - Visão Operacional (Checklists)
Módulo de Extração de Equipes, Status de Checklist e Reconciliação Forense com Equipes Brasil.

Utiliza Chrome DevTools Protocol (CDP) via WebSocket local (porta 9222):
1. Conecta-se à aba ativa da Visão Operacional BidTech (suite360.bidtech.com.br).
2. Valida e ajusta o campo de Data Operacional (input[type='date']) para o dia atual.
3. Extrai as 5 colunas operacionais:
   - Planejadas
   - Em checklist
   - Em operação
   - Retornadas
   - Bloqueadas
4. Extrai todos os campos por card: Equipe, Telefone, Base, Tipo Operacional, Turno,
   Motorista, Integrantes (com crachá L/M), Placa, Tipo de Veículo e Cronômetro de Operação.
5. Persiste no Supabase via UPSERT relacional (tabela 'bid_visao_operacional_records').
6. Alimenta o delivery_manager em memória para auditoria e cruzamento em tempo real (ONLINE x BID).
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
from datetime import datetime, timezone, timedelta

try:
    import websocket
except ImportError:
    websocket = None

from cdp_browser_manager import CDP_HOST, CDP_PORT, garantir_abas_operacionais

BR_TZ = timezone(timedelta(hours=-3))
BID_URL_SUBSTRING = "suite360.bidtech.com.br"

_BID_LOCK = threading.Lock()

_LAST_BID_SYNC_RESULT = {
    "status": "pending",
    "timestamp": None,
    "total_extracted": 0,
    "status_counts": {},
    "message": "Nenhum ciclo executado ainda"
}


_LAST_PAGE_RELOAD_TS = 0.0
_LAST_OPERATIONAL_DATE = None


def get_operational_date_str() -> str:
    """
    Retorna a data operacional atual (YYYY-MM-DD).
    Corte operacional pontualmente às 04:30 da manhã:
    - Das 00:00 às 04:30: pertence ao dia operacional anterior.
    - A partir das 04:31: pertence ao dia operacional atual.
    """
    now = datetime.now(BR_TZ)
    if now.hour < 4 or (now.hour == 4 and now.minute <= 30):
        return (now.date() - timedelta(days=1)).isoformat()
    return now.date().isoformat()


def _send_cdp(ws, method: str, params: dict = None, timeout: int = 15) -> dict:
    """Envia comando CDP via WebSocket e aguarda a resposta com o ID correspondente."""
    import random
    msg_id = random.randint(10000, 99999)
    payload = {"id": msg_id, "method": method}
    if params:
        payload["params"] = params
    ws.send(json.dumps(payload))
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            raw = ws.recv()
            data = json.loads(raw)
            if data.get("id") == msg_id:
                return data
        except Exception:
            break
    return {}


CLEAR_SEARCH_JS = """
(() => {
    const searchInput = document.querySelector('input[placeholder*="Código"], input[type="text"]');
    if (searchInput && searchInput.value) {
        try {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(searchInput, '');
            searchInput.dispatchEvent(new Event('input', { bubbles: true }));
            searchInput.dispatchEvent(new Event('change', { bubbles: true }));
            return { cleared: true, prev: searchInput.value };
        } catch(e) {
            searchInput.value = '';
            return { cleared: true, prev: '' };
        }
    }
    return { cleared: false };
})()
"""


def localizar_aba_bid():
    """Consulta os alvos abertos no navegador via CDP HTTP e localiza a aba do BidTech."""
    try:
        url = f"http://{CDP_HOST}:{CDP_PORT}/json"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=3) as resp:
            targets = json.loads(resp.read().decode('utf-8'))
            for t in targets:
                if t.get('type') == 'page':
                    t_url = (t.get('url') or '').lower()
                    t_title = (t.get('title') or '').lower()
                    if BID_URL_SUBSTRING in t_url or 'visão operacional' in t_title or 'visao-operacional' in t_url:
                        return t
    except Exception as e:
        print(f"[BID CDP] Erro ao consultar alvos CDP: {e}", flush=True)
    return None


DATE_CHECK_JS = """
(() => {
    const TARGET_DATE = "__TARGET_DATE__";
    const dateInput = document.querySelector("input[type='date']");
    if (dateInput && dateInput.value !== TARGET_DATE) {
        try {
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            nativeInputValueSetter.call(dateInput, TARGET_DATE);
            dateInput.dispatchEvent(new Event('input', { bubbles: true }));
            dateInput.dispatchEvent(new Event('change', { bubbles: true }));
            return { adjusted: true, current: dateInput.value };
        } catch(e) {
            dateInput.value = TARGET_DATE;
            return { adjusted: true, current: dateInput.value };
        }
    }
    return { adjusted: false, current: dateInput ? dateInput.value : null };
})()
"""

CLICK_ATUALIZAR_JS = """
(() => {
    const btn = document.querySelector('button[aria-label="Atualizar dashboard"]') || 
                Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Atualizar'));
    if (!btn) return { clicked: false, error: 'Button not found' };
    btn.click();
    return { clicked: true, disabled: btn.disabled };
})()
"""

CHECK_RELOAD_STATUS_JS = """
(() => {
    const btn = document.querySelector('button[aria-label="Atualizar dashboard"]') || 
                Array.from(document.querySelectorAll('button')).find(b => b.textContent && b.textContent.includes('Atualizar'));
    return {
        btnDisabled: btn ? btn.disabled : false
    };
})()
"""

CARDS_EXTRACTION_JS = """
(() => {
    const STATUS_MAP = {
        "Planejadas": "Planejada",
        "Em checklist": "Em Checklist",
        "Em operação": "Em Operação",
        "Retornadas": "Retornada",
        "Bloqueadas": "Bloqueada"
    };

    const colHeaders = Array.from(document.querySelectorAll("h3")).filter(h => 
        Object.keys(STATUS_MAP).includes(h.innerText.trim())
    );

    const extracted = [];
    const seenTeams = new Set();

    colHeaders.forEach(h => {
        const colTitle = h.innerText.trim();
        const statusBid = STATUS_MAP[colTitle] || colTitle;
        const colContainer = h.closest(".rounded-2xl") || h.parentElement.parentElement;
        const scrollArea = colContainer ? colContainer.querySelector(".overflow-auto, [class*='overflow']") : null;
        if (!scrollArea) return;

        const cards = Array.from(scrollArea.querySelectorAll("button"));

        cards.forEach(btn => {
            const lines = btn.innerText.split("\\n").map(l => l.trim()).filter(Boolean);
            if (!lines.length) return;

            // 1. Código da Equipe (ex: EML117, CML326, EVL301)
            const teamCodeEl = btn.querySelector("p.font-heading, p.font-semibold, p");
            let teamCode = teamCodeEl ? teamCodeEl.innerText.trim().toUpperCase() : lines[0].toUpperCase();
            teamCode = teamCode.replace(/[^A-Z0-9]/g, '');
            if (!teamCode || teamCode.length < 3) return;

            const dedupKey = teamCode + "_" + statusBid;
            if (seenTeams.has(dedupKey)) return;
            seenTeams.add(dedupKey);

            // 2. Telefone
            let phone = null;
            const phoneMatch = btn.innerText.match(/\\(\\d{2}\\)\\s*\\d{4,5}-\\d{4}/);
            if (phoneMatch) phone = phoneMatch[0];

            // 3. Badges (Base, Tipo Operacional, Turno)
            const badges = Array.from(btn.querySelectorAll("span.rounded-md")).map(s => s.innerText.trim());
            let base = null;
            let tipoOp = null;
            let turno = null;

            badges.forEach(b => {
                if (/^\\d{2}:\\d{2}$/.test(b)) {
                    turno = b;
                } else if (['L', 'M'].includes(b)) {
                    // Leader / Motorista badge
                } else if (['TMA', 'CORTE', 'RELIGA', 'NOVA LIGAÇÃO', 'LINHA VIVA', 'EMERGÊNCIA', 'COM', 'MIGRACAO', 'INSPECAO'].some(t => b.toUpperCase().includes(t))) {
                    tipoOp = b;
                } else if (['MONTE SANTO', 'ARICANDUVA', 'CATUMBI', 'SANTO ANDRÉ', 'CAJATI', 'FAGUNDES FILHO', 'VILA MEDEIROS', 'SUL', 'OESTE', 'LESTE', 'NORTE'].some(baseName => b.toUpperCase().includes(baseName))) {
                    base = b;
                } else if (!base && b.length > 3 && !['L', 'M'].includes(b)) {
                    base = b;
                }
            });

            // 4. Veículo e Placa
            let plate = null;
            let vehicleType = null;
            const plateMatch = btn.innerText.match(/([A-Z]{3}[0-9][A-Z0-9][0-9]{2})\\s*-\\s*([^\\n•]+)/i);
            if (plateMatch) {
                plate = plateMatch[1].toUpperCase();
                vehicleType = plateMatch[2].trim().toUpperCase();
            } else {
                const simplePlate = btn.innerText.match(/\\b[A-Z]{3}[0-9][A-Z0-9][0-9]{2}\\b/);
                if (simplePlate) plate = simplePlate[0].toUpperCase();
            }

            // 5. Componentes / Eletricistas / Motorista (Extração pura e robusta)
            const memberContainers = Array.from(btn.querySelectorAll("div")).filter(d => d.className && d.className.includes("space-y"));
            const memberDivs = memberContainers.flatMap(c => Array.from(c.children));
            const members = [];
            let driver = null;

            memberDivs.forEach(mc => {
                const pTags = Array.from(mc.querySelectorAll("p"));
                if (!pTags.length) return;
                const name = pTags[0] ? pTags[0].innerText.trim() : null;
                const role = pTags[1] ? pTags[1].innerText.trim() : "";
                if (name) {
                    const hasMotoristaBadge = Array.from(mc.querySelectorAll("span")).some(s => s.innerText.trim() === 'M');
                    const isDriver = hasMotoristaBadge || role.toUpperCase().includes("MOTORISTA") || role.toUpperCase().includes("PICK-UP") || role.toUpperCase().includes("CESTO");
                    if (isDriver && !driver) driver = name;
                    members.push({ name: name, role: role, is_driver: isDriver });
                }
            });

            if (!driver && members.length > 0) {
                driver = members[0].name;
            }

            // 6. Tempo de Operação / Checklist
            let timerLabel = null;
            let timerValue = null;
            const timerEl = btn.querySelector("p.font-mono, p.text-lg");
            if (timerEl) {
                timerValue = timerEl.innerText.trim();
                const timerLabelEl = timerEl.parentElement ? timerEl.parentElement.querySelector("div") : null;
                if (timerLabelEl) timerLabel = timerLabelEl.innerText.trim();
            }

            extracted.push({
                team_code: teamCode,
                status_bid: statusBid,
                col_title: colTitle,
                base: base,
                tipo_operacional: tipoOp,
                turno: turno,
                driver: driver,
                members: members,
                phone: phone,
                plate: plate,
                vehicle_type: vehicleType,
                timer_label: timerLabel,
                timer_value: timerValue
            });
        });
    });

    return {
        total_extracted: extracted.length,
        status_counts: extracted.reduce((acc, e) => { acc[e.status_bid] = (acc[e.status_bid] || 0) + 1; return acc; }, {}),
        records: extracted
    };
})()
"""


def extrair_cards_bid_visao_operacional():
    """
    Conecta via CDP WebSocket na aba do BidTech, verifica necessidade de F5
    (na virada das 04:31 ou a cada 1 hora de ciclo contínuo), limpa campos de busca,
    ajusta a data para a data operacional e extrai todos os cards das 5 colunas.
    """
    global _LAST_PAGE_RELOAD_TS, _LAST_OPERATIONAL_DATE
    if websocket is None:
        return {"status": "error", "message": "Módulo 'websocket-client' não instalado.", "records": []}

    target = localizar_aba_bid()
    if not target:
        garantir_abas_operacionais()
        time.sleep(2)
        target = localizar_aba_bid()

    if not target:
        return {"status": "error", "message": "Aba do portal BidTech (Visão Operacional) não encontrada no navegador.", "records": []}

    ws_url = target.get('webSocketDebuggerUrl')
    if not ws_url:
        return {"status": "error", "message": "webSocketDebuggerUrl ausente para a aba BidTech.", "records": []}

    target_date = get_operational_date_str()
    now_ts = time.time()

    # Verifica se precisa de F5 (Hard Reload da página):
    # 1. Primeiro ciclo de execução (_LAST_PAGE_RELOAD_TS == 0.0)
    # 2. Virada de data operacional após 04:31 (_LAST_OPERATIONAL_DATE != target_date)
    # 3. A cada 1 hora (3600 segundos) de operação contínua
    needs_f5 = False
    reason_f5 = ""
    if _LAST_PAGE_RELOAD_TS == 0.0:
        needs_f5 = True
        reason_f5 = "Inicialização / Primeiro Ciclo do Coletor CDP"
    elif _LAST_OPERATIONAL_DATE is not None and target_date != _LAST_OPERATIONAL_DATE:
        needs_f5 = True
        reason_f5 = f"Virada de Data Operacional ({_LAST_OPERATIONAL_DATE} -> {target_date} após 04:31)"
    elif (now_ts - _LAST_PAGE_RELOAD_TS) >= 3600:
        elapsed_min = int((now_ts - _LAST_PAGE_RELOAD_TS) / 60)
        needs_f5 = True
        reason_f5 = f"Ciclo Horário de Limpeza e Atualização F5 ({elapsed_min} min decorridos)"

    if needs_f5:
        print(f"[BID CDP] Forçando recarregamento 100% da página (F5): {reason_f5}...", flush=True)
        try:
            ws_reload = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)
            _send_cdp(ws_reload, "Page.reload", {"ignoreCache": True})
            ws_reload.close()
        except Exception as rel_err:
            print(f"[BID CDP] Aviso ao disparar Page.reload: {rel_err}", flush=True)
        time.sleep(7.0)
        _LAST_PAGE_RELOAD_TS = time.time()
        _LAST_OPERATIONAL_DATE = target_date

        # Re-localiza a aba caso o webSocketDebuggerUrl tenha sido alterado
        target_refreshed = localizar_aba_bid()
        if target_refreshed and target_refreshed.get('webSocketDebuggerUrl'):
            ws_url = target_refreshed.get('webSocketDebuggerUrl')
    else:
        _LAST_OPERATIONAL_DATE = target_date

    ws = None
    try:
        ws = websocket.create_connection(ws_url, timeout=15, suppress_origin=True)

        # Passo 1: Limpa qualquer filtro de texto no campo de busca (evita tela filtrada/vazia)
        resp_clear = _send_cdp(ws, "Runtime.evaluate", {"expression": CLEAR_SEARCH_JS, "returnByValue": True})
        clear_val = resp_clear.get("result", {}).get("result", {}).get("value", {})
        if clear_val.get("cleared"):
            print("[BID CDP] Campo de busca do dashboard continha filtro e foi limpo automaticamente.", flush=True)
            time.sleep(1.0)

        # Passo 2: Verifica e ajusta a data operacional no seletor
        date_eval_js = DATE_CHECK_JS.replace("__TARGET_DATE__", target_date)
        resp_date = _send_cdp(ws, "Runtime.evaluate", {"expression": date_eval_js, "returnByValue": True})
        date_val = resp_date.get("result", {}).get("result", {}).get("value", {})
        if date_val.get("adjusted"):
            time.sleep(1.0)

        # Passo 3: Clica no botão "Atualizar" para forçar refresh dos dados no portal antes de coletar
        try:
            resp_click = _send_cdp(ws, "Runtime.evaluate", {"expression": CLICK_ATUALIZAR_JS, "returnByValue": True})
            click_val = resp_click.get("result", {}).get("result", {}).get("value", {})
            if click_val.get("clicked"):
                # Aguarda até o botão voltar ao estado ativo/não-desabilitado (máx 12s)
                time.sleep(1.0)
                for _ in range(12):
                    resp_chk = _send_cdp(ws, "Runtime.evaluate", {"expression": CHECK_RELOAD_STATUS_JS, "returnByValue": True})
                    chk_val = resp_chk.get("result", {}).get("result", {}).get("value", {})
                    if not chk_val.get("btnDisabled"):
                        break
                    time.sleep(0.8)
                time.sleep(0.6)
        except Exception as click_err:
            print(f"[BID CDP] Aviso ao clicar em Atualizar: {click_err}", flush=True)

        # Passo 4: Re-verifica se a data continua correta e garante busca limpa
        _send_cdp(ws, "Runtime.evaluate", {"expression": CLEAR_SEARCH_JS, "returnByValue": True})
        resp_date2 = _send_cdp(ws, "Runtime.evaluate", {"expression": date_eval_js, "returnByValue": True})
        date_val2 = resp_date2.get("result", {}).get("result", {}).get("value", {})
        if date_val2.get("adjusted"):
            time.sleep(1.0)

        # Passo 5: Extrai todos os cards das 5 colunas
        resp_cards = _send_cdp(ws, "Runtime.evaluate", {"expression": CARDS_EXTRACTION_JS, "returnByValue": True})
        cards_val = resp_cards.get("result", {}).get("result", {}).get("value", {})

        records = cards_val.get("records", [])
        now_iso = datetime.now(BR_TZ).isoformat()

        for r in records:
            r["date_ref"] = target_date
            r["captured_at"] = now_iso

        status_counts = cards_val.get("status_counts", {})

        return {
            "status": "success",
            "date_ref": target_date,
            "total_extracted": len(records),
            "status_counts": status_counts,
            "records": records,
            "captured_at": now_iso
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Falha na comunicação CDP com a aba BidTech: {str(e)}",
            "records": []
        }
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass


def executar_ciclo_sincronizacao_bid(source_label: str = "Rotina Automática (2 min)"):
    """
    Executa o ciclo completo de coleta da Visão Operacional Bid:
    1. Extrai cards via CDP
    2. Persiste no Supabase
    3. Remove registros fantasmas no Supabase (pruning)
    4. Alimenta o delivery_manager em memória
    """
    global _LAST_BID_SYNC_RESULT
    if not _BID_LOCK.acquire(blocking=False):
        ts = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
        print(f"[{ts}] [CDP BIDTECH] Ciclo anterior ainda em andamento. Ignorando novo disparo ({source_label}).", flush=True)
        return {"status": "busy", "message": "Ciclo anterior do BidTech em andamento"}

    from delivery_manager import delivery_manager
    from supabase_client import push_bid_records_to_supabase

    start_t = time.time()
    ts_start = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
    print(f"\n[{ts_start}] [CDP BIDTECH] >>> INICIANDO CICLO DE COLETA: Visão Operacional ({source_label})...", flush=True)

    try:
        result = extrair_cards_bid_visao_operacional()

        if result.get("status") == "success":
            records = result.get("records", [])
            date_ref = result.get("date_ref")

            # 1. Envia ao Supabase (upsert)
            sb_res = push_bid_records_to_supabase(records, date_ref)

            # 2. Saneamento: remove registros fantasmas que não existem na extração legítima
            if len(records) > 0:
                try:
                    from supabase_client import prune_stale_bid_records
                    valid_codes = [r.get("team_code") for r in records if r.get("team_code")]
                    prune_stale_bid_records(date_ref, valid_codes)
                except Exception as prune_err:
                    print(f"[BID CDP] Aviso ao purgar registros fantasmas: {prune_err}", flush=True)

            # 3. Atualiza o delivery_manager em memória
            delivery_manager.process_raw_bid_records(records, date_ref)

            # 4. Notifica o monitor de saúde no Supabase
            try:
                from supabase_client import update_engine_health
                update_engine_health(
                    "bid_cdp_collector", "OPERATIONAL", is_running=True,
                    error_type="NONE", last_error=None,
                    records_count=len(records),
                    engine_label="Robô CDP BidTech (Checklist Operacional)",
                    details_json={
                        "date_ref": date_ref,
                        "status_counts": result.get("status_counts", {}),
                        "total_extracted": len(records),
                        "sync_source": source_label
                    }
                )
            except Exception:
                pass

            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
            counts_str = ", ".join([f"{k}: {v}" for k, v in result.get("status_counts", {}).items()])
            msg = f"{len(records)} equipes ({counts_str}) sincronizadas em {elapsed}s."

            _LAST_BID_SYNC_RESULT = {
                "status": "success",
                "timestamp": ts_end,
                "total_extracted": len(records),
                "status_counts": result.get("status_counts", {}),
                "message": msg
            }
            print(f"[{ts_end}] [CDP BIDTECH] <<< CICLO FINALIZADO COM SUCESSO: {msg}", flush=True)
            return _LAST_BID_SYNC_RESULT
        else:
            elapsed = round(time.time() - start_t, 2)
            ts_end = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
            err_msg = result.get("message", "Erro desconhecido")
            try:
                from supabase_client import update_engine_health
                update_engine_health(
                    "bid_cdp_collector", "ERROR_CONNECTION", is_running=True,
                    error_type="CONNECTION_REFUSED", last_error=err_msg,
                    records_count=0,
                    engine_label="Robô CDP BidTech (Checklist Operacional)"
                )
            except Exception:
                pass

            _LAST_BID_SYNC_RESULT = {
                "status": "error",
                "timestamp": ts_end,
                "total_extracted": 0,
                "status_counts": {},
                "message": err_msg
            }
            print(f"[{ts_end}] [CDP BIDTECH] <<< CICLO FINALIZADO COM AVISO/ERRO ({elapsed}s): {err_msg}", flush=True)
            return _LAST_BID_SYNC_RESULT
    except Exception as exc:
        elapsed = round(time.time() - start_t, 2)
        ts_end = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
        print(f"[{ts_end}] [CDP BIDTECH] <<< CICLO FINALIZADO COM ERRO CRITICO ({elapsed}s): {exc}", flush=True)
        return {"status": "error", "message": str(exc)}
    finally:
        _BID_LOCK.release()


def bid_background_worker(interval_seconds=120, stop_event=None):
    """
    Thread de background que executa a coleta contínua da Visão Operacional BidTech a cada 120 segundos.
    """
    print(f"[BACKGROUND WORKER] Motor CDP BidTech ativo (intervalo: {interval_seconds}s).", flush=True)
    time.sleep(8)

    while True:
        if stop_event and stop_event.is_set():
            print("[BID BACKGROUND] Worker finalizado via stop_event.", flush=True)
            break

        try:
            executar_ciclo_sincronizacao_bid()
        except Exception as e:
            print(f"[BID BACKGROUND ERROR] Exceção no ciclo: {e}", flush=True)

        sleep_elapsed = 0
        while sleep_elapsed < interval_seconds:
            if stop_event and stop_event.is_set():
                break
            time.sleep(2)
            sleep_elapsed += 2


if __name__ == '__main__':
    print("Testando coletor CDP do BidTech...")
    res = executar_ciclo_sincronizacao_bid()
    print(json.dumps(res, indent=2, ensure_ascii=False))
