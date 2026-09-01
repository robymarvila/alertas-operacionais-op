"""
Data Manager - Conciliação e Auditoria Operacional PowerON vs TRBOnet
Gerencia dados em memória, regras de conciliação, agrupamento regional de bases e histórico analítico.
"""

from datetime import datetime, timedelta
import json
import os

class DataManager:
    def __init__(self):
        # Dicionário oficial de metadados das bases operacionais
        self.official_bases = {
            # Região Norte
            "ENL": {"name": "Base Fagundes", "region": "Região Norte", "code": "ENL"},
            "ECL": {"name": "Base Cajati", "region": "Região Norte", "code": "ECL"},
            "EEL": {"name": "Base Vila Medeiros", "region": "Região Norte", "code": "EEL"},
            # Região Leste
            "EML": {"name": "Base Monte Santo", "region": "Região Leste", "code": "EML"},
            "EQL": {"name": "Base Aricanduva", "region": "Região Leste", "code": "EQL"},
            "EVL": {"name": "Base Catumbi", "region": "Região Leste", "code": "EVL"},
            "ESL": {"name": "Base Santo André", "region": "Região Leste", "code": "ESL"},
        }

        # Base de dados de referência inicial (PowerON)
        self.poweron_teams = [
            "ECL121", "ECL123", "ECL124", "ECL126", "ECL135", "ECL300", "ECL700", "ECL702", "ECL705",
            "EEL101", "EEL102", "EEL105", "EEL106", "EEL108", "EEL301", "EEL700", "EEL702",
            "ENL100", "ENL101", "ENL102", "ENL103", "ENL105", "ENL106", "ENL108", "ENL109", "ENL111", 
            "ENL301", "ENL700", "ENL702", "ENL703", "ENL706", "ENL708",
            "EML107", "EML130", "EML131", "EML302",
            "EQL103", "EQL104", "EQL105", "EQL121",
            "EVL101", "EVL102", "EVL110", "EVL121",
            "ESL103", "ESL104", "ESL301"
        ]

        # Base inicial TRBOnet
        self.trbonet_teams = {
            "ECL121": {"gps": True, "last_signal": "11:25:12", "radio_id": "8121", "channel": "SLOT 1 / CH 03"},
            "ECL123": {"gps": True, "last_signal": "11:28:01", "radio_id": "8123", "channel": "SLOT 2 / CH 03"},
            "ECL126": {"gps": True, "last_signal": "11:15:40", "radio_id": "8126", "channel": "SLOT 1 / CH 03"},
            "EEL102": {"gps": True, "last_signal": "11:29:50", "radio_id": "9102", "channel": "SLOT 1 / CH 05"},
            "EEL105": {"gps": True, "last_signal": "11:24:11", "radio_id": "9105", "channel": "SLOT 2 / CH 05"},
            "EEL108": {"gps": True, "last_signal": "11:20:00", "radio_id": "9108", "channel": "SLOT 1 / CH 05"},
            "ENL100": {"gps": False, "last_signal": "11:10:12", "radio_id": "7100", "channel": "SLOT 1 / CH 01"},
            "ENL101": {"gps": False, "last_signal": "11:15:30", "radio_id": "7101", "channel": "SLOT 1 / CH 01"},
            "ENL103": {"gps": True, "last_signal": "11:27:30", "radio_id": "7103", "channel": "SLOT 1 / CH 01"},
            "ENL105": {"gps": True, "last_signal": "11:30:15", "radio_id": "7105", "channel": "SLOT 1 / CH 01"},
            "ENL108": {"gps": True, "last_signal": "11:29:44", "radio_id": "7108", "channel": "SLOT 2 / CH 01"},
            "EML107": {"gps": False, "last_signal": "11:18:00", "radio_id": "6107", "channel": "SLOT 1 / CH 02"},
            "EML130": {"gps": True, "last_signal": "11:26:00", "radio_id": "6130", "channel": "SLOT 2 / CH 02"},
            "EQL103": {"gps": True, "last_signal": "11:28:40", "radio_id": "5103", "channel": "SLOT 1 / CH 04"},
            "EVL101": {"gps": True, "last_signal": "11:29:10", "radio_id": "4101", "channel": "SLOT 1 / CH 06"},
            "ESL103": {"gps": True, "last_signal": "11:22:15", "radio_id": "3103", "channel": "SLOT 1 / CH 07"}
        }

        # Registro histórico por equipe
        self.team_history = {}
        self._init_team_history()

        self.last_update = datetime.now()
        self.last_trbonet_sync = self.last_update.strftime("%d/%m/%Y %H:%M:%S")
        self.last_poweron_login = "--"
        self.update_count = 1
        self.audit_log = [
            {
                "timestamp": self.last_update.strftime("%H:%M:%S"),
                "event": "Inicialização do Sistema",
                "details": f"Carregadas {len(self.poweron_teams)} equipes PowerON e {len(self.trbonet_teams)} rádios TRBOnet."
            }
        ]
        
        # Carregar automaticamente o arquivo calendário se existir
        try:
            self.carregar_arquivo_calendario_poweron()
        except Exception:
            pass

    def carregar_arquivo_calendario_poweron(self, custom_path=None):
        """
        Lê o arquivo do PowerON (Arquivo Calendário), filtrando:
        1. Equipes sem LOGOFF preenchido (equipes em operação ativa).
        2. Desconsiderando equipes que começam com 'CML'.
        3. Identifica a data e hora da última equipe logada na coluna LOGIN.
        """
        import glob
        import pandas as pd

        folder = custom_path or r"C:\Users\r.marvila\OneDrive - ALPITEL BRASIL IMPLANTACOES DE SISTEMAS LTDA\Área de Trabalho\Documentos\Antigravity IDE RDSM\PowerON_TRBOnet\Arquivo Calendário"
        if os.path.isfile(folder):
            files = [folder]
        else:
            files = sorted(
                glob.glob(os.path.join(folder, "*.csv")) + 
                glob.glob(os.path.join(folder, "*.xlsx")) + 
                glob.glob(os.path.join(folder, "*.xls")),
                key=os.path.getmtime,
                reverse=True
            )

        if not files:
            return {"status": "error", "message": "Nenhum arquivo de calendário encontrado na pasta."}

        target_file = files[0]
        fname = os.path.basename(target_file)
        
        try:
            df = None
            if target_file.endswith('.csv'):
                for sep in ['\t', ';', ',']:
                    for enc in ['utf-16', 'utf-8', 'latin1', 'cp1252']:
                        try:
                            temp_df = pd.read_csv(target_file, sep=sep, encoding=enc)
                            if 'Equipe' in temp_df.columns:
                                df = temp_df
                                break
                        except Exception:
                            pass
                    if df is not None:
                        break
            else:
                df = pd.read_excel(target_file)

            if df is None or 'Equipe' not in df.columns:
                return {"status": "error", "message": f"Formato inválido no arquivo '{fname}'."}

            # Regra 1: Desconsiderar equipes que começam com CML
            df_val = df[~df['Equipe'].astype(str).str.strip().str.upper().str.startswith('CML')].copy()

            # Regra 2: Somente equipes com LOGOFF vazio / nulo (ainda logadas)
            if 'LOGOFF' in df_val.columns:
                df_logadas = df_val[
                    df_val['LOGOFF'].isna() | 
                    df_val['LOGOFF'].astype(str).str.strip().isin(['', 'nan', 'NaT', 'None', '-'])
                ]
            else:
                df_logadas = df_val

            # Regra 3: Obter data e hora da última equipe logada na coluna LOGIN
            if 'LOGIN' in df_logadas.columns and not df_logadas['LOGIN'].dropna().empty:
                logins_list = [str(x).strip() for x in df_logadas['LOGIN'].dropna().tolist() if str(x).strip() not in ['', 'nan', 'NaT', 'None', '-']]
                if logins_list:
                    self.last_poweron_login = sorted(logins_list)[-1]

            equipes_logadas = sorted(df_logadas['Equipe'].astype(str).str.strip().str.upper().unique().tolist())
            equipes_logadas = [e for e in equipes_logadas if len(e) >= 4 and e != 'NAN']

            self.update_data(
                poweron_list=equipes_logadas,
                source_label=f"Arquivo Calendário ({fname})"
            )

            return {
                "status": "success",
                "message": f"Carregadas {len(equipes_logadas)} equipes ativas do PowerON ({fname})!",
                "total_equipes": len(equipes_logadas),
                "arquivo": fname,
                "data": self.consolidate_data()
            }
        except Exception as e:
            return {"status": "error", "message": f"Erro ao ler arquivo: {str(e)}"}

    def _init_team_history(self):
        """Inicializa ou atualiza o acumulador de histórico de equipes."""
        hoje = datetime.now().strftime("%d/%m/%Y")
        all_codes = sorted(list(set(self.poweron_teams + list(self.trbonet_teams.keys()))))
        for code in all_codes:
            if code not in self.team_history:
                in_pw = code in self.poweron_teams
                in_tr = code in self.trbonet_teams
                self.team_history[code] = {
                    "first_seen": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "poweron_days": [hoje] if in_pw else [],
                    "trbonet_days": [hoje] if in_tr else [],
                    "online_minutes": 180 if in_tr else 0, # minutos estimados acumulados
                    "offline_incidents": 1 if (in_pw and not in_tr) else 0,
                    "total_checks": 1,
                    "online_checks": 1 if (in_pw and in_tr) else 0
                }

    def get_base_info(self, team_code):
        """Identifica a base operacional e sua região a partir do prefixo."""
        prefix = team_code[:3].upper() if len(team_code) >= 3 else "OUT"
        if prefix in self.official_bases:
            b = self.official_bases[prefix]
            return prefix, b["name"], b["region"], False # is_other = False
        return prefix, f"Base {prefix}", "Outras Regiões", True # is_other = True

    def consolidate_data(self):
        """
        Executa a conciliação cruzada entre PowerON e TRBOnet,
        calcula métricas de conformidade, agrupa por região e compila os dados históricos.
        """
        all_codes = sorted(list(set(self.poweron_teams + list(self.trbonet_teams.keys()))))
        teams = []

        hoje_str = datetime.now().strftime("%d/%m/%Y")

        for code in all_codes:
            prefix, base_name, region, is_other = self.get_base_info(code)
            in_poweron = code in self.poweron_teams
            in_trbonet = code in self.trbonet_teams
            
            trbo_info = self.trbonet_teams.get(code, {})
            has_gps = trbo_info.get("gps", False) if in_trbonet else False
            last_signal = trbo_info.get("last_signal", "--:--:--") if in_trbonet else None
            radio_id = trbo_info.get("radio_id", "N/A") if in_trbonet else None
            channel = trbo_info.get("channel", "N/A") if in_trbonet else None

            # Classificação de Status
            if in_poweron and in_trbonet:
                if has_gps:
                    status_code = "ONLINE_GPS"
                    status_label = "Online com GPS"
                    status_category = "CONFORME"
                    severity = "success"
                    badge_class = "badge-online-gps"
                    details_text = "Equipe em escala ativa com rádio conectado e sinal de GPS transmitindo perfeitamente."
                else:
                    status_code = "ONLINE_NOGPS"
                    status_label = "Online sem GPS"
                    status_category = "ALERTA_GPS"
                    severity = "info"
                    badge_class = "badge-online-nogps"
                    details_text = "Rádio conectado no TRBOnet, porém sem fixação de satélite GPS. Verificar antena ou cobertura."
            elif in_poweron and not in_trbonet:
                status_code = "OFFLINE"
                status_label = "Offline no TRBOnet"
                status_category = "CRITICO_SEM_RADIO"
                severity = "danger"
                badge_class = "badge-offline"
                details_text = "ALERTA CRÍTICO: Equipe registrada na escala ativa do PowerON, mas o rádio está desligado ou sem sinal."
            else: # in_trbonet and not in_poweron
                status_code = "TRBO_ONLY"
                status_label = "Apenas no TRBOnet"
                status_category = "AVISO_SEM_ESCALA"
                severity = "warning"
                badge_class = "badge-trbonet-only"
                details_text = "Rádio operando no TRBOnet sem registro correspondente de escala de trabalho no PowerON."

            # Dados Históricos da Equipe
            hist = self.team_history.get(code, {
                "first_seen": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "poweron_days": [hoje_str] if in_poweron else [],
                "trbonet_days": [hoje_str] if in_trbonet else [],
                "online_minutes": 120 if in_trbonet else 0,
                "offline_incidents": 1 if (in_poweron and not in_trbonet) else 0,
                "total_checks": 1,
                "online_checks": 1 if (in_poweron and in_trbonet) else 0
            })

            total_chk = max(hist.get("total_checks", 1), 1)
            on_chk = hist.get("online_checks", 0)
            team_compliance = round((on_chk / total_chk) * 100, 1)

            # Formatação de horas e minutos online
            tot_mins = hist.get("online_minutes", 0)
            hrs = tot_mins // 60
            mins = tot_mins % 60
            online_duration_str = f"{hrs}h {mins:02d}m" if hrs > 0 else f"{mins}m"

            teams.append({
                "code": code,
                "prefix": prefix,
                "base": base_name,
                "region": region,
                "is_other_base": is_other,
                "poweron": in_poweron,
                "trbonet": in_trbonet,
                "gps": has_gps,
                "last_signal": last_signal,
                "radio_id": radio_id,
                "channel": channel,
                "status_code": status_code,
                "status_label": status_label,
                "status_category": status_category,
                "severity": severity,
                "badge_class": badge_class,
                "details_text": details_text,
                # Indicadores Históricos
                "history": {
                    "poweron_days_count": len(set(hist.get("poweron_days", []))),
                    "trbonet_days_count": len(set(hist.get("trbonet_days", []))),
                    "poweron_days_list": list(set(hist.get("poweron_days", []))),
                    "trbonet_days_list": list(set(hist.get("trbonet_days", []))),
                    "online_minutes": tot_mins,
                    "online_duration_str": online_duration_str,
                    "offline_incidents": hist.get("offline_incidents", 0),
                    "compliance_rate": team_compliance
                }
            })

        # Métricas Globais
        total_poweron = len(self.poweron_teams)
        total_trbonet = len(self.trbonet_teams)
        online_with_gps = sum(1 for t in teams if t["status_code"] == "ONLINE_GPS")
        online_without_gps = sum(1 for t in teams if t["status_code"] == "ONLINE_NOGPS")
        total_online_poweron = online_with_gps + online_without_gps
        offline_count = sum(1 for t in teams if t["status_code"] == "OFFLINE")
        trbo_only_count = sum(1 for t in teams if t["status_code"] == "TRBO_ONLY")

        # Taxa de conformidade global
        compliance_rate = round((total_online_poweron / total_poweron * 100), 1) if total_poweron > 0 else 0
        gps_rate = round((online_with_gps / total_online_poweron * 100), 1) if total_online_poweron > 0 else 0

        # Compilação Estruturada por Bases (Norte, Leste e Outras)
        bases_norte = ["ENL", "ECL", "EEL"]
        bases_leste = ["EML", "EQL", "EVL", "ESL"]

        def compilar_estatistica_base(prefix_code, custom_name=None, custom_region=None):
            base_teams = [t for t in teams if t["prefix"] == prefix_code]
            if custom_name:
                b_name = custom_name
            elif prefix_code in self.official_bases:
                b_name = self.official_bases[prefix_code]["name"]
            else:
                b_name = f"Base {prefix_code}"

            b_region = custom_region or (self.official_bases[prefix_code]["region"] if prefix_code in self.official_bases else "Outras")
            b_poweron = sum(1 for t in base_teams if t["poweron"])
            b_online_trbo = sum(1 for t in base_teams if t["poweron"] and t["trbonet"])
            b_gps = sum(1 for t in base_teams if t["poweron"] and t["trbonet"] and t["gps"])
            b_offline = sum(1 for t in base_teams if t["poweron"] and not t["trbonet"])
            b_trbo_only = sum(1 for t in base_teams if not t["poweron"] and t["trbonet"])
            b_total_trbo = sum(1 for t in base_teams if t["trbonet"])
            b_compliance = round((b_online_trbo / b_poweron * 100), 1) if b_poweron > 0 else 0

            return {
                "prefix": prefix_code,
                "name": b_name,
                "region": b_region,
                "total_poweron": b_poweron,
                "online_trbo": b_online_trbo,
                "total_trbonet": b_total_trbo,
                "with_gps": b_gps,
                "offline": b_offline,
                "trbo_only": b_trbo_only,
                "compliance_rate": b_compliance,
                "is_other": prefix_code not in self.official_bases
            }

        # Estatísticas das Bases Norte
        norte_stats = [compilar_estatistica_base(p) for p in bases_norte]
        # Estatísticas das Bases Leste
        leste_stats = [compilar_estatistica_base(p) for p in bases_leste]

        # Estatísticas de Outras Bases
        all_other_prefixes = sorted(list(set(t["prefix"] for t in teams if t["prefix"] not in self.official_bases)))
        outras_sub_stats = [compilar_estatistica_base(p) for p in all_other_prefixes]

        # Card consolidado de Outras
        other_teams = [t for t in teams if t["prefix"] not in self.official_bases]
        other_poweron = sum(1 for t in other_teams if t["poweron"])
        other_online_trbo = sum(1 for t in other_teams if t["poweron"] and t["trbonet"])
        other_gps = sum(1 for t in other_teams if t["poweron"] and t["trbonet"] and t["gps"])
        other_offline = sum(1 for t in other_teams if t["poweron"] and not t["trbonet"])
        other_trbo_only = sum(1 for t in other_teams if not t["poweron"] and t["trbonet"])
        other_total_trbo = sum(1 for t in other_teams if t["trbonet"])
        other_compliance = round((other_online_trbo / other_poweron * 100), 1) if other_poweron > 0 else 0

        outras_consolidado = {
            "prefix": "OUTRAS",
            "name": "Outras Bases",
            "region": "Demais Regiões",
            "total_poweron": other_poweron,
            "online_trbo": other_online_trbo,
            "total_trbonet": other_total_trbo,
            "with_gps": other_gps,
            "offline": other_offline,
            "trbo_only": other_trbo_only,
            "compliance_rate": other_compliance,
            "is_other": True,
            "sub_bases_count": len(all_other_prefixes)
        }

        # Todas as bases em formato linear para compatibilidade
        all_bases_list = norte_stats + leste_stats + [outras_consolidado]

        return {
            "summary": {
                "total_poweron": total_poweron,
                "total_trbonet": total_trbonet,
                "online_with_gps": online_with_gps,
                "online_without_gps": online_without_gps,
                "total_online_poweron": total_online_poweron,
                "total_offline": offline_count,
                "total_trbo_only": trbo_only_count,
                "compliance_rate": compliance_rate,
                "gps_rate": gps_rate,
                "total_teams_audited": len(teams),
                "last_update": self.last_update.strftime("%d/%m/%Y %H:%M:%S"),
                "last_trbonet_sync": self.last_trbonet_sync,
                "last_poweron_login": self.last_poweron_login,
                "update_count": self.update_count
            },
            "regions": {
                "norte": {
                    "title": "Região Norte",
                    "bases": norte_stats
                },
                "leste": {
                    "title": "Região Leste",
                    "bases": leste_stats
                },
                "outras": {
                    "title": "Outras Bases Operacionais",
                    "summary": outras_consolidado,
                    "sub_bases": outras_sub_stats
                }
            },
            "bases": all_bases_list,
            "teams": teams,
            "audit_log": self.audit_log[-12:]
        }

    def update_data(self, poweron_list=None, trbonet_dict=None, source_label="Atualização Manual / API"):
        """
        Atualiza o estado de dados e recalcula métricas históricas de tempo online e incidentes.
        """
        changes = []
        hoje_str = datetime.now().strftime("%d/%m/%Y")

        if poweron_list is not None:
            old_count = len(self.poweron_teams)
            self.poweron_teams = sorted(list(set(poweron_list)))
            changes.append(f"PowerON: {old_count} -> {len(self.poweron_teams)} equipes")

        if trbonet_dict is not None:
            old_trbo = len(self.trbonet_teams)
            self.last_trbonet_sync = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            if isinstance(trbonet_dict, list):
                formatted_dict = {}
                for item in trbonet_dict:
                    if isinstance(item, dict):
                        code = item.get("code") or item.get("equipe")
                        if code:
                            formatted_dict[code] = {
                                "gps": item.get("gps", True),
                                "last_signal": item.get("last_signal", datetime.now().strftime("%H:%M:%S")),
                                "radio_id": item.get("radio_id", "N/A"),
                                "channel": item.get("channel", "N/A")
                            }
                    elif isinstance(item, str):
                        formatted_dict[item] = {"gps": True, "last_signal": datetime.now().strftime("%H:%M:%S")}
                self.trbonet_teams = formatted_dict
            elif isinstance(trbonet_dict, dict):
                self.trbonet_teams = trbonet_dict
            changes.append(f"TRBOnet: {old_trbo} -> {len(self.trbonet_teams)} rádios")

        # Atualizar acumulador histórico de equipes
        all_codes = set(self.poweron_teams + list(self.trbonet_teams.keys()))
        for code in all_codes:
            in_pw = code in self.poweron_teams
            in_tr = code in self.trbonet_teams
            
            if code not in self.team_history:
                self.team_history[code] = {
                    "first_seen": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "poweron_days": [hoje_str] if in_pw else [],
                    "trbonet_days": [hoje_str] if in_tr else [],
                    "online_minutes": 30 if in_tr else 0,
                    "offline_incidents": 1 if (in_pw and not in_tr) else 0,
                    "total_checks": 1,
                    "online_checks": 1 if in_tr else 0
                }
            else:
                entry = self.team_history[code]
                if in_pw and hoje_str not in entry["poweron_days"]:
                    entry["poweron_days"].append(hoje_str)
                if in_tr and hoje_str not in entry["trbonet_days"]:
                    entry["trbonet_days"].append(hoje_str)
                
                entry["total_checks"] += 1
                if in_tr:
                    entry["online_checks"] += 1
                    entry["online_minutes"] += 15 # soma incremento de tempo online
                elif in_pw and not in_tr:
                    entry["offline_incidents"] += 1

        self.last_update = datetime.now()
        self.update_count += 1
        
        log_entry = {
            "timestamp": self.last_update.strftime("%H:%M:%S"),
            "event": source_label,
            "details": " | ".join(changes) if changes else "Dados sincronizados sem alteração de volume."
        }
        self.audit_log.append(log_entry)
        return self.consolidate_data()

    def reset_to_baseline(self):
        """Restaura a base de dados para o estado inicial de referência."""
        self.__init__()
        return self.consolidate_data()

# Instância global compartilhada
data_manager = DataManager()
