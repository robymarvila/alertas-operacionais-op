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

    padrao_equipe = re.compile(r'\b(E[A-Z]{2}\d{2,4}[A-Z]?|N[A-Z]{2}\d{2,4}[A-Z]?)\b', re.IGNORECASE)
    
    radios_gps = set()
    radios_nogps = set()
    
    current_category = "GPS"
    stop_scrolling = False

    def scan_current_viewport():
        nonlocal current_category, stop_scrolling
        
        found = target_panel.Element.FindAll(4, text_cond) # 4 = TreeScope_Descendants
        count = found.Length
        
        for i in range(count):
            el = found.GetElement(i)
            txt = el.CurrentName
            if not txt:
                continue
                
            txt_lower = txt.strip().lower()
            
            # Reconhecimento do grupo Offline / Desligado (Interrompe leitura imediatamente)
            if ("offline" in txt_lower or "desligado" in txt_lower) and not padrao_equipe.match(txt):
                stop_scrolling = True
                return
                
            # Reconhecimento Sem GPS / No GPS / Indoor
            elif (
                ("sem gps" in txt_lower) or 
                ("no gps" in txt_lower) or 
                ("gps not fixed" in txt_lower) or
                ("indoor" in txt_lower)
            ) and not padrao_equipe.match(txt):
                current_category = "NOGPS"
                
            # Reconhecimento Com GPS / GPS Fixed
            elif (
                ("com gps" in txt_lower) or 
                ("gps fixed" in txt_lower) or
                ("gps online" in txt_lower)
            ) and not padrao_equipe.match(txt):
                current_category = "GPS"
                
            # Despachantes / Operadores do Sistema (ignora como rádio de campo)
            elif ("dispatcher" in txt_lower or "despachador" in txt_lower) and not padrao_equipe.match(txt):
                current_category = "DISPATCHER"
                
            if current_category == "DISPATCHER":
                continue

            for m in padrao_equipe.findall(txt):
                code = m.upper()
                if len(code) >= 5:
                    if current_category == "GPS":
                        radios_gps.add(code)
                    elif current_category == "NOGPS":
                        radios_nogps.add(code)

    # 1. Rolar suavemente para o topo (0%)
    if sp:
        try:
            sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, 0)
            time.sleep(0.04)
        except Exception:
            pass

    # 2. Ler tela inicial (topo)
    scan_current_viewport()

    # 3. Rolar páginas até encontrar o grupo Offline / Desligado
    if sp and not stop_scrolling:
        for _ in range(8):
            if stop_scrolling:
                break
            prev_pct = sp.VerticalScrollPercent
            sp.Scroll(auto.ScrollAmount.NoAmount, auto.ScrollAmount.LargeIncrement)
            time.sleep(0.04)
            # Se chegou ao final do scroll
            if abs(sp.VerticalScrollPercent - prev_pct) < 0.0001:
                break
            scan_current_viewport()

        # Retornar para o topo
        try:
            sp.SetScrollPercent(auto.ScrollPattern.NoScrollValue, 0)
        except Exception:
            pass

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
            "status": "ONLINE"
        }

    for code in radios_nogps:
        if code not in resultado:
            resultado[code] = {
                "code": code,
                "gps": False,
                "last_signal": agora,
                "channel": "TRBOnet (Sem GPS)",
                "status": "ONLINE"
            }

    return {
        "status": "success",
        "duration_seconds": duracao,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_online": len(resultado),
        "total_com_gps": len(radios_gps),
        "total_sem_gps": len(radios_nogps),
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
    print("="*60)

