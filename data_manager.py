"""
Data Manager - Conciliação e Auditoria Operacional PowerON vs TRBOnet
Gerencia dados em memória, regras de conciliação, agrupamento regional exclusivo de 14 bases oficiais:
- Região Norte Alpitel (ENL, ECL, EEL)
- Região Leste Alpitel (EML, EQL, EVL, ESL)
- Região Norte Própria (ENA, ECA, EEA)
- Região Leste Própria (EMA, EQA, EVA, ESA)
Desconsidera totalmente quaisquer outros códigos não oficiais.
"""

from datetime import datetime, timedelta
import json
import os

class DataManager:
    def __init__(self):
        # 14 Bases Oficiais com empresas e regiões oficiais
        self.official_bases = {
            # Região Norte Alpitel
            "ENL": {"name": "Base Fagundes Filho", "region": "Região Norte Alpitel", "code": "ENL", "company": "Alpitel"},
            "ECL": {"name": "Base Cajati", "region": "Região Norte Alpitel", "code": "ECL", "company": "Alpitel"},
            "EEL": {"name": "Base Vila Medeiros", "region": "Região Norte Alpitel", "code": "EEL", "company": "Alpitel"},
            
            # Região Leste Alpitel
            "EML": {"name": "Base Monte Santo", "region": "Região Leste Alpitel", "code": "EML", "company": "Alpitel"},
            "EQL": {"name": "Base Aricanduva", "region": "Região Leste Alpitel", "code": "EQL", "company": "Alpitel"},
            "EVL": {"name": "Base Catumbi", "region": "Região Leste Alpitel", "code": "EVL", "company": "Alpitel"},
            "ESL": {"name": "Base Santo André", "region": "Região Leste Alpitel", "code": "ESL", "company": "Alpitel"},

            # Região Norte Própria
            "ENA": {"name": "Base Fagundes Filho", "region": "Região Norte Própria", "code": "ENA", "company": "Própria"},
            "ECA": {"name": "Base Cajati", "region": "Região Norte Própria", "code": "ECA", "company": "Própria"},
            "EEA": {"name": "Base Vila Medeiros", "region": "Região Norte Própria", "code": "EEA", "company": "Própria"},

            # Região Leste Própria
            "EMA": {"name": "Base Monte Santo", "region": "Região Leste Própria", "code": "EMA", "company": "Própria"},
            "EQA": {"name": "Base Aricanduva", "region": "Região Leste Própria", "code": "EQA", "company": "Própria"},
            "EVA": {"name": "Base Catumbi", "region": "Região Leste Própria", "code": "EVA", "company": "Própria"},
            "ESA": {"name": "Base Santo André", "region": "Região Leste Própria", "code": "ESA", "company": "Própria"},
        }

        # Base de dados em tempo real (inicia 100% vazia até receber sincronização real)
        self.poweron_teams = []
        self.trbonet_teams = {}
        self.enel_team_details = {}

        # Registro histórico por equipe
        self.team_history = {}

        self.last_update = datetime.now()
        self.last_trbonet_sync = "--"
        self.last_poweron_login = "--"
        self.update_count = 0
        self.audit_log = []
        
        # Carregar automaticamente o arquivo calendário se existir
        try:
            self.carregar_arquivo_calendario_poweron()
        except Exception:
            pass

    def carregar_arquivo_calendario_poweron(self, custom_path=None):
        """
        Lê o arquivo do PowerON (Arquivo Calendário), filtrando:
        1. Equipes sem LOGOFF preenchido (equipes em operação ativa).
        2. Somente prefixos pertencentes às 14 bases oficiais.
        3. Identifica a data e hora da última equipe logada na coluna LOGIN.
        """
        import glob
        try:
            import pandas as pd
        except ImportError:
            return {"status": "error", "message": "pandas não disponível no ambiente."}

        candidate_dirs = [
            custom_path,
            r"C:\Users\robym\Downloads",
            r"C:\Users\robym\Desktop\Documentos\Analise de dados",
            r"C:\Users\robym\Desktop",
            r"C:\Users\robym\OneDrive - ALPITEL BRASIL IMPLANTACOES DE SISTEMAS LTDA\Área de Trabalho\Documentos\Antigravity IDE RDSM\PowerON_TRBOnet\Arquivo Calendário",
            r"C:\Users\r.marvila\OneDrive - ALPITEL BRASIL IMPLANTACOES DE SISTEMAS LTDA\Área de Trabalho\Documentos\Antigravity IDE RDSM\PowerON_TRBOnet\Arquivo Calendário",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data'),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
        ]

        files = []
        for d in candidate_dirs:
            if not d:
                continue
            if os.path.isfile(d):
                files.append(d)
            elif os.path.isdir(d):
                cal_files = glob.glob(os.path.join(d, "*CALENDARIO*.*")) + glob.glob(os.path.join(d, "*Calendario*.*"))
                if cal_files:
                    files.extend(cal_files)
                else:
                    files.extend(glob.glob(os.path.join(d, "*.csv")) + glob.glob(os.path.join(d, "*.xlsx")) + glob.glob(os.path.join(d, "*.xls")))

        # Ordena do mais recente para o mais antigo
        files = sorted(list(set(files)), key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0, reverse=True)

        if not files:
            return {"status": "error", "message": "Nenhum arquivo de calendário do PowerON encontrado nas pastas."}

        target_file = None
        df = None
        fname = ""

        for candidate in files:
            fname = os.path.basename(candidate)
            try:
                if candidate.endswith('.csv'):
                    for enc in ['utf-16', 'utf-8', 'latin1', 'cp1252']:
                        for sep in ['\t', ';', ',']:
                            try:
                                temp_df = pd.read_csv(candidate, sep=sep, encoding=enc, low_memory=False)
                                if 'Equipe' in temp_df.columns:
                                    df = temp_df
                                    target_file = candidate
                                    break
                            except Exception:
                                pass
                        if df is not None:
                            break
                elif candidate.endswith(('.xlsx', '.xls')):
                    temp_df = pd.read_excel(candidate)
                    if 'Equipe' in temp_df.columns:
                        df = temp_df
                        target_file = candidate
                        break
            except Exception:
                continue

            if df is not None:
                break

        if df is None or 'Equipe' not in df.columns:
            return {"status": "error", "message": f"Nenhum arquivo válido com coluna 'Equipe' encontrado."}

        try:
            # Regra 1: Obter data e hora da última equipe logada na coluna LOGIN (maior timestamp)
            if 'LOGIN' in df.columns and not df['LOGIN'].dropna().empty:
                dt_series = pd.to_datetime(df['LOGIN'].dropna(), format='%d/%m/%Y %H:%M:%S', errors='coerce')
                if dt_series.isna().all():
                    dt_series = pd.to_datetime(df['LOGIN'].dropna(), errors='coerce')
                max_login_dt = dt_series.max()
                if pd.notnull(max_login_dt):
                    self.last_poweron_login = max_login_dt.strftime("%d/%m/%Y %H:%M:%S")

            # Regra 2: Somente equipes com LOGOFF vazio / nulo (ainda logadas em operação ativa)
            if 'LOGOFF' in df.columns:
                df_logadas = df[
                    df['LOGOFF'].isna() | 
                    df['LOGOFF'].astype(str).str.strip().isin(['', 'nan', 'NaT', 'None', '-', '0'])
                ].copy()
            else:
                df_logadas = df.copy()

            todas_equipes = sorted(df_logadas['Equipe'].astype(str).str.strip().str.upper().unique().tolist())
            
            # Regra 3: Filtrar ESTRITAMENTE as 14 bases oficiais
            equipes_logadas = [
                e for e in todas_equipes 
                if len(e) >= 4 and e[:3] in self.official_bases
            ]

            self.update_data(
                poweron_list=equipes_logadas,
                source_label=f"Arquivo Calendário ({fname})"
            )

            return {
                "status": "success",
                "message": f"Carregadas {len(equipes_logadas)} equipes oficiais do PowerON ({fname})! Último login: {self.last_poweron_login}",
                "total_equipes": len(equipes_logadas),
                "last_poweron_login": self.last_poweron_login,
                "arquivo": fname,
                "data": self.consolidate_data()
            }
        except Exception as e:
            return {"status": "error", "message": f"Erro ao processar arquivo: {str(e)}"}

    def _init_team_history(self):
        """Inicializa ou atualiza o acumulador de histórico de equipes."""
        hoje = datetime.now().strftime("%d/%m/%Y")
        all_codes = sorted(list(set(self.poweron_teams + list(self.trbonet_teams.keys()))))
        for code in all_codes:
            if code[:3] not in self.official_bases:
                continue
            if code not in self.team_history:
                in_pw = code in self.poweron_teams
                in_tr = code in self.trbonet_teams
                self.team_history[code] = {
                    "first_seen": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "poweron_days": [hoje] if in_pw else [],
                    "trbonet_days": [hoje] if in_tr else [],
                    "online_minutes": 180 if in_tr else 0,
                    "offline_incidents": 1 if (in_pw and not in_tr) else 0,
                    "total_checks": 1,
                    "online_checks": 1 if (in_pw and in_tr) else 0
                }

    def get_base_info(self, team_code):
        """Identifica a base operacional e sua região a partir do prefixo de 3 letras."""
        prefix = team_code[:3].upper() if len(team_code) >= 3 else ""
        if prefix in self.official_bases:
            b = self.official_bases[prefix]
            return prefix, b["name"], b["region"], False
        return prefix, f"Base {prefix}", "Outras", True

    def consolidate_data(self):
        """
        Executa a conciliação cruzada filtrando EXCLUSIVAMENTE as 14 bases oficiais.
        Calcula métricas para:
        - Região Norte Alpitel
        - Região Leste Alpitel
        - Região Norte Própria
        - Região Leste Própria
        """
        # Filtrar exclusivamente códigos que pertencem às 14 bases oficiais
        all_codes = sorted([
            code for code in set(self.poweron_teams + list(self.trbonet_teams.keys()))
            if code[:3] in self.official_bases
        ])

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
                    status_category = "CONFORME"
                    severity = "warning"
                    badge_class = "badge-online-nogps"
                    details_text = "Equipe conectada no TRBOnet, porém sem coordenadas de GPS válidas no momento."
            elif in_poweron and not in_trbonet:
                status_code = "OFFLINE"
                status_label = "Offline Crítico"
                status_category = "APENAS_POWERON"
                severity = "danger"
                badge_class = "badge-offline-critical"
                details_text = "ALERTA CCO: Equipe escalada no PowerON mas sem sinal de rádio ou conexão no TRBOnet."
            elif not in_poweron and in_trbonet:
                status_code = "TRBO_ONLY"
                status_label = "Apenas TRBOnet"
                status_category = "APENAS_TRBONET"
                severity = "purple"
                badge_class = "badge-trbo-only"
                details_text = "Rádio transmitindo no TRBOnet sem registro de escala ativa no PowerON."
            else:
                status_code = "UNKNOWN"
                status_label = "Indeterminado"
                status_category = "OFFLINE"
                severity = "secondary"
                badge_class = "badge-offline-gray"
                details_text = "Sem dados conclusivos nos sistemas."

            # Atualizar Histórico
            if code not in self.team_history:
                self.team_history[code] = {
                    "first_seen": datetime.now().strftime("%d/%m/%Y %H:%M"),
                    "poweron_days": [hoje_str] if in_poweron else [],
                    "trbonet_days": [hoje_str] if in_trbonet else [],
                    "online_minutes": 180 if in_trbonet else 0,
                    "offline_incidents": 1 if (in_poweron and not in_trbonet) else 0,
                    "total_checks": 1,
                    "online_checks": 1 if (in_poweron and in_trbonet) else 0
                }

            hist = self.team_history[code]
            total_chk = max(hist.get("total_checks", 1), 1)
            on_chk = hist.get("online_checks", 0)
            team_compliance = round((on_chk / total_chk) * 100, 1)

            tot_mins = hist.get("online_minutes", 0)
            hrs = tot_mins // 60
            mins = tot_mins % 60
            online_duration_str = f"{hrs}h {mins:02d}m" if hrs > 0 else f"{mins}m"

            enel_d = self.enel_team_details.get(code, {})
            driver = enel_d.get("driver") or "--"
            plate = enel_d.get("plate") or "--"
            vehicle_type = enel_d.get("vehicle_type") or "--"
            shift_slot = enel_d.get("shift_slot") or "--"
            login_time = enel_d.get("login_time") or "--:--"
            logoff_time = enel_d.get("logoff_time") or "--:--"

            teams.append({
                "code": code,
                "prefix": prefix,
                "base": base_name,
                "region": region,
                "is_other_base": False,
                "poweron": in_poweron,
                "trbonet": in_trbonet,
                "gps": has_gps,
                "last_signal": last_signal,
                "radio_id": radio_id,
                "channel": channel,
                "driver": driver,
                "plate": plate,
                "vehicle_type": vehicle_type,
                "shift_slot": shift_slot,
                "login_time": login_time,
                "logoff_time": logoff_time,
                "status_code": status_code,
                "status_label": status_label,
                "status_category": status_category,
                "severity": severity,
                "badge_class": badge_class,
                "details_text": details_text,
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

        # Métricas Globais Filtradas
        total_poweron = sum(1 for t in teams if t["poweron"])
        total_trbonet = sum(1 for t in teams if t["trbonet"])
        online_with_gps = sum(1 for t in teams if t["status_code"] == "ONLINE_GPS")
        online_without_gps = sum(1 for t in teams if t["status_code"] == "ONLINE_NOGPS")
        total_online_poweron = online_with_gps + online_without_gps
        offline_count = sum(1 for t in teams if t["status_code"] == "OFFLINE")
        trbo_only_count = sum(1 for t in teams if t["status_code"] == "TRBO_ONLY")

        compliance_rate = round((total_online_poweron / total_poweron * 100), 1) if total_poweron > 0 else 0
        gps_rate = round((online_with_gps / total_online_poweron * 100), 1) if total_online_poweron > 0 else 0

        # Compilação Estruturada dos 4 Grupos Oficiais
        bases_norte_alpitel = ["ENL", "ECL", "EEL"]
        bases_leste_alpitel = ["EML", "EQL", "EVL", "ESL"]
        bases_norte_propria = ["ENA", "ECA", "EEA"]
        bases_leste_propria = ["EMA", "EQA", "EVA", "ESA"]

        def compilar_estatistica_base(prefix_code):
            base_teams = [t for t in teams if t["prefix"] == prefix_code]
            b_info = self.official_bases.get(prefix_code, {"name": f"Base {prefix_code}", "region": "Oficial"})
            
            b_poweron = sum(1 for t in base_teams if t["poweron"])
            b_online_trbo = sum(1 for t in base_teams if t["poweron"] and t["trbonet"])
            b_gps = sum(1 for t in base_teams if t["poweron"] and t["trbonet"] and t["gps"])
            b_offline = sum(1 for t in base_teams if t["poweron"] and not t["trbonet"])
            b_trbo_only = sum(1 for t in base_teams if not t["poweron"] and t["trbonet"])
            b_total_trbo = sum(1 for t in base_teams if t["trbonet"])
            b_compliance = round((b_online_trbo / b_poweron * 100), 1) if b_poweron > 0 else 0

            return {
                "prefix": prefix_code,
                "name": b_info["name"],
                "region": b_info["region"],
                "total_poweron": b_poweron,
                "online_trbo": b_online_trbo,
                "total_trbonet": b_total_trbo,
                "with_gps": b_gps,
                "offline": b_offline,
                "trbo_only": b_trbo_only,
                "compliance_rate": b_compliance,
                "is_other": False
            }

        norte_alpitel_stats = [compilar_estatistica_base(p) for p in bases_norte_alpitel]
        leste_alpitel_stats = [compilar_estatistica_base(p) for p in bases_leste_alpitel]
        norte_propria_stats = [compilar_estatistica_base(p) for p in bases_norte_propria]
        leste_propria_stats = [compilar_estatistica_base(p) for p in bases_leste_propria]

        all_bases_list = norte_alpitel_stats + leste_alpitel_stats + norte_propria_stats + leste_propria_stats

        return {
            "summary": {
                "total_teams": len(teams),
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
                "NORTE_ALPITEL": {
                    "title": "Região Norte Alpitel",
                    "bases": norte_alpitel_stats
                },
                "LESTE_ALPITEL": {
                    "title": "Região Leste Alpitel",
                    "bases": leste_alpitel_stats
                },
                "NORTE_PROPRIA": {
                    "title": "Região Norte Própria",
                    "bases": norte_propria_stats
                },
                "LESTE_PROPRIA": {
                    "title": "Região Leste Própria",
                    "bases": leste_propria_stats
                }
            },
            "bases": all_bases_list,
            "teams": teams,
            "audit_log": self.audit_log[:40]
        }

    def load_from_snapshot(self, snapshot_data):
        """Reidrata o estado do DataManager a partir de um snapshot do Supabase sem sobrescrever indevidamente."""
        if not snapshot_data or not isinstance(snapshot_data, dict):
            return
        
        teams = snapshot_data.get("teams", [])
        summary = snapshot_data.get("summary", {})
        
        pw_list = []
        tr_dict = {}
        
        for t in teams:
            code = str(t.get("code", "")).strip().upper()
            if not code or len(code) < 3 or code[:3] not in self.official_bases:
                continue
            if t.get("poweron"):
                pw_list.append(code)
            if t.get("trbonet"):
                tr_dict[code] = {
                    "id": t.get("radio_id"),
                    "name": code,
                    "channel": t.get("channel"),
                    "last_signal": t.get("last_signal"),
                    "gps": t.get("gps", False)
                }
        
        if pw_list and not self.poweron_teams:
            self.poweron_teams = sorted(list(set(pw_list)))
        if tr_dict and not self.trbonet_teams:
            self.trbonet_teams = tr_dict
            
        if summary.get("last_poweron_login") and summary.get("last_poweron_login") != "--":
            self.last_poweron_login = summary.get("last_poweron_login")
        if summary.get("last_trbonet_sync") and summary.get("last_trbonet_sync") != "--":
            self.last_trbonet_sync = summary.get("last_trbonet_sync")

    def update_data(self, poweron_list=None, trbonet_dict=None, source_label="Atualização Manual"):
        """Atualiza os dados em memória filtrando ESTRITAMENTE as 14 bases oficiais e preservando o outro fluxo."""
        self.last_update = datetime.now()
        hoje_str = self.last_update.strftime("%d/%m/%Y")

        if poweron_list is not None:
            # Filtrar somente equipes que pertencem às 14 bases oficiais
            self.poweron_teams = sorted(list(set([
                str(t).strip().upper() for t in poweron_list 
                if len(str(t).strip().upper()) >= 3 and str(t).strip().upper()[:3] in self.official_bases
            ])))

        if trbonet_dict is not None:
            # Filtrar somente equipes que pertencem às 14 bases oficiais
            self.trbonet_teams = {
                str(k).strip().upper(): v for k, v in trbonet_dict.items() 
                if len(str(k).strip().upper()) >= 3 and str(k).strip().upper()[:3] in self.official_bases
            }
            self.last_trbonet_sync = self.last_update.strftime("%d/%m/%Y %H:%M:%S")

        # Atualizar contadores históricos das 14 bases oficiais
        all_codes = sorted([
            code for code in set(self.poweron_teams + list(self.trbonet_teams.keys()))
            if len(code) >= 3 and code[:3] in self.official_bases
        ])

        for code in all_codes:
            in_pw = code in self.poweron_teams
            in_tr = code in self.trbonet_teams

            if code not in self.team_history:
                self.team_history[code] = {
                    "first_seen": self.last_update.strftime("%d/%m/%Y %H:%M"),
                    "poweron_days": [hoje_str] if in_pw else [],
                    "trbonet_days": [hoje_str] if in_tr else [],
                    "online_minutes": 180 if in_tr else 0,
                    "offline_incidents": 1 if (in_pw and not in_tr) else 0,
                    "total_checks": 1,
                    "online_checks": 1 if (in_pw and in_tr) else 0
                }
            else:
                h = self.team_history[code]
                h["total_checks"] = h.get("total_checks", 0) + 1
                if in_pw:
                    if hoje_str not in h["poweron_days"]:
                        h["poweron_days"].append(hoje_str)
                if in_tr:
                    if hoje_str not in h["trbonet_days"]:
                        h["trbonet_days"].append(hoje_str)
                    h["online_checks"] = h.get("online_checks", 0) + 1
                    h["online_minutes"] = h.get("online_minutes", 0) + 2
                else:
                    if in_pw:
                        h["offline_incidents"] = h.get("offline_incidents", 0) + 1

        self.update_count += 1
        self.audit_log.insert(0, {
            "timestamp": self.last_update.strftime("%H:%M:%S"),
            "event": f"Sincronização ({source_label})",
            "source": source_label,
            "details": f"Conciliadas {len(self.poweron_teams)} equipes PowerON e {len(self.trbonet_teams)} rádios TRBOnet nas 14 bases oficiais."
        })

        return self.consolidate_data()

    def update_from_enel(self, active_codes, active_details=None, source_label="Enel SP Autônomo (CDP)"):
        """
        Atualiza a lista de equipes ativas diretamente do Módulo de Entrega Enel SP.
        Elimina a necessidade de upload ou leitura de planilhas do PowerON.
        """
        self.last_update = datetime.now()
        hoje_str = self.last_update.strftime("%d/%m/%Y")

        if active_codes is not None:
            self.poweron_teams = sorted(list(set([
                str(t).strip().upper() for t in active_codes 
                if len(str(t).strip().upper()) >= 3 and str(t).strip().upper()[:3] in self.official_bases
            ])))

        if active_details:
            self.enel_team_details.update(active_details)
            logins = [
                d.get("login_time") for d in active_details.values() 
                if d.get("login_time") and d.get("login_time") != "--:--"
            ]
            if logins:
                self.last_poweron_login = f"{hoje_str} {max(logins)}"
            else:
                self.last_poweron_login = self.last_update.strftime("%d/%m/%Y %H:%M:%S")

        self._init_team_history()
        self.update_count += 1
        self.audit_log.insert(0, {
            "timestamp": self.last_update.strftime("%H:%M:%S"),
            "event": f"Sincronização ({source_label})",
            "source": source_label,
            "details": f"Conciliadas {len(self.poweron_teams)} equipes ativas Enel SP e {len(self.trbonet_teams)} rádios TRBOnet."
        })

        return self.consolidate_data()

    def reset_to_baseline(self):
        """Zera todos os dados em memória para estado limpo."""
        self.poweron_teams = []
        self.trbonet_teams = {}
        self.team_history = {}
        self.audit_log = []
        self.last_update = datetime.now()
        self.last_trbonet_sync = "--"
        self.last_poweron_login = "--"
        self.update_count = 0
        return self.consolidate_data()

# Instância singleton do DataManager
data_manager = DataManager()
