"""
Cluster Manager - Gerenciamento de Alta Disponibilidade e Redundância (Ativo-Standby)
Permite executar duas máquinas Windows em paralelo (Máquina 1 - Principal e Máquina 2 - Backup).
Monitora a saúde de cada nó, estado da porta CDP 9222, batimentos cardíacos (heartbeat),
eleição do nó ativo que alimenta o banco Supabase, e failover automático caso o nó principal falhe.
"""

import os
import sys
import json
import time
import socket
import platform
import threading
from datetime import datetime, timezone, timedelta

# Fuso horário oficial de Brasília (UTC-3)
BR_TZ = timezone(timedelta(hours=-3))

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "node_config.json")
_CLUSTER_LOCK = threading.Lock()

# Fallbacks padrão
DEFAULT_NODE_ID = os.environ.get("MACHINE_ID", "MAQUINA_1_PRINCIPAL")
DEFAULT_NODE_LABEL = os.environ.get("MACHINE_LABEL", "Servidor CCO Principal (Máquina 1)")
DEFAULT_ROLE = os.environ.get("MACHINE_ROLE", "PRIMARY")  # 'PRIMARY' ou 'STANDBY'


class ClusterManager:
    """Gerenciador central do nó local e da sincronia de cluster com o Supabase."""

    def __init__(self):
        self.config = self._load_or_create_config()
        self.node_id = self.config.get("node_id", DEFAULT_NODE_ID)
        self.node_label = self.config.get("node_label", DEFAULT_NODE_LABEL)
        self.role = self.config.get("role", DEFAULT_ROLE)
        self.is_feeding_db = bool(self.config.get("is_feeding_db", self.role == "PRIMARY"))
        self.auto_failover_enabled = self.config.get("auto_failover_enabled", True)
        self.manual_override_until = self.config.get("manual_override_until", None)
        self.failover_suspect_count = 0
        self.last_heartbeat = None
        self.active_node_id = "MAQUINA_1_PRINCIPAL"
        self._worker_started = False
        self.start_time = datetime.now(BR_TZ).isoformat()

    def _load_or_create_config(self) -> dict:
        """Carrega a configuração do nó a partir de node_config.json ou cria com valores padrão."""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                    lbl = cfg.get("node_label", "")
                    lbl = str(lbl).replace("MÃ¡quina", "Máquina").replace("M\ufffdquina", "Máquina")
                    if "MAQUINA_1" in cfg.get("node_id", "") and "Máquina" not in lbl:
                        lbl = "Servidor CCO Principal (Máquina 1)"
                    elif "MAQUINA_2" in cfg.get("node_id", "") and "Máquina" not in lbl:
                        lbl = "Servidor CCO Redundante (Máquina 2)"
                    cfg["node_label"] = lbl
                    return cfg
            except Exception as e:
                print(f"[CLUSTER WARN] Erro ao ler {CONFIG_FILE}: {e}", flush=True)

        hostname = socket.gethostname()
        is_backup = "02" in hostname.upper() or "BACKUP" in hostname.upper()
        default_cfg = {
            "node_id": "MAQUINA_2_BACKUP" if is_backup else "MAQUINA_1_PRINCIPAL",
            "node_label": "Servidor CCO Redundante (Máquina 2)" if is_backup else "Servidor CCO Principal (Máquina 1)",
            "role": "STANDBY" if is_backup else "PRIMARY",
            "is_feeding_db": False if is_backup else True,
            "auto_failover_enabled": True,
            "manual_override_until": None,
            "hostname": hostname
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(default_cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CLUSTER WARN] Não foi possível salvar {CONFIG_FILE}: {e}", flush=True)

        return default_cfg

    def save_config(self, new_cfg: dict):
        """Salva novas configurações em disco e atualiza atributos em memória."""
        with _CLUSTER_LOCK:
            self.config.update(new_cfg)
            self.node_id = self.config.get("node_id", self.node_id)
            self.node_label = self.config.get("node_label", self.node_label)
            self.role = self.config.get("role", self.role)
            self.is_feeding_db = bool(self.config.get("is_feeding_db", self.is_feeding_db))
            self.auto_failover_enabled = self.config.get("auto_failover_enabled", self.auto_failover_enabled)
            if "manual_override_until" in new_cfg:
                self.manual_override_until = new_cfg["manual_override_until"]

        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[CLUSTER ERROR] Erro ao persistir {CONFIG_FILE}: {e}", flush=True)

    def get_local_ip(self) -> str:
        """Retorna o IP da máquina na rede local."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(('8.8.8.8', 80))
                return s.getsockname()[0]
        except Exception:
            return '127.0.0.1'

    def is_cdp_port_open(self, host="127.0.0.1", port=9222, timeout=0.8) -> bool:
        """Verifica se o navegador CDP local está ativo na porta 9222."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                return s.connect_ex((host, port)) == 0
        except Exception:
            return False

    def is_feeding_database(self) -> bool:
        """Indica se este nó local está com permissão ativa para gravar no Supabase."""
        return bool(self.is_feeding_db)

    def set_feeding_status(self, is_feeding: bool):
        """Altera localmente e persiste se esta máquina alimenta o banco."""
        self.save_config({"is_feeding_db": is_feeding})

    def get_cluster_leader_from_db(self) -> str:
        """Consulta no Supabase qual é a máquina definida como líder autoritativo e atualiza locks."""
        import requests
        from supabase_client import BASE_REST_URL, get_headers
        try:
            endpoint = f"{BASE_REST_URL}/system_engine_health?engine_name=eq.cluster_leader"
            resp = requests.get(endpoint, headers=get_headers(), timeout=5)
            if resp.status_code == 200:
                data = resp.json() or []
                if data:
                    det = data[0].get("details_json") or {}
                    active_id = det.get("active_node_id")
                    manual_until = det.get("manual_override_until")
                    if manual_until:
                        self.manual_override_until = manual_until
                    if active_id:
                        self.active_node_id = active_id
                        return active_id
        except Exception:
            pass
        return self.active_node_id or "MAQUINA_1_PRINCIPAL"

    def publish_local_heartbeat(self, engines_summary: dict = None) -> dict:
        """
        Publica o estado deste computador no Supabase e sincroniza a liderança.
        """
        from supabase_client import BASE_REST_URL, get_headers, BR_TZ, format_datetime_br, update_engine_health

        now_dt = datetime.now(BR_TZ)
        is_cdp_alive = self.is_cdp_port_open()

        # 1. Monta o payload deste nó
        active_leader = self.get_cluster_leader_from_db()
        is_leader = (self.node_id == active_leader)

        if is_leader != self.is_feeding_db:
            print(f"[CLUSTER SYNC] Alimentação ajustada: {self.node_id} is_feeding_db={is_leader} (Líder: {active_leader})", flush=True)
            self.set_feeding_status(is_leader)

        node_status = "ONLINE" if is_cdp_alive else "WARNING"
        if not is_leader:
            node_status = "STANDBY"

        details = {
            "node_id": self.node_id,
            "node_label": self.node_label,
            "role": self.role,
            "is_feeding_db": self.is_feeding_db,
            "cdp_port_status": "OPEN" if is_cdp_alive else "CLOSED",
            "ip_address": self.get_local_ip(),
            "hostname": socket.gethostname(),
            "os_name": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "geo_location": {
                "city": "São Paulo",
                "region": "SP",
                "country": "Brasil",
                "network": "Alpitel / Enel CCO"
            },
            "started_at": self.start_time,
            "engines": engines_summary or {}
        }

        # 2. Publica no Supabase (system_engine_health)
        try:
            res = update_engine_health(
                engine_name=f"node:{self.node_id}",
                status="OPERATIONAL" if node_status in ["ONLINE", "STANDBY"] else "WARNING",
                is_running=True,
                engine_label=self.node_label,
                details_json=details
            )
            return {"status": "success", "mode": "engine_health", "details": details}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def fetch_all_cluster_nodes(self):
        """
        Busca o status de todas as máquinas conectadas no cluster através do Supabase.
        Retorna tupla (nodes_list, fetch_error: bool) com dados completos de cada computador.
        """
        import requests
        from supabase_client import BASE_REST_URL, get_headers, BR_TZ, format_datetime_br

        nodes_list = []
        now_dt = datetime.now(timezone.utc)
        active_leader = self.get_cluster_leader_from_db()
        fetch_error = False

        try:
            endpoint = f"{BASE_REST_URL}/system_engine_health?engine_name=like.node:*&order=engine_name.asc"
            resp = requests.get(endpoint, headers=get_headers(), timeout=5)
            if resp.status_code == 200:
                raw_eng = resp.json() or []
                for eng in raw_eng:
                    det = eng.get("details_json") or {}
                    hb_str = eng.get("last_heartbeat")
                    is_online = False
                    diff_sec = 9999
                    if hb_str:
                        try:
                            hb_dt = datetime.fromisoformat(hb_str.replace("Z", "+00:00"))
                            if hb_dt.tzinfo is None:
                                hb_dt = hb_dt.replace(tzinfo=timezone.utc)
                            diff_sec = (now_dt - hb_dt).total_seconds()
                            is_online = diff_sec <= 240  # 4 minutos
                        except Exception:
                            pass

                    nid = det.get("node_id") or eng.get("engine_name", "").replace("node:", "")
                    is_feeder = (nid == active_leader)

                    raw_lbl = det.get("node_label") or eng.get("engine_label", nid)
                    clean_lbl = str(raw_lbl).replace("MÃ¡quina", "Máquina").replace("M\ufffdquina", "Máquina")
                    if "MAQUINA_1" in nid:
                        clean_lbl = "Servidor CCO Principal (Máquina 1)"
                    elif "MAQUINA_2" in nid:
                        clean_lbl = "Servidor CCO Redundante (Máquina 2)"

                    node_obj = {
                        "node_id": nid,
                        "node_label": clean_lbl,
                        "role": det.get("role", "PRIMARY" if "1" in nid or "PRINCIPAL" in nid else "STANDBY"),
                        "is_feeding_db": is_feeder,
                        "status": "ONLINE" if is_online else "OFFLINE",
                        "cdp_port_status": det.get("cdp_port_status", "OPEN" if is_online else "UNKNOWN"),
                        "ip_address": det.get("ip_address", "127.0.0.1"),
                        "hostname": det.get("hostname", "Windows"),
                        "os_name": det.get("os_name", "Windows"),
                        "python_version": det.get("python_version", "3.10+"),
                        "geo_location": det.get("geo_location", {
                            "city": "São Paulo", "region": "SP", "country": "Brasil", "network": "Alpitel / Enel CCO"
                        }),
                        "started_at": det.get("started_at"),
                        "last_heartbeat": hb_str,
                        "last_heartbeat_formatted": format_datetime_br(hb_str),
                        "is_communicating": is_online,
                        "seconds_since_heartbeat": int(diff_sec),
                        "engines_status": det.get("engines", {})
                    }
                    nodes_list.append(node_obj)
            else:
                fetch_error = True
        except Exception as e:
            print(f"[CLUSTER FETCH ERROR] {e}", flush=True)
            fetch_error = True

        # Se esta máquina local não veio no retorno remoto, adiciona seus dados locais
        ids = [n["node_id"] for n in nodes_list]
        if self.node_id not in ids:
            nodes_list.append({
                "node_id": self.node_id,
                "node_label": self.node_label,
                "role": self.role,
                "is_feeding_db": (self.node_id == active_leader),
                "status": "ONLINE" if self.is_cdp_port_open() else "DEGRADED",
                "cdp_port_status": "OPEN" if self.is_cdp_port_open() else "CLOSED",
                "ip_address": self.get_local_ip(),
                "hostname": socket.gethostname(),
                "os_name": f"{platform.system()} {platform.release()}",
                "python_version": platform.python_version(),
                "geo_location": {"city": "São Paulo", "region": "SP", "country": "Brasil", "network": "Alpitel / Enel CCO"},
                "started_at": self.start_time,
                "last_heartbeat": datetime.now(BR_TZ).isoformat(),
                "last_heartbeat_formatted": datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M:%S"),
                "is_communicating": True,
                "seconds_since_heartbeat": 0,
                "engines_status": {}
            })

        # Garante a presença dos 2 nós padrão
        ids = [n["node_id"] for n in nodes_list]
        if "MAQUINA_1_PRINCIPAL" not in ids:
            nodes_list.insert(0, {
                "node_id": "MAQUINA_1_PRINCIPAL",
                "node_label": "Servidor CCO Principal (Máquina 1)",
                "role": "PRIMARY",
                "is_feeding_db": (active_leader == "MAQUINA_1_PRINCIPAL"),
                "status": "STANDBY",
                "cdp_port_status": "OPEN",
                "ip_address": "10.171.96.85",
                "hostname": "NOTEMARVILA",
                "os_name": "Windows",
                "geo_location": {"city": "São Paulo", "region": "SP", "country": "Brasil"},
                "last_heartbeat": None,
                "last_heartbeat_formatted": "--:--:--",
                "is_communicating": False,
                "seconds_since_heartbeat": 9999,
                "engines_status": {}
            })
        if "MAQUINA_2_BACKUP" not in ids:
            nodes_list.append({
                "node_id": "MAQUINA_2_BACKUP",
                "node_label": "Servidor CCO Redundante (Máquina 2)",
                "role": "STANDBY",
                "is_feeding_db": (active_leader == "MAQUINA_2_BACKUP"),
                "status": "STANDBY",
                "cdp_port_status": "OPEN",
                "ip_address": "192.168.20.25",
                "hostname": "RobertMarvila",
                "os_name": "Windows",
                "geo_location": {"city": "São Paulo", "region": "SP", "country": "Brasil"},
                "last_heartbeat": None,
                "last_heartbeat_formatted": "--:--:--",
                "is_communicating": False,
                "seconds_since_heartbeat": 9999,
                "engines_status": {}
            })

        return nodes_list, fetch_error

    def promote_node(self, target_node_id: str, is_manual: bool = True) -> dict:
        """
        Promove o nó especificado a líder do cluster no Supabase.
        Garante que apenas UMA máquina fique alimentando o banco.
        Aplica trava de 20 minutos se a promoção for por solicitação manual.
        """
        from supabase_client import update_engine_health, BR_TZ

        now_iso = datetime.now(BR_TZ).isoformat()
        override_until_iso = None

        if is_manual:
            lock_dt = datetime.now(timezone.utc) + timedelta(minutes=20)
            override_until_iso = lock_dt.isoformat()
            self.manual_override_until = override_until_iso
            self.save_config({"manual_override_until": override_until_iso})
            print(f"[CLUSTER MANUAL LOCK] Trava manual ativada até {override_until_iso} (20 min) para {target_node_id}.", flush=True)

        self.failover_suspect_count = 0

        # Atualiza a liderança oficial no Supabase
        details_payload = {
            "active_node_id": target_node_id,
            "promoted_at": now_iso,
            "promoted_by_node": self.node_id,
            "manual_override_until": override_until_iso,
            "is_manual": is_manual
        }

        update_engine_health(
            engine_name="cluster_leader",
            status="OPERATIONAL",
            is_running=True,
            engine_label="Líder do Cluster de Coleta",
            details_json=details_payload
        )

        self.active_node_id = target_node_id
        is_this_node = (target_node_id == self.node_id)
        self.set_feeding_status(is_this_node)

        # Despacha comando explícito no Supabase para alertar todos os nós do cluster
        try:
            from supabase_client import create_sync_command
            create_sync_command("CLUSTER_SET_ROLE", {
                "active_node_id": target_node_id,
                "promoted_by": self.node_id,
                "manual_override_until": override_until_iso,
                "timestamp": now_iso
            })
        except Exception as e:
            print(f"[CLUSTER WARN] Falha ao despachar comando CLUSTER_SET_ROLE: {e}", flush=True)

        # Atualiza heartbeat imediatamente
        self.publish_local_heartbeat()

        msg = f"Máquina '{target_node_id}' promovida a ATIVO. Agora ela é a única alimentando o banco de dados."
        print(f"[CLUSTER PROMOTION] {msg}", flush=True)
        return {
            "status": "success",
            "message": msg,
            "active_node_id": target_node_id,
            "is_this_node_feeding": is_this_node,
            "manual_override_until": override_until_iso
        }

    def check_failover_condition(self, all_nodes: list, fetch_error: bool = False):
        """
        Failover Seguro de Alta Confiabilidade:
        1. Se auto_failover_enabled estiver desligado ou nó já for líder, zera suspeita e sai.
        2. Se houver erro de rede no fetch, ignora para evitar promoção indevida por falha local.
        3. Se houver trava de liderança manual (manual_override_until) vigente (< 20 min), NUNCA dispara failover.
        4. Exige 5 checagens consecutivas (> 100s) com inatividade comprovada > 600s (10 min) para agir.
        """
        if not self.auto_failover_enabled or self.is_feeding_db:
            self.failover_suspect_count = 0
            return

        if fetch_error:
            # Não toma decisões drásticas de failover durante instabilidade local de rede
            return

        # Valida trava manual
        if self.manual_override_until:
            try:
                lock_dt = datetime.fromisoformat(self.manual_override_until.replace("Z", "+00:00"))
                now_utc = datetime.now(timezone.utc)
                if now_utc < lock_dt:
                    rem_sec = int((lock_dt - now_utc).total_seconds())
                    self.failover_suspect_count = 0
                    return
            except Exception:
                pass

        active_leader = self.get_cluster_leader_from_db()
        if active_leader == self.node_id:
            self.failover_suspect_count = 0
            return

        leader_node = next((n for n in all_nodes if n.get("node_id") == active_leader), None)
        if not leader_node:
            return

        sec_since = leader_node.get("seconds_since_heartbeat", 0)

        # Se o dado de heartbeat for fallback não-comprovado (9999), não age
        if sec_since >= 9999:
            return

        if sec_since > 600:  # Mais de 10 minutos sem sinal comprovado
            self.failover_suspect_count += 1
            print(f"[CLUSTER FAILOVER VIGILÂNCIA {self.failover_suspect_count}/5] Líder '{active_leader}' sem sinal há {sec_since}s (>600s)...", flush=True)
            if self.failover_suspect_count >= 5:
                print(f"[CLUSTER FAILOVER CONFIRMADO] 5 checagens consecutivas confirmam inatividade do líder '{active_leader}' ({sec_since}s). Auto-promovendo este nó ({self.node_id})...", flush=True)
                self.failover_suspect_count = 0
                self.promote_node(self.node_id, is_manual=False)
        else:
            # Líder respondeu ou tempo < 600s: zera contador imediatamente
            self.failover_suspect_count = 0

    def start_background_heartbeat(self, get_engines_status_func=None):
        """Inicia a thread de batimento cardíaco periódico e vigilância de failover."""
        if self._worker_started:
            return

        self._worker_started = True

        def _heartbeat_loop():
            print(f"[CLUSTER] Monitor de redundância ativo para nó '{self.node_id}' ({self.role})...", flush=True)
            while True:
                try:
                    engines_summary = {}
                    if get_engines_status_func:
                        try:
                            engines_summary = get_engines_status_func()
                        except Exception:
                            pass

                    self.publish_local_heartbeat(engines_summary)

                    if not self.is_feeding_db:
                        all_nodes, fetch_error = self.fetch_all_cluster_nodes()
                        self.check_failover_condition(all_nodes, fetch_error=fetch_error)

                except Exception as err:
                    print(f"[CLUSTER LOOP WARN] {err}", flush=True)

                time.sleep(20)  # Heartbeat a cada 20 segundos

        t = threading.Thread(target=_heartbeat_loop, name="ClusterHeartbeatWorker", daemon=True)
        t.start()


# Instância Singleton
cluster_manager = ClusterManager()
