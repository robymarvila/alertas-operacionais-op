"""
Fleet Client - Integração com o Sistema 'Controle Operacional' (sist-operacao-norte)
Coleta e gerencia o inventário de veículos da empresa para auditoria e cruzamento
de placas com as equipes ativas do Equipes Brasil.
"""

import os
import re
import json
import time
import requests
from datetime import datetime
from threading import Lock

# Configurações do Supabase Remoto do Controle Operacional (fleet-operacao-app)
REMOTE_SUPABASE_URL = os.environ.get("FLEET_SUPABASE_URL", "https://dbamnuezlbmmxhxpxtiu.supabase.co")
REMOTE_SUPABASE_KEY = os.environ.get("FLEET_SUPABASE_KEY", "sb_publishable_NArb5o1nWAQcPcen4pwzJQ_KG7Vb6hd")

# Cache Local
LOCAL_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOCAL_CACHE_FILE = os.path.join(LOCAL_CACHE_DIR, "fleet_vehicles_cache.json")


def clean_plate(plate: str) -> str:
    """Normaliza placa de veículo removendo traços, pontos, espaços e convertendo para maiúsculo."""
    if not plate:
        return ""
    s = str(plate).strip().upper()
    if s in ['-', '--', 'SEM PLACA', 'NAN', 'NONE', 'NULL']:
        return ""
    cleaned = re.sub(r'[^A-Z0-9]', '', s)
    return cleaned


