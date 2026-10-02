"""
Gerenciador do Módulo: PRIORIZADOR - ORDENS CRÍTICAS (ENEL SP)
Responsável pelo processamento das 25 colunas analíticas do TIBCO Spotfire (Aba ANALISTAS),
regras de criticidade de rede (DJ, RA, CF, BF, CH, RM), cruzamento com Entrega de Equipes,
detecção atômica de mutações para auditoria e gestão da Linha do Tempo da Supervisão.
"""

import os
import sys
import json
import re
import hashlib
import threading
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional

import pandas as pd

# Fuso Horário Oficial de Operação (Brasília - UTC-3)
BR_TZ = timezone(timedelta(hours=-3))

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(WORKSPACE_DIR, "priorizador_daily_cache.json")

# Equipamentos Críticos e Prioritários de Alta Complexidade da Rede Elétrica Enel SP
# Conforme diretriz estrita: DJ, RA, CF, CA, BF, CH e RM
EQUIPAMENTOS_CRITICOS = {'DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM'}

# Mapeamento Oficial das 7 Bases Permitidas (Regiões Norte e Leste)
# Conforme diretriz: "No PAINEL OPERACIONAL DE GRANDES INTERRUPÇÕES precisa ter somente os equipamentos das bases:
# Região Norte: BASE FAGUNDES FILHO, BASE CAJATI, BASE VILA MEDEIROS
# Região Leste: BASE MONTE SANTO, BASE ARICANDUVA, BASE CATUMBI, BASE SANTO ANDRÉ.
# As demais bases não importam, pode descartar essas informações."
BASES_PERMITIDAS = {
    # Região Norte
    "BASE FAGUNDES FILHO": ("BASE FAGUNDES FILHO", "NORTE"),
    "FAGUNDES FILHO": ("BASE FAGUNDES FILHO", "NORTE"),
    "BASE CAJATI": ("BASE CAJATI", "NORTE"),
    "CAJATI": ("BASE CAJATI", "NORTE"),
    "BASE VILA MEDEIROS": ("BASE VILA MEDEIROS", "NORTE"),
    "VILA MEDEIROS": ("BASE VILA MEDEIROS", "NORTE"),

    # Região Leste
    "BASE MONTE SANTO": ("BASE MONTE SANTO", "LESTE"),
    "MONTE SANTO": ("BASE MONTE SANTO", "LESTE"),
    "BASE ARICANDUVA": ("BASE ARICANDUVA", "LESTE"),
    "ARICANDUVA": ("BASE ARICANDUVA", "LESTE"),
    "BASE CATUMBI": ("BASE CATUMBI", "LESTE"),
    "CATUMBI": ("BASE CATUMBI", "LESTE"),
    "BASE SANTO ANDRE": ("BASE SANTO ANDRÉ", "LESTE"),
    "BASE SANTO ANDRÉ": ("BASE SANTO ANDRÉ", "LESTE"),
    "SANTO ANDRE": ("BASE SANTO ANDRÉ", "LESTE"),
    "SANTO ANDRÉ": ("BASE SANTO ANDRÉ", "LESTE"),
}

BASES_NORTE_AUTORIZADAS = {
    "BASE FAGUNDES FILHO", "BASE CAJATI", "BASE VILA MEDEIROS",
    "FAGUNDES FILHO", "CAJATI", "VILA MEDEIROS"
}

BASES_LESTE_AUTORIZADAS = {
    "BASE MONTE SANTO", "BASE ARICANDUVA", "BASE CATUMBI", "BASE SANTO ANDRÉ",
    "BASE SANTO ANDRE", "MONTE SANTO", "ARICANDUVA", "CATUMBI", "SANTO ANDRÉ", "SANTO ANDRE"
}

def normalize_base(raw_base: str) -> tuple:
    """
    Verifica se a base pertence ao escopo autorizado (Norte ou Leste).
    Retorna (is_permitida, nome_canonico, regiao).
    Caso contrário, retorna (False, '', '').
    """
    if not raw_base:
        return False, "", ""
    import unicodedata
    clean = str(raw_base).strip().upper()
    nfkd = unicodedata.normalize('NFKD', clean)
    clean_no_accent = "".join([c for c in nfkd if not unicodedata.combining(c)])

    # 1. Match direto
    if clean in BASES_PERMITIDAS:
        canon, reg = BASES_PERMITIDAS[clean]
        return True, canon, reg

    # 2. Match sem acentos ou sem prefixo "BASE "
    for k, (canon, reg) in BASES_PERMITIDAS.items():
        k_no_accent = "".join([c for c in unicodedata.normalize('NFKD', k) if not unicodedata.combining(c)])
        if clean_no_accent == k_no_accent:
            return True, canon, reg
        if clean_no_accent.replace("BASE ", "").strip() == k_no_accent.replace("BASE ", "").strip():
            return True, canon, reg

    return False, "", ""

def to_int(val, default=0) -> int:
    try:
        if pd.isna(val) or val is None or val == '-' or val == '--' or val == '':
            return default
        clean = re.sub(r'[^0-9-]', '', str(val).replace(',', '.').split('.')[0])
        val_int = int(clean) if clean else default
        if val_int > 2147483647 or val_int < -2147483648:
            return default
        return val_int
    except Exception:
        return default

def to_float(val, default=0.0) -> float:
    try:
        if pd.isna(val) or val is None or val == '-' or val == '--' or val == '':
            return default
        s = str(val).strip().replace('.', '').replace(',', '.')
        s_clean = re.sub(r'[^0-9.-]', '', s)
        return float(s_clean) if s_clean else default
    except Exception:
        return default

