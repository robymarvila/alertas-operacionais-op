"""
Coletor de Dados Automatizado do TRBOnet One (100% Silencioso em Segundo Plano)
Extrai todas as equipes online da árvore lateral esquerda (treeList) com suporte a
UI Virtualization via COM ScrollPattern, sem mover o mouse e sem travar o teclado.
Otimizado para alta performance (UIA FindAll direto) e suporte multilíngue (PT/EN).
"""
import sys
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import ctypes
try:
    user32 = ctypes.windll.user32
except Exception:
    user32 = None

try:
    import uiautomation as auto
except ImportError:
    auto = None

import re
import json
import time
from datetime import datetime

def obter_janela_trbonet():
    """Localiza a janela do TRBOnet One no desktop interativo."""
    if not user32 or not auto:
        return None
    hDesk = user32.OpenInputDesktop(0, False, 0x01FF)
    if hDesk:
        user32.SetThreadDesktop(hDesk)
    
    target_hwnd = [None]
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_long)
    
    def enum_cb(h, lparam):
        length = user32.GetWindowTextLengthW(h)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(h, buff, length + 1)
        if buff.value == 'TRBOnet One' and user32.IsWindowVisible(h):
            target_hwnd[0] = h
            return False
        return True

    user32.EnumDesktopWindows(hDesk, EnumWindowsProc(enum_cb), 0)
    if target_hwnd[0]:
        return auto.ControlFromHandle(target_hwnd[0])
    return None