class FleetClient:
    """Gerencia a coleta remota, cache local e cruzamento de placas."""

    def __init__(self):
        self.lock = Lock()
        self.vehicles_by_plate = {}       # Placa normalizada -> objeto do veículo
        self.vehicles_list = []
        self.last_sync_time = None
        self.last_sync_status = "PENDING"
        self.last_error = None
        self._load_local_cache()

    def _load_local_cache(self):
        """Carrega cache local persistido em disco para resposta instantânea ao iniciar."""
        if os.path.exists(LOCAL_CACHE_FILE):
            try:
                with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    records = data.get("vehicles", [])
                    self._populate_memory(records)
                    self.last_sync_time = data.get("last_sync_time")
                    self.last_sync_status = "LOADED_FROM_FILE"
                    print(f"[FLEET CLIENT] {len(records)} veículos carregados do cache em disco ({LOCAL_CACHE_FILE}).")
            except Exception as e:
                print(f"[FLEET CLIENT WARN] Erro ao carregar cache local: {e}")

    def _populate_memory(self, records: list):
        """Indexa os veículos em memória pela placa normalizada."""
        mapping = {}
        for item in records:
            if not isinstance(item, dict):
                continue
            raw_placa = item.get("placa")
            p_clean = clean_plate(raw_placa)
            if p_clean:
                mapping[p_clean] = item
        with self.lock:
            self.vehicles_by_plate = mapping
            self.vehicles_list = records

    def _save_local_cache(self):
        """Salva a lista atualizada de veículos em arquivo local."""
        try:
            os.makedirs(LOCAL_CACHE_DIR, exist_ok=True)
            with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "last_sync_time": self.last_sync_time,
                    "total": len(self.vehicles_list),
                    "vehicles": self.vehicles_list
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[FLEET CLIENT WARN] Erro ao salvar cache em disco: {e}")

    def fetch_remote_vehicles(self) -> list:
        """
        Consulta a API REST do sist-operacao-norte na tabela 'veiculos'.
        """
        base_url = REMOTE_SUPABASE_URL.rstrip('/')
        if not base_url.endswith('/rest/v1'):
            base_url = f"{base_url}/rest/v1"
        endpoint = f"{base_url}/veiculos?order=placa.asc&limit=1000"

        headers = {
            "apikey": REMOTE_SUPABASE_KEY,
            "Authorization": f"Bearer {REMOTE_SUPABASE_KEY}",
            "Content-Type": "application/json"
        }

        resp = requests.get(endpoint, headers=headers, timeout=12)
        if resp.status_code == 200:
            return resp.json() or []
        else:
            raise RuntimeError(f"Falha na API remota ({resp.status_code}): {resp.text}")

    def sync_fleet_inventory(self) -> dict:
        """
        Sincroniza o inventário com o sist-operacao-norte, atualiza memória,
        persiste em arquivo e envia para a tabela local 'fleet_vehicles_inventory' no Supabase.
        """
        try:
            raw_vehicles = self.fetch_remote_vehicles()
            if not raw_vehicles:
                return {
                    "status": "warning",
                    "message": "Nenhum veículo retornado pelo Controle Operacional.",
                    "total": len(self.vehicles_list)
                }

            now_str = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
            self.last_sync_time = now_str
            self.last_sync_status = "SUCCESS"
            self.last_error = None

            self._populate_memory(raw_vehicles)
            self._save_local_cache()

            # Tenta sincronizar com o Supabase local na tabela 'fleet_vehicles_inventory'
            db_synced = self._push_to_local_supabase(raw_vehicles)

            print(f"[FLEET CLIENT SUCCESS] {len(raw_vehicles)} veículos sincronizados com sucesso do Controle Operacional.")
            return {
                "status": "success",
                "message": f"{len(raw_vehicles)} veículos da frota sincronizados com sucesso.",
                "total": len(raw_vehicles),
                "db_synced": db_synced,
                "synced_at": now_str
            }
        except Exception as err:
            self.last_sync_status = "ERROR"
            self.last_error = str(err)
            print(f"[FLEET CLIENT ERROR] Erro ao sincronizar veículos da frota: {err}")
            return {
                "status": "error",
                "message": str(err),
                "total": len(self.vehicles_list)
            }

    def _push_to_local_supabase(self, vehicles: list) -> bool:
        """Envia os registros normalizados para a tabela fleet_vehicles_inventory do Supabase do projeto."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            endpoint = f"{BASE_REST_URL}/fleet_vehicles_inventory"

            payloads = []
            for v in vehicles:
                raw_p = v.get("placa")
                p_clean = clean_plate(raw_p)
                if not p_clean:
                    continue

                payloads.append({
                    "id": int(v.get("id")),
                    "placa": str(raw_p).strip().upper(),
                    "placa_clean": p_clean,
                    "situacao": str(v.get("situacao") or "ATIVO").strip().upper(),
                    "status": str(v.get("status") or "--").strip(),
                    "tipo": str(v.get("tipo") or "--").strip(),
                    "sub_tipo": str(v.get("subTipo") or "--").strip(),
                    "tipo_op": str(v.get("tipoOp") or "--").strip(),
                    "marca": str(v.get("marca") or "--").strip(),
                    "locadora": str(v.get("locadora") or "--").strip(),
                    "regional": str(v.get("regional") or "--").strip(),
                    "turno": str(v.get("turno") or "--").strip()
                })

            if not payloads:
                return False

            headers = get_headers()
            headers["Prefer"] = "resolution=merge-duplicates"

            # Envia em blocos de 100
            for i in range(0, len(payloads), 100):
                chunk = payloads[i:i + 100]
                r = requests.post(endpoint, headers=headers, json=chunk, timeout=10)
                if r.status_code not in [200, 201]:
                    print(f"[FLEET CLIENT WARN] Erro ao inserir lote de frotas no Supabase ({r.status_code}): {r.text}")
                    return False
            return True
        except Exception as e:
            print(f"[FLEET CLIENT ERROR] Falha no push de frotas para o Supabase: {e}")
            return False

    def cross_reference_plate(self, plate_str: str) -> dict:
        """
        Cruza a placa informada pela equipe no Equipes Brasil com o cadastro de frotas.
        Retorna informações para alimentar as colunas relacionais e os alertas.
        """
        p_clean = clean_plate(plate_str)
        if not p_clean:
            return {
                "plate_clean": "",
                "plate_cadastrada": False,
                "situacao_veiculo_cadastrado": "SEM PLACA INFORMADA",
                "status_veiculo_cadastrado": "--",
                "veiculo": None,
                "match": False
            }

        with self.lock:
            veh = self.vehicles_by_plate.get(p_clean)

        if veh:
            situacao = str(veh.get("situacao") or "ATIVO").strip().upper()
            status = str(veh.get("status") or "--").strip()
            return {
                "plate_clean": p_clean,
                "plate_cadastrada": True,
                "situacao_veiculo_cadastrado": situacao,
                "status_veiculo_cadastrado": status,
                "tipo": veh.get("tipo"),
                "sub_tipo": veh.get("subTipo"),
                "tipo_op": veh.get("tipoOp"),
                "marca": veh.get("marca"),
                "locadora": veh.get("locadora"),
                "regional": veh.get("regional"),
                "turno": veh.get("turno"),
                "veiculo": veh,
                "match": True
            }
        else:
            return {
                "plate_clean": p_clean,
                "plate_cadastrada": False,
                "situacao_veiculo_cadastrado": "NÃO CADASTRADO",
                "status_veiculo_cadastrado": "--",
                "veiculo": None,
                "match": False
            }

    def get_all_vehicles(self) -> list:
        """Retorna todos os veículos conhecidos."""
        with self.lock:
            return list(self.vehicles_list)

    def get_summary(self) -> dict:
        """Retorna o resumo estatístico do inventário de frotas."""
        with self.lock:
            total = len(self.vehicles_list)
            situacoes = {}
            regionais = {}
            for v in self.vehicles_list:
                s = str(v.get("situacao", "OUTROS")).upper()
                situacoes[s] = situacoes.get(s, 0) + 1
                reg = str(v.get("regional", "OUTRAS"))
                regionais[reg] = regionais.get(reg, 0) + 1

            return {
                "total_vehicles": total,
                "last_sync_time": self.last_sync_time,
                "status": self.last_sync_status,
                "error": self.last_error,
                "by_situacao": situacoes,
                "by_regional": regionais
            }


# Instância Singleton
fleet_client = FleetClient()
