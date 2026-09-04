"""
Delivery Manager - Módulo Entrega de Equipes (Enel SP)
Gerencia a consolidação, regras de tipologia veicular, enquadramento de turnos operacionais,
diferenciação entre Equipes ATIVAS (ao vivo) e Equipes TOTAL (acumulado do dia),
agrupamento hierárquico das 14 bases por região (Norte e Leste) e auditoria histórica.
"""

from datetime import datetime, date, timedelta
import json
import os

import re

CACHE_FILE = "delivery_daily_cache.json"

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
        minutes, _ = divmod(remainder, 60)
        return f"{hours:02d}h {minutes:02d}m"
    except Exception:
        return "--"


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
            dt = datetime.now()
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
        self.intraday_curve = {}              # Histórico horário das equipes que entraram
        self.last_sync_time = "--"
        self.sync_source = "Aguardando sincronização"
        self.spotfire_cache = {}              # (date_ref, norm_code) -> dict
        
        self.load_local_cache()

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
                        self.intraday_curve = {}
        except Exception as e:
            print(f"[WARN] Não foi possível ler cache diário de entrega: {e}")

    def save_local_cache(self):
        """Grava em disco o acumulado do dia para resiliência a reinicializações."""
        try:
            payload = {
                "date": self.current_date_str,
                "last_sync_time": self.last_sync_time,
                "accumulated_teams": self.daily_accumulated_teams,
                "intraday_curve": self.intraday_curve
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

        if first_digit == "1":
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

    def process_raw_enel_records(self, raw_records: list, source_label="Portal Enel SP") -> dict:
        """
        Processa linhas brutas extraídas do portal Enel, atualiza a lista de Equipes ATIVAS
        e adiciona de forma cumulativa e deduplicada ao histórico diário (Equipes TOTAL).
        """
        now = datetime.now()
        op_date = self.get_operational_date(now)
        
        # Se virou o dia, reinicia o acumulado diário
        if op_date != self.current_date_str:
            print(f"[DELIVERY] Virada de dia operacional detectada ({self.current_date_str} -> {op_date}). Reiniciando acumulador diário das 05:00...")
            self.current_date_str = op_date
            self.daily_accumulated_teams = {}
            self.intraday_curve = {}

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
                status_oper = rec[9] if len(rec) > 9 else "Logada"
                plate = rec[11] if len(rec) > 11 else "--"
                is_active_val = True
            else:
                continue

            if not team_code or team_code == 'NAN':
                continue

            prefix = team_code[:3]
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
                "plate": plate,
                "ut": ut,
                "filial": filial,
                "tipo_operacional": tipo_oper,
                "status": status_oper,
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

    def reconcile_with_spotfire_records(self, spotfire_records: list, date_ref: str = None):
        """Atualiza o cache de registros do Spotfire e mescla com as equipes acumuladas do dia."""
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
                    if sp.get("inicio_calibrado"):
                        t["login_real"] = sp.get("inicio_calibrado")
                    if sp.get("fim_calibrado"):
                        t["logoff_real"] = sp.get("fim_calibrado")
                        t["logoff_time"] = sp.get("fim_calibrado")
                    t["qtd_os"] = sp.get("qtd_os", 0)
                    t["produtivas"] = sp.get("produtivas", 0)
                    t["improdutiva"] = sp.get("improdutiva", 0)
                    t["verificacoes"] = sp.get("verificacoes", 0)
                    t["no_local"] = sp.get("no_local", 0)
                    t["rejeita"] = sp.get("rejeita", "NÃO")
                    t["duracao_efetiva"] = calculate_time_duration(t.get("login_real") or t.get("login_time"), t.get("logoff_real"))
                    t["status_conciliacao"] = "CONCILIADO_TOTAL" if sp.get("fim_calibrado") and sp.get("fim_calibrado") not in ["--", "--:--"] else "TURNO_EM_ANDAMENTO"
                    t["spotfire_reconciled"] = True

    def get_daily_audit_data(self, date_str: str) -> dict:
        """
        Gera a auditoria consolidada para uma data específica (YYYY-MM-DD),
        confrontando os dados do EquipesBrasil com as informações do TIBCO Spotfire.
        """
        base_teams = []
        if date_str == self.current_date_str:
            state = self.get_consolidated_state()
            base_teams = [dict(t) for t in state["daily_total_teams"]]
        else:
            try:
                from supabase_client import fetch_delivery_records_by_date
                records = fetch_delivery_records_by_date(date_str)
                if records:
                    for r in records:
                        t_code = r.get("team_code", "")
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

        # Busca registros correspondentes no Spotfire
        sp_map = {}
        try:
            from supabase_client import fetch_spotfire_records_by_date
            spotfire_records = fetch_spotfire_records_by_date(date_str)
            for sp in spotfire_records:
                norm = sp.get("equipe_normalizada") or normalize_team_code(sp.get("equipe", ""))
                if norm:
                    sp_map[norm] = sp
        except Exception as e:
            print(f"[SPOTFIRE AUDIT FETCH ERROR] {e}")

        # Reconciliação dos registros de EquipesBrasil com Spotfire
        seen_teams = set()
        for t in base_teams:
            norm = normalize_team_code(t.get("team_code", ""))
            seen_teams.add(norm)
            sp = sp_map.get(norm)
            if sp:
                t["login_real"] = sp.get("inicio_calibrado") or t.get("login_time", "--:--")
                t["logoff_real"] = sp.get("fim_calibrado") or "--:--"
                if sp.get("fim_calibrado") and sp.get("fim_calibrado") not in ["--", "--:--"]:
                    t["logoff_time"] = sp.get("fim_calibrado")
                t["qtd_os"] = sp.get("qtd_os", 0)
                t["produtivas"] = sp.get("produtivas", 0)
                t["improdutiva"] = sp.get("improdutiva", 0)
                t["verificacoes"] = sp.get("verificacoes", 0)
                t["no_local"] = sp.get("no_local", 0)
                t["rejeita"] = sp.get("rejeita", "NÃO")
                t["duracao_efetiva"] = calculate_time_duration(t["login_real"], t["logoff_real"])
                t["status_conciliacao"] = "CONCILIADO_TOTAL" if t["logoff_real"] not in ["--", "--:--"] else "TURNO_EM_ANDAMENTO"
                t["spotfire_reconciled"] = True
            else:
                t["login_real"] = t.get("login_time", "--:--")
                t["logoff_real"] = "--:--"
                t["qtd_os"] = 0
                t["produtivas"] = 0
                t["improdutiva"] = 0
                t["verificacoes"] = 0
                t["no_local"] = 0
                t["rejeita"] = "NÃO"
                t["duracao_efetiva"] = "--"
                t["status_conciliacao"] = "AGUARDANDO_SPOTFIRE"
                t["spotfire_reconciled"] = False

        # Inclui equipes que constam exclusivamente no Spotfire (sem EquipesBrasil)
        for norm, sp in sp_map.items():
            if norm not in seen_teams:
                prefix = norm[:3]
                b_info = self.official_bases.get(prefix)
                v_info = self.classify_vehicle(norm)
                base_teams.append({
                    "team_code": sp.get("equipe") or norm,
                    "base_code": prefix,
                    "base_name": b_info["name"] if b_info else f"Base {prefix}",
                    "base_display": b_info["base_display"] if b_info else f"Base {prefix}",
                    "region": b_info["region"] if b_info else "Outras Bases",
                    "geo": b_info["geo"] if b_info else "Outras",
                    "company": b_info["company"] if b_info else "Outros",
                    "vehicle_type": v_info["type"],
                    "login_time": sp.get("inicio_calibrado") or "--:--",
                    "logoff_time": sp.get("fim_calibrado") or "--:--",
                    "login_real": sp.get("inicio_calibrado") or "--:--",
                    "logoff_real": sp.get("fim_calibrado") or "--:--",
                    "shift_slot": "Spotfire Extra",
                    "shift_code": "Extra",
                    "status": "Apenas Spotfire",
                    "driver": "--",
                    "plate": "--",
                    "qtd_os": sp.get("qtd_os", 0),
                    "produtivas": sp.get("produtivas", 0),
                    "improdutiva": sp.get("improdutiva", 0),
                    "verificacoes": sp.get("verificacoes", 0),
                    "no_local": sp.get("no_local", 0),
                    "rejeita": sp.get("rejeita", "NÃO"),
                    "duracao_efetiva": calculate_time_duration(sp.get("inicio_calibrado"), sp.get("fim_calibrado")),
                    "status_conciliacao": "APENAS_SPOTFIRE",
                    "spotfire_reconciled": True
                })

        metrics = self._build_metrics_breakdown(base_teams)

        # Totais de conciliação para os KPI Cards
        total_delivered = len(base_teams)
        total_eb = len([t for t in base_teams if t.get("status_conciliacao") != "APENAS_SPOTFIRE"])
        reconciled_count = len([t for t in base_teams if t.get("spotfire_reconciled")])
        total_with_logoff = len([t for t in base_teams if t.get("logoff_real") not in ["--", "--:--"]])
        total_os_produtivas = sum(t.get("produtivas", 0) for t in base_teams)
        total_os_geral = sum(t.get("qtd_os", 0) for t in base_teams)
        rate = round((reconciled_count / max(total_eb, 1)) * 100.0, 1) if total_eb > 0 else 0.0

        return {
            "status": "success" if total_delivered > 0 else "empty",
            "date": date_str,
            "total_delivered": total_delivered,
            "summary": metrics,
            "reconciliation": {
                "total_delivered": total_delivered,
                "total_equipes_brasil": total_eb,
                "total_spotfire": len(sp_map),
                "total_with_logoff": total_with_logoff,
                "total_os_produtivas": total_os_produtivas,
                "total_os_geral": total_os_geral,
                "assertiveness_rate": rate
            },
            "teams": base_teams
        }

    def get_monthly_audit_data(self, month_str: str) -> dict:
        """Calcula as métricas consolidadas e médias diárias para o mês especificado (YYYY-MM)."""
        try:
            from supabase_client import fetch_delivery_sessions_by_month
            sessions = fetch_delivery_sessions_by_month(month_str)
            
            # Agrupa sessões por data (pega a sessão com maior total de cada dia como representativa)
            days_map = {}
            for s in sessions:
                d_ref = s.get("date_ref")
                tot = int(s.get("total_teams", 0))
                if d_ref not in days_map or tot > days_map[d_ref]["total_teams"]:
                    days_map[d_ref] = {
                        "date": d_ref,
                        "total_teams": tot,
                        "cesto": int(s.get("total_cesto", 0)),
                        "leve": int(s.get("total_veiculo_leve", 0)),
                        "moto": int(s.get("total_moto", 0)),
                        "munck": int(s.get("total_munck", 0)),
                        "linha_viva": int(s.get("total_linha_viva", 0)),
                        "linhaviva_munck": int(s.get("total_linha_viva", 0)) + int(s.get("total_munck", 0))
                    }

            # Se for o mês atual, inclui também o dia de hoje caso ainda não esteja consolidado
            today_prefix = self.current_date_str[:7]
            if month_str == today_prefix and len(self.daily_accumulated_teams) > 0:
                cur_sum = self._build_metrics_breakdown(list(self.daily_accumulated_teams.values()))
                days_map[self.current_date_str] = {
                    "date": self.current_date_str,
                    "total_teams": cur_sum["total"],
                    "cesto": cur_sum["cesto"],
                    "leve": cur_sum["leve"],
                    "moto": cur_sum["moto"],
                    "munck": cur_sum["munck"],
                    "linha_viva": cur_sum["linhaviva"],
                    "linhaviva_munck": cur_sum["linhaviva_munck"]
                }

            sorted_days = sorted(days_map.values(), key=lambda x: x["date"])
            num_days = len(sorted_days)

            if num_days == 0:
                return {
                    "status": "empty",
                    "month": month_str,
                    "operating_days": 0,
                    "avg_total": 0,
                    "avg_cesto": 0,
                    "avg_leve": 0,
                    "avg_moto": 0,
                    "avg_linhaviva_munck": 0,
                    "days": []
                }

            sum_tot = sum(d["total_teams"] for d in sorted_days)
            sum_cesto = sum(d["cesto"] for d in sorted_days)
            sum_leve = sum(d["leve"] for d in sorted_days)
            sum_moto = sum(d["moto"] for d in sorted_days)
            sum_lvm = sum(d["linhaviva_munck"] for d in sorted_days)

            return {
                "status": "success",
                "month": month_str,
                "operating_days": num_days,
                "avg_total": round(sum_tot / num_days, 1),
                "avg_cesto": round(sum_cesto / num_days, 1),
                "avg_leve": round(sum_leve / num_days, 1),
                "avg_moto": round(sum_moto / num_days, 1),
                "avg_linhaviva_munck": round(sum_lvm / num_days, 1),
                "days": sorted_days
            }
        except Exception as err:
            print(f"[MONTHLY AUDIT ERROR] {err}")
            return {
                "status": "error",
                "message": str(err),
                "month": month_str,
                "operating_days": 0,
                "avg_total": 0,
                "days": []
            }

delivery_manager = DeliveryManager()