def to_str(val, default="--") -> str:
    if pd.isna(val) or val is None:
        return default
    s = str(val).strip()
    return s if s and s.lower() != 'nan' else default

def sanitize_order_code(raw_order: str) -> str:
    """Normaliza o código da ordem removendo espaços e caracteres estranhos."""
    if not raw_order:
        return ""
    return str(raw_order).strip()

def extract_radical_order(raw_order: str) -> str:
    """Extrai apenas os dígitos base da ordem (ex: '16908554-1' -> '16908554')."""
    if not raw_order:
        return ""
    clean = str(raw_order).split('-')[0].strip()
    digits = re.sub(r'[^0-9]', '', clean)
    return digits


class PriorizadorManager:
    """Singleton gerenciador do painel Priorizador - Ordens Críticas."""

    def __init__(self):
        self._lock = threading.RLock()
        self.active_orders: Dict[str, Dict[str, Any]] = {}
        self.supervisor_timelines: Dict[str, List[Dict[str, Any]]] = {}
        self.mutation_history: List[Dict[str, Any]] = []
        self.last_sync_session: Dict[str, Any] = {}
        self.is_collecting = False
        self.last_collect_time: Optional[str] = None
        self.last_collect_status = "IDLE"
        self._load_cache()

    def _load_cache(self):
        """Carrega estado em cache local caso o servidor seja reiniciado."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    raw_orders = data.get("active_orders", {})
                    # Reclassifica todas as ordens carregadas com as regras estritas
                    for o in raw_orders.values():
                        crit = self.classificar_criticidade(o.get("eq", ""), o.get("ci", 0), o.get("control_desp", ""))
                        o["nivel_criticidade"] = crit["nivel"]
                        o["prioridade_rank"] = crit["prioridade_rank"]
                        o["prioridade_codigo"] = crit["prioridade_codigo"]
                        o["criticidade_label"] = crit["label"]
                        o["criticidade_badge_class"] = crit["badge_class"]
                        o["is_urgencia_critica"] = crit["is_urgencia_critica"]
                        o["regra_descricao"] = crit["regra_descricao"]
                        o["status_desp_tipo"] = crit["status_desp_tipo"]
                        o["cruzamento_label"] = crit["cruzamento_label"]
                        o["cruzamento_class"] = crit["cruzamento_class"]

                    self.active_orders = raw_orders
                    self.supervisor_timelines = data.get("supervisor_timelines", {})
                    self.mutation_history = data.get("mutation_history", [])[-200:]
                    self.last_sync_session = data.get("last_sync_session", {})
                    self.last_collect_time = data.get("last_collect_time")
            except Exception as e:
                print(f"[PRIORIZADOR CACHE ERROR] Falha ao carregar cache local: {e}", flush=True)

    def _save_cache(self):
        """Persiste estado consolidado em disco."""
        try:
            payload = {
                "active_orders": self.active_orders,
                "supervisor_timelines": self.supervisor_timelines,
                "mutation_history": self.mutation_history[-300:],
                "last_sync_session": self.last_sync_session,
                "last_collect_time": self.last_collect_time,
                "saved_at": datetime.now(BR_TZ).isoformat()
            }
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[PRIORIZADOR CACHE ERROR] Falha ao salvar cache local: {e}", flush=True)

    def classificar_criticidade(self, eq: str, ci: int, control_desp: str = "") -> Dict[str, Any]:
        """
        Aplica a Regra Estrita de Prioridade Operacional (Independente do status da coluna CONTROL_DESP):
        
        SEQUÊNCIA ESTRITA DE PRIORIDADES:
        1. PRIORIDADE ELEVADA: Equipamentos Críticos (DJ, RA, CF, CA, BF, CH, RM) com CI > 200 clientes.
           Exemplo: BF com 500 clientes desligados. Prioridade máxima absoluta de impacto.
        2. REDE CRÍTICA (EQ CRÍTICO): Equipamentos Críticos (DJ, RA, CF, CA, BF, CH, RM) por si sós são prioridade (CI <= 200).
        3. GRANDE CI (DEMAIS EQUIPAMENTOS): Qualquer outro equipamento fora da lista crítica com CI >= 200 clientes.
        4. CONVENCIONAL: Demais ocorrências (equipamentos convencionais com CI < 200).

        * Essa classificação de prioridade independe do status CONTROL_DESP.
        * O cruzamento com CONTROL_DESP é gerado em campos adicionais para alimentar a Visão Operacional.
        """
        eq_clean = (eq or "").strip().upper()
        cd_clean = (control_desp or "").strip().upper()
        try:
            ci_num = int(float(str(ci).replace(',', ''))) if ci is not None else 0
        except Exception:
            ci_num = 0

        is_eq_critico = eq_clean in EQUIPAMENTOS_CRITICOS

        # 1. HIERARQUIA ESTRITA DE PRIORIDADE INTRÍNSECA (Visão 1: Pura)
        if is_eq_critico and ci_num > 200:
            nivel = "CRITICO_MAXIMO"
            prioridade_rank = 1
            prioridade_codigo = "PRIO_1_ELEVADA"
            label = f"⚡ ELEVADA ({eq_clean} • {ci_num:,} CI)"
            badge_class = "badge-critico-maximo"
            is_urgencia = True
            descricao = f"Equipamento Crítico ({eq_clean}) com CI elevado (>200 clientes)"
        elif is_eq_critico:
            nivel = "EQ_CRITICO"
            prioridade_rank = 2
            prioridade_codigo = "PRIO_2_EQ_CRITICO"
            label = f"🔴 REDE: {eq_clean}"
            badge_class = "badge-eq-critico"
            is_urgencia = False
            descricao = f"Equipamento Crítico de Rede ({eq_clean})"
        elif ci_num >= 200:
            nivel = "CI_ALTO"
            prioridade_rank = 3
            prioridade_codigo = "PRIO_3_CI_ALTO"
            label = f"🟠 CI ELEVADO ({ci_num:,})"
            badge_class = "badge-ci-alto"
            is_urgencia = False
            descricao = "Demais Equipamentos com CI ≥ 200 clientes"
        else:
            nivel = "CONVENCIONAL"
            prioridade_rank = 4
            prioridade_codigo = "PRIO_4_CONVENCIONAL"
            label = "CONVENCIONAL"
            badge_class = "badge-convencional"
            is_urgencia = False
            descricao = "Equipamento convencional com CI < 200 clientes"

        # 2. ANÁLISE OPERACIONAL ATRELADA AO STATUS CONTROL_DESP (Visão 2: Operacional)
        status_desp_tipo = "OUTROS"
        if "AGUARD" in cd_clean:
            status_desp_tipo = "AGUARDANDO_DESPACHO"
        elif "CAMI" in cd_clean:
            status_desp_tipo = "A_CAMINHO"
        elif "LOCAL_>=80" in cd_clean or ">=80" in cd_clean:
            status_desp_tipo = "LOCAL_MAIOR_80MIN"
        elif "LOCAL_" in cd_clean:
            status_desp_tipo = "LOCAL_MENOR_80MIN"

        # Badges operacionais enriquecidos para a Visão 2
        if prioridade_rank == 1 and status_desp_tipo == "AGUARDANDO_DESPACHO":
            cruzamento_label = "🚨 CRÍTICO SEM DESPACHO"
            cruzamento_class = "badge-cruzamento-aguard-urgente"
        elif prioridade_rank in (1, 2) and status_desp_tipo == "LOCAL_MAIOR_80MIN":
            cruzamento_label = "⏱️ CRÍTICO LOCAL ≥ 80m"
            cruzamento_class = "badge-cruzamento-local80"
        elif prioridade_rank == 1 and status_desp_tipo == "A_CAMINHO":
            cruzamento_label = "🚚 CRÍTICO A CAMINHO"
            cruzamento_class = "badge-cruzamento-cami"
        elif prioridade_rank == 2 and status_desp_tipo == "AGUARDANDO_DESPACHO":
            cruzamento_label = "⏳ REDE AGUARD. DESPACHO"
            cruzamento_class = "badge-cruzamento-aguard-rede"
        elif prioridade_rank == 3 and status_desp_tipo == "AGUARDANDO_DESPACHO":
            cruzamento_label = "⏳ CI ELEVADO AGUARDANDO"
            cruzamento_class = "badge-cruzamento-aguard-ci"
        elif status_desp_tipo == "LOCAL_MAIOR_80MIN":
            cruzamento_label = "⏱️ LOCAL ≥ 80m"
            cruzamento_class = "badge-cruzamento-local80"
        else:
            cruzamento_label = cd_clean or "--"
            cruzamento_class = "badge-cruzamento-padrao"

        return {
            "nivel": nivel,
            "prioridade_rank": prioridade_rank,
            "prioridade_codigo": prioridade_codigo,
            "label": label,
            "badge_class": badge_class,
            "is_urgencia_critica": is_urgencia,
            "regra_descricao": descricao,
            # Campos da Visão 2 (Cruzamento com CONTROL_DESP)
            "status_desp_tipo": status_desp_tipo,
            "cruzamento_label": cruzamento_label,
            "cruzamento_class": cruzamento_class
        }

    def cruzar_com_entrega_equipes(self, ordem_str: str) -> Dict[str, Any]:
        """
        Cruza a ordem do Priorizador com a relação de equipes entregues hoje.
        Procura por match exato (ex: '16908554-1') e pelo radical numérico ('16908554').
        """
        res = {
            "equipe_codigo": None,
            "equipe_motorista": None,
            "equipe_veiculo": None,
            "equipe_status": None,
            "equipe_base": None,
            "equipe_vinculada_em": None
        }

        if not ordem_str or ordem_str in ['-', '--', 'nan', 'NAN']:
            return res

        clean_ordem = sanitize_order_code(ordem_str)
        radical_ordem = extract_radical_order(clean_ordem)

        try:
            from delivery_manager import delivery_manager
            
            # Pool unificado de equipes (ativas no momento + acumuladas do dia)
            teams_pool = []
            if hasattr(delivery_manager, 'active_teams') and delivery_manager.active_teams:
                teams_pool.extend(delivery_manager.active_teams)
            if hasattr(delivery_manager, 'daily_accumulated_teams') and delivery_manager.daily_accumulated_teams:
                teams_pool.extend(list(delivery_manager.daily_accumulated_teams.values()))

            # Deduplica equipes pelo código
            seen = set()
            teams = []
            for t in teams_pool:
                code = t.get("team_code")
                if code and code not in seen:
                    seen.add(code)
                    teams.append(t)

            # 1. Procura equipe atual com a ordem corrente ativa
            for t in teams:
                t_ordem = str(t.get("ordem_servico") or "").strip()
                t_rad = extract_radical_order(t_ordem)

                if (clean_ordem == t_ordem and t_ordem != '') or (radical_ordem and radical_ordem == t_rad and t_rad != ''):
                    res["equipe_codigo"] = t.get("team_code")
                    res["equipe_motorista"] = t.get("driver") or "--"
                    res["equipe_veiculo"] = t.get("vehicle_type") or t.get("veiculo_portal") or "--"
                    res["equipe_status"] = t.get("status_equipes_brasil") or t.get("status") or "Logada"
                    res["equipe_base"] = t.get("base_display") or t.get("base_name") or "--"
                    res["equipe_vinculada_em"] = datetime.now(BR_TZ).isoformat()
                    return res

            # 2. Procura no histórico de ordens atribuídas no dia em cada equipe (order_history)
            for t in teams:
                hist_items = t.get("order_history") or []
                for h in hist_items:
                    hist_o = str(h.get("ordem") or "").strip()
                    hist_rad = extract_radical_order(hist_o)
                    if (clean_ordem == hist_o and hist_o != '') or (radical_ordem and radical_ordem == hist_rad and hist_rad != ''):
                        res["equipe_codigo"] = t.get("team_code")
                        res["equipe_motorista"] = t.get("driver") or "--"
                        res["equipe_veiculo"] = t.get("vehicle_type") or t.get("veiculo_portal") or "--"
                        res["equipe_status"] = h.get("status") or t.get("status_equipes_brasil") or t.get("status") or "Logada"
                        res["equipe_base"] = t.get("base_display") or t.get("base_name") or "--"
                        res["equipe_vinculada_em"] = h.get("last_seen") or h.get("first_seen") or datetime.now(BR_TZ).isoformat()
                        return res

        except Exception as e:
            print(f"[PRIORIZADOR CROSS DELIVERY ERROR] {e}", flush=True)

        return res

    def processar_dataframe_spotfire(self, df: pd.DataFrame, source_label="Robô CDP Automático") -> Dict[str, Any]:
        """
        Recebe o DataFrame extraído da tabela 'GRANDES INTERRUPÇÕES (utilize os filtros de CI e tempo):'
        e executa a normalização, cruzamento, auditoria atômica e persistência.
        """
        with self._lock:
            start_t = datetime.now(BR_TZ)
            now_iso = start_t.isoformat()

            if df is None or df.empty:
                print("[PRIORIZADOR] DataFrame recebido vazio ou nulo.", flush=True)
                return {"status": "warning", "message": "Nenhum dado encontrado na extração.", "total": 0}

            # Normalização de nomes de colunas do Spotfire (case e acento insensível)
            col_map = {}
            for col in df.columns:
                c_norm = re.sub(r'[^a-zA-Z0-9]', '', str(col)).upper()
                col_map[c_norm] = col

            def get_val(row, *aliases):
                for a in aliases:
                    an = re.sub(r'[^a-zA-Z0-9]', '', a).upper()
                    if an in col_map:
                        return row[col_map[an]]
                return None

            novas_ordens: Dict[str, Dict[str, Any]] = {}
            mutacoes_detectadas: List[Dict[str, Any]] = []

            for _, row in df.iterrows():
                ordem_raw = to_str(get_val(row, 'ORDEM', 'Ordem', 'NUM_ORDEM'), "")
                if not ordem_raw or ordem_raw in ['--', '-', 'nan', 'NAN']:
                    continue

                ordem = sanitize_order_code(ordem_raw)
                control_desp = to_str(get_val(row, 'CONTROL_DESP', 'CONTROLDESP', 'DESPACHO'), "--")
                data_desligamento = to_str(get_val(row, 'Data Desligamento', 'DATADESLIGAMENTO', 'DATA_DESLIGAMENTO'), "--")
                qtd_reinc_60 = to_int(get_val(row, 'QTD Reinc. -60', 'QTDREINC60', 'REINCIDENCIA'), 0)
                eq = to_str(get_val(row, 'EQ', 'EQUIPAMENTO', 'CATEGORIA_EQ'), "--").upper()
                facility = to_str(get_val(row, 'FACILITY', 'COD_FACILITY'), "--")
                alimentador = to_str(get_val(row, 'ALIMENTADOR', 'CIRCUITO'), "--")
                interrupcoes = to_int(get_val(row, 'INTERRUPCOES', 'INTERRUPÇÕES', 'CLIENTES_TOTAIS'), 0)
                ci = to_int(get_val(row, 'CI', 'CLIENTES_INTERROMPIDOS'), 0)
                chi = to_float(get_val(row, 'CHI', 'CHI_ACUMULADO'), 0.0)
                dm_parcial = to_float(get_val(row, 'DM PARCIAL', 'DMPARCIAL', 'DM'), 0.0)
                num_recla = to_int(get_val(row, 'NUM_RECLA', 'NUMRECLA', 'RECLAMACOES'), 0)
                base_op_raw = to_str(get_val(row, 'Base Op.', 'BASEOP', 'BASE_OPERACIONAL', 'BASE'), "--")
                is_permitida, base_canon, regiao_canon = normalize_base(base_op_raw)

                # DIRETRIZ OPERACIONAL: Manter estritamente ordens das 7 bases autorizadas (Norte e Leste).
                # Demais bases são descartadas.
                if not is_permitida:
                    continue

                base_op = base_canon
                regiao = regiao_canon or to_str(get_val(row, 'REGIÃO', 'REGIAO'), "--").upper()
                situacao_conjunto = to_str(get_val(row, 'SITUAÇÃO CONJUNTO', 'SITUACAOCONJUNTO', 'SITUACAO'), "--")
                organizacao = to_str(get_val(row, 'ORGANIZAÇÃO', 'ORGANIZACAO', 'POSTO'), "--")
                aval_dif = to_str(get_val(row, 'AVAL_DIF.?', 'AVALDIF', 'AVAL_DIF'), "--")
                tempo_ult_recla = to_int(get_val(row, 'Tempo Ult. Recla. (minuto)', 'TEMPOULTRECLA', 'TEMPO_RECLA'), 0)
                meta_dm = to_float(get_val(row, 'META DM', 'METADM'), 0.0)
                dur_min = to_int(get_val(row, 'DUR. (min)', 'DURMIN', 'DURACAO'), 0)
                chi_projetado = to_float(get_val(row, 'CHI_projetado', 'CHIPROJETADO'), 0.0)
                num_equipes = to_int(get_val(row, 'NUM_EQUIPES', 'NUMEQUIPES'), 0)
                tp = to_str(get_val(row, 'TP'), "--")
                tp_1e = to_str(get_val(row, 'TP_1E', 'TP1E'), "--")
                tp_2e = to_str(get_val(row, 'TP_2E', 'TP2E'), "--")

                # 1. Classificação de Criticidade Operacional
                crit = self.classificar_criticidade(eq, ci, control_desp)

                # 2. Cruzamento com Entrega de Equipes
                equipe_info = self.cruzar_com_entrega_equipes(ordem)

                # 3. Preservação de dados da Supervisão existente
                ordem_antiga = self.active_orders.get(ordem, {})
                supervisor_resp = ordem_antiga.get("supervisor_responsavel")
                status_supervisao = ordem_antiga.get("status_supervisao", "Pendente")
                ultima_nota = ordem_antiga.get("ultima_nota_supervisao")
                dt_supervisao = ordem_antiga.get("ultima_atualizacao_supervisao")
                total_notas = len(self.supervisor_timelines.get(ordem, []))
                primeira_coleta = ordem_antiga.get("primeira_coleta_em", now_iso)

                # 4. Hash dos dados para detecção atômica de mutações
                hash_source = f"{ordem}|{ci}|{chi:.2f}|{control_desp}|{equipe_info['equipe_codigo'] or '--'}|{dur_min}"
                hash_dados = hashlib.sha256(hash_source.encode('utf-8')).hexdigest()

                # 5. Detecção de Mutação para Auditoria & Histórico (SEM redundância)
                if not ordem_antiga:
                    # Primeiro registro desta ordem no sistema
                    mut = {
                        "ordem": ordem,
                        "coletado_em": now_iso,
                        "campo_alterado": "PRIMEIRO_REGISTRO",
                        "valor_anterior": None,
                        "valor_novo": f"CI: {ci} | {control_desp}",
                        "ci_atual": ci,
                        "chi_atual": chi,
                        "control_desp_atual": control_desp,
                        "equipe_atual": equipe_info["equipe_codigo"],
                        "motivo_resumo": f"Primeira detecção da OS crítica no Priorizador ({eq} - {facility})"
                    }
                    mutacoes_detectadas.append(mut)
                else:
                    # Compara campos chave
                    ci_ant = ordem_antiga.get("ci", 0)
                    chi_ant = ordem_antiga.get("chi", 0.0)
                    cd_ant = ordem_antiga.get("control_desp", "")
                    eq_ant = ordem_antiga.get("equipe_codigo")

                    if ci != ci_ant:
                        delta_ci = ci - ci_ant
                        sinal = f"+{delta_ci}" if delta_ci > 0 else f"{delta_ci}"
                        mutacoes_detectadas.append({
                            "ordem": ordem,
                            "coletado_em": now_iso,
                            "campo_alterado": "CI",
                            "valor_anterior": str(ci_ant),
                            "valor_novo": str(ci),
                            "ci_atual": ci,
                            "chi_atual": chi,
                            "control_desp_atual": control_desp,
                            "equipe_atual": equipe_info["equipe_codigo"],
                            "motivo_resumo": f"Variação de CI: de {ci_ant} para {ci} ({sinal} clientes)"
                        })

                    if control_desp != cd_ant and cd_ant != "":
                        mutacoes_detectadas.append({
                            "ordem": ordem,
                            "coletado_em": now_iso,
                            "campo_alterado": "CONTROL_DESP",
                            "valor_anterior": cd_ant,
                            "valor_novo": control_desp,
                            "ci_atual": ci,
                            "chi_atual": chi,
                            "control_desp_atual": control_desp,
                            "equipe_atual": equipe_info["equipe_codigo"],
                            "motivo_resumo": f"Avanço de status de despacho: {cd_ant} ➔ {control_desp}"
                        })

                    if equipe_info["equipe_codigo"] != eq_ant and (equipe_info["equipe_codigo"] or eq_ant):
                        mutacoes_detectadas.append({
                            "ordem": ordem,
                            "coletado_em": now_iso,
                            "campo_alterado": "EQUIPE",
                            "valor_anterior": eq_ant or "Nenhuma",
                            "valor_novo": equipe_info["equipe_codigo"] or "Nenhuma",
                            "ci_atual": ci,
                            "chi_atual": chi,
                            "control_desp_atual": control_desp,
                            "equipe_atual": equipe_info["equipe_codigo"],
                            "motivo_resumo": f"Alteração de equipe associada: {eq_ant or 'Sem equipe'} ➔ {equipe_info['equipe_codigo'] or 'Sem equipe'}"
                        })

                # Monta objeto consolidado da OS
                item = {
                    "ordem": ordem,
                    "control_desp": control_desp,
                    "data_desligamento": data_desligamento,
                    "qtd_reinc_60": qtd_reinc_60,
                    "eq": eq,
                    "facility": facility,
                    "alimentador": alimentador,
                    "interrupcoes": interrupcoes,
                    "ci": ci,
                    "chi": chi,
                    "dm_parcial": dm_parcial,
                    "num_recla": num_recla,
                    "base_op": base_op,
                    "situacao_conjunto": situacao_conjunto,
                    "organizacao": organizacao,
                    "aval_dif": aval_dif,
                    "regiao": regiao,
                    "tempo_ult_recla_min": tempo_ult_recla,
                    "meta_dm": meta_dm,
                    "dur_min": dur_min,
                    "chi_projetado": chi_projetado,
                    "num_equipes": num_equipes,
                    "tp": tp,
                    "tp_1e": tp_1e,
                    "tp_2e": tp_2e,
                    # Criticidade calculada estrita (Visão 1: Pura e Visão 2: Operacional)
                    "nivel_criticidade": crit["nivel"],
                    "prioridade_rank": crit["prioridade_rank"],
                    "prioridade_codigo": crit["prioridade_codigo"],
                    "criticidade_label": crit["label"],
                    "criticidade_badge_class": crit["badge_class"],
                    "is_urgencia_critica": crit["is_urgencia_critica"],
                    "regra_descricao": crit["regra_descricao"],
                    "status_desp_tipo": crit["status_desp_tipo"],
                    "cruzamento_label": crit["cruzamento_label"],
                    "cruzamento_class": crit["cruzamento_class"],
                    # Equipe vinculada
                    "equipe_codigo": equipe_info["equipe_codigo"],
                    "equipe_motorista": equipe_info["equipe_motorista"],
                    "equipe_veiculo": equipe_info["equipe_veiculo"],
                    "equipe_status": equipe_info["equipe_status"],
                    "equipe_base": equipe_info["equipe_base"],
                    "equipe_vinculada_em": equipe_info["equipe_vinculada_em"],
                    # Supervisão e Logbook
                    "supervisor_responsavel": supervisor_resp,
                    "status_supervisao": status_supervisao,
                    "ultima_nota_supervisao": ultima_nota,
                    "ultima_atualizacao_supervisao": dt_supervisao,
                    "total_notas_supervisao": total_notas,
                    # Controle
                    "hash_dados": hash_dados,
                    "is_active": True,
                    "primeira_coleta_em": primeira_coleta,
                    "atualizado_em": now_iso
                }

                novas_ordens[ordem] = item

            # Atualiza o dicionário em memória
            self.active_orders = novas_ordens
            if mutacoes_detectadas:
                self.mutation_history.extend(mutacoes_detectadas)
                self.mutation_history = self.mutation_history[-500:]

            elapsed_sec = round((datetime.now(BR_TZ) - start_t).total_seconds(), 2)

            # Métricas da sessão
            tot_ci = sum(o["ci"] for o in novas_ordens.values())
            tot_chi = round(sum(o["chi"] for o in novas_ordens.values()), 2)
            qtd_urgencia = sum(1 for o in novas_ordens.values() if o["is_urgencia_critica"])
            qtd_aguard = sum(1 for o in novas_ordens.values() if 'AGUARD' in (o["control_desp"] or "").upper())
            qtd_loc80 = sum(1 for o in novas_ordens.values() if ('LOCAL_>=80' in (o["control_desp"] or "").upper() or '>=80' in (o["control_desp"] or "").upper()))
            qtd_equipe = sum(1 for o in novas_ordens.values() if o["equipe_codigo"])

            self.last_sync_session = {
                "captured_at": now_iso,
                "total_ordens": len(novas_ordens),
                "total_ci": tot_ci,
                "total_chi": tot_chi,
                "qtd_urgencia_critica": qtd_urgencia,
                "qtd_aguard_desp": qtd_aguard,
                "qtd_local_80min": qtd_loc80,
                "qtd_com_equipe": qtd_equipe,
                "mutacoes_geradas": len(mutacoes_detectadas),
                "tempo_coleta_segundos": elapsed_sec,
                "status": "SUCCESS",
                "origem": source_label
            }

            self.last_collect_time = now_iso
            self.last_collect_status = "SUCCESS"
            self._save_cache()

            # Dispara persistência assíncrona no Supabase
            threading.Thread(
                target=self._push_supabase_worker,
                args=(list(novas_ordens.values()), mutacoes_detectadas, dict(self.last_sync_session)),
                daemon=True
            ).start()

            print(f"[PRIORIZADOR OK] Coleta concluída com sucesso! {len(novas_ordens)} OSs ativas | CI: {tot_ci:,} | Urgências Críticas: {qtd_urgencia} | Mutações: {len(mutacoes_detectadas)} | Tempo: {elapsed_sec}s", flush=True)

            return {
                "status": "success",
                "message": f"{len(novas_ordens)} ordens críticas processadas com sucesso!",
                "session": self.last_sync_session
            }

    def _push_supabase_worker(self, orders: List[Dict[str, Any]], mutations: List[Dict[str, Any]], session: Dict[str, Any]):
        """Persiste os dados no Supabase em segundo plano."""
        try:
            from supabase_client import (
                push_priorizador_active_orders,
                push_priorizador_mutations,
                push_priorizador_session,
                deactivate_missing_priorizador_orders
            )
            push_priorizador_session(session)
            if orders:
                push_priorizador_active_orders(orders)
            deactivate_missing_priorizador_orders(orders)
            if mutations:
                push_priorizador_mutations(mutations)
        except Exception as e:
            print(f"[PRIORIZADOR SUPABASE PUSH ERROR] {e}", flush=True)

    def registrar_nota_supervisao(self, ordem: str, supervisor_nome: str, status_etapa: str, observacao: str) -> Dict[str, Any]:
        """
        Adiciona um novo apontamento na Linha do Tempo da Supervisão (Logbook)
        e atualiza o cabeçalho da ordem em tempo real.
        """
        with self._lock:
            clean_ordem = sanitize_order_code(ordem)
            if clean_ordem not in self.active_orders:
                return {"status": "error", "message": f"Ordem {ordem} não encontrada no Priorizador."}

            now_iso = datetime.now(BR_TZ).isoformat()
            target_order = self.active_orders[clean_ordem]

            nota_item = {
                "id": hashlib.md5(f"{clean_ordem}_{now_iso}_{supervisor_nome}".encode('utf-8')).hexdigest(),
                "ordem": clean_ordem,
                "supervisor_nome": supervisor_nome.strip(),
                "status_etapa": status_etapa.strip(),
                "observacao": observacao.strip(),
                "ci_momento": target_order.get("ci", 0),
                "chi_momento": target_order.get("chi", 0.0),
                "equipe_momento": target_order.get("equipe_codigo"),
                "registrado_em": now_iso
            }

            # Atualiza timeline local
            timeline_list = self.supervisor_timelines.setdefault(clean_ordem, [])
            timeline_list.insert(0, nota_item)  # Mais recente primeiro

            # Atualiza cabeçalho da ordem
            target_order["supervisor_responsavel"] = supervisor_nome.strip()
            target_order["status_supervisao"] = status_etapa.strip()
            target_order["ultima_nota_supervisao"] = observacao.strip()
            target_order["ultima_atualizacao_supervisao"] = now_iso
            target_order["total_notas_supervisao"] = len(timeline_list)

            self._save_cache()

            # Persiste no Supabase
            try:
                from supabase_client import insert_priorizador_supervisor_note, update_priorizador_order_supervisor
                threading.Thread(
                    target=lambda: [
                        insert_priorizador_supervisor_note(nota_item),
                        update_priorizador_order_supervisor(clean_ordem, supervisor_nome, status_etapa, observacao, now_iso)
                    ],
                    daemon=True
                ).start()
            except Exception as e:
                print(f"[PRIORIZADOR TIMELINE SUPABASE ERROR] {e}", flush=True)

            return {
                "status": "success",
                "message": "Apontamento registrado com sucesso na linha do tempo!",
                "note": nota_item,
                "total_notes": len(timeline_list)
            }

    def get_timeline_by_order(self, ordem: str) -> List[Dict[str, Any]]:
        """Retorna a linha do tempo completa de uma ordem específica."""
        with self._lock:
            clean_ordem = sanitize_order_code(ordem)
            local_tl = self.supervisor_timelines.get(clean_ordem, [])
            if local_tl:
                return list(local_tl)

            # Fallback para o Supabase
            try:
                from supabase_client import fetch_priorizador_timeline_by_order
                cloud_tl = fetch_priorizador_timeline_by_order(clean_ordem)
                if cloud_tl:
                    self.supervisor_timelines[clean_ordem] = cloud_tl
                    return cloud_tl
            except Exception:
                pass

            return []

    def get_order_dossier(self, ordem: str) -> Dict[str, Any]:
        """Retorna o dossiê completo de uma OS: dados técnicos, mutações e histórico de supervisão."""
        with self._lock:
            clean_ordem = sanitize_order_code(ordem)
            order_data = self.active_orders.get(clean_ordem)
            
            # Se não estiver nas ativas, tenta buscar do Supabase
            if not order_data:
                try:
                    from supabase_client import get_supabase_client
                    client = get_supabase_client()
                    if client:
                        resp = client.table("priorizador_active_orders").select("*").eq("ordem", clean_ordem).execute()
                        if resp.data and len(resp.data) > 0:
                            order_data = resp.data[0]
                except Exception as e:
                    print(f"[DOSSIER ORDER FETCH ERROR] {e}", flush=True)

            # Filtra mutações dessa ordem
            order_mutations = [m for m in self.mutation_history if m.get("ordem") == clean_ordem]
            if not order_mutations:
                try:
                    from supabase_client import get_supabase_client
                    client = get_supabase_client()
                    if client:
                        resp = client.table("priorizador_mutations").select("*").eq("ordem", clean_ordem).order("coletado_em", desc=False).execute()
                        if resp.data:
                            order_mutations = resp.data
                except Exception as e:
                    print(f"[DOSSIER MUTATIONS FETCH ERROR] {e}", flush=True)

            # Timeline do diário de bordo
            timeline = self.get_timeline_by_order(clean_ordem)

            return {
                "status": "success" if order_data else "not_found",
                "ordem": clean_ordem,
                "order": order_data,
                "mutations": order_mutations,
                "timeline": timeline,
                "total_mutations": len(order_mutations),
                "total_notes": len(timeline)
            }

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Consolida os dados analíticos para alimentar as 3 visões do painel."""
        with self._lock:
            orders = list(self.active_orders.values())

            # Ordena por prioridade: Urgência Máxima primeiro, depois CI decrescente
            orders.sort(key=lambda o: (o.get("prioridade_rank", 99), -o.get("ci", 0), -o.get("chi", 0)))

            tot_ordens = len(orders)
            tot_ci = sum(o.get("ci", 0) for o in orders)
            tot_chi = round(sum(o.get("chi", 0.0) for o in orders), 2)
            tot_urgencia = sum(1 for o in orders if o.get("is_urgencia_critica"))
            tot_aguard = sum(1 for o in orders if 'AGUARD' in (o.get("control_desp") or "").upper())
            tot_loc80 = sum(1 for o in orders if ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper()))
            tot_supervisionadas = sum(1 for o in orders if o.get("supervisor_responsavel"))

            # Contagens das Prioridades Estritas (Independente de CONTROL_DESP)
            tot_prio1 = sum(1 for o in orders if o.get("prioridade_rank") == 1)
            tot_prio2 = sum(1 for o in orders if o.get("prioridade_rank") == 2)
            tot_prio3 = sum(1 for o in orders if o.get("prioridade_rank") == 3)
            tot_prio4 = sum(1 for o in orders if o.get("prioridade_rank") == 4)

            # Matriz de Cruzamento Operacional: Prioridade Estrita x Status CONTROL_DESP (Visão 2)
            prio_desp_matrix = {
                "prio1_aguard": sum(1 for o in orders if o.get("prioridade_rank") == 1 and 'AGUARD' in (o.get("control_desp") or "").upper()),
                "prio1_cami": sum(1 for o in orders if o.get("prioridade_rank") == 1 and 'CAMI' in (o.get("control_desp") or "").upper()),
                "prio1_local80": sum(1 for o in orders if o.get("prioridade_rank") == 1 and ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper())),
                "prio1_local_sub80": sum(1 for o in orders if o.get("prioridade_rank") == 1 and ('LOCAL_' in (o.get("control_desp") or "").upper() and not ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper()))),
                
                "prio2_aguard": sum(1 for o in orders if o.get("prioridade_rank") == 2 and 'AGUARD' in (o.get("control_desp") or "").upper()),
                "prio2_cami": sum(1 for o in orders if o.get("prioridade_rank") == 2 and 'CAMI' in (o.get("control_desp") or "").upper()),
                "prio2_local80": sum(1 for o in orders if o.get("prioridade_rank") == 2 and ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper())),
                "prio2_local_sub80": sum(1 for o in orders if o.get("prioridade_rank") == 2 and ('LOCAL_' in (o.get("control_desp") or "").upper() and not ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper()))),

                "prio3_aguard": sum(1 for o in orders if o.get("prioridade_rank") == 3 and 'AGUARD' in (o.get("control_desp") or "").upper()),
                "prio3_cami": sum(1 for o in orders if o.get("prioridade_rank") == 3 and 'CAMI' in (o.get("control_desp") or "").upper()),
                "prio3_local80": sum(1 for o in orders if o.get("prioridade_rank") == 3 and ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper())),
                "prio3_local_sub80": sum(1 for o in orders if o.get("prioridade_rank") == 3 and ('LOCAL_' in (o.get("control_desp") or "").upper() and not ('LOCAL_>=80' in (o.get("control_desp") or "").upper() or '>=80' in (o.get("control_desp") or "").upper()))),
            }

            # Contagem Regional: Norte vs Leste
            tot_norte = sum(1 for o in orders if (o.get("regiao") or "").upper().startswith("NORTE") or o.get("base_op") in BASES_NORTE_AUTORIZADAS)
            tot_leste = sum(1 for o in orders if (o.get("regiao") or "").upper().startswith("LESTE") or o.get("base_op") in BASES_LESTE_AUTORIZADAS)

            # Breakdown por Equipamentos Críticos (DJ, RA, CF, CA, BF, CH, RM)
            criticos_breakdown = {eq_code: 0 for eq_code in EQUIPAMENTOS_CRITICOS}
            for o in orders:
                eq_code = (o.get("eq") or "").strip().upper()
                if eq_code in criticos_breakdown:
                    criticos_breakdown[eq_code] += 1

            # Distribuição por Equipamento (EQ)
            eq_dist: Dict[str, Dict[str, Any]] = {}
            for o in orders:
                eq_name = o.get("eq") or "OUTROS"
                if eq_name not in eq_dist:
                    eq_dist[eq_name] = {"count": 0, "ci": 0, "chi": 0.0, "is_critico": eq_name in EQUIPAMENTOS_CRITICOS}
                eq_dist[eq_name]["count"] += 1
                eq_dist[eq_name]["ci"] += o.get("ci", 0)
                eq_dist[eq_name]["chi"] = round(eq_dist[eq_name]["chi"] + o.get("chi", 0.0), 2)

            # Distribuição por CONTROL_DESP
            cd_dist: Dict[str, int] = {}
            for o in orders:
                cd_name = o.get("control_desp") or "--"
                cd_dist[cd_name] = cd_dist.get(cd_name, 0) + 1

            # Distribuição por Base Operacional
            base_dist: Dict[str, Dict[str, Any]] = {}
            for o in orders:
                b_name = o.get("base_op") or "--"
                if b_name not in base_dist:
                    base_dist[b_name] = {"count": 0, "ci": 0, "chi": 0.0}
                base_dist[b_name]["count"] += 1
                base_dist[b_name]["ci"] += o.get("ci", 0)
                base_dist[b_name]["chi"] = round(base_dist[b_name]["chi"] + o.get("chi", 0.0), 2)

            return {
                "status": "success",
                "kpis": {
                    "total_ordens": tot_ordens,
                    "total_norte": tot_norte,
                    "total_leste": tot_leste,
                    "criticos_breakdown": criticos_breakdown,
                    "total_ci": tot_ci,
                    "total_chi": tot_chi,
                    "total_urgencia_critica": tot_urgencia,
                    "total_aguard_desp": tot_aguard,
                    "total_local_80min": tot_loc80,
                    "total_supervisionadas": tot_supervisionadas,
                    "percent_supervisionadas": round((tot_supervisionadas / tot_ordens * 100), 1) if tot_ordens > 0 else 0,
                    "total_prio1_elevada": tot_prio1,
                    "total_prio2_eq_critico": tot_prio2,
                    "total_prio3_ci_alto": tot_prio3,
                    "total_prio4_convencional": tot_prio4,
                    "cruzamento_despacho": prio_desp_matrix
                },
                "active_orders": orders,
                "distributions": {
                    "by_equipment": eq_dist,
                    "by_control_desp": cd_dist,
                    "by_base": base_dist
                },
                "mutations_recent": self.mutation_history[-200:],
                "last_session": self.last_sync_session,
                "last_collect_time": self.last_collect_time,
                "is_collecting": self.is_collecting
            }


priorizador_manager = PriorizadorManager()
