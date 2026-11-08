"""
Delivery Manager - Módulo Entrega de Equipes (Enel SP)
Gerencia a consolidação, regras de tipologia veicular, enquadramento de turnos operacionais,
diferenciação entre Equipes ATIVAS (ao vivo) e Equipes TOTAL (acumulado do dia),
agrupamento hierárquico das 14 bases por região (Norte e Leste) e auditoria histórica.
"""

from datetime import datetime, date, timedelta, timezone
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger("delivery_manager")

# Fuso Horário Oficial de Operação (Horário de Brasília - UTC-3)
BR_TZ = timezone(timedelta(hours=-3))

CACHE_FILE = "delivery_daily_cache.json"

# 7 Bases Oficiais Definidas para Data Quality e Confronto (Região Norte e Região Leste)
# Região Norte: ENL (Base Fagundes Filho), ECL (Base Cajati), EEL (Base Vila Medeiros)
# Região Leste: EML (Base Monte Santo), EQL (Base Aricanduva), EVL (Base Catumbi), ESL (Base Santo André)
TARGET_PREFIXES = {'ENL', 'ECL', 'EEL', 'EML', 'EQL', 'EVL', 'ESL'}

def normalize_team_code(raw_name: str) -> str:
    """Padroniza o código da equipe removendo espaços, traços e caracteres especiais."""
    if not raw_name:
        return ""
    return re.sub(r'[^A-Za-z0-9]', '', str(raw_name)).upper()

def calculate_time_duration(start_str: str, end_str: str) -> str:
    """Calcula a duração HH:MM entre dois horários de início e fim."""
    try:
        if not start_str or not end_str or start_str in ["--", "--:--"] or end_str in ["--", "--:--"]:
            return "--"
        fmt1 = "%H:%M:%S" if len(start_str.strip()) > 5 else "%H:%M"
        fmt2 = "%H:%M:%S" if len(end_str.strip()) > 5 else "%H:%M"
        t1 = datetime.strptime(start_str.strip(), fmt1)
        t2 = datetime.strptime(end_str.strip(), fmt2)
        diff = t2 - t1
        if diff.total_seconds() < 0:
            diff += timedelta(days=1)
        hours, remainder = divmod(int(diff.total_seconds()), 3600)
        minutes = remainder // 60
        return f"{hours:02d}h {minutes:02d}m"
    except Exception:
        return "--"


def format_datetime_br(val) -> str:
    """Formata timestamps ISO ou strings para o padrão brasileiro DD/MM/YYYY HH:mm:ss."""
    if not val or str(val).strip() in ["--", "None", ""]:
        return datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    val_str = str(val).strip()
    try:
        if re.match(r'^\d{2}/\d{2}/\d{4}', val_str):
            return val_str
        cleaned = val_str.replace('T', ' ').split('.')[0].replace('Z', '')
        if len(cleaned) == 10:  # YYYY-MM-DD
            dt = datetime.strptime(cleaned, "%Y-%m-%d")
            return dt.strftime("%d/%m/%Y")
        elif len(cleaned) >= 19:  # YYYY-MM-DD HH:MM:SS
            dt = datetime.strptime(cleaned[:19], "%Y-%m-%d %H:%M:%S")
            return dt.strftime("%d/%m/%Y %H:%M:%S")
        elif len(cleaned) == 16:  # YYYY-MM-DD HH:MM
            dt = datetime.strptime(cleaned, "%Y-%m-%d %H:%M")
            return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
def normalize_bid_status(raw_status) -> str:
    """Padroniza e blinda o status da Visão Operacional BidTech contra mojibake ou variações."""
    if not raw_status or str(raw_status).strip() in ["--", "NONE", "NULL", "", "None"]:
        return "Não Encontrada"
    st = str(raw_status).strip()
    s_up = st.upper()
    if "OPERA" in s_up:
        return "Em Operação"
    elif "CHECKLIST" in s_up:
        return "Em Checklist"
    elif "PLANEJAD" in s_up:
        return "Planejada"
    elif "RETORNAD" in s_up:
        return "Retornada"
    elif "BLOQUEAD" in s_up:
        return "Bloqueada"
    elif "NÃO" in s_up or "NAO" in s_up or "ENCONTRADA" in s_up:
        return "Não Encontrada"
    return st

def to_int(val, default=0):
    """Converte valores inteiros com segurança."""
    try:
        if val is None or str(val).strip() in ['-', '', 'None', 'nan']:
            return default
        clean = re.sub(r'[^0-9-]', '', str(val).split('.')[0])
        return int(clean) if clean else default
    except Exception:
        return default

def to_float(val, default=0.0):
    """Converte valores decimais com segurança tratando vírgulas e pontos."""
    try:
        if val is None or str(val).strip() in ['-', '', 'None', 'nan']:
            return default
        s = str(val).strip().replace(',', '.')
        s_clean = re.sub(r'[^0-9.-]', '', s)
        return float(s_clean) if s_clean else default
    except Exception:
        return default

MUNCK_CODES = {
    "ENL210", "ENL211", "ECL210", "ECL211", "EEL210", "EEL211",
    "EML200", "EQL200", "EQL210", "ESL200", "EVL200", "EVL210"
}

PROJETO_RAMAL_CODES = {
    # Região Norte - Base Fagundes Filho
    "ENL216", "ENL217", "ENL218", "ENL219", "ENL220",
    # Região Norte - Base Cajati
    "ECL216", "ECL217", "ECL218", "ECL219", "ECL220",
    # Região Norte - Base Vila Medeiros
    "EEL216", "EEL217", "EEL218", "EEL219", "EEL220"
}

# Equipes dos códigos 200 da Base Leste (a partir do mês 10/2026):
# EML2, EVL2, EQL2, ESL2 (e correlatas próprias EMA2, EVA2, EQA2, ESA2)
LESTE_RAMAL_PREFIXES = ("EML2", "EVL2", "EQL2", "ESL2", "EMA2", "EVA2", "EQA2", "ESA2")

# Equipes de apoio STC Leste com códigos fixos:
# Região Norte:
# Base Cajati: ECL313 a ECL317
# Base Vila Medeiros: EEL305 a EEL309
# Base Fagundes Filho: ENL312 a ENL316
# Região Leste:
# Base Monte Santo: EML310 a EML314
# Base Aricanduva: EQL303 a EQL307
STC_LESTE_CODES = {
    # Região Norte - Base Cajati
    "ECL313", "ECL314", "ECL315", "ECL316", "ECL317",
    # Região Norte - Base Vila Medeiros
    "EEL305", "EEL306", "EEL307", "EEL308", "EEL309",
    # Região Norte - Base Fagundes Filho
    "ENL312", "ENL313", "ENL314", "ENL315", "ENL316",
    # Região Leste - Base Monte Santo
    "EML310", "EML311", "EML312", "EML313", "EML314",
    # Região Leste - Base Aricanduva
    "EQL303", "EQL304", "EQL305", "EQL306", "EQL307"
}
STC_LESTE_EQUIVALENTS = {c.replace("L", "A") for c in STC_LESTE_CODES}
ALL_STC_LESTE_CODES = STC_LESTE_CODES | STC_LESTE_EQUIVALENTS

def is_stc_leste(team_code: str = "", vehicle_type: str = "", base: str = "", date_ref: str = "") -> bool:
    """
    Verifica se a equipe pertence ao grupo STC Leste:
    Equipes que atuam em apoio às demais áreas do TMA com códigos fixos por base:
    - Norte: Cajati (ECL313-317), Vila Medeiros (EEL305-309), Fagundes Filho (ENL312-316)
    - Leste: Monte Santo (EML310-314), Aricanduva (EQL303-307)
    """
    code = str(team_code or "").strip().upper()
    vt = str(vehicle_type or "").strip()
    if vt == "STC Leste" or "STC LESTE" in vt.upper() or "STC_LESTE" in vt.upper():
        return True
    if code in ALL_STC_LESTE_CODES:
        return True
    return False

def is_projeto_ramal(team_code: str = "", vehicle_type: str = "", base: str = "", date_ref: str = "") -> bool:
    """
    Verifica se a equipe pertence ao Projeto Ramal por código, tipo ou regra operacional:
    - Região Norte: Códigos específicos em PROJETO_RAMAL_CODES (ENL216-220, ECL216-220, EEL216-220)
    - Região Leste (a partir de 10/2026): Todas as equipes dos códigos 200 (EML2, EVL2, EQL2, ESL2) que logarem na Base Leste
    """
    code = str(team_code or "").strip().upper()
    vt = str(vehicle_type or "").strip()
    if vt == "Projeto Ramal" or "Ramal" in vt or "PROJETO RAMAL" in vt.upper():
        return True
    if code in PROJETO_RAMAL_CODES:
        return True

    # Regra Exceção Base Leste: aplicável para o mês 10/2026 em diante
    is_month_10_or_later = True
    if date_ref and str(date_ref).strip() not in ["--", "None", "nan", ""]:
        d_clean = str(date_ref).strip()[:7]
        is_month_10_or_later = (d_clean >= "2026-10")

    if is_month_10_or_later:
        if any(code.startswith(pfx) for pfx in LESTE_RAMAL_PREFIXES):
            # Validação defensiva de base: não aplica se a base for expressamente da Região Norte
            if base and str(base).strip() not in ["--", "None", "nan", ""]:
                b_up = str(base).upper()
                norte_bases = ["FAGUNDES", "CAJATI", "VILA MEDEIROS"]
                if any(nb in b_up for nb in norte_bases):
                    return False
            return True

    return False

def is_moto(team_code: str = "", vehicle_type: str = "") -> bool:
    """Verifica se o veículo/equipe é do tipo Moto."""
    vt = str(vehicle_type or "").strip().lower()
    if "moto" in vt:
        return True
    code = str(team_code or "").strip().upper()
    digits = "".join([c for c in code if c.isdigit()])
    if digits and digits.startswith("7"):
        return True
    return False

def is_linha_viva_or_munck(team_code: str = "", vehicle_type: str = "", base: str = "", date_ref: str = "") -> bool:
    """
    Identifica com precisão se a equipe pertence ao grupo Linha Viva ou Munck:
    - Munck: presente na lista estrita MUNCK_CODES ou vehicle_type 'Munck' (exceto exceção Projeto Ramal Leste)
    - Linha Viva: primeiro dígito numérico após o prefixo é '2' ou vehicle_type 'Linha Viva'
    - Cobre equipes específicas citadas (ENL211, ECL211, EEL211, e códigos 200)
    - Exclui expressamente equipes do Projeto Ramal (ENL216-220, ECL216-220, EEL216-220 e códigos 200 Leste)
    """
    code = str(team_code or "").strip().upper()
    vt = str(vehicle_type or "").strip()
    if is_projeto_ramal(code, vt, base=base, date_ref=date_ref) or is_stc_leste(code, vt, base=base, date_ref=date_ref):
        return False
    if vt in ["Linha Viva", "Munck"] or "Munk" in vt or "Linha Viva" in vt:
        return True
    if code in MUNCK_CODES:
        # Se for código 200 da Base Leste no período do Projeto Ramal, é Ramal e não Munck
        if is_projeto_ramal(code, base=base, date_ref=date_ref):
            return False
        return True
    digits = "".join([c for c in code if c.isdigit()])
    if digits and digits.startswith("2"):
        return True
    return False

def is_regiao_norte(team_code: str = "", base: str = "", region: str = "", geo: str = "") -> bool:
    """Verifica se a equipe pertence à Região Norte."""
    if region and "norte" in str(region).lower():
        return True
    if geo and "norte" in str(geo).lower():
        return True
    if base:
        b_up = str(base).upper()
        if any(nb in b_up for nb in ["FAGUNDES", "CAJATI", "VILA MEDEIROS", "NORTE"]):
            return True
        if any(lb in b_up for lb in ["MONTE SANTO", "ARICANDUVA", "CATUMBI", "SANTO ANDRÉ", "SANTO ANDRE", "LESTE"]):
            return False
    code = str(team_code or "").strip().upper()
    prefix = code[:3]
    if prefix in {"ENL", "ECL", "EEL", "ENA", "ECA", "EEA"}:
        return True
    return False

def get_team_shift_duration_hours(team_code: str = "", vehicle_type: str = "", region: str = "", base: str = "", geo: str = "", date_ref: str = "") -> int:
    """
    Retorna a duração da jornada diária da equipe em horas (regra de tempo corrido sem intervalo):
    - Linha Viva: Região Norte = 10h; Região Leste = 8h
    - Munck: Região Norte = 10h; Região Leste = 8h
    - Cesto Aéreo: 8h
    - Veículo Leve: 8h
    - Projeto Ramal (Norte ou Leste): 8h
    - STC Leste: 8h
    - Moto: 8h
    - Demais: 8h
    """
    code = str(team_code or "").strip().upper()
    vt = str(vehicle_type or "").strip()

    # Projeto Ramal e STC Leste têm jornada de 8h fixas
    if is_projeto_ramal(code, vt, base=base, date_ref=date_ref) or is_stc_leste(code, vt, base=base, date_ref=date_ref):
        return 8

    if is_linha_viva_or_munck(code, vt, base=base, date_ref=date_ref):
        if is_regiao_norte(code, base=base, region=region, geo=geo):
            return 10
        else:
            return 8

    return 8

def calculate_team_schedule(team_code: str = "", vehicle_type: str = "", region: str = "", base: str = "", geo: str = "",
                            login_time: str = "--:--", marcacao: str = "--", shift_code: str = "08:00", date_ref: str = "") -> dict:
    """
    Calcula:
    1. shift_hours: Duração da jornada (10h para Linha Viva/Munck Norte, 8h para as demais)
    2. termino: Horário previsto de término/logoff calculado com base na Marcação (ou Turno Programado se sem marcação)
    3. turno_x_login: Comparativo de pontualidade/atraso entre Marcação e Turno Programado
    4. turno_x_login_minutos: Diferença em minutos (positivo = atraso, negativo = adiantado)
    """
    shift_hours = get_team_shift_duration_hours(team_code, vehicle_type, region=region, base=base, geo=geo, date_ref=date_ref)

    marc_clean = str(marcacao or "").strip()
    has_marcacao = bool(marc_clean and marc_clean not in ['--', '-', '', 'None', 'nan', '--:--'])

    # Horário de referência para cálculo do término
    ref_start = None
    start_str = marc_clean if has_marcacao else str(shift_code or login_time or "08:00").strip()
    if not start_str or start_str in ['--', '-', '', 'None', 'nan', '--:--']:
        start_str = "08:00"

    try:
        parts = start_str.split(':')
        if len(parts) >= 2:
            sh = int(parts[0])
            sm = int(parts[1])
            ref_start = (sh, sm)
    except Exception:
        ref_start = None

    if ref_start is not None:
        end_h = (ref_start[0] + shift_hours) % 24
        end_m = ref_start[1]
        termino = f"{end_h:02d}:{end_m:02d}"
    else:
        termino = "--:--"

    # Turno programado de referência para Turno x Login (prioriza turno oficial: 06:00, 08:00, 12:00, 14:00, 20:00, 22:00)
    prog_start_str = str(shift_code or "").strip()
    if not prog_start_str or prog_start_str in ['--', '-', '', 'None', 'nan', '--:--']:
        prog_start_str = str(login_time or "").strip()
    if not prog_start_str or prog_start_str in ['--', '-', '', 'None', 'nan', '--:--']:
        prog_start_str = "08:00"

    prog_min = None
    try:
        p_parts = prog_start_str.split(':')
        if len(p_parts) >= 2:
            prog_min = int(p_parts[0]) * 60 + int(p_parts[1])
    except Exception:
        prog_min = None

    turno_x_login = "--"
    turno_x_login_minutos = 0

    if has_marcacao:
        try:
            m_parts = marc_clean.split(':')
            if len(m_parts) >= 2 and prog_min is not None:
                m_min = int(m_parts[0]) * 60 + int(m_parts[1])
                diff_min = m_min - prog_min
                if diff_min < -720:
                    diff_min += 1440
                elif diff_min > 720:
                    diff_min -= 1440
                turno_x_login_minutos = diff_min
                if diff_min > 0:
                    turno_x_login = f"+{diff_min} min"
                elif diff_min < 0:
                    turno_x_login = f"{diff_min} min"
                else:
                    turno_x_login = "Pontual"
        except Exception:
            turno_x_login = "--"
            turno_x_login_minutos = 0
    else:
        # Se não tiver marcação: Equipe PROGRAMADA (não efetuou login)
        # Permanece com pontualidade neutra para não inflar atrasos/custos fictícios
        turno_x_login = "--"
        turno_x_login_minutos = 0

    return {
        "shift_hours": shift_hours,
        "termino": termino,
        "turno_x_login": turno_x_login,
        "turno_x_login_minutos": turno_x_login_minutos
    }

def classify_spotfire_shift_and_turno(sp_record: dict) -> dict:
    """
    Extrai e classifica com precisão o Turno (Manhã, Tarde, Noite) e o Agrupamento de Horário
    (Turno 06:00, 08:00, 12:00, 14:00, 20:00, 22:00) a partir dos dados do Spotfire:
    - Coluna Período (1 - Manhã, 2 - Tarde, 3 - Noite)
    - login_desc (Início às XX Hrs)
    - inicio_calibrado
    - Macroregra Linha Viva e Munck:
        * Login até 17:00 -> Turno 08:00 (Manhã)
        * Login após 17:00 -> Turno 20:00 (Noite)
    """
    raw_data = sp_record.get("raw_data") if isinstance(sp_record.get("raw_data"), dict) else {}
    raw_periodo = str(raw_data.get("periodo", "") or sp_record.get("periodo", "")).lower()
    login_desc = str(raw_data.get("login_desc", "") or sp_record.get("login_desc", ""))
    inicio_cal = str(sp_record.get("inicio_calendario") or sp_record.get("inicio_calibrado", "") or sp_record.get("login_corrigido") or sp_record.get("login") or "").strip()

    team_code = sp_record.get("equipe_normalizada") or sp_record.get("equipe") or sp_record.get("team_code") or ""
    veh_type = sp_record.get("veiculo") or sp_record.get("sub_tipo") or sp_record.get("tipo") or sp_record.get("vehicle_type") or ""
    base_val = sp_record.get("base") or sp_record.get("base_responsavel") or sp_record.get("base_display") or ""
    date_val = sp_record.get("data_referencia") or sp_record.get("data") or ""

    # 1. Determina Turno Macrocategoria preliminar: Manhã, Tarde, Noite
    turno = None
    if "1" in raw_periodo or "manh" in raw_periodo:
        turno = "Manhã"
    elif "2" in raw_periodo or "tard" in raw_periodo:
        turno = "Tarde"
    elif "3" in raw_periodo or "noit" in raw_periodo:
        turno = "Noite"

    # 2. Determina Horário de Início e Agrupamento Oficial de Turno
    shift_slot = "Turno 08:00"
    shift_code = "08:00"
    shift_pill_class = "shift-08h"

    hrs_match = re.search(r'(\d{1,2})\s*hr', login_desc, re.IGNORECASE)
    login_time_extracted = None
    if hrs_match:
        h = int(hrs_match.group(1))
        login_time_extracted = f"{h:02d}:00"
    elif inicio_cal and ":" in inicio_cal:
        parts = inicio_cal.split(" ")
        time_part = parts[-1] if len(parts) > 1 else parts[0]
        sub = time_part.split(":")
        if len(sub) >= 2:
            try:
                h = int(sub[0])
                m = int(sub[1])
                login_time_extracted = f"{h:02d}:{m:02d}"
            except Exception:
                pass

    if is_projeto_ramal(team_code, veh_type, base=base_val, date_ref=date_val) or is_moto(team_code, veh_type):
        # Macroregra Especial Projeto Ramal e Moto: Entrada sempre fixada no Turno 08:00 (Manhã)
        shift_slot = "Turno 08:00"
        shift_code = "08:00"
        shift_pill_class = "shift-08h"
        turno = "Manhã"
    elif is_linha_viva_or_munck(team_code, veh_type, base=base_val, date_ref=date_val):
        # Macroregra Especial Linha Viva e Munck
        if login_time_extracted:
            try:
                t_parts = login_time_extracted.split(':')
                total_min = int(t_parts[0]) * 60 + int(t_parts[1])
                if total_min <= 1020:  # Até 17:00
                    shift_slot = "Turno 08:00"
                    shift_code = "08:00"
                    shift_pill_class = "shift-08h"
                    turno = "Manhã"
                else:                  # Após 17:00 (noite)
                    shift_slot = "Turno 20:00"
                    shift_code = "20:00"
                    shift_pill_class = "shift-20h"
                    turno = "Noite"
            except Exception:
                shift_slot = "Turno 08:00"
                shift_code = "08:00"
                shift_pill_class = "shift-08h"
                turno = "Manhã"
        else:
            # Sem login identificado: padrão diurno 08:00
            shift_slot = "Turno 08:00"
            shift_code = "08:00"
            shift_pill_class = "shift-08h"
            turno = "Manhã"
    else:
        # Regra Padrão Demais Veículos (Cesto, Leve, Moto)
        if login_time_extracted:
            try:
                t_parts = login_time_extracted.split(':')
                total_min = int(t_parts[0]) * 60 + int(t_parts[1])
                if 240 <= total_min <= 455:      # 04:00 às 07:35
                    shift_slot = "Turno 06:00"
                    shift_code = "06:00"
                    shift_pill_class = "shift-06h"
                elif 456 <= total_min <= 660:    # 07:36 às 11:00
                    shift_slot = "Turno 08:00"
                    shift_code = "08:00"
                    shift_pill_class = "shift-08h"
                elif 661 <= total_min <= 815:    # 11:01 às 13:35
                    shift_slot = "Turno 12:00"
                    shift_code = "12:00"
                    shift_pill_class = "shift-12h"
                elif 816 <= total_min <= 1050:   # 13:36 às 17:30
                    shift_slot = "Turno 14:00"
                    shift_code = "14:00"
                    shift_pill_class = "shift-14h"
                elif 1051 <= total_min <= 1310:  # 17:36 às 21:50
                    shift_slot = "Turno 20:00"
                    shift_code = "20:00"
                    shift_pill_class = "shift-20h"
                else:                            # 21:51 às 03:59
                    shift_slot = "Turno 22:00"
                    shift_code = "22:00"
                    shift_pill_class = "shift-22h"
            except Exception:
                pass

            if not turno:
                if shift_code in ["06:00", "08:00"]:
                    turno = "Manhã"
                elif shift_code in ["12:00", "14:00"]:
                    turno = "Tarde"
                elif shift_code in ["20:00", "22:00"]:
                    turno = "Noite"

        if not turno:
            turno = "Manhã"

        if turno == "Manhã" and shift_code not in ["06:00", "08:00"]:
            shift_code = "08:00"
            shift_slot = "Turno 08:00"
            shift_pill_class = "shift-08h"
        elif turno == "Tarde" and shift_code not in ["12:00", "14:00"]:
            shift_code = "14:00"
            shift_slot = "Turno 14:00"
            shift_pill_class = "shift-14h"
        elif turno == "Noite" and shift_code not in ["20:00", "22:00"]:
            shift_code = "20:00"
            shift_slot = "Turno 20:00"
            shift_pill_class = "shift-20h"

    return {
        "turno": turno,
        "shift_slot": shift_slot,
        "shift_code": shift_code,
        "shift_pill_class": shift_pill_class,
        "login_time_extracted": login_time_extracted
    }


CONTRACT_HOURLY_RATES = {
    "NORTE": {
        "CESTO": 357.01,
        "LEVE": 290.51,
        "MOTO": 292.39
    },
    "LESTE": {
        "CESTO": 353.24,
        "LEVE": 286.61,
        "MOTO": 288.26
    }
}

def _fmt_brl(val):
    if not val or val < 0:
        return "R$ 0,00"
    return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def classify_and_price_team(team_dict: dict, date_ref: str = None) -> dict:
    code = str(team_dict.get("team_code") or "").strip().upper()
    vt = str(team_dict.get("vehicle_type") or "").strip()
    b_name = str(team_dict.get("base_display") or team_dict.get("base_name") or team_dict.get("base_code") or "")
    reg_str = str(team_dict.get("region") or "")
    geo_str = str(team_dict.get("geo") or "")

    is_norte = is_regiao_norte(code, base=b_name, region=reg_str, geo=geo_str)
    reg_key = "NORTE" if is_norte else "LESTE"

    ramal = is_projeto_ramal(code, vt, base=b_name, date_ref=date_ref)
    stc = is_stc_leste(code, vt, base=b_name, date_ref=date_ref)
    moto = is_moto(code, vt)
    linha_munk = is_linha_viva_or_munck(code, vt, base=b_name, date_ref=date_ref)

    if ramal:
        cat_key = "CESTO"
        cat_display = "Projeto Ramal (Cesto)"
    elif stc:
        cat_key = "LEVE"
        cat_display = "STC Leste (Leve)"
    elif moto:
        cat_key = "MOTO"
        cat_display = "Moto"
    elif linha_munk:
        cat_key = "CESTO"
        cat_display = "Linha Viva / Munk (Cesto)"
    elif "cesto" in vt.lower() or "pesado" in str(team_dict.get("vehicle_category", "")).lower():
        cat_key = "CESTO"
        cat_display = "Cesto Aéreo"
    else:
        cat_key = "LEVE"
        cat_display = "Veículo Leve"

    rate = CONTRACT_HOURLY_RATES[reg_key][cat_key]
    d_min = int(team_dict.get("turno_x_login_minutos") or 0)
    financial_loss = round((d_min / 60.0) * rate, 2) if d_min > 0 else 0.0

    return {
        "rate_hour": rate,
        "rate_hour_str": _fmt_brl(rate),
        "delay_minutes": d_min,
        "financial_loss": financial_loss,
        "financial_loss_str": _fmt_brl(financial_loss),
        "contract_regiao": reg_key,
        "contract_category": cat_key,
        "contract_cat_display": cat_display,
        "is_stc_leste": bool(stc),
        "is_ramal": bool(ramal)
    }


