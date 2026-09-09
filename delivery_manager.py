"""
Delivery Manager - Módulo Entrega de Equipes (Enel SP)
Gerencia a consolidação, regras de tipologia veicular, enquadramento de turnos operacionais,
diferenciação entre Equipes ATIVAS (ao vivo) e Equipes TOTAL (acumulado do dia),
agrupamento hierárquico das 14 bases por região (Norte e Leste) e auditoria histórica.
"""

from datetime import datetime, date, timedelta, timezone
import json
import os
import re

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
    return val_str

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

def classify_spotfire_shift_and_turno(sp_record: dict) -> dict:
    """
    Extrai e classifica com precisão o Turno (Manhã, Tarde, Noite) e o Agrupamento de Horário
    (Turno 06:00, 08:00, 12:00, 14:00, 20:00, 22:00) a partir dos dados do Spotfire:
    - Coluna Período (1 - Manhã, 2 - Tarde, 3 - Noite)
    - login_desc (Início às XX Hrs)
    - inicio_calibrado
    """
    raw_data = sp_record.get("raw_data") if isinstance(sp_record.get("raw_data"), dict) else {}
    raw_periodo = str(raw_data.get("periodo", "") or sp_record.get("periodo", "")).lower()
    login_desc = str(raw_data.get("login_desc", "") or sp_record.get("login_desc", ""))
    inicio_cal = str(sp_record.get("inicio_calendario") or sp_record.get("inicio_calibrado", "") or sp_record.get("login_corrigido") or sp_record.get("login") or "").strip()

    # 1. Determina Turno Macrocategoria: Manhã, Tarde, Noite
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