def capturar_radios_trbonet_vivo():
    """
    Executa a varredura ultra-rápida e 100% silenciosa na árvore lateral esquerda (treeList).
    Percorre os nós Online (Com GPS / Sem GPS / GPS Fixed / No GPS) até atingir 'Desligado'/'Offline'.
    """
    t_start = time.time()
    win = obter_janela_trbonet()
    if not win:
        return {"status": "error", "message": "Janela 'TRBOnet One' não encontrada. Verifique se o aplicativo está aberto.", "radios": {}}

    tree = win.TreeControl(AutomationId='treeList')
    if not tree.Exists(0, 0):
        return {"status": "error", "message": "Lista de rádios (treeList) não encontrada no TRBOnet One.", "radios": {}}

    data_panel = tree.PaneControl(AutomationId='dataPresenter')
    target_panel = data_panel if data_panel.Exists(0, 0) else tree

    sp = None
    try:
        sp = tree.GetScrollPattern()
    except Exception:
        pass

    client = auto.uiautomation._AutomationClient.instance()
    uia = client.IUIAutomation
    text_cond = uia.CreatePropertyCondition(auto.PropertyId.ControlTypeProperty, auto.ControlType.TextControl)

    padrao_equipe = re.compile(r'\b([A-Z]{2,6}\d{2,4}[A-Z]?)\b', re.IGNORECASE)
    
    radios_gps = set()
    radios_nogps = set()
    radios_offline = set()
    radio_descriptions = {}
    
    current_category = "GPS"

    def scan_current_viewport():
        nonlocal current_category
        
        found = target_panel.Element.FindAll(4, text_cond) # 4 = TreeScope_Descendants
        count = found.Length
        
        for i in range(count):
            el = found.GetElement(i)
            txt = el.CurrentName
            if not txt:
                continue
                
            txt_lower = txt.strip().lower()
            
            # Reconhecimento do grupo Offline / Desligado
            if ("offline" in txt_lower or "desligado" in txt_lower) and not padrao_equipe.search(txt):
                current_category = "OFFLINE"
                
            # Reconhecimento Sem GPS / No GPS / Indoor
            elif (
                ("sem gps" in txt_lower) or 
                ("no gps" in txt_lower) or 
                ("gps not fixed" in txt_lower) or
                ("indoor" in txt_lower)
            ) and not padrao_equipe.search(txt):
                if current_category != "OFFLINE":
                    current_category = "NOGPS"
                
            # Reconhecimento Com GPS / GPS Fixed
            elif (
                ("com gps" in txt_lower) or 
                ("gps fixed" in txt_lower) or 
                ("gps online" in txt_lower)
            ) and not padrao_equipe.search(txt):
                if current_category != "OFFLINE":
                    current_category = "GPS"
                
            # Despachantes / Operadores do Sistema (ignora como rádio de campo)
            elif ("dispatcher" in txt_lower or "despachador" in txt_lower or "operadores online" in txt_lower) and not padrao_equipe.search(txt):
                if current_category != "OFFLINE":
                    current_category = "DISPATCHER"
                
            if current_category == "DISPATCHER":
                continue

            for m in padrao_equipe.findall(txt):
                code = m.upper()
                radio_descriptions[code] = txt.strip()
                if current_category == "GPS":
                    radios_gps.add(code)
                elif current_category == "NOGPS":
                    radios_nogps.add(code)
                elif current_category == "OFFLINE":
                    if code not in radios_gps and code not in radios_nogps:
                        radios_offline.add(code)

    # 1. Rolar suavemente para o topo (0%)
    if sp:
        try:
            sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, 0)
            time.sleep(0.04)
        except Exception:
            pass

    # FASE 1: Varredura detalhada dos grupos Online (0.0% a 11.0% com passos de 1.0%)
    if sp:
        view_size = getattr(sp, 'VerticalViewSize', 2.4)
        pct = 0.0
        while pct <= 11.0:
            try:
                sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, pct)
                time.sleep(0.01)
            except Exception:
                pass
            scan_current_viewport()
            pct += 1.0

        # FASE 2: Varredura contínua e sobreposta dos Desligados (11.0% a 100.0%)
        current_category = "OFFLINE"
        step_offline = max(1.2, view_size * 0.75)

        while pct <= 100.0:
            try:
                sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, pct)
                time.sleep(0.01)
            except Exception:
                pass
            scan_current_viewport()
            if pct >= 100.0:
                break
            pct = min(100.0, pct + step_offline)

        # Varredura final garantida a 100.0% (últimos itens da árvore)
        try:
            sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, 100.0)
            time.sleep(0.01)
        except Exception:
            pass
        scan_current_viewport()

        # Retornar para o topo
        try:
            sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, 0)
        except Exception:
            pass
    else:
        # Fallback sem scroll
        scan_current_viewport()

    # Garantir que rádios online nunca sejam sobrescritos como offline
    radios_offline = radios_offline - radios_gps - radios_nogps

    t_end = time.time()
    duracao = round(t_end - t_start, 2)
    
    agora = datetime.now().strftime("%H:%M:%S")
    resultado = {}
    
    for code in radios_gps:
        resultado[code] = {
            "code": code,
            "gps": True,
            "last_signal": agora,
            "channel": "TRBOnet (Com GPS)",
            "status": "ONLINE",
            "registered": True,
            "description": radio_descriptions.get(code, code)
        }

    for code in radios_nogps:
        if code not in resultado:
            resultado[code] = {
                "code": code,
                "gps": False,
                "last_signal": agora,
                "channel": "TRBOnet (Sem GPS)",
                "status": "ONLINE",
                "registered": True,
                "description": radio_descriptions.get(code, code)
            }

    for code in radios_offline:
        if code not in resultado:
            resultado[code] = {
                "code": code,
                "gps": False,
                "last_signal": "--:--:--",
                "channel": "TRBOnet (Desligado)",
                "status": "OFFLINE",
                "registered": True,
                "description": radio_descriptions.get(code, code)
            }

    online_total = len(radios_gps) + len(radios_nogps)

    # Salvar cache persistente de códigos cadastrados no disco
    try:
        import os
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, 'data')
        os.makedirs(data_dir, exist_ok=True)
        cache_path = os.path.join(data_dir, 'trbonet_registered_codes.json')
        with open(cache_path, 'w', encoding='utf-8') as f:
            json.dump({
                "updated_at": datetime.now().isoformat(),
                "total_cadastrados": len(resultado),
                "total_online": online_total,
                "total_desligados": len(radios_offline),
                "codes": sorted(list(resultado.keys()))
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {
        "status": "success",
        "duration_seconds": duracao,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_online": online_total,
        "total_com_gps": len(radios_gps),
        "total_sem_gps": len(radios_nogps),
        "total_desligados": len(radios_offline),
        "total_cadastrados": len(resultado),
        "radios": resultado
    }

def extrair_dados_trbonet():
    """Função compatível com endpoints do Flask."""
    res = capturar_radios_trbonet_vivo()
    if res.get("status") == "success":
        return res.get("radios", {})
    return {}

if __name__ == '__main__':
    res = capturar_radios_trbonet_vivo()
    print("\n" + "="*60)
    print("COLETOR TRBONET ONE (ALTA VELOCIDADE)")
    print("="*60)
    print(f"Status: {res['status']}")
    print(f"Tempo de Execução: {res.get('duration_seconds')}s")
    print(f"Total Online: {res.get('total_online', 0)}")
    print(f"Com GPS: {res.get('total_com_gps', 0)}")
    print(f"Sem GPS: {res.get('total_sem_gps', 0)}")
    print(f"Desligados: {res.get('total_desligados', 0)}")
    print(f"Total Cadastrados: {res.get('total_cadastrados', 0)}")
    print("="*60)