class DeliveryManager:
    @staticmethod
    def get_operational_date(dt=None) -> str:
        """
        Retorna a data do dia operacional da Enel/Alpitel.
        O dia operacional vira pontualmente às 04:31 da manhã.
        - Das 00:00 às 04:30: pertence ao dia operacional anterior.
        - Das 04:31 às 23:59: pertence ao dia operacional atual.
        """
        if dt is None:
            dt = datetime.now(BR_TZ)
        if dt.hour < 4 or (dt.hour == 4 and dt.minute <= 30):
            return (dt.date() - timedelta(days=1)).isoformat()
        return dt.date().isoformat()

    def __init__(self):
        # 14 Bases Oficiais com empresas e regiões oficiais
        self.official_bases = {
            # Região Norte Alpitel
            "ENL": {"name": "Base Fagundes Filho", "region": "Região Norte", "company": "Alpitel", "geo": "Norte", "base_display": "Base Fagundes Filho"},
            "ECL": {"name": "Base Cajati", "region": "Região Norte", "company": "Alpitel", "geo": "Norte", "base_display": "Base Cajati"},
            "EEL": {"name": "Base Vila Medeiros", "region": "Região Norte", "company": "Alpitel", "geo": "Norte", "base_display": "Base Vila Medeiros"},
            
            # Região Leste Alpitel
            "EML": {"name": "Base Monte Santo", "region": "Região Leste", "company": "Alpitel", "geo": "Leste", "base_display": "Base Monte Santo"},
            "EQL": {"name": "Base Aricanduva", "region": "Região Leste", "company": "Alpitel", "geo": "Leste", "base_display": "Base Aricanduva"},
            "EVL": {"name": "Base Catumbi", "region": "Região Leste", "company": "Alpitel", "geo": "Leste", "base_display": "Base Catumbi"},
            "ESL": {"name": "Base Santo André", "region": "Região Leste", "company": "Alpitel", "geo": "Leste", "base_display": "Base Santo André"},

            # Região Norte Própria
            "ENA": {"name": "Base Fagundes Filho", "region": "Região Norte", "company": "Própria", "geo": "Norte", "base_display": "Base Fagundes Filho"},
            "ECA": {"name": "Base Cajati", "region": "Região Norte", "company": "Própria", "geo": "Norte", "base_display": "Base Cajati"},
            "EEA": {"name": "Base Vila Medeiros", "region": "Região Norte", "company": "Própria", "geo": "Norte", "base_display": "Base Vila Medeiros"},

            # Região Leste Própria
            "EMA": {"name": "Base Monte Santo", "region": "Região Leste", "company": "Própria", "geo": "Leste", "base_display": "Base Monte Santo"},
            "EQA": {"name": "Base Aricanduva", "region": "Região Leste", "company": "Própria", "geo": "Leste", "base_display": "Base Aricanduva"},
            "EVA": {"name": "Base Catumbi", "region": "Região Leste", "company": "Própria", "geo": "Leste", "base_display": "Base Catumbi"},
            "ESA": {"name": "Base Santo André", "region": "Região Leste", "company": "Própria", "geo": "Leste", "base_display": "Base Santo André"}
        }

        # Agrupamento das 14 bases por região
        self.geo_groups = {
            "Norte": {
                "bases": ["Base Fagundes Filho", "Base Cajati", "Base Vila Medeiros"],
                "codes": ["ENL", "ECL", "EEL", "ENA", "ECA", "EEA"]
            },
            "Leste": {
                "bases": ["Base Monte Santo", "Base Aricanduva", "Base Catumbi", "Base Santo André"],
                "codes": ["EML", "EQL", "EVL", "ESL", "EMA", "EQA", "EVA", "ESA"]
            }
        }

        # Lista estrita de códigos MUNCK
        self.munck_codes = MUNCK_CODES

        self.current_date_str = self.get_operational_date()
        self.active_teams = []                # Instantâneo da última coleta
        self.daily_accumulated_teams = {}     # Acumulado deduplicado do dia (team_code -> dict)
        self.daily_team_order_history = {}    # Histórico deduplicado de ordens de serviço (team_code -> list)
        self.intraday_curve = {}              # Histórico horário das equipes que entraram
        self.last_sync_time = "--"
        self.sync_source = "Aguardando sincronização"
        self.spotfire_cache = {}              # (date_ref, norm_code) -> dict
        self.bid_cache = {}                   # team_code -> dict (Visão Operacional BidTech)
        self.last_bid_sync = "--"             # Última sincronização da BID
        self.daily_delay_justifications = {}  # team_code -> dict (Justificativas de atraso de login)

        # Caches de auditoria em memória de alta performance (<1ms)
        self._daily_audit_cache = {}          # date_str -> dict
        self._daily_audit_cache_ts = {}       # date_str -> timestamp
        self._monthly_audit_cache = {}        # month_str -> dict
        self._monthly_audit_cache_ts = {}     # month_str -> timestamp
        self._audit_dates_cache = None
        self._audit_dates_cache_ts = 0

        # Caches de alta performance para a tela ATRASOS E TURNOS (<1ms)
        self._delays_history_records_cache = {}
        self._delays_analytics_cache = {}

        self.load_local_cache()

    def clear_audit_cache(self, date_str=None):
        """Invalida caches de auditoria quando novos dados são consolidados."""
        self._delays_analytics_cache.clear()
        if date_str:
            self._daily_audit_cache.pop(date_str, None)
            m = date_str[:7]
            self._monthly_audit_cache.pop(m, None)
            self._delays_history_records_cache.pop(date_str, None)
        else:
            self._daily_audit_cache.clear()
            self._monthly_audit_cache.clear()
            self._delays_history_records_cache.clear()
            self._audit_dates_cache = None
            self._audit_dates_cache_ts = 0

    def load_local_cache(self):
        """Carrega o cache cumulativo do dia operacional caso o servidor reinicie."""
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    cached_date = data.get("date")
                    current_op_date = self.get_operational_date()
                    if cached_date == current_op_date:
                        raw_acc = data.get("accumulated_teams", {})
                        self.daily_accumulated_teams = {}
                        now = datetime.now()
                        for code, t in raw_acc.items():
                            raw_shift = t.get("shift_raw") or f"{t.get('login_time', '')}-{t.get('logoff_time', '')}"
                            veh_info = self.classify_vehicle(code)
                            v_type = t.get("vehicle_type") or veh_info.get("type")
                            s_info = self.parse_shift_window(
                                raw_shift,
                                team_code=code,
                                vehicle_type=v_type,
                                marcacao_time=t.get("marcacao", "--"),
                                base=t.get("base_display") or t.get("geo") or t.get("base_raw"),
                                region=t.get("region", ""),
                                geo=t.get("geo", ""),
                                date_ref=cached_date
                            )
                            t.update(s_info)
                            # Se for após as 04:30 da manhã e o turno for da noite anterior (20h/22h) já inativo, descarta
                            if (now.hour > 4 or (now.hour == 4 and now.minute >= 31)) and not t.get("is_active", True) and t.get("shift_code") in ["20:00", "22:00"]:
                                continue
                            # Se a equipe não está ativa e nunca foi vista ativa hoje no dia operacional, descarta
                            if not t.get("is_active", True) and not t.get("seen_active_today"):
                                continue
                            # Se a equipe estiver inativa e pertencer a um turno futuro cujo horário de início ainda não ocorreu hoje, descarta
                            now_min_check = now.hour * 60 + now.minute
                            sc_chk = t.get("shift_code", "08:00")
                            sc_start_chk = {"06:00": 360, "08:00": 480, "12:00": 720, "14:00": 840, "20:00": 1200, "22:00": 1320}.get(sc_chk, 480)
                            if not t.get("is_active", True) and sc_start_chk > now_min_check:
                                continue
                            if t.get("hora_a_caminho"):
                                h_raw = str(t["hora_a_caminho"]).strip()
                                if h_raw not in ["--", "-", "None", ""]:
                                    m_c = re.search(r'\b(\d{1,2}:\d{2})\b', h_raw)
                                    t["hora_a_caminho"] = m_c.group(1).zfill(5) if m_c else h_raw
                            self.daily_accumulated_teams[code] = t

                        self.intraday_curve = data.get("intraday_curve", {})
                        self.daily_team_order_history = data.get("team_order_history", {})
                        self.daily_delay_justifications = data.get("delay_justifications", {})
                        for code_o, o_list in self.daily_team_order_history.items():
                            if isinstance(o_list, list):
                                for o in o_list:
                                    if isinstance(o, dict) and o.get("hora_a_caminho"):
                                        h_raw = str(o["hora_a_caminho"]).strip()
                                        if h_raw not in ["--", "-", "None", ""]:
                                            m_c = re.search(r'\b(\d{1,2}:\d{2})\b', h_raw)
                                            o["hora_a_caminho"] = m_c.group(1).zfill(5) if m_c else h_raw
                        raw_bid_cache = data.get("bid_cache", {})
                        # Purga estritamente qualquer registro que pertença a data anterior
                        self.bid_cache = {
                            k: v for k, v in raw_bid_cache.items()
                            if str(v.get("date_ref") or current_op_date) == current_op_date
                        }
                        self.last_bid_sync = data.get("last_bid_sync", "--")
                        if data.get("last_sync_time") and data.get("last_sync_time") != "--":
                            self.last_sync_time = data.get("last_sync_time")
                        if data.get("sync_source"):
                            self.sync_source = data.get("sync_source")
                        self.active_teams = [t for t in self.daily_accumulated_teams.values() if t.get("is_active", True)]

                        # Reavalia retroativamente as regras de turnos para garantir paridade 100%
                        self.reapply_retroactive_shift_rules()

                        # Hidrata o Módulo TRBOnet com as equipes ativas do cache
                        try:
                            from data_manager import data_manager
                            act_codes = [t["team_code"] for t in self.active_teams if t.get("is_active", True)]
                            act_details = {t["team_code"]: t for t in self.active_teams}
                            data_manager.update_from_enel(act_codes, act_details, source_label="Cache Local Enel SP")
                        except Exception:
                            pass
                    else:
                        print(f"[DELIVERY] Cache em disco ({cached_date}) é anterior ao dia operacional atual ({current_op_date}). Reiniciando acumulador...")
                        self.current_date_str = current_op_date
                        self.daily_accumulated_teams = {}
                        self.daily_team_order_history = {}
                        self.daily_delay_justifications = {}
                        self.intraday_curve = {}
                        self.bid_cache = {}
                        self.last_bid_sync = "--"
                        self.last_sync_time = "--"
        except Exception as e:
            print(f"[WARN] Não foi possível ler cache diário de entrega: {e}")

        # Sincronização Inteligente no Boot com a Nuvem Supabase
        try:
            from supabase_client import fetch_latest_delivery_snapshot_from_supabase, fetch_bid_records_by_date
            current_op_date = self.get_operational_date()
            cloud_snap = fetch_latest_delivery_snapshot_from_supabase(date_ref=current_op_date)
            if cloud_snap.get("status") == "success" and cloud_snap.get("data"):
                c_date = cloud_snap.get("date_ref")
                if c_date and c_date == current_op_date:
                    src_lbl = cloud_snap.get("sync_source") or "Nuvem Supabase (Boot)"
                    cap_at = cloud_snap.get("captured_at")
                    print(f"[DELIVERY] Boot sync: Hidratando {len(cloud_snap['data'])} equipes do Supabase ({cap_at})...", flush=True)
                    self.process_raw_enel_records(cloud_snap["data"], source_label=src_lbl, captured_at=cap_at)
                    self.save_local_cache()
                else:
                    print(f"[DELIVERY] Boot sync: Snapshot da nuvem ignorado (data {c_date} != {current_op_date}). Acumulador inicia limpo.", flush=True)

            # Hidrata também o BID para o dia corrente
            current_op = self.get_operational_date()
            bid_recs = fetch_bid_records_by_date(current_op)
            if bid_recs:
                self.process_raw_bid_records(bid_recs, current_op)

            # Hidrata as justificativas de atraso do Supabase para o dia corrente no boot
            self.hydrate_delay_justifications(current_op, force=True)
        except Exception as err_boot_sync:
            print(f"[DELIVERY] Boot sync Supabase falhou (usando contingência local): {err_boot_sync}", flush=True)

    def save_local_cache(self):
        """Grava em disco o acumulado do dia para resiliência a reinicializações."""
        try:
            payload = {
                "date": self.current_date_str,
                "last_sync_time": self.last_sync_time,
                "sync_source": self.sync_source,
                "accumulated_teams": self.daily_accumulated_teams,
                "team_order_history": self.daily_team_order_history,
                "delay_justifications": self.daily_delay_justifications,
                "intraday_curve": self.intraday_curve,
                "bid_cache": self.bid_cache,
                "last_bid_sync": self.last_bid_sync
            }
            tmp_file = f"{CACHE_FILE}.tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, CACHE_FILE)
        except Exception as e:
            print(f"[WARN] Falha ao salvar cache diário de entrega: {e}")

    def classify_vehicle(self, team_code: str, base_or_geo: str = "", date_ref: str = None) -> dict:
        """
        Classifica o tipo de veículo com base no código da equipe:
        - Projeto Ramal: Códigos específicos do PROJETO_RAMAL_CODES (Norte) ou códigos 200 da Base Leste (EML2, EVL2, EQL2, ESL2) a partir de 10/2026
        - Munck: Códigos específicos da lista MUNCK_CODES (exceto códigos 200 Leste a partir de 10/2026)
        - Cesto Aéreo: Dígito 1 após a base
        - Veículo Leve: Dígito 3 após a base
        - Moto: Dígito 7 após a base
        - Linha Viva: Demais códigos começando com dígito 2
        """
        code = str(team_code).strip().upper()
        d_ref = date_ref if date_ref is not None else self.current_date_str

        if code in PROJETO_RAMAL_CODES or is_projeto_ramal(code, base=base_or_geo, date_ref=d_ref):
            return {
                "type": "Projeto Ramal",
                "unified_group": "Projeto Ramal",
                "badge_class": "badge-vehicle-ramal",
                "pill_class": "pill-ramal",
                "category": "Projeto Ramal"
            }

        if code in ALL_STC_LESTE_CODES or is_stc_leste(code, base=base_or_geo, date_ref=d_ref):
            return {
                "type": "STC Leste",
                "unified_group": "STC Leste",
                "badge_class": "badge-vehicle-stc-leste",
                "pill_class": "pill-stc-leste",
                "category": "STC Leste"
            }

        if code in self.munck_codes:
            return {
                "type": "Munck",
                "unified_group": "Linha Viva + Munk",
                "badge_class": "badge-vehicle-munck",
                "pill_class": "pill-munck",
                "category": "Pesado"
            }

        digits = "".join([c for c in code if c.isdigit()])
        first_digit = digits[0] if digits else ""

        if first_digit in ("1", "6"):
            return {
                "type": "Cesto Aéreo",
                "unified_group": "Cesto Aéreo",
                "badge_class": "badge-vehicle-cesto",
                "pill_class": "pill-cesto",
                "category": "Pesado"
            }
        elif first_digit == "3":
            return {
                "type": "Veículo Leve",
                "unified_group": "Veículo Leve",
                "badge_class": "badge-vehicle-leve",
                "pill_class": "pill-leve",
                "category": "Leve"
            }
        elif first_digit == "7":
            return {
                "type": "Moto",
                "unified_group": "Moto",
                "badge_class": "badge-vehicle-moto",
                "pill_class": "pill-moto",
                "category": "Moto"
            }
        elif first_digit == "2":
            return {
                "type": "Linha Viva",
                "unified_group": "Linha Viva + Munk",
                "badge_class": "badge-vehicle-linhaviva",
                "pill_class": "pill-linhaviva",
                "category": "Pesado"
            }
        else:
            return {
                "type": "Outros",
                "unified_group": "Outros",
                "badge_class": "badge-vehicle-outros",
                "pill_class": "pill-outros",
                "category": "Apoio"
            }

    def parse_shift_window(self, shift_str: str, team_code: str = "", vehicle_type: str = "", marcacao_time: str = "",
                           base: str = "", region: str = "", geo: str = "", date_ref: str = "") -> dict:
        """
        Interpreta a escala da equipe e enquadra no turno oficial.
        
        Regra Operacional Atualizada:
        - Horário de Turno Ativo: Considera o horário da coluna Marcação (login efetivo).
        - Caso NÃO tenha horário de marcação no momento ('--'), considera o horário da coluna Turno Programado.
        - Se a equipe tiver horário de marcação: status_login = 'LOGADA'
        - Se a equipe NÃO tiver horário de marcação: status_login = 'PROGRAMADA'
        
        Macroregra Especial Projeto Ramal e Moto:
        - Horário sempre fixado no Turno 08:00 (Manhã), independente do horário do turno e do login/marcação.
        
        Macroregra Linha Viva e Munck (incluindo ENL211, ECL211, EEL211 e código 200):
        - Login até 17:00: enquadrado no Turno 08:00 (Manhã)
        - Login após 17:00: enquadrado no Turno 20:00 (Noite)
        
        Demais Equipes (Cesto Aéreo, Veículo Leve, etc.):
        - Turno 06:00: 04:00 às 07:35
        - Turno 08:00: 07:36 às 11:00
        - Turno 12:00: 11:01 às 13:35
        - Turno 14:00: 13:36 às 17:30
        - Turno 20:00: 17:36 às 21:50
        - Turno 22:00: 21:51 às 03:59
        """
        clean = str(shift_str or '').replace('–', '-').replace('—', '-').strip()
        parts = [p.strip() for p in clean.split('-') if p.strip()]
        login_time = parts[0] if len(parts) > 0 else "--:--"
        logoff_time = parts[1] if len(parts) > 1 else "--:--"

        # Classificação de Status Login:
        # Se tiver horário de marcação válido: LOGADA; se ausente ou '--': PROGRAMADA
        marc_clean = str(marcacao_time or '').strip()
        has_marcacao = bool(marc_clean and marc_clean not in ['--', '-', '', 'None', 'nan'])
        status_login = "LOGADA" if has_marcacao else "PROGRAMADA"

        # Horário de turno ativo: usa Marcação; se não houver, usa Turno Programado
        active_time_str = marc_clean if has_marcacao else login_time

        shift_slot = "Turno 08:00"
        shift_code = "08:00"
        shift_pill_class = "shift-08h"
        turno = "Manhã"

        total_min = None
        try:
            t_parts = active_time_str.split(':')
            if len(t_parts) >= 2:
                h = int(t_parts[0])
                m = int(t_parts[1])
                total_min = h * 60 + m
        except Exception:
            pass

        if is_projeto_ramal(team_code, vehicle_type, date_ref=self.current_date_str) or is_moto(team_code, vehicle_type):
            # Macroregra Especial Projeto Ramal e Moto: Entrada sempre fixada no Turno 08:00 (Manhã)
            shift_slot = "Turno 08:00"
            shift_code = "08:00"
            shift_pill_class = "shift-08h"
            turno = "Manhã"
        elif is_linha_viva_or_munck(team_code, vehicle_type, date_ref=self.current_date_str):
            if total_min is not None and total_min > 1020:  # Após 17:00 (17 * 60 = 1020)
                shift_slot = "Turno 20:00"
                shift_code = "20:00"
                shift_pill_class = "shift-20h"
                turno = "Noite"
            else:  # Até 17:00 ou sem horário de início definido
                shift_slot = "Turno 08:00"
                shift_code = "08:00"
                shift_pill_class = "shift-08h"
                turno = "Manhã"
        else:
            # Regra padrão para demais veículos
            if total_min is not None:
                if 240 <= total_min <= 455:      # 04:00 às 07:35
                    shift_slot = "Turno 06:00"
                    shift_code = "06:00"
                    shift_pill_class = "shift-06h"
                    turno = "Manhã"
                elif 456 <= total_min <= 660:    # 07:36 às 11:00
                    shift_slot = "Turno 08:00"
                    shift_code = "08:00"
                    shift_pill_class = "shift-08h"
                    turno = "Manhã"
                elif 661 <= total_min <= 815:    # 11:01 às 13:35
                    shift_slot = "Turno 12:00"
                    shift_code = "12:00"
                    shift_pill_class = "shift-12h"
                    turno = "Tarde"
                elif 816 <= total_min <= 1050:   # 13:36 às 17:30
                    shift_slot = "Turno 14:00"
                    shift_code = "14:00"
                    shift_pill_class = "shift-14h"
                    turno = "Tarde"
                elif 1051 <= total_min <= 1310:  # 17:36 às 21:50
                    shift_slot = "Turno 20:00"
                    shift_code = "20:00"
                    shift_pill_class = "shift-20h"
                    turno = "Noite"
                else:                            # 21:51 às 03:59
                    shift_slot = "Turno 22:00"
                    shift_code = "22:00"
                    shift_pill_class = "shift-22h"
                    turno = "Noite"

        sched = calculate_team_schedule(
            team_code=team_code,
            vehicle_type=vehicle_type,
            region=region,
            base=base,
            geo=geo,
            login_time=login_time,
            marcacao=marcacao_time,
            shift_code=shift_code,
            date_ref=date_ref or getattr(self, "current_date_str", "")
        )
        termino_calc = sched["termino"]

        return {
            "login_time": login_time,
            "logoff_time": termino_calc if termino_calc != "--:--" else logoff_time,
            "termino": termino_calc,
            "turno_x_login": sched["turno_x_login"],
            "turno_x_login_minutos": sched["turno_x_login_minutos"],
            "shift_hours": sched["shift_hours"],
            "shift_slot": shift_slot,
            "shift_code": shift_code,
            "shift_pill_class": shift_pill_class,
            "turno": turno,
            "status_login": status_login,
            "effective_shift_time": active_time_str
        }

    def reapply_retroactive_shift_rules(self):
        """
        Aplica retroativamente as regras de turnos e status de login a todas as equipes acumuladas e ativas:
        - Horário da Marcação define o enquadramento de turno ativo (com fallback para Turno Programado se '--')
        - Se possuir marcação: status_login = 'LOGADA'; se não possuir: status_login = 'PROGRAMADA'
        - Atualiza a curva intraday e salva o cache
        """
        for code, t in self.daily_accumulated_teams.items():
            base_hint = t.get("base_display") or t.get("geo") or t.get("base_raw")
            veh_info = self.classify_vehicle(code, base_or_geo=base_hint, date_ref=self.current_date_str)
            t["vehicle_type"] = veh_info["type"]
            t["unified_group"] = veh_info["unified_group"]
            t["vehicle_category"] = veh_info["category"]
            t["vehicle_badge_class"] = veh_info["badge_class"]
            t["vehicle_pill_class"] = veh_info["pill_class"]
            v_type = veh_info["type"]
            raw_shift = t.get("raw_shift") or t.get("shift_raw") or f"{t.get('login_time', '')}-{t.get('logoff_time', '')}"
            marcacao = t.get("marcacao") or "--"
            s_info = self.parse_shift_window(
                raw_shift,
                team_code=code,
                vehicle_type=v_type,
                marcacao_time=marcacao,
                base=base_hint,
                region=t.get("region", ""),
                geo=t.get("geo", ""),
                date_ref=self.current_date_str
            )
            t["shift_slot"] = s_info["shift_slot"]
            t["shift_code"] = s_info["shift_code"]
            t["shift_pill_class"] = s_info["shift_pill_class"]
            t["turno"] = s_info.get("turno", "Manhã" if s_info["shift_code"] in ["06:00", "08:00"] else "Noite")
            t["status_login"] = s_info.get("status_login", "PROGRAMADA")
            t["shift_hours"] = s_info.get("shift_hours", 8)
            t["termino"] = s_info.get("termino", "--")
            t["logoff_time"] = s_info.get("termino", t.get("logoff_time", "--"))
            t["turno_x_login"] = s_info.get("turno_x_login", "--")
            t["turno_x_login_minutos"] = s_info.get("turno_x_login_minutos", 0)

        # Atualiza equipes ativas espelhando as acumuladas
        self.active_teams = [t for t in self.daily_accumulated_teams.values() if t.get("is_active", True)]

        # Recalcula a curva intraday
        curve_calc = {"06:00": 0, "08:00": 0, "12:00": 0, "14:00": 0, "20:00": 0, "22:00": 0}
        for t in self.daily_accumulated_teams.values():
            sc = t.get("shift_code", "08:00")
            if sc in curve_calc:
                curve_calc[sc] += 1
        self.intraday_curve = curve_calc

    def _build_metrics_breakdown(self, team_list: list) -> dict:
        """Gera contadores detalhados para uma lista arbitrária de equipes."""
        total = len(team_list)
        cesto = sum(1 for t in team_list if t.get("vehicle_type") == "Cesto Aéreo")
        leve = sum(1 for t in team_list if t.get("vehicle_type") == "Veículo Leve" and not is_stc_leste(t.get("team_code", ""), t.get("vehicle_type", "")))
        moto = sum(1 for t in team_list if t.get("vehicle_type") == "Moto")
        munck = sum(1 for t in team_list if t.get("vehicle_type") == "Munck")
        linhaviva = sum(1 for t in team_list if t.get("vehicle_type") == "Linha Viva" and not is_projeto_ramal(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str))
        linhaviva_munck = linhaviva + munck
        ramal = sum(1 for t in team_list if t.get("vehicle_type") == "Projeto Ramal" or t.get("unified_group") == "Projeto Ramal" or is_projeto_ramal(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str))
        stc_leste = sum(1 for t in team_list if t.get("vehicle_type") == "STC Leste" or t.get("unified_group") == "STC Leste" or is_stc_leste(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str))

        # Contagem por turno
        shifts = {"06:00": 0, "08:00": 0, "12:00": 0, "14:00": 0, "20:00": 0, "22:00": 0}
        for t in team_list:
            sc = t.get("shift_code", "08:00")
            if sc in shifts:
                shifts[sc] += 1

        # Contagem hierárquica por Região Norte e Leste
        norte_teams = [t for t in team_list if t.get("geo") == "Norte"]
        leste_teams = [t for t in team_list if t.get("geo") == "Leste"]
        outras_teams = [t for t in team_list if t.get("geo") not in ["Norte", "Leste"]]

        def _base_block(sub_teams):
            logadas = [t for t in sub_teams if t.get("marcacao") and str(t.get("marcacao")).strip() not in ['--', '-', '', 'None', 'nan', '--:--']]
            return {
                "total": len(sub_teams),
                "total_logadas": len(logadas),
                "total_programadas": len(sub_teams) - len(logadas),
                "cesto": sum(1 for t in sub_teams if t.get("vehicle_type") == "Cesto Aéreo"),
                "leve": sum(1 for t in sub_teams if t.get("vehicle_type") == "Veículo Leve" and not is_stc_leste(t.get("team_code", ""), t.get("vehicle_type", ""))),
                "moto": sum(1 for t in sub_teams if t.get("vehicle_type") == "Moto"),
                "linhaviva_munck": sum(1 for t in sub_teams if t.get("vehicle_type") in ["Linha Viva", "Munck"] and not is_projeto_ramal(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str)),
                "munck": sum(1 for t in sub_teams if t.get("vehicle_type") == "Munck"),
                "linhaviva": sum(1 for t in sub_teams if t.get("vehicle_type") == "Linha Viva" and not is_projeto_ramal(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str)),
                "ramal": sum(1 for t in sub_teams if t.get("vehicle_type") == "Projeto Ramal" or t.get("unified_group") == "Projeto Ramal" or is_projeto_ramal(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str)),
                "stc_leste": sum(1 for t in sub_teams if t.get("vehicle_type") == "STC Leste" or t.get("unified_group") == "STC Leste" or is_stc_leste(t.get("team_code", ""), t.get("vehicle_type", ""), base=t.get("base_display") or t.get("geo"), date_ref=self.current_date_str))
            }

        bases_norte = {
            "Base Fagundes Filho": _base_block([t for t in norte_teams if t.get("base_display") == "Base Fagundes Filho"]),
            "Base Cajati": _base_block([t for t in norte_teams if t.get("base_display") == "Base Cajati"]),
            "Base Vila Medeiros": _base_block([t for t in norte_teams if t.get("base_display") == "Base Vila Medeiros"])
        }

        bases_leste = {
            "Base Monte Santo": _base_block([t for t in leste_teams if t.get("base_display") == "Base Monte Santo"]),
            "Base Aricanduva": _base_block([t for t in leste_teams if t.get("base_display") == "Base Aricanduva"]),
            "Base Catumbi": _base_block([t for t in leste_teams if t.get("base_display") == "Base Catumbi"]),
            "Base Santo André": _base_block([t for t in leste_teams if t.get("base_display") == "Base Santo André"])
        }

        return {
            "total": total,
            "cesto": cesto,
            "leve": leve,
            "moto": moto,
            "munck": munck,
            "linhaviva": linhaviva,
            "linhaviva_munck": linhaviva_munck,
            "ramal": ramal,
            "stc_leste": stc_leste,
            "shifts": shifts,
            "regiao_norte": {
                "total_block": _base_block(norte_teams),
                "bases": bases_norte
            },
            "regiao_leste": {
                "total_block": _base_block(leste_teams),
                "bases": bases_leste
            },
            "outras_bases": _base_block(outras_teams)
        }

    def process_raw_enel_records(self, raw_records: list, source_label="Portal Enel SP", captured_at=None) -> dict:
        """
        Processa linhas brutas extraídas do portal Enel, atualiza a lista de Equipes ATIVAS
        e adiciona de forma cumulativa e deduplicada ao histórico diário (Equipes TOTAL).
        """
        now = datetime.now(BR_TZ)
        op_date = self.get_operational_date(now)
        
        # Se virou o dia, reinicia o acumulado diário
        if op_date != self.current_date_str:
            print(f"[DELIVERY] Virada de dia operacional detectada ({self.current_date_str} -> {op_date}). Reiniciando acumulador diário das 04:31...")
            self.current_date_str = op_date
            self.daily_accumulated_teams = {}
            self.daily_team_order_history = {}
            self.intraday_curve = {}

        if captured_at:
            from supabase_client import format_datetime_br
            self.last_sync_time = format_datetime_br(captured_at)
        else:
            self.last_sync_time = now.strftime("%d/%m/%Y %H:%M:%S")
        self.sync_source = source_label

        active_dict = {}
        active_processed = []

        for rec in raw_records:
            gps_min_input = None
            data_desc_input = None
            hora_desc_input = None

            if isinstance(rec, dict):
                team_code = str(rec.get("EQUIPE") or rec.get("equipe") or rec.get("code") or rec.get("team_code") or "").strip().upper()
                shift_raw = rec.get("TURNO") or rec.get("turno") or rec.get("shift") or rec.get("login_time") or rec.get("shift_slot") or ""
                driver = rec.get("MOTORISTA") or rec.get("motorista") or rec.get("driver") or "--"
                vehicle_desc = rec.get("VEÍCULO") or rec.get("VEICULO") or rec.get("tipo_veiculo") or rec.get("vehicle_type") or ""
                tipo_oper = rec.get("TIPO") or rec.get("tipo") or rec.get("tipo_operacional") or ""
                status_oper = rec.get("STATUS") or rec.get("status") or "Logada"
                plate = rec.get("PLACA") or rec.get("placa") or rec.get("plate") or "--"
                ut = rec.get("UT") or rec.get("ut") or "--"
                base_raw = rec.get("BASE") or rec.get("base") or rec.get("base_name") or rec.get("base_code") or "--"
                filial = rec.get("FILIAL") or rec.get("filial") or "--"
                gps_raw = rec.get("GPS") or rec.get("gps") or rec.get("gps_update_str") or "--"
                gps_min_input = rec.get("gps_update_minutes")
                descanso_raw = rec.get("INICIO_DESCANSO") or rec.get("INÍCIO DESCANSO") or rec.get("inicio_descanso") or "--"
                data_desc_input = rec.get("data_inicio_descanso")
                hora_desc_input = rec.get("hora_inicio_descanso")
                ordem_raw = rec.get("ORDEM") or rec.get("ordem") or rec.get("ordem_servico") or "--"
                hora_a_caminho_raw = rec.get("HORA_A_CAMINHO") or rec.get("hora_a_caminho") or rec.get("HORA A CAMINHO") or "--"
                marcacao_raw = rec.get("MARCACAO") or rec.get("marcacao") or rec.get("MARCAÇÃO") or rec.get("marcação") or rec.get("RAW_MARCACAO") or "--"
                desvio_raw = rec.get("DESVIO") or rec.get("desvio") or "--"
                is_act_input = rec.get("is_active")
                is_active_val = bool(is_act_input) if is_act_input is not None else True
            elif isinstance(rec, (list, tuple)) and len(rec) >= 5:
                ut = rec[0] if len(rec) > 0 else "--"
                base_raw = rec[1] if len(rec) > 1 else "--"
                filial = rec[2] if len(rec) > 2 else "--"
                vehicle_desc = rec[3] if len(rec) > 3 else "--"
                team_code = str(rec[4]).strip().upper() if len(rec) > 4 else ""
                tipo_oper = rec[5] if len(rec) > 5 else "--"
                driver = rec[6] if len(rec) > 6 else "--"
                shift_raw = rec[7] if len(rec) > 7 else "--"
                marcacao_raw = rec[8] if len(rec) > 8 else "--"
                gps_raw = rec[9] if len(rec) > 9 else "--"
                status_oper = rec[10] if len(rec) > 10 else "Logada"
                plate = rec[11] if len(rec) > 11 else "--"
                descanso_raw = rec[12] if len(rec) > 12 else "--"
                ordem_raw = rec[13] if len(rec) > 13 else "--"
                hora_a_caminho_raw = rec[14] if len(rec) > 14 else "--"
                desvio_raw = "--"
                is_active_val = True
            else:
                continue

            if not team_code or team_code == 'NAN':
                continue

            prefix = team_code[:3]
            # Data Quality: descarta qualquer equipe fora das 7 bases oficiais definidas
            if prefix not in TARGET_PREFIXES:
                continue

            # Fallback Oficial de Filial: Se vier PSE ALPITEL ou contiver ALPITEL/PSE, normalizar para ALPITEL ENERGY
            filial_str = str(filial or "").strip()
            if "PSE" in filial_str.upper() or "ALPITEL" in filial_str.upper() or not filial_str or filial_str == "--":
                filial = "ALPITEL ENERGY"

            # Fallback Oficial de UT por prefixo de Base/Região:
            # Região Norte (ENL, ECL, EEL) = "UT Norte" | Região Leste (EML, EQL, EVL, ESL) = "UT Leste"
            if prefix in ['ENL', 'ECL', 'EEL']:
                ut = "UT Norte"
            elif prefix in ['EML', 'EQL', 'EVL', 'ESL']:
                ut = "UT Leste"
            else:
                ut = str(ut or "").strip() or "--"

            # Tratamento de MARCAÇÃO e DESVIO (Nova Coluna EquipesBrasil)
            m_str = str(marcacao_raw or "").strip()
            d_str = str(desvio_raw or "").strip()
            if "(" in m_str:
                parts = m_str.split("(")
                hora_marc = parts[0].strip()
                if d_str in ["--", ""]:
                    d_str = parts[1].replace(")", "").strip()
            else:
                hora_marc = m_str if m_str not in ['-', '', 'None', 'nan'] else "--"

            desvio_display = d_str if d_str not in ['-', '', 'None', 'nan'] else "--"
            desvio_minutos = 0
            if desvio_display != "--":
                try:
                    clean_d = desvio_display.replace("(", "").replace(")", "").replace("min", "").replace(" ", "")
                    is_neg = "-" in clean_d
                    nums = re.findall(r'\d+', clean_d)
                    if nums:
                        val = int(nums[0])
                        desvio_minutos = -val if is_neg else val
                except Exception:
                    desvio_minutos = 0

            # Tratamento de GPS (String original e Minutos inteiros)
            gps_str = str(gps_raw or "").strip()
            gps_update_str = gps_str if gps_str and gps_str not in ['-', '--', 'None', 'nan'] else "--"
            gps_update_minutes = None

            # 1. Se já veio gps_update_minutes válido (ex: vindo do banco Supabase ou processamento anterior)
            if 'gps_min_input' in locals() and gps_min_input is not None and str(gps_min_input).strip() not in ['', 'None', 'nan', '--']:
                try:
                    gps_update_minutes = int(gps_min_input)
                    if gps_update_str == "--":
                        gps_update_str = f"{gps_update_minutes}min"
                except Exception:
                    gps_update_minutes = None

            # 2. Se ainda não possui minutos inteiros, extrai de forma robusta da string do CDP
            if gps_update_minutes is None and gps_update_str != "--":
                try:
                    total_m = 0
                    has_match = False
                    h_match = re.search(r'(\d+)\s*h', gps_update_str, re.IGNORECASE)
                    m_match = re.search(r'(\d+)\s*m', gps_update_str, re.IGNORECASE)
                    if h_match:
                        total_m += int(h_match.group(1)) * 60
                        has_match = True
                    if m_match:
                        total_m += int(m_match.group(1))
                        has_match = True
                    elif not h_match and re.search(r'^\d+$', gps_update_str):
                        total_m = int(gps_update_str)
                        has_match = True
                    if has_match:
                        gps_update_minutes = total_m
                except Exception:
                    gps_update_minutes = None

            # Tratamento de INÍCIO DESCANSO (Separar Data e Hora)
            data_inicio_descanso = str(data_desc_input).strip() if ('data_desc_input' in locals() and data_desc_input and str(data_desc_input).strip() not in ['-', '--', 'None', 'nan']) else None
            hora_inicio_descanso = str(hora_desc_input).strip() if ('hora_desc_input' in locals() and hora_desc_input and str(hora_desc_input).strip() not in ['-', '--', 'None', 'nan']) else None

            descanso_str = str(descanso_raw or "").strip()
            if descanso_str and descanso_str not in ['-', '--', 'None', 'nan']:
                # Extração de hora no formato HH:MM
                time_match = re.search(r'\b\d{1,2}:\d{2}\b', descanso_str)
                if time_match and not hora_inicio_descanso:
                    hora_inicio_descanso = time_match.group(0)
                    if len(hora_inicio_descanso) == 4:
                        hora_inicio_descanso = f"0{hora_inicio_descanso}"
                # Extração de data no formato DD/MM
                date_match = re.search(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', descanso_str)
                if date_match and not data_inicio_descanso:
                    data_inicio_descanso = date_match.group(0)

            # Blindagem Operacional: Se a equipe já registrou início de descanso hoje, NUNCA perde o horário mesmo voltando a Em Atendimento
            if not hora_inicio_descanso and team_code in self.daily_accumulated_teams:
                prev_h_desc = self.daily_accumulated_teams[team_code].get("hora_inicio_descanso")
                if prev_h_desc and prev_h_desc not in ['-', '--', 'None', 'nan', '']:
                    hora_inicio_descanso = prev_h_desc
            if not data_inicio_descanso and team_code in self.daily_accumulated_teams:
                prev_d_desc = self.daily_accumulated_teams[team_code].get("data_inicio_descanso")
                if prev_d_desc and prev_d_desc not in ['-', '--', 'None', 'nan', '']:
                    data_inicio_descanso = prev_d_desc

            # Tratamento de ORDEM
            ordem_str = str(ordem_raw or "").strip()
            ordem_servico = ordem_str if ordem_str and ordem_str not in ['-', '--', 'NAN', 'nan'] else None

            # Tratamento de HORA A CAMINHO (Nova Coluna EquipesBrasil)
            caminho_str = str(hora_a_caminho_raw or "").strip()
            hora_a_caminho = "--"
            if caminho_str and caminho_str not in ['-', '--', 'None', 'nan']:
                t_match = re.search(r'\b(\d{1,2}:\d{2})\b', caminho_str)
                if t_match:
                    hora_a_caminho = t_match.group(1).zfill(5)
                else:
                    hora_a_caminho = caminho_str

            order_history_list = self.daily_team_order_history.setdefault(team_code, [])

            # Hidrata histórico de ordens persistido se disponível no payload
            if isinstance(rec, dict) and rec.get("order_history") and isinstance(rec["order_history"], list):
                for old_o in rec["order_history"]:
                    if isinstance(old_o, dict) and old_o.get("ordem"):
                        match = next((o for o in order_history_list if o.get("ordem") == old_o["ordem"]), None)
                        if not match:
                            order_history_list.append(dict(old_o))
                        else:
                            if match.get("hora_a_caminho") in ["--", None, ""] and old_o.get("hora_a_caminho"):
                                match["hora_a_caminho"] = old_o["hora_a_caminho"]

            # Recupera hora_a_caminho do histórico ou da equipe acumulada se não veio nesta leitura
            if hora_a_caminho == "--" and ordem_servico:
                hist_match = next((o for o in order_history_list if o.get("ordem") == ordem_servico and o.get("hora_a_caminho") not in ["--", "-", None, ""]), None)
                if hist_match:
                    h_cand = str(hist_match["hora_a_caminho"]).strip()
                    m_cand = re.search(r'\b(\d{1,2}:\d{2})\b', h_cand)
                    hora_a_caminho = m_cand.group(1).zfill(5) if m_cand else h_cand

            if hora_a_caminho == "--" and team_code in self.daily_accumulated_teams:
                prev_caminho = self.daily_accumulated_teams[team_code].get("hora_a_caminho")
                if prev_caminho and prev_caminho not in ["--", "-", "None", ""]:
                    p_cand = str(prev_caminho).strip()
                    m_cand = re.search(r'\b(\d{1,2}:\d{2})\b', p_cand)
                    hora_a_caminho = m_cand.group(1).zfill(5) if m_cand else p_cand

            # Rastreamento do Histórico de Ordens de Serviço (Deduplicação Inteligente a cada 120s)
            # Regra: Se a mesma ordem se repetir em várias atualizações, permanece registrada uma única vez!
            now_time_str = now.strftime("%H:%M:%S")
            if ordem_servico:
                existing_order = next((o for o in order_history_list if o.get("ordem") == ordem_servico), None)
                if existing_order:
                    existing_order["last_seen"] = now_time_str
                    existing_order["status"] = status_oper
                    existing_order["cycles_count"] = existing_order.get("cycles_count", 1) + 1
                    if hora_a_caminho != "--":
                        m_c = re.search(r'\b(\d{1,2}:\d{2})\b', str(hora_a_caminho))
                        existing_order["hora_a_caminho"] = m_c.group(1).zfill(5) if m_c else hora_a_caminho
                else:
                    m_c = re.search(r'\b(\d{1,2}:\d{2})\b', str(hora_a_caminho))
                    c_clean = m_c.group(1).zfill(5) if m_c else hora_a_caminho
                    order_history_list.append({
                        "ordem": ordem_servico,
                        "hora_a_caminho": c_clean,
                        "first_seen": now_time_str,
                        "last_seen": now_time_str,
                        "status": status_oper,
                        "cycles_count": 1
                    })

            # Cruzamento de Placa com o Inventário de Frotas (Controle Operacional)
            plate_val = str(plate or "").strip()
            plate_display = plate_val if plate_val and plate_val not in ['-', '--'] else "--"
            from fleet_client import fleet_client
            fleet_match = fleet_client.cross_reference_plate(plate_display)

            base_info = self.official_bases.get(prefix)

            if base_info:
                base_code = prefix
                base_name = base_info["name"]
                region = base_info["region"]
                company = base_info["company"]
                geo = base_info["geo"]
                base_display = base_info["base_display"]
                is_official = True
            else:
                base_code = prefix
                base_name = base_raw if base_raw != "--" else f"Base {prefix}"
                region = "Outras Bases"
                company = "Outros"
                geo = "Outras"
                base_display = base_name
                is_official = False

            veh_info = self.classify_vehicle(team_code, base_or_geo=base_display or geo or base_raw, date_ref=self.current_date_str)
            shift_info = self.parse_shift_window(
                shift_raw,
                team_code=team_code,
                vehicle_type=veh_info.get("type"),
                marcacao_time=hora_marc,
                base=base_display or geo or base_raw,
                region=region,
                geo=geo,
                date_ref=self.current_date_str
            )

            # Enriquecimento com dados da Visão Operacional BidTech (Checklists)
            bid_entry = self.bid_cache.get(team_code)
            status_bid = normalize_bid_status(bid_entry.get("status_bid")) if bid_entry else ("Não Encontrada" if self.last_bid_sync != "--" else "--")

            team_obj = {
                "team_code": team_code,
                "prefix": prefix,
                "base_code": base_code,
                "base_name": base_name,
                "base_display": base_display,
                "region": region,
                "geo": geo,
                "company": company,
                "is_official": is_official,
                "driver": driver,
                "plate": plate_display,
                "plate_clean": fleet_match.get("plate_clean", ""),
                "plate_cadastrada": fleet_match.get("plate_cadastrada", False),
                "situacao_veiculo_cadastrado": fleet_match.get("situacao_veiculo_cadastrado", "SEM PLACA INFORMADA"),
                "status_veiculo_cadastrado": fleet_match.get("status_veiculo_cadastrado", "--"),
                "ut": ut,
                "filial": filial,
                "veiculo_portal": str(vehicle_desc or "--").strip(),
                "tipo_operacional": tipo_oper,
                "status": status_oper,
                "status_equipes_brasil": status_oper,
                "status_login": shift_info.get("status_login", "PROGRAMADA"),
                "status_bid": status_bid,
                "bid_info": bid_entry,
                "marcacao": hora_marc,
                "desvio": desvio_display,
                "desvio_minutos": desvio_minutos,
                "gps_update_str": gps_update_str,
                "gps_update_minutes": gps_update_minutes,
                "data_inicio_descanso": data_inicio_descanso,
                "hora_inicio_descanso": hora_inicio_descanso,
                "ordem_servico": ordem_servico,
                "hora_a_caminho": hora_a_caminho,
                "order_history": [dict(o) for o in order_history_list],
                "is_active": is_active_val,
                "vehicle_type": veh_info["type"],
                "unified_group": veh_info["unified_group"],
                "vehicle_category": veh_info["category"],
                "vehicle_badge_class": veh_info["badge_class"],
                "vehicle_pill_class": veh_info["pill_class"],
                "login_time": shift_info["login_time"],
                "logoff_time": shift_info.get("termino", shift_info["logoff_time"]),
                "termino": shift_info.get("termino", "--"),
                "turno_x_login": shift_info.get("turno_x_login", "--"),
                "turno_x_login_minutos": shift_info.get("turno_x_login_minutos", 0),
                "delay_justification": self.daily_delay_justifications.get(team_code),
                "shift_hours": shift_info.get("shift_hours", 8),
                "shift_slot": shift_info["shift_slot"],
                "shift_code": shift_info["shift_code"],
                "shift_pill_class": shift_info["shift_pill_class"],
                "turno": shift_info.get("turno", "Manhã"),
                "raw_shift": str(shift_raw),
                "last_seen_time": now.strftime("%H:%M:%S")
            }
            if is_active_val:
                team_obj["seen_active_today"] = True
                # Se a equipe já existia no acumulado com valores ricos e team_obj veio com vazios (ex: sync de nuvem):
                if team_code in self.daily_accumulated_teams:
                    prev = self.daily_accumulated_teams[team_code]
                    for rich_k in ["marcacao", "gps_update_str", "gps_update_minutes", "hora_inicio_descanso", "data_inicio_descanso", "ordem_servico", "hora_a_caminho", "desvio", "desvio_minutos"]:
                        if team_obj.get(rich_k) in ["--", None, "", -9999] and prev.get(rich_k) not in ["--", None, "", -9999]:
                            team_obj[rich_k] = prev.get(rich_k)
                active_dict[team_code] = team_obj

            # Acumula no histórico do dia
            if team_code not in self.daily_accumulated_teams:
                # Se vier inativa em carga de snapshot e nunca foi vista ativa hoje no dia operacional, não adiciona
                if not is_active_val and not team_obj.get("seen_active_today"):
                    continue
                team_copy = dict(team_obj)
                team_copy["first_seen_time"] = now.strftime("%H:%M:%S")
                self.daily_accumulated_teams[team_code] = team_copy
            else:
                # Atualiza com as informações mais recentes mantendo first_seen_time
                existing = self.daily_accumulated_teams[team_code]
                if is_active_val:
                    existing["seen_active_today"] = True
                f_seen = existing.get("first_seen_time", now.strftime("%H:%M:%S"))
                for k, v in team_obj.items():
                    if k == "first_seen_time":
                        continue
                    # Se o novo valor for vazio/None/-- mas o existente já tinha valor operacional válido, preserva!
                    if v in ["--", None, "", -9999] and existing.get(k) not in ["--", None, "", -9999]:
                        continue
                    existing[k] = v
                existing["first_seen_time"] = f_seen
                existing["is_active"] = is_active_val

        active_processed = sorted(list(active_dict.values()), key=lambda x: x["team_code"])

        # Marca equipes acumuladas que saíram da lista ativa nesta coleta
        active_codes = set(active_dict.keys())
        now_min = now.hour * 60 + now.minute
        for code, t in list(self.daily_accumulated_teams.items()):
            if code not in active_codes:
                # Se a equipe nunca foi vista ativa hoje no dia operacional, purga imediatamente (registro fantasma)
                if not t.get("seen_active_today"):
                    del self.daily_accumulated_teams[code]
                    continue
                t["is_active"] = False
                t["status"] = "Deslogada / Turno Concluído"
                # Se for após as 04:30 e for turno da noite anterior (20h/22h), descarta do acumulado do dia atual
                if (now.hour > 4 or (now.hour == 4 and now.minute >= 31)) and t.get("shift_code") in ["20:00", "22:00"]:
                    del self.daily_accumulated_teams[code]
                    continue
                # Se a equipe estiver inativa e pertencer a um turno futuro cujo início ainda não ocorreu hoje, descarta
                sc_cand = t.get("shift_code", "08:00")
                sc_min = {"06:00": 360, "08:00": 480, "12:00": 720, "14:00": 840, "20:00": 1200, "22:00": 1320}.get(sc_cand, 480)
                if sc_min > now_min:
                    del self.daily_accumulated_teams[code]

        self.active_teams = active_processed

        # Registra ponto na curva intraday por faixa de horário (06h, 08h, 12h, 14h, 20h, 22h)
        for t in self.daily_accumulated_teams.values():
            s_code = t.get("shift_code", "08:00")
            if s_code not in self.intraday_curve:
                self.intraday_curve[s_code] = 0
            # A curva de turnos registra as equipes acumuladas que entraram por turno
        
        # Recalcula a contagem de turnos acumulada
        curve_calc = {"06:00": 0, "08:00": 0, "12:00": 0, "14:00": 0, "20:00": 0, "22:00": 0}
        for t in self.daily_accumulated_teams.values():
            sc = t.get("shift_code", "08:00")
            if sc in curve_calc:
                curve_calc[sc] += 1
        self.intraday_curve = curve_calc
        self.save_local_cache()
        self.clear_audit_cache(self.current_date_str)

        # Integração Automática com o Módulo TRBOnet:
        # Alimenta a lista de equipes do TRBOnet diretamente com as equipes ativas da Enel SP
        try:
            from data_manager import data_manager
            act_codes = [t["team_code"] for t in self.active_teams if t.get("is_active")]
            act_details = {t["team_code"]: t for t in self.active_teams}
            data_manager.update_from_enel(act_codes, act_details, source_label="Robô CDP Enel SP")
        except Exception as err:
            print(f"[INTEGRATION WARN] Erro ao sincronizar Enel com TRBOnet: {err}")

        return self.get_consolidated_state()

    def get_active_teams(self) -> list:
        """Retorna lista das equipes ativas no momento."""
        return list(self.active_teams or [])

    def get_all_teams_today(self) -> list:
        """Retorna todas as equipes acumuladas do dia (deduplicadas)."""
        return list(self.daily_accumulated_teams.values() if self.daily_accumulated_teams else [])

    def get_consolidated_state(self) -> dict:
        """Retorna o estado operacional completo com Ativas vs Total e agrupamento de bases."""
        # Garante hidratação contínua das justificativas de atraso do Supabase
        self.hydrate_delay_justifications(self.current_date_str)

        active_list = self.active_teams
        total_list = sorted(list(self.daily_accumulated_teams.values()), key=lambda x: x["team_code"])

        for t in total_list:
            c = t.get("team_code")
            if c in self.daily_delay_justifications:
                t["delay_justification"] = self.daily_delay_justifications[c]
        for t in active_list:
            c = t.get("team_code")
            if c in self.daily_delay_justifications:
                t["delay_justification"] = self.daily_delay_justifications[c]

        metrics_active = self._build_metrics_breakdown(active_list)
        metrics_total = self._build_metrics_breakdown(total_list)

        ts = self.last_sync_time
        if not ts or ts == "--":
            for t in (active_list or total_list):
                cand = t.get("captured_at") or t.get("last_seen_time") or t.get("marcacao")
                if cand and cand != "--":
                    ts = format_datetime_br(cand)
                    self.last_sync_time = ts
                    break

        return {
            "status": "success",
            "date": self.current_date_str,
            "timestamp": ts or "--",
            "last_sync": ts or "--",
            "sync_source": self.sync_source,
            # Equipes ATIVAS (momento presente)
            "active_teams": active_list,
            "active_total": len(active_list),
            "summary_active": metrics_active,
            # Equipes TOTAL (acumulado deduplicado do dia)
            "daily_total_teams": total_list,
            "total_delivered_day": len(total_list),
            "summary_total": metrics_total,
            # Curva Intraday de entrada por turno
            "intraday_curve": self.intraday_curve,
            # Estrutura hierárquica das bases para renderização ágil
            "geo_groups": self.geo_groups,
            # Justificativas de atraso de entrada da data
            "delay_justifications": self.daily_delay_justifications,
            # Resumo Forense dos Últimos 3 Dias (Norte x Leste x Total) para o Hub Central
            "recent_3days": self.get_recent_3days_audit_summary(today_metrics=metrics_total)
        }

    def get_team_details(self, team_code: str) -> dict:
        """
        Retorna os detalhes completos da equipe no dia operacional,
        incluindo o histórico deduplicado de ordens de serviço e dados da Visão Operacional BidTech.
        """
        code = str(team_code).strip().upper()
        team_data = self.daily_accumulated_teams.get(code)
        if not team_data:
            for t in self.active_teams:
                if t.get("team_code") == code:
                    team_data = t
                    break

        history = self.daily_team_order_history.get(code, [])
        bid_info = self.bid_cache.get(code, {})

        return {
            "status": "success",
            "team_code": code,
            "found": bool(team_data or bid_info),
            "team_data": team_data or {},
            "order_history": list(history),
            "bid_info": bid_info or {}
        }

    def process_raw_bid_records(self, raw_records: list, date_ref: str = None):
        """
        Recebe a lista de registros extraídos da Visão Operacional BidTech via CDP.
        Atualiza o cache em memória e enriquece as equipes acumuladas e ativas.
        """
        if not date_ref:
            date_ref = self.get_operational_date()

        # Garante que o bid_cache mantenha estritamente os registros válidos extraídos
        new_bid_cache = {}
        for r in raw_records:
            code = str(r.get("team_code", "")).strip().upper()
            if code:
                r_copy = dict(r)
                r_copy["date_ref"] = date_ref
                r_copy["status_bid"] = normalize_bid_status(r.get("status_bid"))
                new_bid_cache[code] = r_copy

        self.bid_cache = new_bid_cache

        now = datetime.now(BR_TZ)
        self.last_bid_sync = now.strftime("%d/%m/%Y %H:%M:%S")

        # Atualiza o status_bid nas equipes acumuladas e ativas
        for code, t in self.daily_accumulated_teams.items():
            b_info = self.bid_cache.get(code)
            t["status_bid"] = normalize_bid_status(b_info.get("status_bid")) if b_info else "Não Encontrada"
            t["bid_info"] = b_info

        for t in self.active_teams:
            code = t.get("team_code")
            b_info = self.bid_cache.get(code)
            t["status_bid"] = b_info.get("status_bid") if b_info else "Não Encontrada"
            t["bid_info"] = b_info

        self.save_local_cache()

    def get_online_x_bid_state(self, date_str: str = None) -> dict:
        """
        Retorna a reconciliação forense completa entre Equipes Brasil (Logadas/Ativas)
        e a Visão Operacional BidTech (Checklists & Em Operação).
        """
        current_op = self.get_operational_date()
        if current_op != self.current_date_str:
            self.current_date_str = current_op

        if not date_str:
            date_str = current_op
        else:
            # Blindagem contra divergência de calendário civil vs operacional:
            # Durante a madrugada (00:00 às 04:30), o dia civil já avançou (ex: 2026-09-19),
            # mas o dia operacional Enel/CCO ainda é ontem (2026-09-18).
            # Se o front-end ou cliente enviar a data civil atual ou uma data futura,
            # normaliza para a data operacional vigente.
            now_br = datetime.now(BR_TZ)
            civil_today = now_br.date().isoformat()
            if date_str > current_op or (date_str == civil_today and current_op != civil_today):
                date_str = current_op

        is_today = (date_str == current_op)
        is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'

        # 1. Obtém universo do EquipesBrasil
        # Regra Estrita: no painel online em tempo real de hoje, somente equipes presentes na extração corrente
        # do EB são consideradas (seja como LOGADA ou como PROGRAMADA). Se a equipe não constar mais na extração,
        # ela não é considerada nem ativa e nem programada.
        eb_teams = {}
        try:
            from supabase_client import fetch_delivery_records_by_date, fetch_latest_delivery_snapshot_from_supabase
            if is_today:
                if not self.active_teams and not self.daily_accumulated_teams:
                    cloud_snap = fetch_latest_delivery_snapshot_from_supabase(date_ref=current_op)
                    if cloud_snap.get("status") == "success" and cloud_snap.get("data") and cloud_snap.get("date_ref") == current_op:
                        self.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase", captured_at=cloud_snap.get("captured_at"))

                if self.active_teams:
                    eb_teams = {t["team_code"]: dict(t) for t in self.active_teams}
                elif self.daily_accumulated_teams:
                    eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values() if t.get("is_active", True)}
            else:
                deliv_records = fetch_delivery_records_by_date(date_str)
                if deliv_records:
                    eb_teams = {r["team_code"]: r for r in deliv_records if r.get("team_code")}
                elif self.active_teams:
                    eb_teams = {t["team_code"]: dict(t) for t in self.active_teams}
                elif self.daily_accumulated_teams:
                    eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values() if not is_today or t.get("is_active", True)}

                # Complementa/enriquece com registros analíticos do Scanner caso os registros de delivery do dia sejam escassos
                if len(eb_teams) < 50:
                    try:
                        from supabase_client import BASE_REST_URL, get_headers
                        import requests
                        url_scan = f"{BASE_REST_URL}/team_scanner_records?data_referencia=eq.{date_str}&limit=2000"
                        resp_s = requests.get(url_scan, headers=get_headers(), timeout=10)
                        if resp_s.status_code == 200:
                            for s in resp_s.json() or []:
                                c = str(s.get("equipe_normalizada") or "").strip().upper()
                                if c and c not in eb_teams and c[:3] in TARGET_PREFIXES:
                                    log_raw = str(s.get("login") or s.get("login_corrigido") or "--")
                                    eb_teams[c] = {
                                        "team_code": c,
                                        "date_ref": date_str,
                                        "login_time": log_raw[-8:] if len(log_raw) >= 8 else log_raw,
                                        "logoff_time": str(s.get("logoff") or s.get("logoff_corrigido") or "--")[-8:],
                                        "shift_slot": "Turno 08:00",
                                        "status": "Deslogada / Turno Concluído",
                                        "base_display": f"Base {s.get('base') or ''}",
                                        "is_active": True
                                    }
                    except Exception as e_scan:
                        print(f"[ONLINE x BID SCANNER FALLBACK WARN] {e_scan}")
        except Exception as err:
            print(f"[ONLINE x BID ERROR] Falha ao consultar Supabase para EB {date_str}: {err}")
            if self.active_teams:
                eb_teams = {t["team_code"]: dict(t) for t in self.active_teams}
            elif self.daily_accumulated_teams:
                eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values() if not is_today or t.get("is_active", True)}

        # 2. Obtém universo da Visão Operacional BID
        bid_records_map = {}
        bid_last_sync_time = self.last_bid_sync
        try:
            from supabase_client import fetch_bid_records_by_date, format_datetime_br
            bid_list = fetch_bid_records_by_date(date_str)
            if bid_list:
                bid_records_map = {r["team_code"]: r for r in bid_list if r.get("team_code")}
                if not bid_last_sync_time:
                    cap = bid_list[0].get("captured_at") or bid_list[0].get("updated_at")
                    if cap:
                        bid_last_sync_time = format_datetime_br(cap)
                if is_today:
                    for r in bid_list:
                        code = str(r.get("team_code", "")).strip().upper()
                        if code:
                            self.bid_cache[code] = dict(r)
            elif self.bid_cache:
                bid_records_map = {
                    k: dict(v) for k, v in self.bid_cache.items()
                    if str(v.get("date_ref") or date_str) == date_str
                }
        except Exception as err:
            print(f"[ONLINE x BID ERROR] Falha ao consultar Supabase para BID {date_str}: {err}")
            if self.bid_cache:
                bid_records_map = {
                    k: dict(v) for k, v in self.bid_cache.items()
                    if str(v.get("date_ref") or date_str) == date_str
                }

        def normalize_bid_status(raw_status):
            if not raw_status or str(raw_status).strip() in ["--", "NONE", "NULL", ""]:
                return "Não Encontrada"
            st = str(raw_status).strip()
            s_up = st.upper()
            if "OPERA" in s_up:
                return "Em Operação"
            elif "CHECKLIST" in s_up:
                return "Em Checklist"
            elif "PLANEJAD" in s_up:
                return "Planejada"
            elif "RETORNAD" in s_up:
                return "Retornada"
            elif "BLOQUEAD" in s_up:
                return "Bloqueada"
            return st

        # 3. Cruzamento Forense Linha a Linha
        all_team_codes = set(eb_teams.keys()) | set(bid_records_map.keys())
        reconciled_rows = []

        kpis = {
            "total_logadas_eb": 0,
            "total_em_operacao_bid": 0,
            "conforme": 0,            # Logada no EB e Em Operação no BID
            "alerta_critico": 0,      # Logada no EB e Em Checklist no BID
            "alerta_grave": 0,        # Logada no EB e Planejada no BID
            "alerta_gravissimo": 0,   # Logada no EB e Não Encontrada no BID
            "alerta_impeditivo": 0,   # Logada no EB e Bloqueada/Retornada no BID
            "aguardando_apresentacao": 0, # BID Planejada mas deslogada/não logada no EB
            "bid_sem_login_eb": 0     # BID Em Operação mas deslogada no EB
        }

        for code in sorted(all_team_codes):
            prefix = code[:3]
            # Data Quality: Mantém foco nas 7 bases oficiais definidas
            if prefix not in TARGET_PREFIXES:
                continue

            eb = eb_teams.get(code)
            bid = bid_records_map.get(code)

            if is_today:
                is_eb_active = eb.get("is_active", True) if eb else False
            else:
                # Em datas passadas consolidadas, qualquer equipe presente nos registros de entrega trabalhou/logou no dia
                is_eb_active = True if eb else False
            eb_status = eb.get("status", "Deslogada") if eb else "Não Logada"
            bid_status = normalize_bid_status(bid.get("status_bid") if bid else "Não Encontrada")

            cross_status = "NÃO_CLASSIFICADO"
            cross_severity = "neutral"
            cross_badge = "badge-neutral"
            cross_desc = ""

            if is_eb_active:
                kpis["total_logadas_eb"] += 1

                if bid_status == "Em Operação":
                    cross_status = "CONFORME"
                    cross_severity = "success"
                    cross_badge = "badge-conforme"
                    cross_desc = "Checklist Concluído • Em Operação"
                    kpis["conforme"] += 1
                elif bid_status == "Em Checklist":
                    cross_status = "ALERTA CRÍTICO"
                    cross_severity = "warning"
                    cross_badge = "badge-alerta-critico"
                    cross_desc = "Logada • Checklist em Andamento"
                    kpis["alerta_critico"] += 1
                elif bid_status == "Planejada":
                    cross_status = "ALERTA GRAVE"
                    cross_severity = "danger"
                    cross_badge = "badge-alerta-grave"
                    cross_desc = "Logada • Sem Iniciar Checklist"
                    kpis["alerta_grave"] += 1
                elif bid_status in ["Bloqueada", "Retornada"]:
                    cross_status = "ALERTA IMPEDITIVO"
                    cross_severity = "danger"
                    cross_badge = "badge-alerta-impeditivo"
                    cross_desc = f"Logada • Status Checklist: {bid_status}"
                    kpis["alerta_impeditivo"] += 1
                else:
                    cross_status = "ALERTA GRAVÍSSIMO"
                    cross_severity = "purple"
                    cross_badge = "badge-alerta-gravissimo"
                    cross_desc = "Logada • Não Encontrada no Checklist"
                    kpis["alerta_gravissimo"] += 1
            else:
                if bid_status == "Em Operação":
                    cross_status = "BID SEM LOGIN EB"
                    cross_severity = "orange"
                    cross_badge = "badge-alerta-orange"
                    cross_desc = "Em Operação no Checklist • Não Logada"
                    kpis["bid_sem_login_eb"] += 1
                elif bid_status == "Planejada":
                    cross_status = "AGUARDANDO APRESENTAÇÃO"
                    cross_severity = "info"
                    cross_badge = "badge-aguardando"
                    cross_desc = "Planejada no Checklist • Não Logada"
                    kpis["aguardando_apresentacao"] += 1
                elif bid_status == "Em Checklist":
                    cross_status = "CHECKLIST PRÉVIO"
                    cross_severity = "info"
                    cross_badge = "badge-info"
                    cross_desc = "Em Checklist • Não Logada"
                elif bid_status in ["Bloqueada", "Retornada"]:
                    cross_status = "BID SEM LOGIN EB"
                    cross_severity = "orange"
                    cross_badge = "badge-alerta-orange"
                    cross_desc = f"{bid_status} no Checklist • Não Logada no Despacho"
                    kpis["bid_sem_login_eb"] += 1
                else:
                    continue

            if bid_status == "Em Operação":
                kpis["total_em_operacao_bid"] += 1

            base_info = self.official_bases.get(prefix, {})
            base_display = (eb.get("base_display") if eb else None) or base_info.get("base_display") or (f"Base {bid.get('base')}" if bid and bid.get("base") else f"Base {prefix}")
            geo = (eb.get("geo") if eb else None) or base_info.get("geo") or "--"
            # Turno estritamente do Equipes Brasil (conforme requisito operacional)
            turno = (eb.get("shift_slot") or eb.get("shift_code") or eb.get("raw_shift") or "--") if eb else "--"
            shift_pill_class = eb.get("shift_pill_class", "") if eb else ""
            driver = (eb.get("driver") if eb else None) or (bid.get("driver") if bid else "--")
            
            # Validação Forense de Placas (Divergência entre Despacho e Checklist)
            raw_plate_eb = (eb.get("plate") or "").strip().upper() if eb else ""
            raw_plate_bid = (bid.get("plate") or "").strip().upper() if bid else ""
            plate_eb = raw_plate_eb if raw_plate_eb not in ["--", "NONE", "NULL", ""] else ""
            plate_bid = raw_plate_bid if raw_plate_bid not in ["--", "NONE", "NULL", ""] else ""
            norm_eb = plate_eb.replace("-", "").replace(" ", "")
            norm_bid = plate_bid.replace("-", "").replace(" ", "")

            plate_divergent = False
            plate_match = False
            if norm_eb and norm_bid:
                if norm_eb != norm_bid:
                    plate_divergent = True
                else:
                    plate_match = True

            plate_display = plate_eb or plate_bid or "--"
            vehicle_type = (eb.get("vehicle_type") if eb else None) or (bid.get("vehicle_type") if bid else "--")

            termino_val = (eb.get("termino") or eb.get("logoff_time")) if eb else "--"
            turno_x_login_val = eb.get("turno_x_login") if eb else "--"
            turno_x_login_min_val = eb.get("turno_x_login_minutos", 0) if eb else 0
            shift_hours_val = eb.get("shift_hours", 8) if eb else 8

            if eb and (not termino_val or termino_val in ["--", "--:--"]):
                calc = calculate_team_schedule(
                    team_code=code,
                    vehicle_type=vehicle_type,
                    region=eb.get("region", ""),
                    base=base_display,
                    geo=geo,
                    login_time=eb.get("login_time", "--:--"),
                    marcacao=eb.get("marcacao", "--"),
                    shift_code=eb.get("shift_code", "08:00"),
                    date_ref=date_str
                )
                termino_val = calc["termino"]
                turno_x_login_val = calc["turno_x_login"]
                turno_x_login_min_val = calc["turno_x_login_minutos"]
                shift_hours_val = calc["shift_hours"]

            # Quantidade de OS Coletadas no Dia
            order_hist = (eb.get("order_history") if eb else None) or self.daily_team_order_history.get(code, [])
            distinct_orders = set()
            if isinstance(order_hist, list):
                for o_item in order_hist:
                    if isinstance(o_item, dict) and o_item.get("ordem"):
                        val = str(o_item["ordem"]).strip()
                        if val and val not in ["--", "-", "None", "nan", ""]:
                            distinct_orders.add(val)
                    elif isinstance(o_item, str):
                        val = o_item.strip()
                        if val and val not in ["--", "-", "None", "nan", ""]:
                            distinct_orders.add(val)
            
            curr_os = eb.get("ordem_servico") if eb else None
            if curr_os and str(curr_os).strip() not in ["--", "-", "None", "nan", ""]:
                distinct_orders.add(str(curr_os).strip())

            qtd_os_coletadas = len(distinct_orders)

            row_item = {
                "team_code": code,
                "prefix": prefix,
                "base_display": base_display,
                "geo": geo,
                "turno": turno,
                "shift_pill_class": shift_pill_class,
                "driver": driver,
                "plate": plate_display,
                "plate_eb": plate_eb or "--",
                "plate_bid": plate_bid or "--",
                "plate_divergent": plate_divergent,
                "plate_match": plate_match,
                "vehicle_type": vehicle_type,
                "is_eb_active": is_eb_active,
                "status_eb": eb_status,
                "status_prog": eb_status,
                "status_login": (eb.get("status_login") or ("LOGADA" if (eb.get("marcacao") and str(eb.get("marcacao")).strip() not in ["--", "-", "", "None", "nan"]) else "PROGRAMADA")) if eb else "--",
                "status_bid": bid_status,
                "cross_status": cross_status,
                "cross_severity": cross_severity,
                "cross_badge": cross_badge,
                "cross_desc": cross_desc,
                "bid_phone": bid.get("phone") if bid else "--",
                "bid_tipo_operacional": bid.get("tipo_operacional") if bid else "--",
                "bid_members": bid.get("members", []) if bid else [],
                "bid_timer_label": bid.get("timer_label") if bid else "",
                "bid_timer_value": bid.get("timer_value") if bid else "--",
                "login_time_eb": eb.get("login_time") if eb else "--",
                "marcacao_eb": eb.get("marcacao") if eb else "--",
                "termino": termino_val,
                "turno_x_login": turno_x_login_val,
                "turno_x_login_minutos": turno_x_login_min_val,
                "shift_hours": shift_hours_val,
                "ordem_servico": eb.get("ordem_servico") if eb else "--",
                "hora_a_caminho": eb.get("hora_a_caminho") if eb else "--",
                "qtd_os_coletadas": qtd_os_coletadas,
                "delay_justification": (eb.get("delay_justification") if eb else None) or self.daily_delay_justifications.get(code),
                "order_history": [dict(o) for o in order_hist] if isinstance(order_hist, list) else [],
                "hora_inicio_descanso": eb.get("hora_inicio_descanso") if eb else None,
                "data_inicio_descanso": eb.get("data_inicio_descanso") if eb else None,
                "gps_update_minutes": eb.get("gps_update_minutes") if eb else None,
                "gps_update_str": eb.get("gps_update_str") if eb else "--"
            }
            reconciled_rows.append(row_item)

        taxa = round((kpis["conforme"] / kpis["total_logadas_eb"] * 100), 1) if kpis["total_logadas_eb"] > 0 else 0.0
        kpis["indice_conformidade"] = taxa

        return {
            "status": "success",
            "date": date_str,
            "last_bid_sync": bid_last_sync_time or self.last_bid_sync or "--:--:--",
            "last_eb_sync": self.last_sync_time,
            "kpis": kpis,
            "rows": reconciled_rows,
            "total_rows": len(reconciled_rows)
        }

    def reconcile_with_spotfire_records(self, spotfire_records: list, date_ref: str = None):
        """Atualiza o cache de registros do Spotfire/Scanner e mescla com as equipes acumuladas do dia."""
        if not date_ref:
            date_ref = self.get_operational_date()
        for r in spotfire_records:
            norm = r.get("equipe_normalizada") or normalize_team_code(r.get("equipe", ""))
            if norm:
                self.spotfire_cache[(date_ref, norm)] = r

        # Se for do dia atual, enriquece as equipes acumuladas em memória
        if date_ref == self.current_date_str:
            for code, t in self.daily_accumulated_teams.items():
                norm = normalize_team_code(code)
                sp = self.spotfire_cache.get((date_ref, norm))
                if sp:
                    login_c = str(sp.get("login_corrigido") or sp.get("login") or sp.get("primeiro_login_corrigido") or sp.get("primeiro_login") or sp.get("inicio_calibrado") or "").strip()
                    logoff_c = str(sp.get("logoff_corrigido") or sp.get("logoff") or sp.get("fim_calibrado") or "").strip()
                    if login_c and login_c not in ["--", "--:--"]:
                        t["login_real"] = login_c
                    if logoff_c and logoff_c not in ["--", "--:--"]:
                        t["logoff_real"] = logoff_c
                        t["logoff_time"] = logoff_c
                    t["qtd_os"] = to_int(sp.get("qtd_servicos") or sp.get("qtd_task") or sp.get("qtd_os") or 0)
                    t["produtivas"] = to_int(sp.get("os_tma_total") or sp.get("os_tma") or sp.get("produtivas") or 0)
                    t["improdutiva"] = to_int(sp.get("os_improdutiva_total") or sp.get("os_improdutiva") or sp.get("improdutiva") or 0)
                    t["verificacoes"] = to_int(sp.get("verificacoes") or 0)
                    t["no_local"] = to_int(sp.get("no_local") or 0)
                    t["rejeita"] = str(sp.get("desvios") or sp.get("rejeita") or "NÃO")
                    t["duracao_efetiva"] = calculate_time_duration(t.get("login_real") or t.get("login_time"), t.get("logoff_real"))
                    t["status_conciliacao"] = "CONCILIADO_TOTAL" if logoff_c and logoff_c not in ["--", "--:--"] else "TURNO_EM_ANDAMENTO"
                    t["spotfire_reconciled"] = True
        self.clear_audit_cache(date_ref)

    def get_daily_audit_data(self, date_str: str) -> dict:
        """
        Gera a auditoria consolidada para uma data específica (YYYY-MM-DD),
        confrontando os dados do EquipesBrasil com as informações do Scanner 5.0 / TIBCO Spotfire.
        Utiliza cache em memória para datas passadas (resposta <1ms).
        """
        import time
        now_ts = time.time()
        ttl = 30 if date_str == self.current_date_str else 3600
        if hasattr(self, '_daily_audit_cache') and date_str in self._daily_audit_cache:
            if now_ts - self._daily_audit_cache_ts.get(date_str, 0) < ttl:
                return self._daily_audit_cache[date_str]

        base_teams = []
        if date_str == self.current_date_str:
            state = self.get_consolidated_state()
            base_teams = [dict(t) for t in state["daily_total_teams"] if t.get("team_code", "")[:3] in TARGET_PREFIXES]
        else:
            try:
                from supabase_client import fetch_delivery_records_by_date
                records = fetch_delivery_records_by_date(date_str)
                if records:
                    # DEDUPLICAÇÃO ATÔMICA POR EQUIPE: consolida múltiplas sessões do mesmo dia
                    seen_eb = {}
                    for r in records:
                        t_code = r.get("team_code", "")
                        prefix = t_code[:3]
                        if prefix not in TARGET_PREFIXES:
                            continue
                        if t_code in seen_eb:
                            cur_logoff = seen_eb[t_code].get("logoff_time")
                            new_logoff = r.get("logoff_time")
                            if (not cur_logoff or cur_logoff in ["--", "--:--"]) and (new_logoff and new_logoff not in ["--", "--:--"]):
                                seen_eb[t_code] = r
                        else:
                            seen_eb[t_code] = r

                    for t_code, r in seen_eb.items():
                        prefix = t_code[:3]
                        b_info = self.official_bases.get(prefix)
                        v_info = self.classify_vehicle(t_code, base_or_geo=b_info["name"] if b_info else r.get("base_name"), date_ref=date_str)
                        base_teams.append({
                            "team_code": t_code,
                            "base_code": prefix,
                            "base_name": b_info["name"] if b_info else r.get("base_name", f"Base {prefix}"),
                            "base_display": b_info["base_display"] if b_info else r.get("base_name", f"Base {prefix}"),
                            "region": b_info["region"] if b_info else r.get("region", "Outras Bases"),
                            "geo": b_info["geo"] if b_info else "Outras",
                            "company": b_info["company"] if b_info else r.get("company", "Outros"),
                            "vehicle_type": v_info["type"],
                            "login_time": r.get("login_time", "--:--"),
                            "logoff_time": r.get("logoff_time", "--:--"),
                            "shift_slot": r.get("shift_slot", "Turno 08:00"),
                            "shift_code": r.get("shift_slot", "08:00").replace("Turno ", "").strip(),
                            "status": r.get("status", "Entregue"),
                            "driver": r.get("raw_info", {}).get("driver", "--") if isinstance(r.get("raw_info"), dict) else "--",
                            "plate": r.get("raw_info", {}).get("plate", "--") if isinstance(r.get("raw_info"), dict) else "--"
                        })
            except Exception as err:
                print(f"[AUDIT FETCH ERROR] {err}")

        # Busca registros correspondentes no Scanner 5.0 / Spotfire (apenas as 7 bases oficiais)
        sp_map = {}
        try:
            from supabase_client import fetch_scanner_records_by_date, fetch_spotfire_records_by_date
            spotfire_records = fetch_scanner_records_by_date(date_str)
            if not spotfire_records:
                spotfire_records = fetch_spotfire_records_by_date(date_str)
            for sp in spotfire_records:
                norm = sp.get("equipe_normalizada") or normalize_team_code(sp.get("equipe", ""))
                if norm and norm[:3] in TARGET_PREFIXES:
                    sp_map[norm] = sp
        except Exception as e:
            print(f"[SCANNER AUDIT FETCH ERROR] {e}")

        # Reconciliação dos registros de EquipesBrasil com Scanner/Spotfire
        seen_teams = set()
        for t in base_teams:
            norm = normalize_team_code(t.get("team_code", ""))
            seen_teams.add(norm)
            sp = sp_map.get(norm)
            if sp:
                shift_info = classify_spotfire_shift_and_turno(sp)
                t["turno"] = shift_info["turno"]
                t["shift_slot"] = shift_info["shift_slot"]
                t["shift_code"] = shift_info["shift_code"]
                t["shift_pill_class"] = shift_info["shift_pill_class"]
                login_c = str(sp.get("login_corrigido") or sp.get("login") or sp.get("primeiro_login_corrigido") or sp.get("primeiro_login") or sp.get("inicio_calibrado") or "").strip()
                logoff_c = str(sp.get("logoff_corrigido") or sp.get("logoff") or sp.get("fim_calibrado") or "").strip()
                t["login_real"] = login_c if (login_c and login_c not in ["--", "--:--"]) else t.get("login_time", "--:--")
                t["logoff_real"] = logoff_c if (logoff_c and logoff_c not in ["--", "--:--"]) else "--:--"
                if logoff_c and logoff_c not in ["--", "--:--"]:
                    t["logoff_time"] = logoff_c
                t["qtd_os"] = to_int(sp.get("qtd_servicos") or sp.get("qtd_task") or sp.get("qtd_os") or 0)
                t["produtivas"] = to_int(sp.get("os_tma_total") or sp.get("os_tma") or sp.get("produtivas") or 0)
                t["improdutiva"] = to_int(sp.get("os_improdutiva_total") or sp.get("os_improdutiva") or sp.get("improdutiva") or 0)
                t["verificacoes"] = to_int(sp.get("verificacoes") or 0)
                t["no_local"] = to_int(sp.get("no_local") or 0)
                t["rejeita"] = str(sp.get("desvios") or sp.get("rejeita") or "NÃO")
                t["duracao_efetiva"] = calculate_time_duration(t["login_real"], t["logoff_real"])
                t["status_conciliacao"] = "CONCILIADO_TOTAL" if t["logoff_real"] not in ["--", "--:--"] else "CONCILIADO_AMBOS"
                t["spotfire_reconciled"] = True
            else:
                sc = t.get("shift_code", "08:00")
                if sc in ["06:00", "08:00"]:
                    t["turno"] = "Manhã"
                elif sc in ["12:00", "14:00"]:
                    t["turno"] = "Tarde"
                elif sc in ["20:00", "22:00"]:
                    t["turno"] = "Noite"
                else:
                    t["turno"] = "Manhã"
                t["login_real"] = t.get("login_time", "--:--")
                t["logoff_real"] = "--:--"
                t["qtd_os"] = 0
                t["produtivas"] = 0
                t["improdutiva"] = 0
                t["verificacoes"] = 0
                t["no_local"] = 0
                t["rejeita"] = "NÃO"
                t["duracao_efetiva"] = "--"
                t["status_conciliacao"] = "APENAS_EQUIPESBRASIL"
                t["spotfire_reconciled"] = False

        # Inclui equipes que constam exclusivamente no Scanner 5.0 (sem EquipesBrasil)
        for norm, sp in sp_map.items():
            if norm not in seen_teams:
                prefix = norm[:3]
                if prefix not in TARGET_PREFIXES:
                    continue
                b_info = self.official_bases.get(prefix)
                v_info = self.classify_vehicle(norm, base_or_geo=b_info["name"] if b_info else sp.get("base"), date_ref=date_str)
                shift_info = classify_spotfire_shift_and_turno(sp)
                login_c = str(sp.get("login_corrigido") or sp.get("login") or sp.get("primeiro_login_corrigido") or sp.get("primeiro_login") or sp.get("inicio_calibrado") or "").strip()
                logoff_c = str(sp.get("logoff_corrigido") or sp.get("logoff") or sp.get("fim_calibrado") or "").strip()
                base_teams.append({
                    "team_code": sp.get("equipe") or norm,
                    "base_code": prefix,
                    "base_name": b_info["name"] if b_info else f"Base {prefix}",
                    "base_display": b_info["base_display"] if b_info else f"Base {prefix}",
                    "region": b_info["region"] if b_info else "Outras Bases",
                    "geo": b_info["geo"] if b_info else "Outras",
                    "company": b_info["company"] if b_info else "Outros",
                    "vehicle_type": v_info["type"],
                    "login_time": login_c or "--:--",
                    "logoff_time": logoff_c or "--:--",
                    "login_real": login_c or "--:--",
                    "logoff_real": logoff_c or "--:--",
                    "turno": shift_info["turno"],
                    "shift_slot": shift_info["shift_slot"],
                    "shift_code": shift_info["shift_code"],
                    "shift_pill_class": shift_info["shift_pill_class"],
                    "status": "Apenas Spotfire" if logoff_c in ["--", "--:--", ""] else "Turno Concluído (Spotfire)",
                    "driver": sp.get("motorista") or sp.get("equipe1") or "--",
                    "plate": sp.get("placa") or "--",
                    "qtd_os": to_int(sp.get("qtd_servicos") or sp.get("qtd_task") or sp.get("qtd_os") or 0),
                    "produtivas": to_int(sp.get("os_tma_total") or sp.get("os_tma") or sp.get("produtivas") or 0),
                    "improdutiva": to_int(sp.get("os_improdutiva_total") or sp.get("os_improdutiva") or sp.get("improdutiva") or 0),
                    "verificacoes": to_int(sp.get("verificacoes") or 0),
                    "no_local": to_int(sp.get("no_local") or 0),
                    "rejeita": str(sp.get("desvios") or sp.get("rejeita") or "NÃO"),
                    "duracao_efetiva": calculate_time_duration(login_c or "--:--", logoff_c or "--:--"),
                    "status_conciliacao": "APENAS_SPOTFIRE",
                    "spotfire_reconciled": True
                })

        metrics = self._build_metrics_breakdown(base_teams)

        # Totais de conciliação para os KPI Cards e Segmento de Confronto
        total_delivered = len(base_teams)
        total_eb = len([t for t in base_teams if t.get("status_conciliacao") != "APENAS_SPOTFIRE"])
        total_conciliado_ambos = len([t for t in base_teams if t.get("status_conciliacao") in ["CONCILIADO_TOTAL", "CONCILIADO_AMBOS", "TURNO_EM_ANDAMENTO"]])
        total_apenas_spotfire = len([t for t in base_teams if t.get("status_conciliacao") == "APENAS_SPOTFIRE"])
        total_apenas_eb = len([t for t in base_teams if t.get("status_conciliacao") == "APENAS_EQUIPESBRASIL"])
        total_with_logoff = len([t for t in base_teams if t.get("logoff_real") not in ["--", "--:--"]])
        total_os_produtivas = sum(t.get("produtivas", 0) for t in base_teams)
        total_os_geral = sum(t.get("qtd_os", 0) for t in base_teams)
        base_divisor = max(len(sp_map), total_delivered, 1)
        rate = round((total_conciliado_ambos / base_divisor) * 100.0, 1) if len(sp_map) > 0 else (100.0 if total_eb == 0 else 0.0)

        res = {
            "status": "success" if total_delivered > 0 else "empty",
            "date": date_str,
            "total_delivered": total_delivered,
            "summary": metrics,
            "reconciliation": {
                "total_delivered": total_delivered,
                "total_equipes_brasil": total_eb,
                "total_spotfire": len(sp_map),
                "total_conciliado_ambos": total_conciliado_ambos,
                "total_apenas_spotfire": total_apenas_spotfire,
                "total_apenas_equipesbrasil": total_apenas_eb,
                "total_with_logoff": total_with_logoff,
                "total_os_produtivas": total_os_produtivas,
                "total_os_geral": total_os_geral,
                "assertiveness_rate": rate
            },
            "teams": base_teams
        }
        if total_delivered > 0:
            self._daily_audit_cache[date_str] = res
            self._daily_audit_cache_ts[date_str] = now_ts
        return res

    def get_comparative_targets_audit(self, date_str: str, region: str = "Norte") -> dict:
        """
        Calcula o comparativo oficial entre Metas Planejadas (PLAN), Entregas Efetivas (REAL) e Desvios (GAP)
        para a data (ou múltiplas datas selecionadas) e região especificadas, estruturado exatamente nas 3 visões executivas:
        1. BASES
        2. TURNO
        3. TIPO VEÍCULO
        
        Quando múltiplas datas são selecionadas, calcula a MÉDIA DIÁRIA exata de cada categoria e o GAP resultante.
        Utiliza 100% dos registros tratados do TIBCO Spotfire como verdade oficial de fechamento.
        """
        reg_key = "Norte" if str(region).lower() in ["norte", "região norte"] else "Leste"
        
        # 1. Trata uma ou múltiplas datas selecionadas
        if not date_str:
            from datetime import date
            date_list = [date.today().isoformat()]
        else:
            raw_parts = [d.strip() for d in str(date_str).replace("|", ",").split(",") if d.strip()]
            date_list = list(dict.fromkeys(raw_parts))  # Preserva a ordem sem duplicatas
            if not date_list:
                from datetime import date
                date_list = [date.today().isoformat()]

        num_days = len(date_list)
        first_date = date_list[0]

        # 2. Carrega Metas de Planejamento (Supabase / JSON) para o mês de referência
        from supabase_client import fetch_delivery_planning_targets, fetch_spotfire_records_by_date
        p_targets = fetch_delivery_planning_targets(first_date[:7])
        reg_targets = p_targets.get(reg_key, {})
        plan_bases = reg_targets.get("bases", {})
        plan_turno = reg_targets.get("turno", {})
        plan_veiculo = reg_targets.get("veiculo", {})

        # Filtra equipes da região selecionada estritamente pelos prefixos oficiais
        if reg_key == "Norte":
            target_prefixes = {"ENL", "ECL", "EEL"}
        else:
            target_prefixes = {"EML", "EQL", "EVL", "ESL"}

        prefix_to_base = {
            "ENL": "Fagundes Filho",
            "ECL": "Cajati",
            "EEL": "Vila Medeiros",
            "EML": "Monte Santo",
            "EVL": "Catumbi",
            "EQL": "Aricanduva",
            "ESL": "Santo André"
        }

        # 3. Carrega equipes reais tratadas diretamente do Spotfire para cada data selecionada
        from concurrent.futures import ThreadPoolExecutor

        def fetch_and_classify_for_date(d_str):
            recs = fetch_spotfire_records_by_date(d_str)
            teams = []
            for r in recs:
                code = normalize_team_code(r.get("equipe_normalizada") or r.get("equipe", ""))
                pfx = code[:3]
                if pfx not in target_prefixes:
                    continue
                login_val = r.get("login_corrigido") or r.get("login") or ""
                if not str(login_val).strip() or str(login_val).strip().lower() in ["none", "nan", "-", "0", "0.0"]:
                    continue
                v_info = self.classify_vehicle(code, base_or_geo=r.get("base"), date_ref=d_str)
                shift_info = classify_spotfire_shift_and_turno(r)
                teams.append({
                    "team_code": code,
                    "base_code": pfx,
                    "vehicle_type": v_info["type"],
                    "turno": shift_info["turno"],
                    "shift_slot": shift_info["shift_slot"],
                    "shift_code": shift_info["shift_code"],
                    "raw_record": r
                })
            return d_str, teams

        day_teams_map = {}
        if num_days == 1:
            _, teams = fetch_and_classify_for_date(date_list[0])
            day_teams_map[date_list[0]] = teams
        else:
            with ThreadPoolExecutor(max_workers=min(num_days, 8)) as ex:
                results = ex.map(fetch_and_classify_for_date, date_list)
                for d_str, teams in results:
                    day_teams_map[d_str] = teams

        # 4. Contabilização Real por Categoria acumulada ao longo dos dias selecionados
        base_sum_counts = {b: 0 for b in plan_bases.keys()}
        turno_sum_counts = {"Manhã": 0, "Tarde": 0, "Noite": 0}
        veh_sum_counts = {"Cesto Aéreo": 0, "Veículo Leve": 0, "Moto": 0, "LV": 0, "Munk": 0, "Projeto Ramal": 0, "STC Leste": 0}
        total_teams_sum = 0

        for d_str in date_list:
            teams_of_day = day_teams_map.get(d_str, [])
            total_teams_sum += len(teams_of_day)

            for t in teams_of_day:
                code = t.get("team_code", "").upper()
                v_type = t.get("vehicle_type", "")
                pfx = code[:3]
                raw_rec = t.get("raw_record") if isinstance(t.get("raw_record"), dict) else {}
                base_raw_val = raw_rec.get("base") or ""
                is_ramal_team = (v_type == "Projeto Ramal" or is_projeto_ramal(code, v_type, base=base_raw_val, date_ref=d_str))
                is_stc_team = (v_type == "STC Leste" or is_stc_leste(code, v_type, base=base_raw_val, date_ref=d_str))

                # Classificação em BASES
                if is_ramal_team:
                    b_name = prefix_to_base.get(pfx)
                    if b_name and b_name in base_sum_counts:
                        base_sum_counts[b_name] += 1
                elif v_type == "Munck" or code in self.munck_codes:
                    if "Munk" in base_sum_counts:
                        base_sum_counts["Munk"] += 1
                    elif "Munck" in base_sum_counts:
                        base_sum_counts["Munck"] += 1
                elif v_type == "Linha Viva":
                    if "LV" in base_sum_counts:
                        base_sum_counts["LV"] += 1
                else:
                    b_name = prefix_to_base.get(pfx)
                    if b_name and b_name in base_sum_counts:
                        base_sum_counts[b_name] += 1

                # Classificação em TURNO
                t_name = t.get("turno", "Manhã")
                if t_name in turno_sum_counts:
                    turno_sum_counts[t_name] += 1
                else:
                    turno_sum_counts["Manhã"] += 1

                # Classificação em TIPO VEÍCULO
                if is_ramal_team:
                    veh_sum_counts["Projeto Ramal"] = veh_sum_counts.get("Projeto Ramal", 0) + 1
                elif is_stc_team:
                    veh_sum_counts["STC Leste"] = veh_sum_counts.get("STC Leste", 0) + 1
                elif v_type == "Munck" or code in self.munck_codes:
                    veh_sum_counts["Munk"] += 1
                elif v_type == "Linha Viva":
                    veh_sum_counts["LV"] += 1
                elif v_type == "Cesto Aéreo":
                    veh_sum_counts["Cesto Aéreo"] += 1
                elif v_type == "Veículo Leve":
                    veh_sum_counts["Veículo Leve"] += 1
                elif v_type == "Moto":
                    veh_sum_counts["Moto"] += 1

        # Helper para cálculo de média diária e GAP
        def calc_avg(val_sum):
            if num_days <= 1:
                return int(val_sum)
            avg = val_sum / float(num_days)
            return round(avg, 1) if (val_sum % num_days != 0) else int(val_sum // num_days)

        def calc_gap(r_val, p_val):
            diff = r_val - p_val
            return round(diff, 1) if isinstance(diff, float) and (diff % 1 != 0) else int(diff)

        # 4.1 Tabela BASES (com média diária)
        table_bases = []
        sum_plan_tma = 0
        sum_real_tma = 0
        for b_name, p_val in plan_bases.items():
            r_sum = base_sum_counts.get(b_name, 0)
            r_avg = calc_avg(r_sum)
            gap_val = calc_gap(r_avg, p_val)
            table_bases.append({
                "categoria": b_name,
                "plan": p_val,
                "real": r_avg,
                "gap": gap_val,
                "is_special": b_name in ["LV", "Munk", "Munck"]
            })
            if b_name not in ["LV", "Munk", "Munck"]:
                sum_plan_tma += p_val
                sum_real_tma += r_avg

        lv_plan = plan_bases.get("LV", 0)
        lv_real = calc_avg(base_sum_counts.get("LV", 0))
        munk_plan = plan_bases.get("Munk", plan_bases.get("Munck", 0))
        munk_real = calc_avg(base_sum_counts.get("Munk", base_sum_counts.get("Munck", 0)))

        if reg_key == "Norte":
            sum_real_tma = round(sum_real_tma, 1) if isinstance(sum_real_tma, float) and (sum_real_tma % 1 != 0) else int(sum_real_tma)
            table_bases.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": calc_gap(sum_real_tma, sum_plan_tma),
                "is_total": True
            })
            tot_lv_tma_plan = sum_plan_tma + lv_plan + munk_plan
            tot_lv_tma_real = sum_real_tma + lv_real + munk_real
            tot_lv_tma_real = round(tot_lv_tma_real, 1) if isinstance(tot_lv_tma_real, float) and (tot_lv_tma_real % 1 != 0) else int(tot_lv_tma_real)
            table_bases.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": calc_gap(tot_lv_tma_real, tot_lv_tma_plan),
                "is_grand_total": True
            })
        else:
            tot_p_bases = sum(plan_bases.values())
            tot_r_bases = calc_avg(sum(base_sum_counts.values()))
            table_bases.append({
                "categoria": "Total",
                "plan": tot_p_bases,
                "real": tot_r_bases,
                "gap": calc_gap(tot_r_bases, tot_p_bases),
                "is_grand_total": True
            })

        # 4.2 Tabela TURNO (com média diária)
        table_turno = []
        for t_name in ["Manhã", "Tarde", "Noite"]:
            p_val = plan_turno.get(t_name, 0)
            r_avg = calc_avg(turno_sum_counts.get(t_name, 0))
            table_turno.append({
                "categoria": t_name,
                "plan": p_val,
                "real": r_avg,
                "gap": calc_gap(r_avg, p_val)
            })

        if reg_key == "Norte":
            table_turno.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": calc_gap(sum_real_tma, sum_plan_tma),
                "is_total": True
            })
            table_turno.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": calc_gap(tot_lv_tma_real, tot_lv_tma_plan),
                "is_grand_total": True
            })
        else:
            tot_p_turno = sum(plan_turno.values())
            tot_r_turno = calc_avg(sum(turno_sum_counts.values()))
            table_turno.append({
                "categoria": "Total",
                "plan": tot_p_turno,
                "real": tot_r_turno,
                "gap": calc_gap(tot_r_turno, tot_p_turno),
                "is_grand_total": True
            })

        # 4.3 Tabela TIPO VEÍCULO (com média diária)
        table_veiculo = []
        for v_name in ["Cesto Aéreo", "Veículo Leve", "Moto", "LV", "Munk"]:
            p_val = plan_veiculo.get(v_name, 0)
            r_avg = calc_avg(veh_sum_counts.get(v_name, 0))
            table_veiculo.append({
                "categoria": v_name,
                "plan": p_val,
                "real": r_avg,
                "gap": calc_gap(r_avg, p_val),
                "is_special": v_name in ["LV", "Munk"]
            })

        if reg_key == "Norte":
            table_veiculo.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": calc_gap(sum_real_tma, sum_plan_tma),
                "is_total": True
            })
            table_veiculo.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": calc_gap(tot_lv_tma_real, tot_lv_tma_plan),
                "is_grand_total": True
            })
        else:
            tot_p_veh = sum(plan_veiculo.values())
            tot_r_veh = calc_avg(sum(veh_sum_counts.values()))
            table_veiculo.append({
                "categoria": "Total",
                "plan": tot_p_veh,
                "real": tot_r_veh,
                "gap": calc_gap(tot_r_veh, tot_p_veh),
                "is_grand_total": True
            })

        # Cards rápidos de frota (média diária)
        fleet_cards = {
            "cesto": calc_avg(veh_sum_counts["Cesto Aéreo"]),
            "leve": calc_avg(veh_sum_counts["Veículo Leve"]),
            "moto": calc_avg(veh_sum_counts["Moto"]),
            "linhaviva": calc_avg(veh_sum_counts["LV"]),
            "munck": calc_avg(veh_sum_counts["Munk"]),
            "total_regiao": calc_avg(total_teams_sum)
        }

        last_scanner_sync = None
        try:
            sync_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scanner_last_sync.json")
            if os.path.exists(sync_file):
                with open(sync_file, "r", encoding="utf-8") as f:
                    last_scanner_sync = json.load(f).get("last_sync")
        except Exception:
            pass
        if not last_scanner_sync:
            last_scanner_sync = format_datetime_br(datetime.now())

        return {
            "status": "success",
            "date": date_str,
            "dates": date_list,
            "num_days": num_days,
            "is_average": num_days > 1,
            "period_label": f"Média de {num_days} dias selecionados" if num_days > 1 else f"Dia {date_list[0]}",
            "region": reg_key,
            "updated_at": last_scanner_sync,
            "daily_meta": p_targets.get("daily_meta", 226),
            "tables": {
                "bases": table_bases,
                "turno": table_turno,
                "veiculo": table_veiculo
            },
            "fleet_cards": fleet_cards
        }

    def get_monthly_audit_data(self, month_str: str = None) -> dict:
        """
        Retorna registros analíticos consolidados de equipes do mês selecionado (YYYY-MM),
        com dimensões normalizadas para filtragem instantânea no front-end e cache inteligente.
        """
        if not month_str:
            month_str = datetime.now().strftime("%Y-%m")

        import os, json, time
        now_ts = time.time()
        # Se estiver em cache em memória, retorna instantaneamente (<1ms)
        if hasattr(self, '_monthly_audit_cache') and month_str in self._monthly_audit_cache:
            cache_ttl = 120 if month_str == datetime.now().strftime("%Y-%m") else 86400
            if now_ts - self._monthly_audit_cache_ts.get(month_str, 0) < cache_ttl:
                return self._monthly_audit_cache[month_str]

        # Se for mês passado e existir cache em disco, carrega instantaneamente (<5ms)
        cache_path = os.path.join("data", f"monthly_audit_{month_str}.json")
        if month_str != datetime.now().strftime("%Y-%m") and os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as fp:
                    disk_res = json.load(fp)
                if disk_res and disk_res.get("status") == "success" and disk_res.get("raw_records"):
                    if not hasattr(self, '_monthly_audit_cache'):
                        self._monthly_audit_cache = {}
                        self._monthly_audit_cache_ts = {}
                    self._monthly_audit_cache[month_str] = disk_res
                    self._monthly_audit_cache_ts[month_str] = now_ts
                    return disk_res
            except Exception:
                pass

        try:
            import calendar
            import requests
            from supabase_client import BASE_REST_URL, get_headers, fetch_delivery_planning_targets
            
            headers = get_headers()
            cols_to_select = "data_referencia,equipe_normalizada,equipe,base_responsavel,base,tipo_equipe,login_corrigido,logoff_corrigido,inicio_calendario,fim_calendario,login,logoff,periodo"
            
            parts = month_str.split("-")
            y, m = int(parts[0]), int(parts[1])
            last_day = calendar.monthrange(y, m)[1]
            start_dt = f"{y:04d}-{m:02d}-01"
            end_dt = f"{y:04d}-{m:02d}-{last_day:02d}"

            raw_data = []
            offset = 0
            chunk_size = 1000
            for _ in range(7):  # Até 7000 registros (cobre com folga o mês inteiro de todas as bases)
                url = f"{BASE_REST_URL}/team_scanner_records?data_referencia=gte.{start_dt}&data_referencia=lte.{end_dt}&select={cols_to_select}&order=data_referencia.asc&limit={chunk_size}&offset={offset}"
                r = requests.get(url, headers=headers, timeout=10)
                batch = r.json() if r.status_code == 200 else []
                if not batch:
                    break
                raw_data.extend(batch)
                if len(batch) < chunk_size:
                    break
                offset += chunk_size
            
            if not raw_data:
                offset = 0
                for _ in range(3):
                    url_leg = f"{BASE_REST_URL}/team_spotfire_records?data_referencia=gte.{start_dt}&data_referencia=lte.{end_dt}&order=data_referencia.asc&limit={chunk_size}&offset={offset}"
                    r_leg = requests.get(url_leg, headers=headers, timeout=10)
                    batch_leg = r_leg.json() if r_leg.status_code == 200 else []
                    if not batch_leg:
                        break
                    raw_data.extend(batch_leg)
                    if len(batch_leg) < chunk_size:
                        break
                    offset += chunk_size

            p_targets = fetch_delivery_planning_targets(month_str)

            norm_records = []
            regions_set = set()
            bases_set = set()
            vehicles_set = set()

            ALPITEL_PREFIXES = {"ENL", "ECL", "EEL", "EML", "EQL", "EVL", "ESL"}
            prefix_to_base = {
                "ENL": "Base Fagundes Filho",
                "ECL": "Base Cajati",
                "EEL": "Base Vila Medeiros",
                "EML": "Base Monte Santo",
                "EQL": "Base Aricanduva",
                "EVL": "Base Catumbi",
                "ESL": "Base Santo André"
            }
            prefix_to_region = {
                "ENL": "Região Norte",
                "ECL": "Região Norte",
                "EEL": "Região Norte",
                "EML": "Região Leste",
                "EQL": "Região Leste",
                "EVL": "Região Leste",
                "ESL": "Região Leste"
            }

            for row in raw_data:
                team_code = normalize_team_code(row.get("equipe_normalizada") or row.get("equipe") or "")
                if not team_code:
                    continue
                pfx = team_code[:3]
                if pfx not in ALPITEL_PREFIXES:
                    continue
                
                # Validação mandatória: presença de login efetivo registrado
                login_t = row.get("login_corrigido") or row.get("login") or ""
                if not str(login_t).strip() or str(login_t).strip().lower() in ["none", "nan", "-", "0", "0.0"]:
                    continue

                base_name = prefix_to_base.get(pfx, "Outros")
                reg = prefix_to_region.get(pfx, "Outros")
                
                dt_ref = str(row.get("data_referencia") or "")
                
                v_info = self.classify_vehicle(team_code, base_or_geo=base_name, date_ref=dt_ref)
                v_type = v_info.get("type", "Outros")
                
                shift_info = classify_spotfire_shift_and_turno(row)
                turno = shift_info.get("turno") or "Manhã"
                shift_code = shift_info.get("shift_code") or "08:00"

                rec = {
                    "date": dt_ref,
                    "team_code": team_code,
                    "prefix": pfx,
                    "base": base_name,
                    "region": reg,
                    "turno": turno,
                    "shift_code": shift_code,
                    "vehicle_type": v_type
                }
                norm_records.append(rec)
                
                if reg and reg != "Outros":
                    regions_set.add(reg)
                if base_name and base_name != "Outros":
                    bases_set.add(base_name)
                if v_type and v_type != "Outros":
                    vehicles_set.add(v_type)

            # Agregação por dia em nível de backend para resposta leve
            day_counts = {}
            for r in norm_records:
                d = r.get("date")
                if d:
                    day_counts[d] = day_counts.get(d, 0) + 1

            all_days = sorted(list(day_counts.keys()))
            days_list = [{"date": d, "total_teams": day_counts[d]} for d in all_days]
            op_days = len([d for d in days_list if d["total_teams"] > 0])
            avg_tot = (sum(d["total_teams"] for d in days_list) / max(op_days, 1)) if op_days > 0 else 0

            cesto_tot = sum(1 for r in norm_records if r.get("vehicle_type") == "Cesto Aéreo")
            leve_tot = sum(1 for r in norm_records if r.get("vehicle_type") == "Veículo Leve" and not is_stc_leste(r.get("team_code", ""), r.get("vehicle_type", ""), base=r.get("base"), date_ref=r.get("date")))
            moto_tot = sum(1 for r in norm_records if r.get("vehicle_type") == "Moto")
            linhaviva_munck_tot = sum(1 for r in norm_records if r.get("vehicle_type") in ["Linha Viva", "Munck"] and not is_projeto_ramal(r.get("team_code", ""), r.get("vehicle_type", ""), base=r.get("base"), date_ref=r.get("date")))
            ramal_tot = sum(1 for r in norm_records if r.get("vehicle_type") == "Projeto Ramal" or is_projeto_ramal(r.get("team_code", ""), r.get("vehicle_type", ""), base=r.get("base"), date_ref=r.get("date")))
            stc_leste_tot = sum(1 for r in norm_records if r.get("vehicle_type") == "STC Leste" or is_stc_leste(r.get("team_code", ""), r.get("vehicle_type", ""), base=r.get("base"), date_ref=r.get("date")))

            res = {
                "status": "success",
                "month": month_str,
                "planning_targets": p_targets,
                "total_records": len(norm_records),
                "operating_days": op_days,
                "avg_total": round(avg_tot, 1),
                "avg_cesto": round(cesto_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "avg_leve": round(leve_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "avg_moto": round(moto_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "avg_linhaviva_munck": round(linhaviva_munck_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "avg_ramal": round(ramal_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "avg_stc_leste": round(stc_leste_tot / max(op_days, 1), 1) if op_days > 0 else 0,
                "days": days_list,
                "unique_dimensions": {
                    "regions": sorted(list(regions_set)),
                    "bases": sorted(list(bases_set)),
                    "turnos": ["Manhã", "Tarde", "Noite"],
                    "vehicles": sorted(list(vehicles_set))
                },
                "raw_records": norm_records
            }
            if len(norm_records) > 0:
                self._monthly_audit_cache[month_str] = res
                self._monthly_audit_cache_ts[month_str] = now_ts
                # Salva cache em disco para meses passados (imutáveis)
                if month_str != datetime.now().strftime("%Y-%m"):
                    try:
                        import os, json
                        os.makedirs("data", exist_ok=True)
                        cache_path = os.path.join("data", f"monthly_audit_{month_str}.json")
                        with open(cache_path, "w", encoding="utf-8") as fp:
                            json.dump(res, fp, ensure_ascii=False)
                    except Exception:
                        pass
            return res
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "month": month_str,
                "planning_targets": {},
                "unique_dimensions": {},
                "raw_records": [],
                "days": []
            }

    def clear_audit_cache(self, month: str = None):
        """Limpa o cache em memória de auditoria mensal e de datas disponíveis."""
        if month and hasattr(self, '_monthly_audit_cache'):
            self._monthly_audit_cache.pop(month, None)
            if hasattr(self, '_monthly_audit_cache_ts'):
                self._monthly_audit_cache_ts.pop(month, None)
        else:
            self._monthly_audit_cache = {}
            self._monthly_audit_cache_ts = {}
            self._audit_dates_cache = None
            self._audit_dates_cache_ts = 0

    def get_available_audit_dates(self, force_refresh: bool = False) -> dict:
        """
        Retorna a lista completa de datas e meses com dados no Supabase para o calendário e dropdown.
        Utiliza cache persistente em disco (data/delivery_available_dates.json) e memória para tempo de resposta <1ms.
        """
        import os, json, time, calendar
        now = time.time()

        # 1. Verifica cache em memória (TTL: 300 segundos)
        if not force_refresh and hasattr(self, '_audit_dates_cache') and self._audit_dates_cache:
            if now - getattr(self, '_audit_dates_cache_ts', 0) < 300:
                return self._audit_dates_cache

        # 2. Verifica cache em disco (se recente <300s e não force_refresh)
        cache_file = os.path.join("data", "delivery_available_dates.json")
        disk_data = None
        if os.path.isfile(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                with open(cache_file, "r", encoding="utf-8") as fp:
                    disk_data = json.load(fp)
                if not force_refresh and (now - mtime < 300) and disk_data and disk_data.get("dates"):
                    self._audit_dates_cache = disk_data
                    self._audit_dates_cache_ts = now
                    return disk_data
            except Exception:
                pass

        try:
            import requests
            from concurrent.futures import ThreadPoolExecutor
            from supabase_client import BASE_REST_URL, get_headers
            headers = get_headers()
            raw_dates = set()

            # Se tínhamos dados de disco, aproveita para não re-escanear todo o passado
            if disk_data and disk_data.get("dates"):
                raw_dates.update(disk_data.get("dates"))

            # 1. Busca datas recentes nos cabeçalhos de sessões (entregas e coletas operacionais)
            try:
                r_sess = requests.get(
                    f"{BASE_REST_URL}/team_delivery_sessions?select=date_ref&order=date_ref.desc&limit=200",
                    headers=headers,
                    timeout=5
                )
                if r_sess.status_code == 200:
                    for row in (r_sess.json() or []):
                        d = row.get("date_ref")
                        if d:
                            raw_dates.add(str(d).strip())
            except Exception:
                pass

            try:
                r_opsess = requests.get(
                    f"{BASE_REST_URL}/operational_sync_sessions?select=captured_date&order=captured_date.desc&limit=50",
                    headers=headers,
                    timeout=5
                )
                if r_opsess.status_code == 200:
                    for row in (r_opsess.json() or []):
                        d = row.get("captured_date")
                        if d:
                            raw_dates.add(str(d).strip())
            except Exception:
                pass

            # Se houver equipes em memória no dia atual, adiciona a data de hoje
            if getattr(self, 'daily_accumulated_teams', None):
                raw_dates.add(datetime.now().strftime("%Y-%m-%d"))

            # 2. Busca datas em paralelo com paginação por cursor para todos os meses
            curr_year = datetime.now().year
            curr_month = datetime.now().month

            def fetch_month_dates(mo):
                last_day = calendar.monthrange(curr_year, mo)[1]
                cur_dt = f"{curr_year}-{mo:02d}-01"
                end_dt = f"{curr_year}-{mo:02d}-{last_day:02d}"
                m_dates = set()
                while cur_dt <= end_dt:
                    url = f"{BASE_REST_URL}/team_scanner_records?data_referencia=gte.{cur_dt}&data_referencia=lte.{end_dt}&select=data_referencia&order=data_referencia.asc&limit=1000"
                    r = requests.get(url, headers=headers, timeout=10)
                    items = r.json() if r.status_code == 200 else []
                    if not items:
                        break
                    for x in items:
                        d_val = x.get("data_referencia")
                        if d_val:
                            m_dates.add(str(d_val).strip())
                    last = items[-1].get("data_referencia")
                    if len(items) < 1000 or not last:
                        break
                    try:
                        dt_obj = datetime.strptime(last, "%Y-%m-%d") + timedelta(days=1)
                        cur_dt = dt_obj.strftime("%Y-%m-%d")
                    except Exception:
                        break
                return list(m_dates)

            # Se force_refresh ou não havia cache em disco, escaneia todos os meses (1 até curr_month)
            months_to_scan = range(1, curr_month + 1) if (force_refresh or not disk_data) else [curr_month]
            try:
                with ThreadPoolExecutor(max_workers=9) as ex:
                    results = ex.map(fetch_month_dates, months_to_scan)
                    for res_list in results:
                        raw_dates.update(res_list)
            except Exception as e:
                print(f"[AUDIT DATES SCAN ERROR] {e}")

            sorted_dates = sorted(list(raw_dates), reverse=True)
            months_set = sorted(list(set(d[:7] for d in sorted_dates if len(d) >= 7)), reverse=False)

            month_names = {
                "01": "Janeiro", "02": "Fevereiro", "03": "Março",
                "04": "Abril", "05": "Maio", "06": "Junho",
                "07": "Julho", "08": "Agosto", "09": "Setembro",
                "10": "Outubro", "11": "Novembro", "12": "Dezembro"
            }

            months_list = []
            for m in months_set:
                parts = m.split("-")
                if len(parts) == 2:
                    y, mo = parts[0], parts[1]
                    m_label = f"{month_names.get(mo, mo)}/{y}"
                    months_list.append({"value": m, "label": m_label})

            res = {
                "status": "success",
                "dates": sorted_dates,
                "months": months_list,
                "latest_date": sorted_dates[0] if sorted_dates else datetime.now().strftime("%Y-%m-%d"),
                "latest_month": months_set[-1] if months_set else datetime.now().strftime("%Y-%m")
            }

            # Salva no arquivo de cache persistente
            try:
                os.makedirs("data", exist_ok=True)
                with open(cache_file, "w", encoding="utf-8") as fp:
                    json.dump(res, fp, ensure_ascii=False, indent=2)
            except Exception:
                pass

            self._audit_dates_cache = res
            self._audit_dates_cache_ts = now
            return res
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "dates": [],
                "months": []
            }

    def get_recent_3days_audit_summary(self, today_metrics: dict = None) -> dict:
        """
        Retorna o consolidado dos últimos 3 dias disponíveis na Auditoria & Histórico:
        - Datas consideradas
        - Total entregue nos 3 dias
        - Total Norte nos 3 dias
        - Total Leste nos 3 dias
        - Médias diárias
        - Detalhamento por dia
        Utiliza cache em memória com TTL de 30s para datas passadas, integrando
        as métricas em tempo real de hoje sem recursão.
        """
        import time
        now_ts = time.time()
        if hasattr(self, '_recent_3days_cache') and self._recent_3days_cache:
            if now_ts - getattr(self, '_recent_3days_cache_ts', 0) < 20:
                return self._recent_3days_cache

        try:
            avail = self.get_available_audit_dates()
            dates = avail.get("dates", [])[:3]
            if not dates:
                dates = [self.current_date_str]

            daily_list = []
            tot_3days = 0
            norte_3days = 0
            leste_3days = 0

            for d in dates:
                if d == self.current_date_str:
                    if today_metrics:
                        tot = today_metrics.get("total", len(self.daily_accumulated_teams))
                        norte_cnt = today_metrics.get("regiao_norte", {}).get("total_block", {}).get("total", 0)
                        leste_cnt = today_metrics.get("regiao_leste", {}).get("total_block", {}).get("total", 0)
                    else:
                        tot = len(self.daily_accumulated_teams)
                        norte_cnt = sum(1 for t in self.daily_accumulated_teams.values() if t.get("geo") == "Norte" or t.get("team_code", "")[:3] in ["ENL", "ECL", "EEL"])
                        leste_cnt = sum(1 for t in self.daily_accumulated_teams.values() if t.get("geo") == "Leste" or t.get("team_code", "")[:3] in ["EML", "EQL", "EVL", "ESL"])
                else:
                    aud = self.get_daily_audit_data(d)
                    tot = aud.get("total_delivered", 0)
                    sum_reg = aud.get("summary", {})
                    norte_cnt = sum_reg.get("regiao_norte", {}).get("total_block", {}).get("total", 0)
                    leste_cnt = sum_reg.get("regiao_leste", {}).get("total_block", {}).get("total", 0)

                tot_3days += tot
                norte_3days += norte_cnt
                leste_3days += leste_cnt

                d_parts = d.split("-")
                d_br = f"{d_parts[2]}/{d_parts[1]}" if len(d_parts) == 3 else d
                daily_list.append({
                    "date": d,
                    "date_br": d_br,
                    "total": tot,
                    "norte": norte_cnt,
                    "leste": leste_cnt
                })

            num_days = max(len(dates), 1)
            first_d = dates[-1].split("-")
            last_d = dates[0].split("-")
            f_br = f"{first_d[2]}/{first_d[1]}" if len(first_d) == 3 else dates[-1]
            l_br = f"{last_d[2]}/{last_d[1]}" if len(last_d) == 3 else dates[0]
            range_label = f"{f_br} a {l_br}" if f_br != l_br else f_br

            res = {
                "status": "success",
                "dates": dates,
                "date_range_label": range_label,
                "total_3days": tot_3days,
                "norte_3days": norte_3days,
                "leste_3days": leste_3days,
                "avg_norte_day": round(norte_3days / num_days, 1),
                "avg_leste_day": round(leste_3days / num_days, 1),
                "daily_breakdown": daily_list
            }

            self._recent_3days_cache = res
            self._recent_3days_cache_ts = now_ts
            return res
        except Exception as e:
            print(f"[WARN 3DAYS AUDIT SUMMARY] {e}", flush=True)
            return {
                "status": "error",
                "message": str(e),
                "dates": [],
                "date_range_label": "--",
                "total_3days": 0,
                "norte_3days": 0,
                "leste_3days": 0,
                "avg_norte_day": 0,
                "avg_leste_day": 0,
                "daily_breakdown": []
            }


    def hydrate_delay_justifications(self, date_ref: str = None, force: bool = False) -> dict:
        """
        Sincroniza e hidrata as justificativas de atraso diretamente da tabela relacional
        public.team_delay_justifications do Supabase.
        Garante que mesmo após reboot do servidor ou refresh no front-end, todos os dados persistam com integridade.
        """
        if not date_ref:
            date_ref = self.get_operational_date()

        now_ts = time.time()
        last_sync = getattr(self, "_last_just_sync_ts", 0)
        # Se for hoje e não for forçado, respeita intervalo de 4s caso já tenha dados em memória
        if not force and self.daily_delay_justifications and (now_ts - last_sync < 4) and (date_ref == self.get_operational_date()):
            return dict(self.daily_delay_justifications)

        try:
            from supabase_client import fetch_team_delay_justifications
            cloud_justs = fetch_team_delay_justifications(date_ref)
            if cloud_justs:
                if date_ref == self.get_operational_date():
                    self.daily_delay_justifications.update(cloud_justs)
                    self._last_just_sync_ts = now_ts
                    # Aplica a justificativa em cada equipe acumulada e ativa
                    for code, just in self.daily_delay_justifications.items():
                        c_upper = code.strip().upper()
                        if c_upper in self.daily_accumulated_teams:
                            self.daily_accumulated_teams[c_upper]["delay_justification"] = dict(just)
                        for t in self.active_teams:
                            if t.get("team_code") == c_upper:
                                t["delay_justification"] = dict(just)
                    return dict(self.daily_delay_justifications)
                return cloud_justs
            else:
                if date_ref == self.get_operational_date():
                    self._last_just_sync_ts = now_ts
                    return dict(self.daily_delay_justifications)
                return {}
        except Exception as e:
            print(f"[WARN] Falha ao sincronizar justificativas de atraso com Supabase: {e}", flush=True)
            return dict(self.daily_delay_justifications) if date_ref == self.get_operational_date() else {}

    def save_delay_justification(self, team_code: str, user_name: str, macro_reason: str, sub_reason: str, observation: str = "", date_ref: str = None) -> dict:
        """
        Registra ou edita uma justificativa de atraso de entrada/login de uma equipe.
        Persiste no cache diário em memória, em disco e sincroniza com o Supabase.
        """
        code = str(team_code).strip().upper()
        if not date_ref:
            date_ref = self.get_operational_date()

        team = self.daily_accumulated_teams.get(code)
        shift_code = "08:00"
        delay_minutes = 0
        if team:
            shift_code = team.get("shift_code") or "08:00"
            delay_minutes = int(team.get("turno_x_login_minutos") or 0)
        else:
            for t in self.active_teams:
                if t.get("team_code") == code:
                    shift_code = t.get("shift_code") or "08:00"
                    delay_minutes = int(t.get("turno_x_login_minutos") or 0)
                    break

        now_str = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S")
        just_record = {
            "date_ref": date_ref,
            "team_code": code,
            "shift_code": shift_code,
            "delay_minutes": delay_minutes,
            "user_name": str(user_name).strip(),
            "macro_reason": str(macro_reason).strip(),
            "sub_reason": str(sub_reason).strip(),
            "observation": str(observation or "").strip(),
            "updated_at": now_str
        }

        self.daily_delay_justifications[code] = just_record

        # Atualiza a referência direta na equipe acumulada e ativa
        if team:
            team["delay_justification"] = dict(just_record)
        for t in self.active_teams:
            if t.get("team_code") == code:
                t["delay_justification"] = dict(just_record)

        self.save_local_cache()

        # Sincronização assíncrona com Supabase
        def _async_push():
            try:
                from supabase_client import save_team_delay_justification
                save_team_delay_justification(dict(just_record))
            except Exception as sb_err:
                print(f"[WARN] Falha ao enviar justificativa ao Supabase: {sb_err}", flush=True)

        threading.Thread(target=_async_push, daemon=True).start()
        return {"status": "success", "justification": just_record}

    def get_delay_analytics_summary(self, date_ref: str = None, geo_scope: str = "ALL") -> dict:
        """
        Gera os dados analíticos consolidados de pontualidade e atrasos por turno
        para a visão alternativa de Gestão de Atrasos no Painel da TV.
        """
        if not date_ref:
            date_ref = self.get_operational_date()

        is_today = (date_ref == self.get_operational_date())
        teams_list = []
        if is_today:
            # Painel TV / ONLINE REAL TIME: somente equipes ativas no momento (is_active == True)
            if self.active_teams:
                teams_list = [t for t in self.active_teams if t.get("is_active", True)]
            else:
                teams_list = [t for t in self.daily_accumulated_teams.values() if t.get("is_active", True)]
        else:
            from supabase_client import fetch_delivery_records_by_date
            teams_list = fetch_delivery_records_by_date(date_ref)

        # Filtragem por Escopo Regional (ALL, NORTE, LESTE)
        scope_clean = str(geo_scope or "ALL").strip().upper()
        BASES_NORTE = ["FAGUNDES", "CAJATI", "VILA MEDEIROS", "NORTE"]

        if scope_clean == "NORTE":
            filtered_teams = []
            for t in teams_list:
                b = str(t.get("base_name") or t.get("base_display") or t.get("base_code") or "").upper()
                r = str(t.get("region") or "").upper()
                if any(nb in b for nb in BASES_NORTE) or "NORTE" in r:
                    filtered_teams.append(t)
            teams_list = filtered_teams
        elif scope_clean == "LESTE":
            filtered_teams = []
            for t in teams_list:
                b = str(t.get("base_name") or t.get("base_display") or t.get("base_code") or "").upper()
                r = str(t.get("region") or "").upper()
                is_norte = any(nb in b for nb in BASES_NORTE) or "NORTE" in r
                if not is_norte:
                    filtered_teams.append(t)
            teams_list = filtered_teams

        justifications = self.hydrate_delay_justifications(date_ref, force=True)

        def _fmt_hm(mins):
            if not mins or mins <= 0:
                return "00h 00m"
            h = mins // 60
            m = mins % 60
            return f"{h:02d}h {m:02d}m"

        shifts_data = {
            "06:00": {"periodo": "Manhã", "shift_code": "06:00", "label": "06:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0},
            "08:00": {"periodo": "Manhã", "shift_code": "08:00", "label": "08:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0},
            "12:00": {"periodo": "Tarde", "shift_code": "12:00", "label": "12:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0},
            "14:00": {"periodo": "Tarde", "shift_code": "14:00", "label": "14:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0},
            "20:00": {"periodo": "Noite", "shift_code": "20:00", "label": "20:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0},
            "22:00": {"periodo": "Noite", "shift_code": "22:00", "label": "22:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "tempo_no_prazo_min": 0}
        }

        total_atrasadas = 0
        total_no_prazo = 0
        total_tempo_atraso_min = 0
        total_tempo_no_prazo_min = 0
        delayed_teams = []

        macro_reasons_stats = {
            "PROBLEMAS TI": {"macro_reason": "PROBLEMAS TI", "icon": "laptop", "color": "#38bdf8", "qtd_equipes": 0, "tempo_min": 0},
            "PROBLEMAS VEÍCULO": {"macro_reason": "PROBLEMAS VEÍCULO", "icon": "truck", "color": "#f59e0b", "qtd_equipes": 0, "tempo_min": 0},
            "PROBLEMAS LOGISTICA": {"macro_reason": "PROBLEMAS LOGISTICA", "icon": "package", "color": "#ec4899", "qtd_equipes": 0, "tempo_min": 0},
            "PROBLEMAS SESMT": {"macro_reason": "PROBLEMAS SESMT", "icon": "shield-check", "color": "#10b981", "qtd_equipes": 0, "tempo_min": 0},
            "PROBLEMAS CCO": {"macro_reason": "PROBLEMAS CCO", "icon": "radio", "color": "#818cf8", "qtd_equipes": 0, "tempo_min": 0},
            "PROBLEMAS ABS": {"macro_reason": "PROBLEMAS ABS", "icon": "user-x", "color": "#f43f5e", "qtd_equipes": 0, "tempo_min": 0},
            "NÃO JUSTIFICADO": {"macro_reason": "NÃO JUSTIFICADO", "icon": "help-circle", "color": "#94a3b8", "qtd_equipes": 0, "tempo_min": 0}
        }

        for t in teams_list:
            code = t.get("team_code")
            if not code:
                continue
            sc = t.get("shift_code") or "08:00"
            if sc not in shifts_data:
                slot = str(t.get("shift_slot") or "")
                for candidate in ["06:00", "08:00", "12:00", "14:00", "20:00", "22:00"]:
                    if candidate in slot:
                        sc = candidate
                        break
            if sc not in shifts_data:
                sc = "08:00"

            d_min = int(t.get("turno_x_login_minutos") or 0)
            shifts_data[sc]["total"] += 1

            just = justifications.get(code) or t.get("delay_justification")

            if d_min > 0:
                shifts_data[sc]["atrasadas"] += 1
                shifts_data[sc]["tempo_atraso_min"] += d_min
                total_atrasadas += 1
                total_tempo_atraso_min += d_min

                macro = (just.get("macro_reason") if just else None) or "NÃO JUSTIFICADO"
                norm_macro = macro.replace("LOGÍSTICA", "LOGISTICA")
                if norm_macro not in macro_reasons_stats:
                    norm_macro = "NÃO JUSTIFICADO"

                macro_reasons_stats[norm_macro]["qtd_equipes"] += 1
                macro_reasons_stats[norm_macro]["tempo_min"] += d_min

                delayed_teams.append({
                    "team_code": code,
                    "base": t.get("base_display") or t.get("base_code") or "--",
                    "turno": f"Turno {sc}",
                    "shift_code": sc,
                    "marcacao": t.get("marcacao") or t.get("login_time") or "--",
                    "delay_minutes": d_min,
                    "delay_str": f"+{d_min} min",
                    "macro_reason": just.get("macro_reason") if just else "NÃO JUSTIFICADO",
                    "sub_reason": just.get("sub_reason") if just else "--",
                    "user_name": just.get("user_name") if just else None,
                    "observation": just.get("observation") if just else None,
                    "has_justification": bool(just)
                })
            else:
                shifts_data[sc]["no_prazo"] += 1
                tempo_no_prazo = abs(d_min)
                shifts_data[sc]["tempo_no_prazo_min"] += tempo_no_prazo
                total_no_prazo += 1
                total_tempo_no_prazo_min += tempo_no_prazo

        for sc, s in shifts_data.items():
            s["tempo_atraso_str"] = _fmt_hm(s["tempo_atraso_min"])
            s["tempo_no_prazo_str"] = _fmt_hm(s["tempo_no_prazo_min"])
            s["taxa_pontualidade"] = round((s["no_prazo"] / s["total"] * 100), 1) if s["total"] > 0 else 100.0

        for m_key, m_val in macro_reasons_stats.items():
            m_val["tempo_str"] = _fmt_hm(m_val["tempo_min"])
            m_val["percentual_tempo"] = round((m_val["tempo_min"] / total_tempo_atraso_min * 100), 1) if total_tempo_atraso_min > 0 else 0.0

        top5 = sorted(delayed_teams, key=lambda x: x["delay_minutes"], reverse=True)[:5]
        macro_list = sorted(macro_reasons_stats.values(), key=lambda x: x["tempo_min"], reverse=True)

        return {
            "date_ref": date_ref,
            "geo_scope": scope_clean,
            "total_equipes": len(teams_list),
            "total_atrasadas": total_atrasadas,
            "total_no_prazo": total_no_prazo,
            "total_tempo_atraso_min": total_tempo_atraso_min,
            "total_tempo_atraso_str": _fmt_hm(total_tempo_atraso_min),
            "total_tempo_no_prazo_min": total_tempo_no_prazo_min,
            "total_tempo_no_prazo_str": _fmt_hm(total_tempo_no_prazo_min),
            "taxa_pontualidade_geral": round((total_no_prazo / len(teams_list) * 100), 1) if teams_list else 100.0,
            "shifts": shifts_data,
            "top5_atrasos": top5,
            "macro_motivos": macro_list
        }



    def get_delays_and_shifts_analytics(
        self,
        mode: str = "realtime",
        date_ref: str = None,
        month_ref: str = None,
        geo_scope: str = "ALL",
        base_filter = None,
        vehicle_filter = None,
        shift_filter = None,
        shift_code_filter = None,
        status_login_filter = None,
        include_stc_leste: bool = True
    ) -> dict:
        """
        Consolida a visao operacional e executiva completa para a tela 'ATRASOS E TURNOS'.
        Suporta os 3 horizontes temporais (realtime, daily, monthly), filtros Multi-Select,
        impacto financeiro por tipo de veiculo e agregacao de TOP Justificativas de atraso.
        """
        def _fmt_hm(mins):
            if not mins or mins <= 0:
                return "00h 00m"
            h = mins // 60
            m = mins % 60
            return f"{h:02d}h {m:02d}m"

        def _fmt_min_or_hm(mins):
            if not mins or mins <= 0:
                return "0 min"
            mins_r = int(round(mins))
            if mins_r < 60:
                return f"{mins_r} min"
            h = mins_r // 60
            m = mins_r % 60
            return f"{h:02d}h {m:02d}m"

        def _fmt_brl(val):
            if not val or val <= 0:
                return "R$ 0,00"
            return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def _to_clean_list(raw):
            if not raw:
                return []
            if isinstance(raw, (list, tuple, set)):
                items = []
                for x in raw:
                    items.extend([s.strip().upper() for s in str(x).split(",") if s.strip()])
                return [i for i in items if i not in ["", "ALL", "TODOS", "TODAS"]]
            clean_str = str(raw).strip()
            if clean_str in ["", "ALL", "TODOS", "TODAS"]:
                return []
            return [s.strip().upper() for s in clean_str.split(",") if s.strip() and s.strip().upper() not in ["ALL", "TODOS", "TODAS"]]

        def _identify_base(team_code, base_raw):
            tc = str(team_code or "").strip().upper()
            bs = str(base_raw or "").strip().upper()
            if tc.startswith("ENL") or "FAGUNDES" in bs:
                return "Fagundes Filho", "Norte"
            if tc.startswith("ECL") or "CAJATI" in bs:
                return "Cajati", "Norte"
            if tc.startswith("EEL") or "MEDEIROS" in bs:
                return "Vila Medeiros", "Norte"
            if tc.startswith("EML") or tc.startswith("EMA") or "MONTE SANTO" in bs:
                return "Monte Santo", "Leste"
            if tc.startswith("EQL") or tc.startswith("EQA") or "ARICANDUVA" in bs:
                return "Aricanduva", "Leste"
            if tc.startswith("EVL") or tc.startswith("EVA") or "CATUMBI" in bs:
                return "Catumbi", "Leste"
            if tc.startswith("ESL") or tc.startswith("ESA") or "SANTO ANDR" in bs:
                return "Santo André", "Leste"
            return "Outras Bases", "Norte"

        today_op = self.get_operational_date()
        if mode == "realtime":
            date_ref = today_op
        elif not date_ref or date_ref > today_op:
            date_ref = today_op
        if not month_ref:
            month_ref = date_ref[:7] if date_ref else today_op[:7]

        clean_scope = str(geo_scope or "ALL").strip().upper()
        selected_bases = _to_clean_list(base_filter)
        selected_vehicles = _to_clean_list(vehicle_filter)
        selected_shifts = _to_clean_list(shift_filter)
        selected_shift_codes = _to_clean_list(shift_code_filter)
        selected_statuses = _to_clean_list(status_login_filter)

        # Chave de cache em memória ultrarrápida
        cache_key = (
            mode,
            date_ref if mode != "monthly" else month_ref,
            clean_scope,
            tuple(sorted(selected_bases)),
            tuple(sorted(selected_vehicles)),
            tuple(sorted(selected_shifts)),
            tuple(sorted(selected_shift_codes)),
            tuple(sorted(selected_statuses)),
            include_stc_leste
        )
        now_ts = time.time()
        ttl = 30 if mode == "realtime" else 180
        if cache_key in self._delays_analytics_cache:
            c_ts, c_data = self._delays_analytics_cache[cache_key]
            if now_ts - c_ts < ttl:
                return c_data

        now_dt = datetime.now(BR_TZ)
        is_post_midnight_op = (now_dt.hour < 4 or (now_dt.hour == 4 and now_dt.minute <= 30))
        if is_post_midnight_op:
            current_clock_minutes = (now_dt.hour + 24) * 60 + now_dt.minute
        else:
            current_clock_minutes = now_dt.hour * 60 + now_dt.minute

        def _matches_filters(t_obj, pricing):
            # 0. Regra Executiva/Operacional:
            # - No modo TEMPO REAL (HOJE):
            #   Considerar todas as equipes que efetivamente logaram (possuem marcação) ou que estão ativas no portal.
            #   Equipes sem marcação (apenas programadas) de turnos futuros (cujo horário ainda não iniciou) são descartadas.
            # - Nos modos HISTÓRICO DIA A DIA e ACUMULADO DO MÊS:
            #   Desconsiderar equipes apenas programadas que não efetuaram login (mostrar somente equipes que logaram).
            has_marc = bool(t_obj.get("marcacao") and str(t_obj.get("marcacao")).strip() not in ["--", "-", "None", "nan", "", "--:--"])
            is_active = bool(t_obj.get("is_active", False))

            if mode in ["daily", "monthly"]:
                if not has_marc:
                    return False
            elif mode == "realtime":
                if not has_marc and not is_active:
                    # Se não tem marcação e não está ativa, descarta apenas se o turno for futuro
                    raw_sc = str(t_obj.get("shift_code") or "08:00").strip()
                    t_turno = str(t_obj.get("turno") or "").lower()
                    if "tarde" in t_turno or raw_sc in ["11:30", "12:00", "12:30", "13:00", "14:00", "15:00", "15:30"]:
                        sc_canon = "12:00" if raw_sc in ["11:30", "12:00", "12:30", "13:00"] else "14:00"
                    elif "noite" in t_turno or raw_sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00", "22:00"]:
                        sc_canon = "20:00" if raw_sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00"] else "22:00"
                    else:
                        sc_canon = "06:00" if raw_sc in ["06:00", "06:30", "07:00", "07:30"] else "08:00"

                    sc_start_min = {"06:00": 360, "08:00": 480, "12:00": 720, "14:00": 840, "20:00": 1200, "22:00": 1320}.get(sc_canon, 480)
                    if sc_start_min > current_clock_minutes:
                        return False

            code = str(t_obj.get("team_code") or "").strip().upper()
            b_raw = str(t_obj.get("base_display") or t_obj.get("base_name") or t_obj.get("base_code") or "").upper()
            base_std, reg_std = _identify_base(code, b_raw)

            # 1. Filtro STC Leste
            if not include_stc_leste and pricing["is_stc_leste"]:
                return False

            # 2. Filtro Regional
            if clean_scope == "NORTE" and reg_std != "Norte":
                return False
            if clean_scope == "LESTE" and reg_std != "Leste":
                return False

            # 3. Filtro Multi-Select Base
            if selected_bases:
                base_matched = False
                for sb in selected_bases:
                    if sb in base_std.upper() or sb in b_raw or sb in code:
                        base_matched = True
                        break
                if not base_matched:
                    return False

            # 4. Filtro Multi-Select Frota / Veiculo
            if selected_vehicles:
                veh_matched = False
                vt_curr = str(t_obj.get("vehicle_type") or "").upper()
                ug_curr = str(t_obj.get("unified_group") or "").upper()
                cat_k = pricing["contract_category"]

                for sv in selected_vehicles:
                    if sv == "CESTO" and cat_k == "CESTO":
                        veh_matched = True; break
                    elif sv == "LEVE" and cat_k == "LEVE":
                        veh_matched = True; break
                    elif sv == "MOTO" and cat_k == "MOTO":
                        veh_matched = True; break
                    elif sv == "RAMAL" and pricing["is_ramal"]:
                        veh_matched = True; break
                    elif sv == "STC" and pricing["is_stc_leste"]:
                        veh_matched = True; break
                    elif sv in vt_curr or sv in ug_curr:
                        veh_matched = True; break
                if not veh_matched:
                    return False

            # 5. Filtro Multi-Select Turno (Manha, Tarde, Noite)
            if selected_shifts:
                t_turno = str(t_obj.get("turno") or "").upper()
                if not any(ss in t_turno for ss in selected_shifts):
                    return False

            # 6. Filtro Multi-Select Horario (Agrupamento Oficial: 06:00, 08:00, 12:00, 14:00, 20:00, 22:00)
            if selected_shift_codes:
                raw_sc = str(t_obj.get("shift_code") or "").strip()
                t_turno = str(t_obj.get("turno") or "").lower()
                # Aplica regra de agrupamento oficial
                if "tarde" in t_turno or raw_sc in ["12:00", "14:00", "15:00", "15:30", "11:30", "12:30", "13:00"]:
                    sc_canon = "12:00" if raw_sc in ["11:30", "12:00", "12:30", "13:00"] else "14:00"
                elif "noite" in t_turno or raw_sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00", "22:00"]:
                    sc_canon = "20:00" if raw_sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00"] else "22:00"
                else:
                    sc_canon = "06:00" if raw_sc in ["06:00", "06:30", "07:00", "07:30"] else "08:00"

                if not (sc_canon in selected_shift_codes or raw_sc in selected_shift_codes):
                    return False

            # 7. Filtro Multi-Select Status Login (Logado, Programado, Em Atraso, No Prazo)
            if selected_statuses:
                is_delay = pricing["delay_minutes"] > 0 and has_marc

                status_matched = False
                for ss in selected_statuses:
                    ss_u = ss.upper()
                    if ss_u in ["LOGADA", "LOGADO"] and has_marc:
                        status_matched = True; break
                    elif ss_u in ["PROGRAMADA", "PROGRAMADO", "SEM_LOGIN"] and not has_marc:
                        status_matched = True; break
                    elif ss_u in ["ATRASADA", "EM ATRASO", "EM_ATRASO"] and is_delay:
                        status_matched = True; break
                    elif ss_u in ["NO_PRAZO", "NO PRAZO", "PONTUAL"] and (has_marc and not is_delay):
                        status_matched = True; break
                if not status_matched:
                    return False

            return True

        # =====================================================================
        # MODO 3: MENSAL (ACUMULADO DO MES - C-LEVEL EXECUTIVO)
        # =====================================================================
        if mode == "monthly":
            avail = self.get_available_audit_dates()
            all_dates = avail.get("dates", [])
            month_dates = sorted([d for d in all_dates if str(d).startswith(month_ref)])
            if today_op.startswith(month_ref) and today_op not in month_dates:
                month_dates.append(today_op)
            month_dates = sorted(list(set(month_dates)))

            daily_trend = []
            tot_monthly_teams = 0
            tot_monthly_teams_norte = 0
            tot_monthly_teams_leste = 0

            tot_monthly_atrasadas = 0
            tot_monthly_atrasadas_norte = 0
            tot_monthly_atrasadas_leste = 0

            tot_monthly_no_prazo = 0
            tot_monthly_no_prazo_norte = 0
            tot_monthly_no_prazo_leste = 0

            tot_monthly_tempo_atraso_min = 0
            tot_monthly_tempo_atraso_norte_min = 0
            tot_monthly_tempo_atraso_leste_min = 0

            tot_monthly_tempo_no_prazo_min = 0
            tot_monthly_tempo_no_prazo_norte_min = 0
            tot_monthly_tempo_no_prazo_leste_min = 0

            tot_monthly_perda_financeira = 0.0
            tot_monthly_perda_financeira_norte = 0.0
            tot_monthly_perda_financeira_leste = 0.0

            # Bases oficiais
            bases_accum = {
                "Fagundes Filho": {"name": "Fagundes Filho", "region": "Norte", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Cajati": {"name": "Cajati", "region": "Norte", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Vila Medeiros": {"name": "Vila Medeiros", "region": "Norte", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Monte Santo": {"name": "Monte Santo", "region": "Leste", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Aricanduva": {"name": "Aricanduva", "region": "Leste", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Catumbi": {"name": "Catumbi", "region": "Leste", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Santo André": {"name": "Santo André", "region": "Leste", "equipes": 0, "atrasadas": 0, "tempo_min": 0, "perda_reais": 0.0}
            }

            shifts_accum = {
                "Manhã": {"turno": "Manhã", "atrasadas": 0, "no_prazo": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Tarde": {"turno": "Tarde", "atrasadas": 0, "no_prazo": 0, "tempo_min": 0, "perda_reais": 0.0},
                "Noite": {"turno": "Noite", "atrasadas": 0, "no_prazo": 0, "tempo_min": 0, "perda_reais": 0.0}
            }

            teams_recurrent = {}
            justifications_monthly_accum = {}

            # Carrega justificativas do mes via Supabase
            from supabase_client import fetch_team_delay_justifications_by_month
            month_justs_raw = fetch_team_delay_justifications_by_month(month_ref)
            just_by_date_team = {}
            for jrec in month_justs_raw:
                d_k = jrec.get("date_ref")
                t_k = str(jrec.get("team_code") or "").strip().upper()
                if d_k and t_k:
                    just_by_date_team[(d_k, t_k)] = jrec

            # Carregamento em paralelo de alta performance para datas ainda não cacheadas
            missing_dates = [d for d in month_dates if d != today_op and d not in self._delays_history_records_cache]
            if missing_dates:
                from supabase_client import fetch_delivery_records_by_date
                with ThreadPoolExecutor(max_workers=min(len(missing_dates), 10)) as executor:
                    fut_to_date = {executor.submit(fetch_delivery_records_by_date, d): d for d in missing_dates}
                    for fut in as_completed(fut_to_date):
                        target_d = fut_to_date[fut]
                        try:
                            recs = fut.result() or []
                            self._delays_history_records_cache[target_d] = recs
                        except Exception as ex:
                            logger.warning(f"[Delays Monthly] Erro ao carregar data {target_d}: {ex}")
                            self._delays_history_records_cache[target_d] = []

            for d_str in month_dates:
                is_curr_day = (d_str == today_op)
                day_teams = []
                if is_curr_day:
                    day_teams = list(self.daily_accumulated_teams.values()) if self.daily_accumulated_teams else list(self.active_teams)
                else:
                    day_teams = self._delays_history_records_cache.get(d_str, [])

                d_atrasadas = 0
                d_no_prazo = 0
                d_tempo_atraso = 0
                d_tempo_no_prazo = 0
                d_perda_fin = 0.0
                d_count = 0

                for t in day_teams:
                    code = str(t.get("team_code") or "").strip().upper()
                    if not code:
                        continue
                    pricing = classify_and_price_team(t, date_ref=d_str)
                    if not _matches_filters(t, pricing):
                        continue

                    d_count += 1
                    is_norte = (pricing["contract_regiao"] == "NORTE")
                    if is_norte:
                        tot_monthly_teams_norte += 1
                    else:
                        tot_monthly_teams_leste += 1

                    d_min = pricing["delay_minutes"]
                    loss = pricing["financial_loss"]

                    # Base match
                    b_raw = str(t.get("base_display") or t.get("base_name") or t.get("base_code") or "").upper()
                    matched_base, _ = _identify_base(code, b_raw)

                    # Turno match
                    t_turno = str(t.get("turno") or "Manhã").lower()
                    if "tarde" in t_turno:
                        t_shift_key = "Tarde"
                    elif "noite" in t_turno:
                        t_shift_key = "Noite"
                    else:
                        t_shift_key = "Manhã"

                    if code not in teams_recurrent:
                        teams_recurrent[code] = {
                            "team_code": code,
                            "base": matched_base,
                            "region": pricing["contract_regiao"],
                            "vehicle_type": pricing["contract_cat_display"],
                            "dias_trabalhados": 0,
                            "dias_atraso": 0,
                            "tempo_atraso_min": 0,
                            "perda_financeira": 0.0
                        }
                    teams_recurrent[code]["dias_trabalhados"] += 1

                    if d_min > 0:
                        d_atrasadas += 1
                        d_tempo_atraso += d_min
                        d_perda_fin += loss

                        if is_norte:
                            tot_monthly_atrasadas_norte += 1
                            tot_monthly_tempo_atraso_norte_min += d_min
                            tot_monthly_perda_financeira_norte += loss
                        else:
                            tot_monthly_atrasadas_leste += 1
                            tot_monthly_tempo_atraso_leste_min += d_min
                            tot_monthly_perda_financeira_leste += loss

                        if matched_base in bases_accum:
                            bases_accum[matched_base]["atrasadas"] += 1
                            bases_accum[matched_base]["tempo_min"] += d_min
                            bases_accum[matched_base]["perda_reais"] += loss

                        shifts_accum[t_shift_key]["atrasadas"] += 1
                        shifts_accum[t_shift_key]["tempo_min"] += d_min
                        shifts_accum[t_shift_key]["perda_reais"] += loss

                        teams_recurrent[code]["dias_atraso"] += 1
                        teams_recurrent[code]["tempo_atraso_min"] += d_min
                        teams_recurrent[code]["perda_financeira"] += loss

                        # Acumula Justificativa Mensal
                        just_data = just_by_date_team.get((d_str, code)) or t.get("delay_justification") or {}
                        macro = just_data.get("macro_reason") or "Sem Justificativa Registrada"
                        sub = just_data.get("sub_reason") or "--"

                        if macro not in justifications_monthly_accum:
                            justifications_monthly_accum[macro] = {
                                "macro_reason": macro,
                                "has_justification": bool(just_data.get("macro_reason")),
                                "sub_reasons": {},
                                "qtd_equipes": 0,
                                "tempo_min": 0,
                                "perda_reais": 0.0
                            }
                        justifications_monthly_accum[macro]["qtd_equipes"] += 1
                        justifications_monthly_accum[macro]["tempo_min"] += d_min
                        justifications_monthly_accum[macro]["perda_reais"] += loss
                        if sub and sub != "--":
                            justifications_monthly_accum[macro]["sub_reasons"][sub] = justifications_monthly_accum[macro]["sub_reasons"].get(sub, 0) + 1
                    else:
                        d_no_prazo += 1
                        d_tempo_no_prazo += abs(d_min)
                        shifts_accum[t_shift_key]["no_prazo"] += 1

                        if is_norte:
                            tot_monthly_no_prazo_norte += 1
                            tot_monthly_tempo_no_prazo_norte_min += abs(d_min)
                        else:
                            tot_monthly_no_prazo_leste += 1
                            tot_monthly_tempo_no_prazo_leste_min += abs(d_min)

                    if matched_base in bases_accum:
                        bases_accum[matched_base]["equipes"] += 1

                tot_monthly_teams += d_count
                tot_monthly_atrasadas += d_atrasadas
                tot_monthly_no_prazo += d_no_prazo
                tot_monthly_tempo_atraso_min += d_tempo_atraso
                tot_monthly_tempo_no_prazo_min += d_tempo_no_prazo
                tot_monthly_perda_financeira += d_perda_fin

                day_num = int(d_str.split("-")[-1]) if "-" in d_str else 0
                daily_trend.append({
                    "date": d_str,
                    "day": day_num,
                    "total_equipes": d_count,
                    "atrasadas": d_atrasadas,
                    "no_prazo": d_no_prazo,
                    "tempo_atraso_min": d_tempo_atraso,
                    "tempo_atraso_str": _fmt_hm(d_tempo_atraso),
                    "perda_financeira": round(d_perda_fin, 2),
                    "perda_financeira_str": _fmt_brl(d_perda_fin)
                })

            top_recurrent = sorted(teams_recurrent.values(), key=lambda x: (x["perda_financeira"], x["tempo_atraso_min"]), reverse=True)[:15]
            for tr in top_recurrent:
                tr["perda_financeira_str"] = _fmt_brl(tr["perda_financeira"])
                tr["tempo_atraso_str"] = _fmt_hm(tr["tempo_atraso_min"])

            bases_list = sorted(bases_accum.values(), key=lambda x: x["perda_reais"], reverse=True)
            for b in bases_list:
                b["perda_reais_str"] = _fmt_brl(b["perda_reais"])
                b["tempo_str"] = _fmt_hm(b["tempo_min"])

            shifts_list = list(shifts_accum.values())
            for s in shifts_list:
                s["perda_reais_str"] = _fmt_brl(s["perda_reais"])
                s["tempo_str"] = _fmt_hm(s["tempo_min"])

            # Formata Justificativas Mensais
            just_monthly_list = sorted(justifications_monthly_accum.values(), key=lambda x: x["perda_reais"], reverse=True)
            for jm in just_monthly_list:
                jm["perda_reais_str"] = _fmt_brl(jm["perda_reais"])
                jm["tempo_str"] = _fmt_hm(jm["tempo_min"])
                jm["pct_perda"] = round((jm["perda_reais"] / tot_monthly_perda_financeira * 100), 1) if tot_monthly_perda_financeira > 0 else 0.0
                # Top sub reason
                if jm["sub_reasons"]:
                    top_sub = max(jm["sub_reasons"].items(), key=lambda item: item[1])[0]
                    jm["top_sub_reason"] = top_sub
                else:
                    jm["top_sub_reason"] = "--"

            # Prepara enriquecimento de equipes para tabela mensal (top reincidentes)
            monthly_table_teams = []
            for r in top_recurrent:
                monthly_table_teams.append({
                    "ut": f"UT {str(r.get('region', 'Norte')).title()}",
                    "team_code": r["team_code"],
                    "base": r["base"],
                    "region": r["region"],
                    "vehicle_type": r["vehicle_type"],
                    "turno": "Mensal",
                    "shift_code": "--",
                    "login_time": f"{r['dias_atraso']}/{r['dias_trabalhados']}d atraso",
                    "marcacao": "--",
                    "status_login": "REINCIDENTE",
                    "delay_minutes": r["tempo_atraso_min"],
                    "delay_str": r["tempo_atraso_str"],
                    "rate_hour": 0.0,
                    "rate_hour_str": "--",
                    "financial_loss": r["perda_financeira"],
                    "financial_loss_str": r["perda_financeira_str"],
                    "macro_reason": "Reincidência Mensal",
                    "sub_reason": f"{r['dias_atraso']} dias em atraso",
                    "has_justification": False
                })

            custo_medio_mensal_atrasada = (tot_monthly_perda_financeira / tot_monthly_atrasadas) if tot_monthly_atrasadas > 0 else 0.0
            taxa_pont_mensal_norte = round((tot_monthly_no_prazo_norte / tot_monthly_teams_norte * 100), 1) if tot_monthly_teams_norte > 0 else 100.0
            taxa_pont_mensal_leste = round((tot_monthly_no_prazo_leste / tot_monthly_teams_leste * 100), 1) if tot_monthly_teams_leste > 0 else 100.0
            taxa_pont_mensal_geral = round((tot_monthly_no_prazo / tot_monthly_teams * 100), 1) if tot_monthly_teams > 0 else 100.0

            res_monthly = {
                "status": "success",
                "mode": "monthly",
                "month_ref": month_ref,
                "geo_scope": clean_scope,
                "include_stc_leste": include_stc_leste,
                "total_equipes": tot_monthly_teams,
                "total_atrasadas": tot_monthly_atrasadas,
                "total_no_prazo": tot_monthly_no_prazo,

                "total_perda_financeira": round(tot_monthly_perda_financeira, 2),
                "total_perda_financeira_str": _fmt_brl(tot_monthly_perda_financeira),
                "perda_financeira_norte": round(tot_monthly_perda_financeira_norte, 2),
                "perda_financeira_norte_str": _fmt_brl(tot_monthly_perda_financeira_norte),
                "perda_financeira_leste": round(tot_monthly_perda_financeira_leste, 2),
                "perda_financeira_leste_str": _fmt_brl(tot_monthly_perda_financeira_leste),
                "custo_medio_atrasada": custo_medio_mensal_atrasada,
                "custo_medio_atrasada_str": _fmt_brl(custo_medio_mensal_atrasada),

                "total_tempo_atraso_min": tot_monthly_tempo_atraso_min,
                "total_tempo_atraso_str": _fmt_hm(tot_monthly_tempo_atraso_min),
                "tempo_atraso_norte_min": tot_monthly_tempo_atraso_norte_min,
                "tempo_atraso_norte_str": _fmt_hm(tot_monthly_tempo_atraso_norte_min),
                "tempo_atraso_leste_min": tot_monthly_tempo_atraso_leste_min,
                "tempo_atraso_leste_str": _fmt_hm(tot_monthly_tempo_atraso_leste_min),
                "media_tempo_atrasada_str": _fmt_min_or_hm((tot_monthly_tempo_atraso_min / tot_monthly_atrasadas) if tot_monthly_atrasadas > 0 else 0),

                "total_tempo_no_prazo_min": tot_monthly_tempo_no_prazo_min,
                "total_tempo_no_prazo_str": _fmt_hm(tot_monthly_tempo_no_prazo_min),
                "tempo_no_prazo_norte_min": tot_monthly_tempo_no_prazo_norte_min,
                "tempo_no_prazo_norte_str": _fmt_hm(tot_monthly_tempo_no_prazo_norte_min),
                "tempo_no_prazo_leste_min": tot_monthly_tempo_no_prazo_leste_min,
                "tempo_no_prazo_leste_str": _fmt_hm(tot_monthly_tempo_no_prazo_leste_min),
                "media_tempo_no_prazo_str": _fmt_min_or_hm((tot_monthly_tempo_no_prazo_min / tot_monthly_no_prazo) if tot_monthly_no_prazo > 0 else 0),

                "taxa_pontualidade_geral": taxa_pont_mensal_geral,
                "taxa_pontualidade_geral_str": f"{taxa_pont_mensal_geral}%",
                "taxa_pontualidade_norte": taxa_pont_mensal_norte,
                "taxa_pontualidade_norte_str": f"{taxa_pont_mensal_norte}%",
                "taxa_pontualidade_leste": taxa_pont_mensal_leste,
                "taxa_pontualidade_leste_str": f"{taxa_pont_mensal_leste}%",

                "daily_trend": daily_trend,
                "bases_summary": bases_list,
                "shifts_summary": shifts_list,
                "top_recurrent_teams": top_recurrent,
                "justifications_summary": just_monthly_list,
                "teams": monthly_table_teams
            }
            self._delays_analytics_cache[cache_key] = (now_ts, res_monthly)
            return res_monthly

        # =====================================================================
        # MODO 1 E 2: REALTIME (AO VIVO) OU DAILY (HISTORICO DO DIA)
        # =====================================================================
        is_today = (date_ref == today_op)
        teams_list = []
        if is_today:
            # Combina equipes do Supabase (para persistência e resiliência a reinicialização de containers)
            # com o acumulador diário em memória e as equipes ativas
            teams_dict = {}
            try:
                from supabase_client import fetch_delivery_records_by_date
                supa_recs = fetch_delivery_records_by_date(today_op) or []
                for r in supa_recs:
                    c = str(r.get("team_code") or "").strip().upper()
                    if c:
                        teams_dict[c] = r
            except Exception as e_sup:
                logger.warning(f"[Delays Analytics] Erro ao carregar registros do Supabase para {today_op}: {e_sup}")

            # 2. Mescla com acumulador diário em memória (mais recente)
            for c, t in self.daily_accumulated_teams.items():
                code = str(c or "").strip().upper()
                if code:
                    teams_dict[code] = t

            # 3. Mescla com equipes ativas no momento
            for t in (self.active_teams or []):
                code = str(t.get("team_code") or "").strip().upper()
                if code:
                    teams_dict[code] = t

            teams_list = list(teams_dict.values())
        elif date_ref in self._delays_history_records_cache:
            teams_list = self._delays_history_records_cache[date_ref]
        else:
            from supabase_client import fetch_delivery_records_by_date
            teams_list = fetch_delivery_records_by_date(date_ref) or []
            self._delays_history_records_cache[date_ref] = teams_list

        # Justificativas do dia
        justifications = self.hydrate_delay_justifications(date_ref, force=True)

        shifts_structure = {
            "Manhã": {
                "turno": "Manhã",
                "label": "Turno Manhã",
                "icon": "sun",
                "color": "#38bdf8",
                "atrasadas": 0,
                "no_prazo": 0,
                "total": 0,
                "tempo_atraso_min": 0,
                "tempo_no_prazo_min": 0,
                "perda_financeira": 0.0,
                "horarios": {
                    "06:00": {"shift_code": "06:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0},
                    "08:00": {"shift_code": "08:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0}
                }
            },
            "Tarde": {
                "turno": "Tarde",
                "label": "Turno Tarde",
                "icon": "sunset",
                "color": "#f59e0b",
                "atrasadas": 0,
                "no_prazo": 0,
                "total": 0,
                "tempo_atraso_min": 0,
                "tempo_no_prazo_min": 0,
                "perda_financeira": 0.0,
                "horarios": {
                    "12:00": {"shift_code": "12:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0},
                    "14:00": {"shift_code": "14:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0}
                }
            },
            "Noite": {
                "turno": "Noite",
                "label": "Turno Noite",
                "icon": "moon",
                "color": "#c084fc",
                "atrasadas": 0,
                "no_prazo": 0,
                "total": 0,
                "tempo_atraso_min": 0,
                "tempo_no_prazo_min": 0,
                "perda_financeira": 0.0,
                "horarios": {
                    "20:00": {"shift_code": "20:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0},
                    "22:00": {"shift_code": "22:00", "atrasadas": 0, "no_prazo": 0, "total": 0, "tempo_atraso_min": 0, "perda_financeira": 0.0}
                }
            }
        }

        total_filtradas = 0
        total_filtradas_norte = 0
        total_filtradas_leste = 0

        total_atrasadas = 0
        total_atrasadas_norte = 0
        total_atrasadas_leste = 0

        total_no_prazo = 0
        total_no_prazo_norte = 0
        total_no_prazo_leste = 0

        total_tempo_atraso_min = 0
        tempo_atraso_norte_min = 0
        tempo_atraso_leste_min = 0

        total_tempo_no_prazo_min = 0
        tempo_no_prazo_norte_min = 0
        tempo_no_prazo_leste_min = 0

        total_perda_financeira = 0.0
        perda_financeira_norte = 0.0
        perda_financeira_leste = 0.0

        enriched_teams = []
        delayed_teams = []
        justifications_daily_accum = {}

        # Estrutura para Curva Horaria Dinamica de Perdas e Tempo (Baseada na Hora da Marcacao/Login)
        def _extract_hour(marc_val):
            if not marc_val:
                return "08:00", 8
            m_str = str(marc_val).strip()
            if " " in m_str:
                m_str = m_str.split(" ")[-1]
            elif "T" in m_str:
                m_str = m_str.split("T")[-1]
            if ":" in m_str:
                parts = m_str.split(":")
                try:
                    h = int(parts[0])
                    if 0 <= h <= 23:
                        return f"{h:02d}:00", h
                except Exception:
                    pass
            return "08:00", 8

        hourly_accum = {}
        for h in range(5, 24):
            h_str = f"{h:02d}:00"
            hourly_accum[h_str] = {
                "hour_str": h_str,
                "hour_num": h,
                "total_loss": 0.0,
                "total_delay_min": 0,
                "count_teams": 0,
                "norte": {"loss": 0.0, "delay_min": 0, "count": 0},
                "leste": {"loss": 0.0, "delay_min": 0, "count": 0},
                "_bases": {},
                "_teams": []
            }

        for t in teams_list:
            code = str(t.get("team_code") or "").strip().upper()
            if not code:
                continue

            pricing = classify_and_price_team(t, date_ref=date_ref)
            if not _matches_filters(t, pricing):
                continue

            total_filtradas += 1
            is_norte = (pricing["contract_regiao"] == "NORTE")
            if is_norte:
                total_filtradas_norte += 1
            else:
                total_filtradas_leste += 1

            d_min = pricing["delay_minutes"]
            loss = pricing["financial_loss"]
            sc = str(t.get("shift_code") or "08:00").strip()

            # Identifica Turno Macro e Consolida no Agrupamento Oficial
            t_turno = str(t.get("turno") or "").lower()
            if "tarde" in t_turno or sc in ["11:30", "12:00", "12:30", "13:00", "14:00", "15:00", "15:30"]:
                turno_key = "Tarde"
                sc = "12:00" if sc in ["11:30", "12:00", "12:30", "13:00"] else "14:00"
            elif "noite" in t_turno or sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00", "22:00"]:
                turno_key = "Noite"
                sc = "20:00" if sc in ["18:00", "18:30", "19:00", "20:00", "20:30", "21:00"] else "22:00"
            else:
                turno_key = "Manhã"
                sc = "06:00" if sc in ["06:00", "06:30", "07:00", "07:30"] else "08:00"

            t_has_marc = bool(t.get("marcacao") and str(t.get("marcacao")).strip() not in ["--", "-", "None", "nan", "", "--:--"])

            # Trava Temporal Absoluta em Tempo Real:
            # Se a equipe JÁ LOGOU (possui marcação), o atraso dela é real e histórico! JAMAIS deve ser zerado.
            # A trava de turno futuro SÓ se aplica para equipes SEM MARCAÇÃO (programadas) cujo horário de turno ainda não começou hoje!
            sc_start_min = {"06:00": 360, "08:00": 480, "12:00": 720, "14:00": 840, "20:00": 1200, "22:00": 1320}.get(sc, 480)
            if mode == "realtime" and not t_has_marc and sc_start_min > current_clock_minutes:
                d_min = 0
                loss = 0.0

            if sc not in shifts_structure[turno_key]["horarios"]:
                shifts_structure[turno_key]["horarios"][sc] = {
                    "shift_code": sc,
                    "atrasadas": 0,
                    "no_prazo": 0,
                    "total": 0,
                    "tempo_atraso_min": 0,
                    "perda_financeira": 0.0
                }

            shifts_structure[turno_key]["total"] += 1
            shifts_structure[turno_key]["horarios"][sc]["total"] += 1

            just = justifications.get(code) or t.get("delay_justification")
            b_raw = str(t.get("base_display") or t.get("base_name") or t.get("base_code") or "").upper()
            base_std, _ = _identify_base(code, b_raw)

            macro_r = just.get("macro_reason") if just else "Sem Justificativa Registrada"
            sub_r = just.get("sub_reason") if just else "--"
            st_login_val = "LOGADA" if t_has_marc else "PROGRAMADA"

            ut_val = str(t.get("ut") or "").strip()
            if not ut_val or ut_val in ["--", "-", "None", "nan", ""]:
                ut_val = "UT Norte" if pricing["contract_regiao"] == "NORTE" else "UT Leste"

            if d_min > 0 and t_has_marc:
                total_atrasadas += 1
                total_tempo_atraso_min += d_min
                total_perda_financeira += loss

                if is_norte:
                    perda_financeira_norte += loss
                    total_atrasadas_norte += 1
                    tempo_atraso_norte_min += d_min
                else:
                    perda_financeira_leste += loss
                    total_atrasadas_leste += 1
                    tempo_atraso_leste_min += d_min

                shifts_structure[turno_key]["atrasadas"] += 1
                shifts_structure[turno_key]["tempo_atraso_min"] += d_min
                shifts_structure[turno_key]["perda_financeira"] += loss

                shifts_structure[turno_key]["horarios"][sc]["atrasadas"] += 1
                shifts_structure[turno_key]["horarios"][sc]["tempo_atraso_min"] += d_min
                shifts_structure[turno_key]["horarios"][sc]["perda_financeira"] += loss

                team_entry = {
                    "ut": ut_val,
                    "team_code": code,
                    "base": base_std,
                    "region": pricing["contract_regiao"],
                    "vehicle_type": pricing["contract_cat_display"],
                    "turno": turno_key,
                    "shift_code": sc,
                    "login_time": t.get("login_time") or "--",
                    "marcacao": t.get("marcacao") or "--",
                    "status_login": st_login_val,
                    "delay_minutes": d_min,
                    "delay_str": f"+{d_min} min",
                    "rate_hour": pricing["rate_hour"],
                    "rate_hour_str": pricing["rate_hour_str"],
                    "financial_loss": loss,
                    "financial_loss_str": pricing["financial_loss_str"],
                    "macro_reason": macro_r,
                    "sub_reason": sub_r,
                    "user_name": just.get("user_name") if just else None,
                    "observation": just.get("observation") if just else None,
                    "has_justification": bool(just)
                }
                delayed_teams.append(team_entry)
                enriched_teams.append(team_entry)

                # Acumula na analise de Justificativas
                if macro_r not in justifications_daily_accum:
                    justifications_daily_accum[macro_r] = {
                        "macro_reason": macro_r,
                        "has_justification": bool(just),
                        "sub_reasons": {},
                        "qtd_equipes": 0,
                        "tempo_min": 0,
                        "perda_reais": 0.0
                    }
                justifications_daily_accum[macro_r]["qtd_equipes"] += 1
                justifications_daily_accum[macro_r]["tempo_min"] += d_min
                justifications_daily_accum[macro_r]["perda_reais"] += loss
                if sub_r and sub_r != "--":
                    justifications_daily_accum[macro_r]["sub_reasons"][sub_r] = justifications_daily_accum[macro_r]["sub_reasons"].get(sub_r, 0) + 1

                # Acumula na Curva Horaria Dinamica pela Hora da Marcacao/Login (Termino da Ociosidade)
                h_str, h_num = _extract_hour(t.get("marcacao") or t.get("login_time"))
                if h_str not in hourly_accum:
                    hourly_accum[h_str] = {
                        "hour_str": h_str,
                        "hour_num": h_num,
                        "total_loss": 0.0,
                        "total_delay_min": 0,
                        "count_teams": 0,
                        "norte": {"loss": 0.0, "delay_min": 0, "count": 0},
                        "leste": {"loss": 0.0, "delay_min": 0, "count": 0},
                        "_bases": {},
                        "_teams": []
                    }

                h_bucket = hourly_accum[h_str]
                h_bucket["total_loss"] += loss
                h_bucket["total_delay_min"] += d_min
                h_bucket["count_teams"] += 1

                is_norte = (pricing["contract_regiao"] == "NORTE")
                reg_k = "norte" if is_norte else "leste"
                h_bucket[reg_k]["loss"] += loss
                h_bucket[reg_k]["delay_min"] += d_min
                h_bucket[reg_k]["count"] += 1

                if base_std not in h_bucket["_bases"]:
                    h_bucket["_bases"][base_std] = {
                        "name": base_std,
                        "region": "Norte" if is_norte else "Leste",
                        "loss": 0.0,
                        "delay_min": 0,
                        "count": 0
                    }
                h_bucket["_bases"][base_std]["loss"] += loss
                h_bucket["_bases"][base_std]["delay_min"] += d_min
                h_bucket["_bases"][base_std]["count"] += 1

                h_bucket["_teams"].append({
                    "team_code": code,
                    "base": base_std,
                    "region": "Norte" if is_norte else "Leste",
                    "marcacao": t.get("marcacao") or "--",
                    "delay_minutes": d_min,
                    "delay_str": f"+{d_min} min",
                    "financial_loss": loss,
                    "financial_loss_str": pricing["financial_loss_str"]
                })
            else:
                if t_has_marc:
                    total_no_prazo += 1
                    tempo_no_prazo = abs(d_min)
                    total_tempo_no_prazo_min += tempo_no_prazo

                    if is_norte:
                        total_no_prazo_norte += 1
                        tempo_no_prazo_norte_min += tempo_no_prazo
                    else:
                        total_no_prazo_leste += 1
                        tempo_no_prazo_leste_min += tempo_no_prazo

                    shifts_structure[turno_key]["no_prazo"] += 1
                    shifts_structure[turno_key]["tempo_no_prazo_min"] += tempo_no_prazo
                    shifts_structure[turno_key]["horarios"][sc]["no_prazo"] += 1

                enriched_teams.append({
                    "ut": ut_val,
                    "team_code": code,
                    "base": base_std,
                    "region": pricing["contract_regiao"],
                    "vehicle_type": pricing["contract_cat_display"],
                    "turno": turno_key,
                    "shift_code": sc,
                    "login_time": t.get("login_time") or "--",
                    "marcacao": t.get("marcacao") or "--",
                    "status_login": st_login_val,
                    "delay_minutes": d_min if t_has_marc else 0,
                    "delay_str": f"{d_min} min" if (t_has_marc and d_min < 0) else ("No Prazo" if t_has_marc else "Programada"),
                    "rate_hour": pricing["rate_hour"],
                    "rate_hour_str": pricing["rate_hour_str"],
                    "financial_loss": 0.0,
                    "financial_loss_str": "R$ 0,00",
                    "macro_reason": "NO PRAZO" if t_has_marc else "PROGRAMADA",
                    "sub_reason": "--",
                    "user_name": None,
                    "observation": None,
                    "has_justification": False
                })

        # Formata estruturas de turnos
        for t_k, t_data in shifts_structure.items():
            t_data["perda_financeira_str"] = _fmt_brl(t_data["perda_financeira"])
            t_data["tempo_atraso_str"] = _fmt_hm(t_data["tempo_atraso_min"])
            t_data["tempo_no_prazo_str"] = _fmt_hm(t_data["tempo_no_prazo_min"])
            # Ordena horarios
            sorted_horarios = dict(sorted(t_data["horarios"].items(), key=lambda x: x[0]))
            for h_k, h_val in sorted_horarios.items():
                h_val["perda_financeira_str"] = _fmt_brl(h_val["perda_financeira"])
                h_val["tempo_atraso_str"] = _fmt_hm(h_val["tempo_atraso_min"])
            t_data["horarios"] = sorted_horarios

        # TOP Equipes em Atraso
        top_delayed = sorted(delayed_teams, key=lambda x: (x["financial_loss"], x["delay_minutes"]), reverse=True)[:10]

        # TOP Justificativas Diarias
        just_daily_list = sorted(justifications_daily_accum.values(), key=lambda x: x["perda_reais"], reverse=True)
        for jd in just_daily_list:
            jd["perda_reais_str"] = _fmt_brl(jd["perda_reais"])
            jd["tempo_str"] = _fmt_hm(jd["tempo_min"])
            jd["pct_perda"] = round((jd["perda_reais"] / total_perda_financeira * 100), 1) if total_perda_financeira > 0 else 0.0
            if jd["sub_reasons"]:
                top_sub = max(jd["sub_reasons"].items(), key=lambda item: item[1])[0]
                jd["top_sub_reason"] = top_sub
            else:
                jd["top_sub_reason"] = "--"

        custo_medio_atrasada = (total_perda_financeira / total_atrasadas) if total_atrasadas > 0 else 0.0

        # Consolida a Curva Horaria Dinamica de Perdas e Tempo
        hourly_curve_list = []
        max_loss_val = -1.0
        peak_hour_loss = {"hour": "--:--", "loss": 0.0, "loss_str": "R$ 0,00"}
        max_delay_val = -1
        peak_hour_delay = {"hour": "--:--", "delay_min": 0, "delay_str": "00h 00m"}

        for h_k in sorted(hourly_accum.keys(), key=lambda x: hourly_accum[x]["hour_num"]):
            b = hourly_accum[h_k]
            tot_l = round(b["total_loss"], 2)
            tot_d = b["total_delay_min"]

            # Top base daquela hora
            if b["_bases"]:
                top_b_item = sorted(b["_bases"].values(), key=lambda x: (x["loss"], x["delay_min"]), reverse=True)[0]
                top_base_dict = {
                    "name": top_b_item["name"],
                    "region": top_b_item["region"],
                    "loss": round(top_b_item["loss"], 2),
                    "loss_str": _fmt_brl(top_b_item["loss"]),
                    "delay_min": top_b_item["delay_min"],
                    "delay_str": _fmt_hm(top_b_item["delay_min"]),
                    "count": top_b_item["count"]
                }
            else:
                top_base_dict = None

            # TOP 3 Equipes daquela hora
            top_3_teams_hour = sorted(b["_teams"], key=lambda x: (x["financial_loss"], x["delay_minutes"]), reverse=True)[:3]

            n_loss = round(b["norte"]["loss"], 2)
            l_loss = round(b["leste"]["loss"], 2)

            h_entry = {
                "hour_str": b["hour_str"],
                "hour_num": b["hour_num"],
                "total_loss": tot_l,
                "total_loss_str": _fmt_brl(tot_l),
                "total_delay_min": tot_d,
                "total_delay_str": _fmt_hm(tot_d),
                "count_teams": b["count_teams"],
                "norte": {
                    "loss": n_loss,
                    "loss_str": _fmt_brl(n_loss),
                    "delay_min": b["norte"]["delay_min"],
                    "delay_str": _fmt_hm(b["norte"]["delay_min"]),
                    "count": b["norte"]["count"]
                },
                "leste": {
                    "loss": l_loss,
                    "loss_str": _fmt_brl(l_loss),
                    "delay_min": b["leste"]["delay_min"],
                    "delay_str": _fmt_hm(b["leste"]["delay_min"]),
                    "count": b["leste"]["count"]
                },
                "top_base": top_base_dict,
                "top_teams": top_3_teams_hour
            }
            hourly_curve_list.append(h_entry)

            if tot_l > max_loss_val and tot_l > 0:
                max_loss_val = tot_l
                peak_hour_loss = {"hour": b["hour_str"], "loss": tot_l, "loss_str": _fmt_brl(tot_l)}

            if tot_d > max_delay_val and tot_d > 0:
                max_delay_val = tot_d
                peak_hour_delay = {"hour": b["hour_str"], "delay_min": tot_d, "delay_str": _fmt_hm(tot_d)}

        # Modelo Matematico de Linha de Tendencia e Projecao (Ultimos 3 Dias + Ritmo Intraday)
        trend_projection = self._compute_hourly_trend_projection(
            date_ref=date_ref,
            clean_scope=clean_scope,
            base_filter=base_filter,
            vehicle_filter=vehicle_filter,
            shift_filter=shift_filter,
            shift_code_filter=shift_code_filter,
            status_login_filter=status_login_filter,
            include_stc_leste=include_stc_leste,
            hourly_curve_list=hourly_curve_list
        )

        media_tempo_atrasada_min = (total_tempo_atraso_min / total_atrasadas) if total_atrasadas > 0 else 0
        media_tempo_no_prazo_min = (total_tempo_no_prazo_min / total_no_prazo) if total_no_prazo > 0 else 0

        taxa_pont_diaria_norte = round((total_no_prazo_norte / total_filtradas_norte * 100), 1) if total_filtradas_norte > 0 else 100.0
        taxa_pont_diaria_leste = round((total_no_prazo_leste / total_filtradas_leste * 100), 1) if total_filtradas_leste > 0 else 100.0
        taxa_pont_diaria_geral = round((total_no_prazo / total_filtradas * 100), 1) if total_filtradas > 0 else 100.0

        res_daily = {
            "status": "success",
            "mode": mode,
            "date_ref": date_ref,
            "geo_scope": clean_scope,
            "include_stc_leste": include_stc_leste,
            "total_equipes": total_filtradas,
            "total_atrasadas": total_atrasadas,
            "total_no_prazo": total_no_prazo,

            "total_perda_financeira": round(total_perda_financeira, 2),
            "total_perda_financeira_str": _fmt_brl(total_perda_financeira),
            "perda_financeira_norte": round(perda_financeira_norte, 2),
            "perda_financeira_norte_str": _fmt_brl(perda_financeira_norte),
            "perda_financeira_leste": round(perda_financeira_leste, 2),
            "perda_financeira_leste_str": _fmt_brl(perda_financeira_leste),
            "custo_medio_atrasada": custo_medio_atrasada,
            "custo_medio_atrasada_str": _fmt_brl(custo_medio_atrasada),

            "total_tempo_atraso_min": total_tempo_atraso_min,
            "total_tempo_atraso_str": _fmt_hm(total_tempo_atraso_min),
            "tempo_atraso_norte_min": tempo_atraso_norte_min,
            "tempo_atraso_norte_str": _fmt_hm(tempo_atraso_norte_min),
            "tempo_atraso_leste_min": tempo_atraso_leste_min,
            "tempo_atraso_leste_str": _fmt_hm(tempo_atraso_leste_min),
            "media_tempo_atrasada_str": _fmt_min_or_hm(media_tempo_atrasada_min),

            "total_tempo_no_prazo_min": total_tempo_no_prazo_min,
            "total_tempo_no_prazo_str": _fmt_hm(total_tempo_no_prazo_min),
            "tempo_no_prazo_norte_min": tempo_no_prazo_norte_min,
            "tempo_no_prazo_norte_str": _fmt_hm(tempo_no_prazo_norte_min),
            "tempo_no_prazo_leste_min": tempo_no_prazo_leste_min,
            "tempo_no_prazo_leste_str": _fmt_hm(tempo_no_prazo_leste_min),
            "media_tempo_no_prazo_str": _fmt_min_or_hm(media_tempo_no_prazo_min),

            "taxa_pontualidade_geral": taxa_pont_diaria_geral,
            "taxa_pontualidade_geral_str": f"{taxa_pont_diaria_geral}%",
            "taxa_pontualidade_norte": taxa_pont_diaria_norte,
            "taxa_pontualidade_norte_str": f"{taxa_pont_diaria_norte}%",
            "taxa_pontualidade_leste": taxa_pont_diaria_leste,
            "taxa_pontualidade_leste_str": f"{taxa_pont_diaria_leste}%",

            "shifts": shifts_structure,
            "top_teams": top_delayed,
            "justifications_summary": just_daily_list,
            "teams": enriched_teams,
            "hourly_loss_curve": hourly_curve_list,
            "peak_hour_loss": peak_hour_loss,
            "peak_hour_delay": peak_hour_delay,
            "trend_projection": trend_projection
        }
        self._delays_analytics_cache[cache_key] = (now_ts, res_daily)
        return res_daily

    def _compute_hourly_trend_projection(
        self,
        date_ref: str,
        clean_scope: str,
        base_filter,
        vehicle_filter,
        shift_filter,
        shift_code_filter,
        status_login_filter,
        include_stc_leste: bool,
        hourly_curve_list: list
    ) -> dict:
        """
        Modelo Matematico Preditivo para Projecao da Perda e Atraso Hora a Hora.
        Combina o perfil historico dos ultimos 3 dias operacionais com o ritmo do dia corrente (Pace Factor).
        Atualiza dinamicamente conforme novos dias avancam.
        """
        def _fmt_hm(mins):
            if not mins or mins <= 0: return "00h 00m"
            return f"{mins // 60:02d}h {mins % 60:02d}m"

        def _fmt_brl(val):
            if not val or val <= 0: return "R$ 0,00"
            return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        def _extract_hour(marc_val):
            if not marc_val: return "08:00", 8
            m_str = str(marc_val).strip()
            if " " in m_str: m_str = m_str.split(" ")[-1]
            elif "T" in m_str: m_str = m_str.split("T")[-1]
            if ":" in m_str:
                try:
                    h = int(m_str.split(":")[0])
                    if 0 <= h <= 23: return f"{h:02d}:00", h
                except Exception: pass
            return "08:00", 8

        avail = self.get_available_audit_dates()
        all_dates = sorted([str(d) for d in avail.get("dates", []) if str(d) < str(date_ref)])
        prev_3_dates = all_dates[-3:]

        if not prev_3_dates:
            return {
                "status": "SEM_HISTORICO",
                "pace_factor": 1.0,
                "diff_pct": 0.0,
                "diff_str": "0%",
                "comparison_label": "Sem base historica previa",
                "reference_days": [],
                "curve": [{"hour_str": h["hour_str"], "hour_num": h["hour_num"], "projected_loss": 0.0, "projected_loss_str": "R$ 0,00", "projected_delay_min": 0, "projected_delay_str": "00h 00m"} for h in hourly_curve_list]
            }

        # Pesos exponenciais do mais antigo para o mais recente (ex: 3 dias -> 0.20, 0.30, 0.50)
        n_days = len(prev_3_dates)
        if n_days == 3:
            weights = [0.20, 0.30, 0.50]
        elif n_days == 2:
            weights = [0.40, 0.60]
        else:
            weights = [1.0]

        hourly_baseline = {f"{h:02d}:00": {"loss": 0.0, "delay_min": 0.0} for h in range(5, 24)}

        # Carrega e agrega cada dia historico
        for dt, w in zip(prev_3_dates, weights):
            if dt in self._delays_history_records_cache:
                recs = self._delays_history_records_cache[dt]
            else:
                from supabase_client import fetch_delivery_records_by_date
                recs = fetch_delivery_records_by_date(dt) or []
                self._delays_history_records_cache[dt] = recs

            day_h = {f"{h:02d}:00": {"loss": 0.0, "delay_min": 0} for h in range(5, 24)}
            for t in recs:
                # Aplica filtros de escopo e inclusao de STC Leste
                t_code = str(t.get("team_code") or "").strip().upper()
                if not t_code:
                    continue

                pricing = classify_and_price_team(t, date_ref=dt)
                if not include_stc_leste and pricing["is_stc_leste"]:
                    continue

                if clean_scope != "ALL" and pricing["contract_regiao"] != clean_scope:
                    continue

                d_min = pricing["delay_minutes"]
                loss = pricing["financial_loss"]
                has_m = bool(t.get("marcacao") and str(t.get("marcacao")).strip() not in ["--", "-", "None", "nan", "", "--:--"])
                if d_min > 0 and has_m:
                    h_str, _ = _extract_hour(t.get("marcacao") or t.get("login_time"))
                    if h_str in day_h:
                        day_h[h_str]["loss"] += loss
                        day_h[h_str]["delay_min"] += d_min

            for h_str in hourly_baseline:
                hourly_baseline[h_str]["loss"] += day_h[h_str]["loss"] * w
                hourly_baseline[h_str]["delay_min"] += day_h[h_str]["delay_min"] * w

        # Determina o ritmo do dia corrente (Pace Factor)
        active_hours_today = [h for h in hourly_curve_list if h.get("count_teams", 0) > 0 or h.get("total_loss", 0) > 0]
        max_h_observed = max([h["hour_num"] for h in active_hours_today]) if active_hours_today else 8

        cum_today_loss = sum(h["total_loss"] for h in hourly_curve_list if h["hour_num"] <= max_h_observed)
        cum_base_loss = sum(hourly_baseline[f"{h:02d}:00"]["loss"] for h in range(5, max_h_observed + 1))

        if cum_base_loss > 50.0:
            raw_pace = cum_today_loss / cum_base_loss
            # Amortecimento: 70% ritmo de hoje + 30% baseline neutro (1.0), com teto seguro [0.40, 2.50]
            pace = max(0.40, min(2.50, 0.70 * raw_pace + 0.30 * 1.0))
            diff_pct = ((cum_today_loss - cum_base_loss) / cum_base_loss) * 100.0
        else:
            pace = 1.0
            diff_pct = 0.0

        if diff_pct <= -5.0:
            status = "MELHOR"
            comparison_label = f"Ritmo do dia {abs(diff_pct):.1f}% MELHOR que a projeção média"
        elif diff_pct >= 5.0:
            status = "PIOR"
            comparison_label = f"Ritmo do dia {abs(diff_pct):.1f}% PIOR que a projeção média"
        else:
            status = "EM_LINHA"
            comparison_label = "Ritmo do dia EM LINHA com a projeção esperada"

        projected_curve = []
        for h_item in hourly_curve_list:
            h_str = h_item["hour_str"]
            base_loss = hourly_baseline.get(h_str, {}).get("loss", 0.0)
            base_delay = hourly_baseline.get(h_str, {}).get("delay_min", 0.0)

            proj_loss = round(base_loss * pace, 2)
            proj_delay = int(round(base_delay * pace))

            projected_curve.append({
                "hour_str": h_str,
                "hour_num": h_item["hour_num"],
                "projected_loss": proj_loss,
                "projected_loss_str": _fmt_brl(proj_loss),
                "projected_delay_min": proj_delay,
                "projected_delay_str": _fmt_hm(proj_delay)
            })

        return {
            "status": status,
            "pace_factor": round(pace, 2),
            "diff_pct": round(diff_pct, 1),
            "diff_str": f"{abs(diff_pct):.1f}%",
            "comparison_label": comparison_label,
            "reference_days": prev_3_dates,
            "curve": projected_curve
        }


delivery_manager = DeliveryManager()