class DeliveryManager:
    @staticmethod
    def get_operational_date(dt=None) -> str:
        """
        Retorna a data do dia operacional da Enel/Alpitel.
        O dia operacional vira pontualmente às 05:00 da manhã.
        - Das 00:00 às 04:59: pertence ao dia operacional anterior.
        - Das 05:00 às 23:59: pertence ao dia operacional atual.
        """
        if dt is None:
            dt = datetime.now(BR_TZ)
        if dt.hour < 5:
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
        self.munck_codes = {
            "ENL210", "ENL211", "ECL210", "ECL211", "EEL210", "EEL211",
            "EML200", "EQL200", "EQL210", "ESL200", "EVL200", "EVL210"
        }

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

        # Caches de auditoria em memória de alta performance (<1ms)
        self._daily_audit_cache = {}          # date_str -> dict
        self._daily_audit_cache_ts = {}       # date_str -> timestamp
        self._monthly_audit_cache = {}        # month_str -> dict
        self._monthly_audit_cache_ts = {}     # month_str -> timestamp
        self._audit_dates_cache = None
        self._audit_dates_cache_ts = 0

        self.load_local_cache()

    def clear_audit_cache(self, date_str=None):
        """Invalida caches de auditoria quando novos dados são consolidados."""
        if date_str:
            self._daily_audit_cache.pop(date_str, None)
            m = date_str[:7]
            self._monthly_audit_cache.pop(m, None)
        else:
            self._daily_audit_cache.clear()
            self._monthly_audit_cache.clear()
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
                            s_info = self.parse_shift_window(raw_shift)
                            t.update(s_info)
                            # Se for após as 05:00 da manhã e o turno for da noite anterior (20h/22h) já inativo, descarta
                            if now.hour >= 5 and not t.get("is_active", True) and t.get("shift_code") in ["20:00", "22:00"]:
                                continue
                            self.daily_accumulated_teams[code] = t

                        self.intraday_curve = data.get("intraday_curve", {})
                        self.daily_team_order_history = data.get("team_order_history", {})
                        self.bid_cache = data.get("bid_cache", {})
                        self.last_bid_sync = data.get("last_bid_sync", "--")
                        self.active_teams = [t for t in self.daily_accumulated_teams.values() if t.get("is_active", True)]

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
                        self.intraday_curve = {}
                        self.bid_cache = {}
                        self.last_bid_sync = "--"
        except Exception as e:
            print(f"[WARN] Não foi possível ler cache diário de entrega: {e}")

    def save_local_cache(self):
        """Grava em disco o acumulado do dia para resiliência a reinicializações."""
        try:
            payload = {
                "date": self.current_date_str,
                "last_sync_time": self.last_sync_time,
                "accumulated_teams": self.daily_accumulated_teams,
                "team_order_history": self.daily_team_order_history,
                "intraday_curve": self.intraday_curve,
                "bid_cache": self.bid_cache,
                "last_bid_sync": self.last_bid_sync
            }
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[WARN] Falha ao salvar cache diário de entrega: {e}")

    def classify_vehicle(self, team_code: str) -> dict:
        """
        Classifica o tipo de veículo com base no código da equipe:
        - Munck: Códigos específicos da lista MUNCK_CODES
        - Cesto Aéreo: Dígito 1 após a base
        - Veículo Leve: Dígito 3 após a base
        - Moto: Dígito 7 após a base
        - Linha Viva: Demais códigos começando com dígito 2
        """
        code = str(team_code).strip().upper()
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

    def parse_shift_window(self, shift_str: str) -> dict:
        """
        Interpreta a coluna TURNO (ex: '07:52–16:00') e enquadra no turno oficial:
        - Turno 06:00: 04:00 às 07:30
        - Turno 08:00: 07:31 às 10:30
        - Turno 12:00: 10:31 às 13:30
        - Turno 14:00: 13:31 às 17:00
        - Turno 20:00: 17:01 às 21:00
        - Turno 22:00: 21:01 às 03:59
        """
        clean = str(shift_str or '').replace('–', '-').replace('—', '-').strip()
        parts = [p.strip() for p in clean.split('-') if p.strip()]
        login_time = parts[0] if len(parts) > 0 else "--:--"
        logoff_time = parts[1] if len(parts) > 1 else "--:--"

        shift_slot = "Turno 08:00"
        shift_code = "08:00"
        shift_pill_class = "shift-08h"

        try:
            t_parts = login_time.split(':')
            if len(t_parts) >= 2:
                h = int(t_parts[0])
                m = int(t_parts[1])
                total_min = h * 60 + m

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
                elif 1051 <= total_min <= 1310:  # 19:00 às 21:50 (cobre a partir de 17:36)
                    shift_slot = "Turno 20:00"
                    shift_code = "20:00"
                    shift_pill_class = "shift-20h"
                else:                            # 21:51 às 03:59
                    shift_slot = "Turno 22:00"
                    shift_code = "22:00"
                    shift_pill_class = "shift-22h"
        except Exception:
            pass

        return {
            "login_time": login_time,
            "logoff_time": logoff_time,
            "shift_slot": shift_slot,
            "shift_code": shift_code,
            "shift_pill_class": shift_pill_class
        }

    def _build_metrics_breakdown(self, team_list: list) -> dict:
        """Gera contadores detalhados para uma lista arbitrária de equipes."""
        total = len(team_list)
        cesto = sum(1 for t in team_list if t["vehicle_type"] == "Cesto Aéreo")
        leve = sum(1 for t in team_list if t["vehicle_type"] == "Veículo Leve")
        moto = sum(1 for t in team_list if t["vehicle_type"] == "Moto")
        munck = sum(1 for t in team_list if t["vehicle_type"] == "Munck")
        linhaviva = sum(1 for t in team_list if t["vehicle_type"] == "Linha Viva")
        linhaviva_munck = linhaviva + munck

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
            return {
                "total": len(sub_teams),
                "cesto": sum(1 for t in sub_teams if t["vehicle_type"] == "Cesto Aéreo"),
                "leve": sum(1 for t in sub_teams if t["vehicle_type"] == "Veículo Leve"),
                "moto": sum(1 for t in sub_teams if t["vehicle_type"] == "Moto"),
                "linhaviva_munck": sum(1 for t in sub_teams if t["vehicle_type"] in ["Linha Viva", "Munck"]),
                "munck": sum(1 for t in sub_teams if t["vehicle_type"] == "Munck"),
                "linhaviva": sum(1 for t in sub_teams if t["vehicle_type"] == "Linha Viva")
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
            print(f"[DELIVERY] Virada de dia operacional detectada ({self.current_date_str} -> {op_date}). Reiniciando acumulador diário das 05:00...")
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
                gps_raw = rec.get("GPS") or rec.get("gps") or "--"
                descanso_raw = rec.get("INICIO_DESCANSO") or rec.get("INÍCIO DESCANSO") or rec.get("inicio_descanso") or rec.get("data_inicio_descanso") or "--"
                ordem_raw = rec.get("ORDEM") or rec.get("ordem") or rec.get("ordem_servico") or "--"
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
            gps_update_str = gps_str if gps_str and gps_str not in ['-', '--'] else "--"
            gps_update_minutes = None
            if gps_update_str != "--":
                try:
                    total_m = 0
                    h_match = re.search(r'(\d+)\s*h', gps_update_str, re.IGNORECASE)
                    m_match = re.search(r'(\d+)\s*min', gps_update_str, re.IGNORECASE)
                    if h_match:
                        total_m += int(h_match.group(1)) * 60
                    if m_match:
                        total_m += int(m_match.group(1))
                    elif not h_match and re.search(r'^\d+$', gps_update_str):
                        total_m = int(gps_update_str)
                    gps_update_minutes = total_m
                except Exception:
                    gps_update_minutes = None

            # Tratamento de INÍCIO DESCANSO (Separar Data e Hora)
            descanso_str = str(descanso_raw or "").strip()
            data_inicio_descanso = None
            hora_inicio_descanso = None
            if descanso_str and descanso_str not in ['-', '--']:
                parts = [p.strip() for p in re.split(r'[, ]+', descanso_str) if p.strip()]
                if len(parts) >= 2:
                    data_inicio_descanso = parts[0]
                    hora_inicio_descanso = parts[1]
                elif len(parts) == 1:
                    if ":" in parts[0]:
                        hora_inicio_descanso = parts[0]
                    elif "/" in parts[0]:
                        data_inicio_descanso = parts[0]

            # Tratamento de ORDEM
            ordem_str = str(ordem_raw or "").strip()
            ordem_servico = ordem_str if ordem_str and ordem_str not in ['-', '--', 'NAN', 'nan'] else None

            # Rastreamento do Histórico de Ordens de Serviço (Deduplicação Inteligente a cada 120s)
            # Regra: Se a mesma ordem se repetir em várias atualizações, permanece registrada uma única vez!
            order_history_list = self.daily_team_order_history.setdefault(team_code, [])
            now_time_str = now.strftime("%H:%M:%S")
            if ordem_servico:
                existing_order = next((o for o in order_history_list if o.get("ordem") == ordem_servico), None)
                if existing_order:
                    existing_order["last_seen"] = now_time_str
                    existing_order["status"] = status_oper
                    existing_order["cycles_count"] = existing_order.get("cycles_count", 1) + 1
                else:
                    order_history_list.append({
                        "ordem": ordem_servico,
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

            veh_info = self.classify_vehicle(team_code)
            shift_info = self.parse_shift_window(shift_raw)

            # Enriquecimento com dados da Visão Operacional BidTech (Checklists)
            bid_entry = self.bid_cache.get(team_code)
            status_bid = bid_entry.get("status_bid") if bid_entry else ("Não Encontrada" if self.last_bid_sync != "--" else "--")

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
                "order_history": [dict(o) for o in order_history_list],
                "is_active": is_active_val,
                "vehicle_type": veh_info["type"],
                "unified_group": veh_info["unified_group"],
                "vehicle_category": veh_info["category"],
                "vehicle_badge_class": veh_info["badge_class"],
                "vehicle_pill_class": veh_info["pill_class"],
                "login_time": shift_info["login_time"],
                "logoff_time": shift_info["logoff_time"],
                "shift_slot": shift_info["shift_slot"],
                "shift_code": shift_info["shift_code"],
                "shift_pill_class": shift_info["shift_pill_class"],
                "raw_shift": str(shift_raw),
                "last_seen_time": now.strftime("%H:%M:%S")
            }
            if is_active_val:
                active_dict[team_code] = team_obj

            # Acumula no histórico do dia
            if team_code not in self.daily_accumulated_teams:
                team_copy = dict(team_obj)
                team_copy["first_seen_time"] = now.strftime("%H:%M:%S")
                self.daily_accumulated_teams[team_code] = team_copy
            else:
                # Atualiza com as informações mais recentes mantendo first_seen_time
                existing = self.daily_accumulated_teams[team_code]
                f_seen = existing.get("first_seen_time", now.strftime("%H:%M:%S"))
                self.daily_accumulated_teams[team_code].update(team_obj)
                self.daily_accumulated_teams[team_code]["first_seen_time"] = f_seen
                self.daily_accumulated_teams[team_code]["is_active"] = is_active_val

        active_processed = sorted(list(active_dict.values()), key=lambda x: x["team_code"])

        # Marca equipes acumuladas que saíram da lista ativa nesta coleta
        active_codes = set(active_dict.keys())
        for code, t in list(self.daily_accumulated_teams.items()):
            if code not in active_codes:
                t["is_active"] = False
                t["status"] = "Deslogada / Turno Concluído"
                # Se for após as 05:00 e for turno da noite anterior (20h/22h), descarta do acumulado do dia atual
                if now.hour >= 5 and t.get("shift_code") in ["20:00", "22:00"]:
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

    def get_consolidated_state(self) -> dict:
        """Retorna o estado operacional completo com Ativas vs Total e agrupamento de bases."""
        active_list = self.active_teams
        total_list = sorted(list(self.daily_accumulated_teams.values()), key=lambda x: x["team_code"])

        metrics_active = self._build_metrics_breakdown(active_list)
        metrics_total = self._build_metrics_breakdown(total_list)

        return {
            "status": "success",
            "date": self.current_date_str,
            "timestamp": self.last_sync_time,
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
            "geo_groups": self.geo_groups
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
        bid_info = self.bid_cache.get(code)
        return {
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

        for r in raw_records:
            code = str(r.get("team_code", "")).strip().upper()
            if code:
                self.bid_cache[code] = dict(r)

        now = datetime.now(BR_TZ)
        self.last_bid_sync = now.strftime("%d/%m/%Y %H:%M:%S")

        # Atualiza o status_bid nas equipes acumuladas e ativas
        for code, t in self.daily_accumulated_teams.items():
            b_info = self.bid_cache.get(code)
            t["status_bid"] = b_info.get("status_bid") if b_info else "Não Encontrada"
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
        if not date_str:
            date_str = self.current_date_str

        is_today = (date_str == self.current_date_str)
        is_cloud = os.environ.get("VERCEL") is not None or os.name != 'nt'

        # 1. Obtém universo do EquipesBrasil
        eb_teams = {}
        if is_today and self.daily_accumulated_teams and not is_cloud:
            eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values()}
        else:
            try:
                from supabase_client import fetch_delivery_records_by_date, fetch_latest_delivery_snapshot_from_supabase
                if is_today and not self.daily_accumulated_teams:
                    cloud_snap = fetch_latest_delivery_snapshot_from_supabase()
                    if cloud_snap.get("status") == "success" and cloud_snap.get("data"):
                        self.process_raw_enel_records(cloud_snap["data"], source_label="Nuvem Supabase", captured_at=cloud_snap.get("captured_at"))

                deliv_records = fetch_delivery_records_by_date(date_str)
                if deliv_records:
                    eb_teams = {r["team_code"]: r for r in deliv_records if r.get("team_code")}
                    if is_today:
                        for r in deliv_records:
                            t_code = r.get("team_code")
                            if t_code and t_code not in self.daily_accumulated_teams:
                                self.daily_accumulated_teams[t_code] = r
                elif self.daily_accumulated_teams:
                    eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values()}
            except Exception as err:
                print(f"[ONLINE x BID ERROR] Falha ao consultar Supabase para EB {date_str}: {err}")
                eb_teams = {t["team_code"]: dict(t) for t in self.daily_accumulated_teams.values()}

        # 2. Obtém universo da Visão Operacional BID
        bid_records_map = {}
        bid_last_sync_time = self.last_bid_sync
        if is_today and self.bid_cache and not is_cloud:
            bid_records_map = dict(self.bid_cache)
        else:
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
                    bid_records_map = dict(self.bid_cache)
            except Exception as err:
                print(f"[ONLINE x BID ERROR] Falha ao consultar Supabase para BID {date_str}: {err}")
                if self.bid_cache:
                    bid_records_map = dict(self.bid_cache)

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

            is_eb_active = eb.get("is_active", True) if eb else False
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
                "ordem_servico": eb.get("ordem_servico") if eb else "--"
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
                        v_info = self.classify_vehicle(t_code)
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
                v_info = self.classify_vehicle(norm)
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
        para a data e região especificadas, estruturado exatamente nas 3 visões executivas:
        1. BASES
        2. TURNO
        3. TIPO VEÍCULO
        
        Utiliza 100% dos registros tratados do TIBCO Spotfire como verdade oficial de fechamento.
        """
        reg_key = "Norte" if region.lower() in ["norte", "região norte"] else "Leste"
        
        # 1. Carrega Metas de Planejamento (Supabase / JSON)
        from supabase_client import fetch_delivery_planning_targets
        p_targets = fetch_delivery_planning_targets(date_str[:7])
        reg_targets = p_targets.get(reg_key, {})
        plan_bases = reg_targets.get("bases", {})
        plan_turno = reg_targets.get("turno", {})
        plan_veiculo = reg_targets.get("veiculo", {})

        # 2. Carrega equipes reais tratadas diretamente do Spotfire (verdade oficial fechada)
        from supabase_client import fetch_spotfire_records_by_date
        sp_recs = fetch_spotfire_records_by_date(date_str)

        # Filtra equipes da região selecionada estritamente pelos prefixos oficiais
        if reg_key == "Norte":
            target_prefixes = {"ENL", "ECL", "EEL"}
        else:
            target_prefixes = {"EML", "EQL", "EVL", "ESL"}

        reg_teams = []
        for r in sp_recs:
            code = normalize_team_code(r.get("equipe_normalizada") or r.get("equipe", ""))
            pfx = code[:3]
            if pfx not in target_prefixes:
                continue

            # Validação mandatória: presença de login efetivo registrado
            login_val = r.get("login_corrigido") or r.get("login") or ""
            if not str(login_val).strip() or str(login_val).strip().lower() in ["none", "nan", "-", "0", "0.0"]:
                continue

            v_info = self.classify_vehicle(code)
            shift_info = classify_spotfire_shift_and_turno(r)
            reg_teams.append({
                "team_code": code,
                "base_code": pfx,
                "vehicle_type": v_info["type"],
                "turno": shift_info["turno"],
                "shift_slot": shift_info["shift_slot"],
                "shift_code": shift_info["shift_code"],
                "raw_record": r
            })

        # 3. Contabilização Real por Categoria
        # 3.1 BASES
        base_real_counts = {}
        for b_name in plan_bases.keys():
            base_real_counts[b_name] = 0

        # Mapeamento oficial de prefixo para nome da base
        prefix_to_base = {
            "ENL": "Fagundes Filho",
            "ECL": "Cajati",
            "EEL": "Vila Medeiros",
            "EML": "Monte Santo",
            "EVL": "Catumbi",
            "EQL": "Aricanduva",
            "ESL": "Santo André"
        }

        for t in reg_teams:
            code = t.get("team_code", "").upper()
            v_type = t.get("vehicle_type", "")
            pfx = code[:3]
            
            # Identifica se é Linha Viva ou Munck
            if v_type == "Munck" or code in self.munck_codes:
                if "Munk" in base_real_counts:
                    base_real_counts["Munk"] += 1
                elif "Munck" in base_real_counts:
                    base_real_counts["Munck"] += 1
            elif v_type == "Linha Viva":
                if "LV" in base_real_counts:
                    base_real_counts["LV"] += 1
            else:
                # Pertence à base TMA
                b_name = prefix_to_base.get(pfx)
                if b_name and b_name in base_real_counts:
                    base_real_counts[b_name] += 1

        # Constrói tabela 1: BASES
        table_bases = []
        sum_plan_tma = 0
        sum_real_tma = 0
        for b_name, p_val in plan_bases.items():
            r_val = base_real_counts.get(b_name, 0)
            gap_val = r_val - p_val
            table_bases.append({
                "categoria": b_name,
                "plan": p_val,
                "real": r_val,
                "gap": gap_val,
                "is_special": b_name in ["LV", "Munk", "Munck"]
            })
            if b_name not in ["LV", "Munk", "Munck"]:
                sum_plan_tma += p_val
                sum_real_tma += r_val

        lv_plan = plan_bases.get("LV", 0)
        lv_real = base_real_counts.get("LV", 0)
        munk_plan = plan_bases.get("Munk", plan_bases.get("Munck", 0))
        munk_real = base_real_counts.get("Munk", base_real_counts.get("Munck", 0))

        if reg_key == "Norte":
            table_bases.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": sum_real_tma - sum_plan_tma,
                "is_total": True
            })
            tot_lv_tma_plan = sum_plan_tma + lv_plan + munk_plan
            tot_lv_tma_real = sum_real_tma + lv_real + munk_real
            table_bases.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": tot_lv_tma_real - tot_lv_tma_plan,
                "is_grand_total": True
            })
        else:
            table_bases.append({
                "categoria": "Total",
                "plan": sum(plan_bases.values()),
                "real": sum(base_real_counts.values()),
                "gap": sum(base_real_counts.values()) - sum(plan_bases.values()),
                "is_grand_total": True
            })

        # 3.2 TURNO (Auditoria precisa por Período: Manhã, Tarde, Noite)
        turno_real_counts = {"Manhã": 0, "Tarde": 0, "Noite": 0}
        for t in reg_teams:
            t_name = t.get("turno", "Manhã")
            if t_name in turno_real_counts:
                turno_real_counts[t_name] += 1
            else:
                turno_real_counts["Manhã"] += 1

        table_turno = []
        for t_name in ["Manhã", "Tarde", "Noite"]:
            p_val = plan_turno.get(t_name, 0)
            r_val = turno_real_counts.get(t_name, 0)
            table_turno.append({
                "categoria": t_name,
                "plan": p_val,
                "real": r_val,
                "gap": r_val - p_val
            })

        if reg_key == "Norte":
            table_turno.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": sum_real_tma - sum_plan_tma,
                "is_total": True
            })
            table_turno.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": tot_lv_tma_real - tot_lv_tma_plan,
                "is_grand_total": True
            })
        else:
            tot_p_turno = sum(plan_turno.values())
            tot_r_turno = sum(turno_real_counts.values())
            table_turno.append({
                "categoria": "Total",
                "plan": tot_p_turno,
                "real": tot_r_turno,
                "gap": tot_r_turno - tot_p_turno,
                "is_grand_total": True
            })

        # 3.3 TIPO VEÍCULO
        veh_real_counts = {"Cesto Aéreo": 0, "Veículo Leve": 0, "Moto": 0, "LV": 0, "Munk": 0}
        for t in reg_teams:
            vt = t.get("vehicle_type", "Outros")
            code = t.get("team_code", "").upper()
            if vt == "Munck" or code in self.munck_codes:
                veh_real_counts["Munk"] += 1
            elif vt == "Linha Viva":
                veh_real_counts["LV"] += 1
            elif vt == "Cesto Aéreo":
                veh_real_counts["Cesto Aéreo"] += 1
            elif vt == "Veículo Leve":
                veh_real_counts["Veículo Leve"] += 1
            elif vt == "Moto":
                veh_real_counts["Moto"] += 1

        table_veiculo = []
        for v_name in ["Cesto Aéreo", "Veículo Leve", "Moto", "LV", "Munk"]:
            p_val = plan_veiculo.get(v_name, 0)
            r_val = veh_real_counts.get(v_name, 0)
            table_veiculo.append({
                "categoria": v_name,
                "plan": p_val,
                "real": r_val,
                "gap": r_val - p_val,
                "is_special": v_name in ["LV", "Munk"]
            })

        if reg_key == "Norte":
            table_veiculo.append({
                "categoria": "Total TMA",
                "plan": sum_plan_tma,
                "real": sum_real_tma,
                "gap": sum_real_tma - sum_plan_tma,
                "is_total": True
            })
            table_veiculo.append({
                "categoria": "Total LV + TMA",
                "plan": tot_lv_tma_plan,
                "real": tot_lv_tma_real,
                "gap": tot_lv_tma_real - tot_lv_tma_plan,
                "is_grand_total": True
            })
        else:
            tot_p_veh = sum(plan_veiculo.values())
            tot_r_veh = sum(veh_real_counts.values())
            table_veiculo.append({
                "categoria": "Total",
                "plan": tot_p_veh,
                "real": tot_r_veh,
                "gap": tot_r_veh - tot_p_veh,
                "is_grand_total": True
            })

        # Cards rápidos de frota
        fleet_cards = {
            "cesto": veh_real_counts["Cesto Aéreo"],
            "leve": veh_real_counts["Veículo Leve"],
            "moto": veh_real_counts["Moto"],
            "linhaviva": veh_real_counts["LV"],
            "munck": veh_real_counts["Munk"],
            "total_regiao": len(reg_teams)
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
                
                v_info = self.classify_vehicle(team_code)
                v_type = v_info.get("type", "Outros")
                
                shift_info = classify_spotfire_shift_and_turno(row)
                turno = shift_info.get("turno") or "Manhã"
                shift_code = shift_info.get("shift_code") or "08:00"

                dt_ref = str(row.get("data_referencia") or "")

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

            res = {
                "status": "success",
                "month": month_str,
                "planning_targets": p_targets,
                "total_records": len(norm_records),
                "operating_days": op_days,
                "avg_total": round(avg_tot, 1),
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

        # 1. Verifica cache em memória
        if not force_refresh and hasattr(self, '_audit_dates_cache') and self._audit_dates_cache:
            if now - getattr(self, '_audit_dates_cache_ts', 0) < 600:
                return self._audit_dates_cache

        # 2. Verifica cache em disco (se recente ou meses históricos)
        cache_file = os.path.join("data", "delivery_available_dates.json")
        disk_data = None
        if not force_refresh and os.path.isfile(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as fp:
                    disk_data = json.load(fp)
                if disk_data and disk_data.get("dates"):
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

            # 1. Busca datas recentes nos cabeçalhos de sessões (limit 200)
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

delivery_manager = DeliveryManager()

