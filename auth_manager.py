"""
Auth Manager - Sistema Corporativo de Autenticação, Criptografia e RBAC (Zero-Knowledge)
Suporta 4 perfis estritos de acesso: Supervisor, Coordenador, Gerente e Administrador.
Gerencia usuário master 'administrado', troca obrigatória de senha e importação do Fleet.
"""

import os
import re
import json
import time
import uuid
import hmac
import hashlib
import secrets
from datetime import datetime

# Segredo de assinatura de tokens de sessão (E2EE)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "alpitel-cco-secret-auth-key-2026")
LOCAL_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_users.json")
LOCAL_ACCESS_REQUESTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_access_requests.json")
FLEET_SALT = "alpitel_fleet_salt_2026"

VALID_ROLES = ["operador_cco", "supervisor", "coordenador", "gerente", "administrador"]

def format_as_uuid(raw_id: str) -> str:
    """Garante que qualquer identificador de usuário seja um UUID válido com hífens exigido pelo PostgreSQL."""
    if not raw_id:
        return str(uuid.uuid4())
    raw_str = str(raw_id).strip()
    try:
        return str(uuid.UUID(raw_str))
    except Exception:
        pass
    if len(raw_str) == 32:
        try:
            return str(uuid.UUID(hex=raw_str))
        except Exception:
            pass
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, raw_str))

def normalize_role(role_name: str) -> str:
    """Normaliza o nome do perfil RBAC para a chave interna da aplicação."""
    r = str(role_name or "supervisor").strip().lower()
    if r in ["admin", "administrador"]:
        return "administrador"
    elif r == "gerente":
        return "gerente"
    elif r == "coordenador":
        return "coordenador"
    elif r in ["operador", "operador_cco", "operator"]:
        return "operador_cco"
    elif r == "supervisor":
        return "supervisor"
    return "supervisor"

def map_role_for_supabase(role_name: str) -> str:
    """Mapeia o perfil para os valores aceitos pela check constraint de system_users no Supabase."""
    r = normalize_role(role_name)
    if r in ["administrador", "gerente"]:
        return "admin"
    elif r in ["coordenador", "supervisor"]:
        return "supervisor"
    elif r == "operador_cco":
        return "operator"
    return "supervisor"

def map_status_for_supabase(status_name: str) -> str:
    """Mapeia o status da aplicação para a check constraint de system_users no Supabase."""
    s = str(status_name or "ativo").strip().lower()
    if s in ["ativo", "approved", "active"]:
        return "approved"
    elif s in ["inativo", "rejected"]:
        return "rejected"
    elif s in ["pendente", "pending"]:
        return "pending"
    return "approved"

def hash_password_pbkdf2(password: str) -> str:
    """Gera hash criptográfico seguro com salt aleatório usando PBKDF2-HMAC-SHA256 (100.000 iterações)."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"

def hash_password_fleet(password: str) -> str:
    """Gera hash compatível com padrão Web Crypto do sistema Fleet (SHA-256 com salt fixo)."""
    msg = (str(password) + FLEET_SALT).encode('utf-8')
    h = hashlib.sha256(msg).hexdigest()
    return f"sha256:{h}"

def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Verifica senha com suporte a PBKDF2, SHA-256 Fleet e texto provisório."""
    if not plain_password or not stored_hash:
        return False
    
    plain_password = str(plain_password).strip()
    stored_hash = str(stored_hash).strip()

    # 1. PBKDF2-HMAC-SHA256 padrão
    if stored_hash.startswith("pbkdf2:sha256:"):
        try:
            parts = stored_hash.split('$')
            if len(parts) == 3:
                iterations = int(parts[0].split(':')[2])
                salt = parts[1]
                stored_key = parts[2]
                computed = hashlib.pbkdf2_hmac(
                    'sha256',
                    plain_password.encode('utf-8'),
                    salt.encode('utf-8'),
                    iterations
                ).hex()
                return hmac.compare_digest(stored_key, computed)
        except Exception:
            pass

    # 2. SHA-256 padrão Fleet
    if stored_hash.startswith("sha256:"):
        expected = hash_password_fleet(plain_password)
        if hmac.compare_digest(stored_hash.lower(), expected.lower()):
            return True

    # 3. Comparação com senha provisória de fallback
    if plain_password == stored_hash:
        return True

    return False

def generate_session_token(user_id: str, role: str, email: str, matricula: str, nome: str, username: str) -> str:
    """Gera um token de sessão assinado com HMAC-SHA256 e expiração de 24 horas."""
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "matricula": matricula,
        "nome": nome,
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + (24 * 3600)
    }
    payload_str = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
    token = f"{payload_str.encode('utf-8').hex()}.{signature}"
    return token

def verify_session_token(token: str):
    """Valida a integridade, expiração e assinatura criptográfica do token de sessão."""
    if not token or '.' not in token:
        return None
    try:
        hex_payload, signature = token.split('.', 1)
        payload_str = bytes.fromhex(hex_payload).decode('utf-8')
        expected_sig = hmac.new(SESSION_SECRET.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
        
        if not hmac.compare_digest(expected_sig, signature):
            return None
        
        payload = json.loads(payload_str)
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


class AuthManager:
    def __init__(self):
        self.users = {}
        self.access_requests = {}
        self._load_local_users()
        self._load_access_requests()
        self._ensure_built_in_admin()
        self._sync_with_supabase()
        self._sync_access_requests_from_cloud()

    def _ensure_built_in_admin(self):
        """Garante a existência do usuário mestre obrigatório 'administrado' com acesso irrestrito."""
        admin_id = "00000000-0000-0000-0000-000000000001"
        admin_user = self.users.get(admin_id) or {}
        
        # O usuário master 'administrado' nunca pode ter seu perfil rebaixado ou ser excluído
        self.users[admin_id] = {
            "id": admin_id,
            "nome": "ADMINISTRADOR GERAL",
            "email": "admin@alpitelbrasil.com.br",
            "username": "administrado",
            "matricula": "BR0000000000",
            "password_hash": admin_user.get("password_hash") or hash_password_pbkdf2("Tim@3021"),
            "role": "administrador",
            "status": "ativo",
            "precisa_trocar_senha": False,
            "is_master": True,
            "created_at": admin_user.get("created_at") or datetime.now().isoformat(),
            "last_login": admin_user.get("last_login")
        }
        self._save_local_users()

    def _load_local_users(self):
        """Carrega usuários persistidos no cache JSON local (apenas base oficial CCO, descartando legados do Fleet)."""
        if os.path.exists(LOCAL_USERS_FILE):
            try:
                with open(LOCAL_USERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        cleaned = {}
                        for k, v in data.items():
                            k_str = str(k)
                            # Descarta cadastros antigos importados do Fleet com IDs numéricos longos
                            if v.get("origem") in ["importado_fleet", "fleet"] or (k_str.isdigit() and len(k_str) > 10):
                                continue

                            # Normaliza role legada se necessário
                            r = str(v.get("role") or "").lower()
                            if r in ["admin", "administrador"]:
                                v["role"] = "administrador"
                            elif r in ["gerente"]:
                                v["role"] = "gerente"
                            elif r in ["coordenador"]:
                                v["role"] = "coordenador"
                            elif r in ["supervisor", "operator"]:
                                v["role"] = "supervisor"
                            else:
                                v["role"] = "supervisor"
                            
                            # Normaliza status
                            if v.get("status") in ["approved", "active", "ativo"]:
                                v["status"] = "ativo"
                            elif v.get("status") in ["inativo", "rejected"]:
                                v["status"] = "inativo"
                            else:
                                v["status"] = "ativo"

                            u_uuid = format_as_uuid(v.get("id") or k_str)
                            v["id"] = u_uuid
                            cleaned[u_uuid] = v
                        self.users = cleaned
            except Exception as e:
                print(f"[AUTH] Falha ao carregar cache local de usuários: {e}")

    def _save_local_users(self):
        """Salva usuários no arquivo JSON local de backup."""
        try:
            with open(LOCAL_USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AUTH] Falha ao salvar cache local de usuários: {e}")

    def _load_access_requests(self):
        """Carrega as solicitações de acesso de colaboradores pendentes/históricas."""
        if os.path.exists(LOCAL_ACCESS_REQUESTS_FILE):
            try:
                with open(LOCAL_ACCESS_REQUESTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.access_requests = data
            except Exception as e:
                print(f"[AUTH] Falha ao carregar solicitações de acesso: {e}")

    def _save_access_requests(self):
        """Persiste as solicitações de acesso no arquivo JSON local."""
        try:
            with open(LOCAL_ACCESS_REQUESTS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.access_requests, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AUTH] Falha ao salvar solicitações de acesso: {e}")

    def _push_user_to_supabase(self, user_dict: dict) -> bool:
        """
        Persiste o usuário no Supabase respeitando estritamente o schema do PostgreSQL:
        1. ID formatado como UUID válido com hífens
        2. Status mapeado para 'approved' / 'rejected' / 'pending'
        3. Role mapeada para 'admin' / 'supervisor' / 'operator'
        4. Metadados ricos (role real, regional, setor, telefone, precisa_trocar_senha) persistidos em system_commands
        """
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests

            u_id = format_as_uuid(user_dict.get("id"))
            user_dict["id"] = u_id

            clean_row = {
                "id": u_id,
                "nome": str(user_dict.get("nome") or "COLABORADOR").strip().upper(),
                "email": str(user_dict.get("email") or "").strip().lower(),
                "matricula": str(user_dict.get("matricula") or "").strip().upper(),
                "password_hash": str(user_dict.get("password_hash") or ""),
                "role": map_role_for_supabase(user_dict.get("role")),
                "status": map_status_for_supabase(user_dict.get("status")),
                "created_at": user_dict.get("created_at") or datetime.now().isoformat(),
                "last_login": user_dict.get("last_login")
            }

            resp = requests.post(f"{BASE_REST_URL}/system_users?on_conflict=email", headers=get_headers(), json=clean_row, timeout=5)

            # Persiste os metadados ricos em system_commands (JSONB)
            meta_payload = {
                "user_id": u_id,
                "email": clean_row["email"],
                "role": normalize_role(user_dict.get("role")),
                "regional": str(user_dict.get("regional") or "Global").strip(),
                "setor": str(user_dict.get("setor") or "Operações CCO").strip(),
                "telefone": str(user_dict.get("telefone") or "").strip(),
                "username": str(user_dict.get("username") or clean_row["email"].split("@")[0]).strip(),
                "precisa_trocar_senha": bool(user_dict.get("precisa_trocar_senha", False)),
                "updated_at": datetime.now().isoformat()
            }
            meta_cmd_id = str(uuid.uuid5(uuid.NAMESPACE_OID, f"meta_{u_id}"))
            requests.post(f"{BASE_REST_URL}/system_commands?on_conflict=id", headers=get_headers(), json={
                "id": meta_cmd_id,
                "command": "USER_METADATA",
                "status": "COMPLETED",
                "payload": meta_payload,
                "result": {"synced": True}
            }, timeout=5)

            return resp.status_code in [200, 201]
        except Exception as e:
            print(f"[AUTH] Falha ao persistir usuário no Supabase: {e}")
            return False

    def _sync_with_supabase(self):
        """Sincroniza usuários com a tabela 'system_users' e hidrata metadados do Supabase."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests

            # 1. Carrega metadados ricos de system_commands (role granular, regional, setor, etc.)
            user_meta_map = {}
            try:
                resp_meta = requests.get(f"{BASE_REST_URL}/system_commands?command=eq.USER_METADATA&limit=300", headers=get_headers(), timeout=5)
                if resp_meta.status_code == 200:
                    for c in resp_meta.json() or []:
                        p = c.get("payload") or {}
                        uid = p.get("user_id")
                        em = str(p.get("email") or "").lower()
                        if uid:
                            user_meta_map[str(uid)] = p
                        if em:
                            user_meta_map[em] = p
            except Exception:
                pass

            # 2. Carrega usuários da tabela oficial system_users
            endpoint = f"{BASE_REST_URL}/system_users?select=*"
            resp = requests.get(endpoint, headers=get_headers(), timeout=5)
            if resp.status_code == 200:
                cloud_users = resp.json()
                if isinstance(cloud_users, list) and len(cloud_users) > 0:
                    for u in cloud_users:
                        uid = u.get("id")
                        if not uid:
                            continue
                        uid_str = format_as_uuid(uid)
                        u["id"] = uid_str

                        # Usuários pendentes pertencem à fila de solicitações e não aos usuários ativos
                        if u.get("status") in ["pending", "pendente"]:
                            continue

                        # Hidrata metadados ricos se existirem
                        meta = user_meta_map.get(uid_str) or user_meta_map.get(str(u.get("email") or "").lower()) or {}

                        # Converte role de volta para o perfil exato
                        if meta.get("role"):
                            u["role"] = normalize_role(meta["role"])
                        else:
                            r = str(u.get("role") or "").lower()
                            if r in ["admin", "administrador"]:
                                u["role"] = "administrador"
                            elif r in ["operator", "operador_cco"]:
                                u["role"] = "operador_cco"
                            else:
                                u["role"] = "supervisor"

                        u["regional"] = meta.get("regional") or u.get("regional") or "Global"
                        u["setor"] = meta.get("setor") or u.get("setor") or "Operações CCO"
                        u["telefone"] = meta.get("telefone") or u.get("telefone") or ""
                        if "precisa_trocar_senha" in meta:
                            u["precisa_trocar_senha"] = bool(meta["precisa_trocar_senha"])
                        elif "precisa_trocar_senha" not in u:
                            u["precisa_trocar_senha"] = False

                        # Normaliza status para padrão interno
                        if u.get("status") in ["approved", "active", "ativo"]:
                            u["status"] = "ativo"
                        else:
                            u["status"] = "inativo"

                        if uid_str == "00000000-0000-0000-0000-000000000001":
                            u["username"] = "administrado"
                            u["is_master"] = True
                            u["role"] = "administrador"
                            u["status"] = "ativo"

                        if not u.get("username"):
                            if meta.get("username"):
                                u["username"] = meta["username"]
                            elif u.get("email"):
                                u["username"] = u["email"].split("@")[0].lower()
                            elif u.get("matricula"):
                                u["username"] = u["matricula"].lower()

                        # Deduplicação preventiva contra duplicatas na nuvem
                        dup_key, existing_local = self._find_duplicate_user(
                            email=u.get("email"),
                            matricula=u.get("matricula"),
                            nome=u.get("nome"),
                            exclude_user_id=uid_str
                        )
                        if existing_local:
                            if str(dup_key).replace('-', '').lower() == uid_str.replace('-', '').lower():
                                # É o mesmo usuário com chave UUID unificada
                                self.users[uid_str] = u
                                continue
                            print(f"[AUTH] Duplicata detectada no Supabase ({uid_str} vs {dup_key} para {u.get('nome')}). Purgando {uid_str}...")
                            try:
                                requests.delete(f"{BASE_REST_URL}/system_users?id=eq.{uid_str}", headers=get_headers(), timeout=5)
                            except Exception:
                                pass
                            continue

                        self.users[uid_str] = u
                    self._save_local_users()

            # 3. Garante que todos os colaboradores legítimos locais estejam persistidos no Supabase
            for uid_local, u_data in list(self.users.items()):
                self._push_user_to_supabase(u_data)
        except Exception as e:
            print(f"[AUTH] Aviso sincronização Supabase: {e}")

    def _find_user(self, identifier):
        """
        Busca flexível e resiliente de usuário no cache por:
        1. ID exato (string ou int)
        2. E-mail corporativo (case-insensitive)
        3. Username ou Login (case-insensitive)
        4. Matrícula (case-insensitive)
        5. Nome completo (case-insensitive)
        Retorna (key, user_dict) ou (None, None).
        """
        if identifier is None:
            return None, None

        id_str = str(identifier).strip()
        if not id_str:
            return None, None

        # 1. Busca direta por chave string
        if id_str in self.users:
            return id_str, self.users[id_str]

        # 2. Busca por chave inteira (se aplicável)
        if id_str.isdigit():
            id_int = int(id_str)
            if id_int in self.users:
                return id_int, self.users[id_int]

        # 3. Busca iterativa abrangente
        id_lower = id_str.lower()
        id_upper = id_str.upper()

        for k, u in self.users.items():
            if not isinstance(u, dict):
                continue
            u_id = str(u.get("id") or "").strip()
            u_email = str(u.get("email") or "").strip().lower()
            u_username = str(u.get("username") or "").strip().lower()
            u_login = str(u.get("login") or "").strip().lower()
            u_mat = str(u.get("matricula") or "").strip().upper()
            u_nome = str(u.get("nome") or "").strip().upper()

            if (u.get("is_master") or u_id == "00000000-0000-0000-0000-000000000001") and id_lower in ["administrado", "admin"]:
                return k, u

            if u_id == id_str:
                return k, u
            if u_email and u_email == id_lower:
                return k, u
            if u_username and u_username == id_lower:
                return k, u
            if u_login and u_login == id_lower:
                return k, u
            if u_mat and u_mat == id_upper:
                return k, u
            if u_nome and u_nome == id_upper:
                return k, u

        return None, None

    def _find_duplicate_user(self, email: str = None, matricula: str = None, username: str = None, nome: str = None, exclude_user_id: str = None):
        """
        Verifica com rigor se já existe algum usuário no sistema com dados coincidentes:
        - E-mail corporativo (case-insensitive)
        - Matrícula (case-insensitive)
        - Login / Username (case-insensitive)
        - Nome completo idêntico (case-insensitive, quando contiver nome e sobrenome)
        Desconsidera o ID fornecido em exclude_user_id (essencial para edição).
        Retorna (user_id, user_dict) ou (None, None).
        """
        excl_str = str(exclude_user_id).strip() if exclude_user_id else None

        email_clean = str(email or "").strip().lower()
        mat_clean = str(matricula or "").strip().upper()
        user_clean = str(username or "").strip().lower()
        nome_clean = " ".join(str(nome or "").strip().upper().split())

        for uid, u in self.users.items():
            if not isinstance(u, dict):
                continue
            uid_str = str(uid).strip()
            u_id_field = str(u.get("id") or "").strip()

            if excl_str:
                excl_norm = excl_str.replace('-', '').lower()
                if uid_str.replace('-', '').lower() == excl_norm or u_id_field.replace('-', '').lower() == excl_norm:
                    continue

            u_email = str(u.get("email") or "").strip().lower()
            u_mat = str(u.get("matricula") or "").strip().upper()
            u_user = str(u.get("username") or u.get("login") or "").strip().lower()
            u_nome = " ".join(str(u.get("nome") or "").strip().upper().split())

            # 1. Checagem por e-mail
            if email_clean and u_email and email_clean == u_email:
                return uid_str, u

            # 2. Checagem por matrícula
            if mat_clean and u_mat and mat_clean == u_mat:
                return uid_str, u

            # 3. Checagem por login/username
            if user_clean and u_user and user_clean == u_user:
                return uid_str, u

            # 4. Checagem por nome completo idêntico
            if nome_clean and u_nome and len(nome_clean.split()) >= 2 and nome_clean == u_nome:
                return uid_str, u

        return None, None

    def authenticate(self, login_identifier: str, password: str) -> dict:
        """
        Autentica o usuário por Usuário, E-mail ou Matrícula e Senha.
        Reconhece o usuário mestre 'administrado' com a senha 'Tim@3021'.
        """
        raw_id = (login_identifier or "").strip()
        login_clean = raw_id.lower()
        mat_clean = raw_id.upper()
        pwd_clean = (password or "").strip()

        if not raw_id or not pwd_clean:
            return {"status": "error", "message": "Informe o usuário e a senha."}

        # 1. Login Mestre Direto do Administrador ('administrado' ou 'admin')
        is_admin_id = login_clean in ["administrado", "admin", "admin@alpitelbrasil.com.br"] or mat_clean in ["ADMIN", "BR0000000000"]
        if is_admin_id and pwd_clean == "Tim@3021":
            admin_user = self.users.get("00000000-0000-0000-0000-000000000001")
            if not admin_user:
                self._ensure_built_in_admin()
                admin_user = self.users["00000000-0000-0000-0000-000000000001"]
            
            admin_user["last_login"] = datetime.now().isoformat()
            self._save_local_users()

            token = generate_session_token(
                admin_user["id"], 
                "administrador", 
                admin_user["email"], 
                admin_user.get("matricula", "BR0000000000"),
                admin_user["nome"],
                admin_user.get("username", "administrado")
            )
            return {
                "status": "success",
                "message": "Autenticado com sucesso como Administrador!",
                "token": token,
                "user": {
                    "id": admin_user["id"],
                    "nome": admin_user["nome"],
                    "username": admin_user.get("username", "administrado"),
                    "email": admin_user["email"],
                    "role": "administrador",
                    "status": "ativo",
                    "precisa_trocar_senha": False
                }
            }

        # 2. Busca entre todos os usuários registrados de forma resiliente
        k, matched_user = self._find_user(raw_id)

        if not matched_user:
            return {"status": "error", "message": "Usuário não encontrado. Verifique seu login ou e-mail."}

        # Verificar se está inativo
        if str(matched_user.get("status") or "").lower() == "inativo":
            return {"status": "error", "message": "Este usuário está inativo no sistema. Procure a Administração."}

        # Verificar senha
        stored_hash = matched_user.get("password_hash") or matched_user.get("senha") or ""
        precisa_trocar = bool(matched_user.get("precisa_trocar_senha", False))
        
        # Se o usuário está com flag de troca obrigatória ativa e digitar a senha provisória padrão 'Alpitel@2026', aceita diretamente
        is_temp_alpitel = precisa_trocar and pwd_clean == "Alpitel@2026"
        is_pwd_valid = is_temp_alpitel or verify_password(pwd_clean, stored_hash)

        if not is_pwd_valid:
            return {"status": "error", "message": "Senha incorreta. Verifique os dados digitados."}

        # Atualiza último login
        matched_user["last_login"] = datetime.now().isoformat()
        self._save_local_users()

        role = str(matched_user.get("role") or "supervisor").lower()
        if role not in VALID_ROLES:
            role = "supervisor"

        token = generate_session_token(
            str(matched_user["id"]),
            role,
            matched_user.get("email", ""),
            matched_user.get("matricula", ""),
            matched_user.get("nome", "Colaborador"),
            matched_user.get("username", matched_user.get("login", ""))
        )

        return {
            "status": "success",
            "message": f"Bem-vindo(a), {matched_user.get('nome')}!",
            "token": token,
            "precisa_trocar_senha": precisa_trocar,
            "user": {
                "id": str(matched_user["id"]),
                "nome": matched_user.get("nome"),
                "username": matched_user.get("username") or matched_user.get("login") or matched_user.get("email"),
                "email": matched_user.get("email"),
                "matricula": matched_user.get("matricula"),
                "role": role,
                "status": matched_user.get("status", "ativo"),
                "precisa_trocar_senha": precisa_trocar
            }
        }

    def change_password(self, user_id: str, new_password: str) -> dict:
        """Altera a senha de um usuário autenticado e remove o flag de troca obrigatória."""
        k, u = self._find_user(user_id)
        if not u:
            return {"status": "error", "message": "Usuário não localizado para alteração de senha."}

        new_password = str(new_password or "").strip()
        if len(new_password) < 6:
            return {"status": "error", "message": "A nova senha deve ter no mínimo 6 caracteres."}

        u["password_hash"] = hash_password_pbkdf2(new_password)
        u["precisa_trocar_senha"] = False
        u["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        # Atualiza no Supabase interno se couber (UUIDs)
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{u.get('id')}", headers=get_headers(), json={
                "password_hash": u["password_hash"],
                "precisa_trocar_senha": False,
                "updated_at": u["updated_at"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": "Senha atualizada com sucesso! Acesso integral liberado."
        }

    def set_temporary_password(self, target_user_id: str, temp_password: str, operator_user: dict) -> dict:
        """Permite a um Administrador ou Gerente definir uma senha provisória com troca obrigatória."""
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Gerentes ou Administradores podem emitir senhas provisórias."}

        k, target = self._find_user(target_user_id)
        if not target:
            return {"status": "error", "message": f"Usuário '{target_user_id}' não encontrado."}

        # Gerente não pode alterar senha de Administrador
        if op_role == "gerente" and target.get("role") == "administrador":
            return {"status": "error", "message": "Gerente não possui permissão para redefinir senha de Administrador."}

        temp_password = str(temp_password or "Alpitel@2026").strip()
        if len(temp_password) < 6:
            return {"status": "error", "message": "A senha provisória deve conter no mínimo 6 caracteres."}

        target["password_hash"] = hash_password_pbkdf2(temp_password)
        target["precisa_trocar_senha"] = True
        target["updated_at"] = datetime.now().isoformat()
        target["senha_alterada_por"] = operator_user.get("nome", "Gestor")
        self._save_local_users()

        # Tenta atualizar no Supabase interno
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target.get('id')}", headers=get_headers(), json={
                "password_hash": target["password_hash"],
                "precisa_trocar_senha": True,
                "updated_at": target["updated_at"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Senha provisória definida com sucesso para {target.get('nome')}! A troca de senha será exigida no primeiro acesso."
        }

    def update_user_role(self, target_user_id: str, new_role: str, operator_user: dict) -> dict:
        """Altera o perfil RBAC de um usuário (Apenas Administrador)."""
        op_role = str(operator_user.get("role") or "").lower()
        if op_role != "administrador":
            return {"status": "error", "message": "Apenas o Administrador pode alterar o perfil de acesso de usuários."}

        new_role = str(new_role or "").lower()
        if new_role not in VALID_ROLES:
            return {"status": "error", "message": f"Perfil inválido. Perfis permitidos: {', '.join(VALID_ROLES)}."}

        k, target = self._find_user(target_user_id)
        if not target:
            return {"status": "error", "message": "Usuário não localizado."}

        # Proteção do Administrador Master 'administrado'
        if target.get("is_master") or target.get("username") == "administrado" or str(target.get("id")) == "00000000-0000-0000-0000-000000000001":
            return {"status": "error", "message": "O perfil do Administrador Master não pode ser alterado."}

        target["role"] = new_role
        target["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target.get('id')}", headers=get_headers(), json={
                "role": new_role,
                "updated_at": target["updated_at"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Perfil de {target.get('nome')} atualizado para: {new_role.upper()}!"
        }

    def update_user_status(self, target_user_id: str, new_status: str, operator_user: dict) -> dict:
        """Ativa ou inativa um usuário (Administrador e Gerente para subordinados)."""
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Acesso negado para alteração de status."}

        k, target = self._find_user(target_user_id)
        if not target:
            return {"status": "error", "message": "Usuário não localizado."}

        if target.get("is_master") or target.get("username") == "administrado" or str(target.get("id")) == "00000000-0000-0000-0000-000000000001":
            return {"status": "error", "message": "O Administrador Master não pode ser desativado."}

        new_status = "ativo" if str(new_status).lower() in ["ativo", "approved", "active"] else "inativo"
        target["status"] = new_status
        target["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target.get('id')}", headers=get_headers(), json={
                "status": new_status,
                "updated_at": target["updated_at"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Usuário {target.get('nome')} definido como {new_status.upper()}!"
        }

    def update_user(self, user_id: str, operator_user: dict, update_data: dict) -> dict:
        """
        Permite que Administradores e Gerentes editem os dados cadastrais de um colaborador.
        Sincroniza atomicamente no banco local e no Supabase em tempo real.
        """
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Gerentes e Administradores podem editar colaboradores."}

        target_key, target = self._find_user(user_id)
        if not target:
            return {"status": "error", "message": "Colaborador não localizado."}

        is_master = target.get("is_master") or str(target.get("id")) == "00000000-0000-0000-0000-000000000001" or target.get("username") == "administrado"

        # Gerente não pode alterar perfil nem dados de Administradores
        target_role = str(target.get("role") or "").lower()
        if op_role == "gerente" and (is_master or target_role == "administrador"):
            return {"status": "error", "message": "Gerente não possui permissão para editar contas de Administrador."}

        # Valida perfil pretendido
        nova_role = str(update_data.get("role") or target.get("role") or "supervisor").strip().lower()
        if nova_role not in VALID_ROLES:
            nova_role = "supervisor"

        if is_master:
            nova_role = "administrador"
            novo_status = "ativo"
        else:
            if op_role == "gerente" and nova_role == "administrador":
                return {"status": "error", "message": "Gerente não possui permissão para definir o perfil Administrador."}
            novo_status = str(update_data.get("status") or target.get("status") or "ativo").strip().lower()
            if novo_status not in ["ativo", "inativo"]:
                novo_status = "ativo"

        # Prevenção contra duplicidades ao alterar Nome, E-mail ou Matrícula
        cand_email = str(update_data.get("email") or target.get("email") or "").strip().lower()
        cand_mat = str(update_data.get("matricula") or target.get("matricula") or "").strip().upper()
        cand_nome = str(update_data.get("nome") or target.get("nome") or "").strip().upper()

        dup_id, dup_user = self._find_duplicate_user(
            email=cand_email,
            matricula=cand_mat,
            nome=cand_nome,
            exclude_user_id=target.get("id") or target_key
        )
        if dup_user:
            return {
                "status": "error",
                "message": f"Conflito de duplicidade: já existe outro colaborador registrado com estes dados: '{dup_user.get('nome')}' (Matrícula: {dup_user.get('matricula') or '--'}, E-mail: {dup_user.get('email')})."
            }

        # Atualiza campos cadastrais
        if "nome" in update_data and str(update_data["nome"]).strip():
            target["nome"] = str(update_data["nome"]).strip().upper()
        if "email" in update_data and str(update_data["email"]).strip():
            target["email"] = str(update_data["email"]).strip().lower()
        if "matricula" in update_data:
            target["matricula"] = str(update_data["matricula"]).strip().upper()
        if "telefone" in update_data:
            target["telefone"] = str(update_data["telefone"]).strip()
        if "regional" in update_data:
            target["regional"] = str(update_data["regional"]).strip()
        if "setor" in update_data:
            target["setor"] = str(update_data["setor"]).strip()

        target["role"] = nova_role
        target["status"] = novo_status
        target["updated_at"] = datetime.now().isoformat()
        target["updated_by"] = operator_user.get("nome", "Gestor")

        # Se fornecida nova senha
        nova_senha = str(update_data.get("nova_senha") or update_data.get("password") or "").strip()
        if nova_senha:
            if len(nova_senha) < 4:
                return {"status": "error", "message": "A nova senha deve ter no mínimo 4 caracteres."}
            target["password_hash"] = hash_password_pbkdf2(nova_senha)
            target["precisa_trocar_senha"] = bool(update_data.get("forcar_troca_senha", False))

        self._save_local_users()

        # Sincroniza atomicamente no Supabase
        try:
            self._push_user_to_supabase(target)
        except Exception as e:
            print(f"[AUTH] Falha ao persistir usuário editado no Supabase: {e}")

        return {
            "status": "success",
            "message": f"Dados de {target['nome']} atualizados com sucesso!",
            "user": {
                "id": target["id"],
                "nome": target["nome"],
                "email": target["email"],
                "matricula": target.get("matricula", ""),
                "role": target["role"],
                "status": target["status"],
                "regional": target.get("regional", ""),
                "setor": target.get("setor", "")
            }
        }

    def create_user(self, operator_user: dict, user_data: dict) -> dict:
        """
        Permite ao Administrador ou Gerente cadastrar diretamente um colaborador no sistema.
        Criação atômica com PBKDF2-HMAC-SHA256 e sincronização em tempo real.
        """
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Gerentes e Administradores podem cadastrar usuários."}

        nome = str(user_data.get("nome") or "").strip().upper()
        email = str(user_data.get("email") or "").strip().lower()
        matricula = str(user_data.get("matricula") or "").strip().upper()
        role = str(user_data.get("role") or "supervisor").strip().lower()
        senha = str(user_data.get("password") or user_data.get("senha") or "Alpitel@2026").strip()
        precisa_trocar = bool(user_data.get("precisa_trocar_senha", True))

        if not nome:
            return {"status": "error", "message": "Informe o Nome Completo do colaborador."}
        if not email and not matricula:
            return {"status": "error", "message": "Informe ao menos a Matrícula ou E-mail corporativo."}
        if len(senha) < 4:
            return {"status": "error", "message": "A senha deve conter no mínimo 4 caracteres."}
        if role not in VALID_ROLES:
            role = "supervisor"

        if op_role == "gerente" and role == "administrador":
            return {"status": "error", "message": "Gerente não possui permissão para cadastrar Administradores."}

        # Checa duplicidade rigorosa (E-mail, Matrícula, Login ou Nome Completo)
        username = email.split("@")[0] if "@" in email else matricula.lower()
        dup_id, dup_user = self._find_duplicate_user(
            email=email,
            matricula=matricula,
            username=username,
            nome=nome
        )
        if dup_user:
            return {
                "status": "error",
                "message": f"Não é permitido cadastrar colaboradores duplicados! Já existe um registro no sistema com dados coincidentes para '{dup_user.get('nome')}' (Matrícula: {dup_user.get('matricula') or '--'}, E-mail: {dup_user.get('email')}, Perfil: {str(dup_user.get('role')).upper()})."
            }

        new_uid = format_as_uuid(secrets.token_hex(16))

        novo_u = {
            "id": new_uid,
            "nome": nome,
            "email": email or f"{matricula.lower()}@alpitelbrasil.com.br",
            "username": username,
            "matricula": matricula,
            "telefone": str(user_data.get("telefone") or "").strip(),
            "regional": str(user_data.get("regional") or "").strip(),
            "setor": str(user_data.get("setor") or "").strip(),
            "password_hash": hash_password_pbkdf2(senha),
            "role": role,
            "status": "ativo",
            "precisa_trocar_senha": precisa_trocar,
            "origem": "cadastro_direto",
            "created_at": datetime.now().isoformat(),
            "created_by": operator_user.get("nome", "Gestor"),
            "last_login": None
        }

        self.users[new_uid] = novo_u
        self._save_local_users()

        # Sincroniza atomicamente no Supabase
        try:
            self._push_user_to_supabase(novo_u)
        except Exception as e:
            print(f"[AUTH] Falha ao persistir novo usuário no Supabase: {e}")

        return {
            "status": "success",
            "message": f"Colaborador {nome} ({role.upper()}) cadastrado com sucesso! Senha: '{senha}'",
            "user": novo_u
        }

    def delete_user(self, target_user_id: str, operator_user: dict) -> dict:
        """
        Exclui permanentemente o cadastro de um colaborador.
        Restrito a Administradores e Gerentes.
        Protege o Administrador Master e impede auto-exclusão.
        Sincroniza a exclusão imediatamente no Supabase e no arquivo JSON local.
        """
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Administradores e Gerentes possuem permissão para excluir colaboradores."}

        target_key, target = self._find_user(target_user_id)
        if not target:
            return {"status": "error", "message": "Colaborador não localizado."}

        # 1. Proteção absoluta do Administrador Master
        is_master = target.get("is_master") or str(target.get("id")) == "00000000-0000-0000-0000-000000000001" or target.get("username") == "administrado"
        if is_master:
            return {"status": "error", "message": "O Administrador Master não pode ser excluído."}

        # 2. Impede auto-exclusão
        op_id = str(operator_user.get("id") or "")
        target_id_str = str(target.get("id") or target_key)
        if op_id and (op_id == target_id_str or op_id == str(target_key)):
            return {"status": "error", "message": "Operação não permitida: Você não pode excluir a sua própria conta de usuário."}

        # 3. Gerente não pode excluir Administrador
        target_role = str(target.get("role") or "").lower()
        if op_role != "administrador" and target_role == "administrador":
            return {"status": "error", "message": "Gerente não possui permissão para excluir um Administrador."}

        user_nome = target.get("nome", "Colaborador")

        # 4. Remove do dicionário local e persiste
        if target_key in self.users:
            del self.users[target_key]
        if target_id_str in self.users and target_id_str != target_key:
            del self.users[target_id_str]

        self._save_local_users()

        # 5. Remove do Supabase em tempo real
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.delete(f"{BASE_REST_URL}/system_users?id=eq.{target_id_str}", headers=get_headers(), timeout=5)
        except Exception as e:
            print(f"[AUTH] Falha ao sincronizar exclusão no Supabase: {e}")

        # 6. Atualiza solicitações vinculadas se existirem
        for req in self.access_requests.values():
            if str(req.get("assigned_user_id")) == target_id_str:
                req["assigned_user_id"] = None
        self._save_access_requests()

        return {
            "status": "success",
            "message": f"Colaborador {user_nome} excluído com sucesso do sistema CCO."
        }

    def list_users(self) -> list:
        """Retorna lista pública de usuários sanitizada (Zero-Knowledge: sem hashes de senha)."""
        result = []
        for u in self.users.values():
            result.append({
                "id": u.get("id"),
                "nome": u.get("nome"),
                "email": u.get("email"),
                "username": u.get("username") or (u.get("email", "").split("@")[0] if "@" in u.get("email", "") else ""),
                "matricula": u.get("matricula"),
                "telefone": u.get("telefone"),
                "regional": u.get("regional"),
                "setor": u.get("setor"),
                "role": u.get("role", "supervisor"),
                "status": u.get("status", "ativo"),
                "precisa_trocar_senha": bool(u.get("precisa_trocar_senha", False)),
                "is_master": bool(u.get("is_master", False)),
                "created_at": u.get("created_at"),
                "last_login": u.get("last_login")
            })
        return sorted(result, key=lambda x: (
            0 if x.get("is_master") else 1,
            {"administrador": 0, "gerente": 1, "coordenador": 2, "supervisor": 3}.get(x.get("role"), 4),
            x.get("nome") or ""
        ))

    def _push_access_request_to_cloud(self, req: dict):
        """Envia solicitação para a tabela 'system_commands' no Supabase para sincronização atômica entre todos os servidores e instâncias."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            cmd_payload = dict(req)
            requests.post(f"{BASE_REST_URL}/system_commands", headers=get_headers(), json={
                "command": "ACCESS_REQUEST",
                "status": "PENDING",
                "payload": cmd_payload
            }, timeout=5)
        except Exception as e:
            print(f"[AUTH] Falha ao enviar solicitação para o Supabase: {e}")

    def _update_cloud_request_status(self, req: dict, cloud_status: str, result_dict: dict):
        """Atualiza o status de uma solicitação no Supabase (system_commands e system_users)."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            cmd_id = req.get("cloud_command_id")
            if cmd_id:
                requests.patch(f"{BASE_REST_URL}/system_commands?id=eq.{cmd_id}", headers=get_headers(), json={
                    "status": cloud_status,
                    "result": result_dict,
                    "updated_at": datetime.now().isoformat()
                }, timeout=5)
            else:
                proto = req.get("protocolo")
                if proto:
                    requests.patch(f"{BASE_REST_URL}/system_commands?payload->>protocolo=eq.{proto}", headers=get_headers(), json={
                        "status": cloud_status,
                        "result": result_dict,
                        "updated_at": datetime.now().isoformat()
                    }, timeout=5)
            
            # Se houver usuário correspondente em system_users no Supabase, atualiza status
            u_id = req.get("user_id") or req.get("id")
            if u_id:
                new_u_status = "approved" if cloud_status == "COMPLETED" else "rejected"
                requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{u_id}", headers=get_headers(), json={
                    "status": new_u_status
                }, timeout=5)
        except Exception as e:
            print(f"[AUTH] Falha ao atualizar status da solicitação na nuvem: {e}")

    def _sync_access_requests_from_cloud(self):
        """
        Sincroniza solicitações de acesso de todas as fontes:
        1. Comandos 'ACCESS_REQUEST' em 'system_commands' no Supabase
        2. Usuários com status 'pending' em 'system_users' no Supabase
        3. Usuários locais pendentes
        """
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests

            # 1. Busca solicitações registradas em system_commands
            endpoint_cmd = f"{BASE_REST_URL}/system_commands?command=eq.ACCESS_REQUEST&order=created_at.desc&limit=150"
            resp_cmd = requests.get(endpoint_cmd, headers=get_headers(), timeout=5)
            if resp_cmd.status_code == 200:
                cmds = resp_cmd.json() or []
                for c in cmds:
                    payload = c.get("payload") or {}
                    if not payload.get("nome") and not payload.get("matricula") and not payload.get("email"):
                        continue
                    cmd_id = c.get("id")
                    req_id = str(payload.get("id") or cmd_id)
                    c_status = c.get("status")

                    mapped_status = "pendente"
                    if c_status == "COMPLETED":
                        mapped_status = "aprovado"
                    elif c_status == "FAILED":
                        mapped_status = "recusado"
                    elif payload.get("status"):
                        mapped_status = payload.get("status")

                    payload["id"] = req_id
                    payload["cloud_command_id"] = cmd_id
                    payload["status"] = mapped_status
                    if not payload.get("protocolo"):
                        payload["protocolo"] = f"CCO-{str(req_id)[:8].upper()}"

                    # Se já constar localmente como aprovado/recusado, não sobrescreve com pendente
                    local_existing = self.access_requests.get(req_id)
                    if local_existing and local_existing.get("status") in ["aprovado", "recusado"] and mapped_status == "pendente":
                        continue

                    self.access_requests[req_id] = payload

            # 2. Busca usuários com status 'pending' no Supabase
            endpoint_u = f"{BASE_REST_URL}/system_users?status=eq.pending&limit=100"
            resp_u = requests.get(endpoint_u, headers=get_headers(), timeout=5)
            if resp_u.status_code == 200:
                pending_cloud_users = resp_u.json() or []
                for pu in pending_cloud_users:
                    pu_id = str(pu.get("id"))
                    pu_email = str(pu.get("email") or "").lower()
                    pu_mat = str(pu.get("matricula") or "").upper()
                    
                    # Verifica se já está mapeado em access_requests
                    already_present = pu_id in self.access_requests or any(
                        (pu_email and r.get("email") and r.get("email").lower() == pu_email) or
                        (pu_mat and r.get("matricula") and r.get("matricula").upper() == pu_mat)
                        for r in self.access_requests.values()
                    )
                    if not already_present:
                        proto = f"CCO-PEND-{pu_mat[-6:] if len(pu_mat) >= 6 else pu_id[:6].upper()}"
                        self.access_requests[pu_id] = {
                            "id": pu_id,
                            "protocolo": proto,
                            "nome": pu.get("nome", "COLABORADOR"),
                            "email": pu.get("email", ""),
                            "matricula": pu_mat,
                            "role": pu.get("role", "supervisor"),
                            "regional": pu.get("regional", "Global"),
                            "setor": pu.get("setor", "Operações"),
                            "telefone": pu.get("telefone", ""),
                            "justificativa": "Colaborador aguardando liberação de acesso pelo gestor",
                            "tipo": "NOVO_COLABORADOR",
                            "status": "pendente",
                            "user_id": pu_id,
                            "created_at": pu.get("created_at") or datetime.now().isoformat()
                        }

            # 3. Varre self.users por pendentes locais
            for uid, u in self.users.items():
                if u.get("status") in ["pending", "pendente"]:
                    uid_str = str(uid)
                    u_email = str(u.get("email") or "").lower()
                    u_mat = str(u.get("matricula") or "").upper()
                    already_present = uid_str in self.access_requests or any(
                        (u_email and r.get("email") and r.get("email").lower() == u_email) or
                        (u_mat and r.get("matricula") and r.get("matricula").upper() == u_mat)
                        for r in self.access_requests.values()
                    )
                    if not already_present:
                        proto = f"CCO-PEND-{u_mat[-6:] if len(u_mat) >= 6 else uid_str[:6].upper()}"
                        self.access_requests[uid_str] = {
                            "id": uid_str,
                            "protocolo": proto,
                            "nome": u.get("nome", "COLABORADOR"),
                            "email": u.get("email", ""),
                            "matricula": u_mat,
                            "role": u.get("role", "supervisor"),
                            "regional": u.get("regional", "Global"),
                            "setor": u.get("setor", "Operações"),
                            "telefone": u.get("telefone", ""),
                            "justificativa": "Colaborador com cadastro pendente de aprovação",
                            "tipo": "NOVO_COLABORADOR",
                            "status": "pendente",
                            "user_id": uid_str,
                            "created_at": u.get("created_at") or datetime.now().isoformat()
                        }

            # 4. Auto-cura: Verifica solicitações com status 'aprovado'. Se o colaborador não estiver em self.users ou ativo, cria/recupera
            for req_id, req in list(self.access_requests.items()):
                if req.get("status") == "aprovado":
                    matched_k, matched_u = self._find_duplicate_user(
                        email=req.get("email"),
                        matricula=req.get("matricula"),
                        nome=req.get("nome")
                    )
                    if not matched_u and req.get("user_id"):
                        matched_k, matched_u = self._find_user(req["user_id"])
                    
                    if not matched_u:
                        new_u_id = format_as_uuid(req.get("assigned_user_id") or req.get("user_id") or req.get("id"))
                        final_r = normalize_role(req.get("assigned_role") or req.get("role") or "supervisor")
                        novo_u = {
                            "id": new_u_id,
                            "nome": str(req.get("nome") or "COLABORADOR").strip().upper(),
                            "email": str(req.get("email") or "").strip().lower(),
                            "username": str(req.get("email") or "").split("@")[0].lower() if "@" in str(req.get("email") or "") else str(req.get("matricula") or "").lower(),
                            "matricula": str(req.get("matricula") or "").strip().upper(),
                            "telefone": str(req.get("telefone") or "").strip(),
                            "regional": str(req.get("regional") or "Global").strip(),
                            "setor": str(req.get("setor") or "Operações CCO").strip(),
                            "password_hash": hash_password_pbkdf2("Alpitel@2026"),
                            "role": final_r,
                            "status": "ativo",
                            "precisa_trocar_senha": True,
                            "origem": "auto_cura_solicitacao",
                            "created_at": req.get("created_at") or datetime.now().isoformat(),
                            "aprovado_por": req.get("approved_by") or "Gestor CCO",
                            "aprovado_em": req.get("approved_at") or datetime.now().isoformat(),
                            "last_login": None
                        }
                        self.users[new_u_id] = novo_u
                        req["assigned_user_id"] = new_u_id
                        self._save_local_users()
                        self._push_user_to_supabase(novo_u)
                    elif not req.get("assigned_user_id"):
                        req["assigned_user_id"] = str(matched_u.get("id"))

            self._save_access_requests()
        except Exception as e:
            print(f"[AUTH] Falha ao sincronizar solicitações com a nuvem: {e}")

    def request_access(self, nome: str, email: str, matricula: str, role: str = "supervisor",
                       regional: str = "", setor: str = "", telefone: str = "", justificativa: str = "") -> dict:
        """
        Registra uma solicitação de acesso para colaborador (novo ou já cadastrado na base Fleet).
        Cria protocolo único e armazena na nuvem (Supabase) e local para aprovação de Gerentes/Administradores.
        """
        nome_clean = str(nome or "").strip().upper()
        email_clean = str(email or "").strip().lower()
        mat_clean = str(matricula or "").strip().upper()
        role_clean = str(role or "supervisor").strip().lower()
        if role_clean not in ["operador_cco", "supervisor", "coordenador", "gerente"]:
            role_clean = "supervisor"

        if not nome_clean:
            return {"status": "error", "message": "Informe o Nome Completo do colaborador."}
        if not email_clean and not mat_clean:
            return {"status": "error", "message": "Informe ao menos a Matrícula ou o E-mail corporativo."}

        # 1. Carrega dados mais recentes da nuvem e do disco antes de validar
        self._load_access_requests()

        # 2. Checa se o colaborador já possui cadastro no sistema
        existing_uid, existing_user = self._find_duplicate_user(
            email=email_clean,
            matricula=mat_clean,
            nome=nome_clean
        )

        # 3. Checa se já existe solicitação pendente para esse e-mail, matrícula ou nome completo
        for req in self.access_requests.values():
            if req.get("status") == "pendente":
                req_email = str(req.get("email") or "").lower()
                req_mat = str(req.get("matricula") or "").upper()
                req_nome = " ".join(str(req.get("nome") or "").upper().split())
                if (email_clean and email_clean == req_email) or (mat_clean and mat_clean == req_mat) or (nome_clean and len(nome_clean.split()) >= 2 and nome_clean == req_nome):
                    return {
                        "status": "pending_exists",
                        "protocolo": req.get("protocolo"),
                        "message": f"Já existe uma solicitação pendente de análise para este colaborador sob o Protocolo #{req.get('protocolo')}."
                    }

        # 4. Define o tipo e mensagem da solicitação
        if existing_user:
            tipo_solicitacao = "REDEFINICAO_SENHA"
            msg_feedback = "Solicitação de redefinição de senha registrada com sucesso! O Gerente ou Administrador CCO foi notificado para gerar uma nova senha provisória."
        else:
            tipo_solicitacao = "NOVO_COLABORADOR"
            msg_feedback = "Solicitação de acesso registrada com sucesso! O Gerente ou Administrador CCO avaliará o pedido para liberação das credenciais."

        # 5. Cria protocolo único e estrutura da solicitação
        req_id = secrets.token_hex(16)
        date_str = datetime.now().strftime("%Y%m%d")
        rand_suffix = secrets.token_hex(2).upper()
        protocolo = f"CCO-{date_str}-{rand_suffix}"

        nova_req = {
            "id": req_id,
            "protocolo": protocolo,
            "nome": nome_clean,
            "email": email_clean or (existing_user.get("email") if existing_user else f"{mat_clean.lower()}@alpitelbrasil.com.br"),
            "matricula": mat_clean or (existing_user.get("matricula") if existing_user else ""),
            "role": role_clean,
            "regional": str(regional or (existing_user.get("regional") if existing_user else "")).strip(),
            "setor": str(setor or (existing_user.get("setor") if existing_user else "")).strip(),
            "telefone": str(telefone or (existing_user.get("telefone") if existing_user else "")).strip(),
            "justificativa": str(justificativa or "").strip(),
            "tipo": tipo_solicitacao,
            "user_id": str(existing_user.get("id")) if existing_user else None,
            "status": "pendente",
            "created_at": datetime.now().isoformat(),
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None
        }

        self.access_requests[req_id] = nova_req
        self._save_access_requests()

        # 6. Sincroniza imediatamente com o Supabase em tempo real
        self._push_access_request_to_cloud(nova_req)

        return {
            "status": "success",
            "protocolo": protocolo,
            "message": f"{msg_feedback} Protocolo: #{protocolo}"
        }

    def list_access_requests(self, force_sync: bool = True) -> list:
        """Retorna lista de todas as solicitações de acesso (pendentes primeiro), sincronizada em tempo real com a nuvem."""
        self._load_access_requests()
        if force_sync:
            self._sync_access_requests_from_cloud()
        reqs = list(self.access_requests.values())
        return sorted(reqs, key=lambda x: (
            0 if x.get("status") == "pendente" else 1,
            x.get("created_at") or ""
        ), reverse=True)

    def approve_access_request(self, request_id: str, operator_user: dict, initial_password: str = None, assigned_role: str = None) -> dict:
        """Aprova uma solicitação de acesso e cadastra/ativa o colaborador com senha provisória sincronizada."""
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Gerentes e Administradores podem aprovar solicitações de acesso."}

        req = self.access_requests.get(request_id)
        if not req:
            self._sync_access_requests_from_cloud()
            req = self.access_requests.get(request_id)
        if not req:
            return {"status": "error", "message": "Solicitação não localizada."}
        if req.get("status") == "recusado":
            return {"status": "error", "message": "Esta solicitação foi recusada anteriormente. Para conceder acesso, o colaborador deve efetuar um novo pedido ou ser cadastrado diretamente."}

        final_role = normalize_role(str(assigned_role or req.get("role") or "supervisor").lower())
        if final_role not in VALID_ROLES:
            final_role = "supervisor"

        if op_role == "gerente" and final_role == "administrador":
            return {"status": "error", "message": "Gerente não possui permissão para aprovar acessos como Administrador."}

        temp_pwd = str(initial_password or "Alpitel@2026").strip()

        # 1. Verifica se já é um colaborador cadastrado (evita qualquer duplicidade)
        target_uid, existing_u = None, None
        if req.get("assigned_user_id"):
            target_uid, existing_u = self._find_user(req["assigned_user_id"])
        if not existing_u and req.get("user_id"):
            target_uid, existing_u = self._find_user(req["user_id"])
        if not existing_u and req.get("matricula"):
            target_uid, existing_u = self._find_user(req["matricula"])
        if not existing_u and req.get("email"):
            target_uid, existing_u = self._find_user(req["email"])
        if not existing_u:
            target_uid, existing_u = self._find_duplicate_user(
                email=req.get("email"),
                matricula=req.get("matricula"),
                nome=req.get("nome")
            )

        if existing_u:
            existing_u["password_hash"] = hash_password_pbkdf2(temp_pwd)
            existing_u["precisa_trocar_senha"] = True
            existing_u["status"] = "ativo"
            existing_u["role"] = final_role
            existing_u["aprovado_por"] = operator_user.get("nome", "Gestor")
            existing_u["aprovado_em"] = datetime.now().isoformat()
            if req.get("telefone") and not existing_u.get("telefone"):
                existing_u["telefone"] = req["telefone"]
            if req.get("regional") and not existing_u.get("regional"):
                existing_u["regional"] = req["regional"]
            if req.get("setor") and not existing_u.get("setor"):
                existing_u["setor"] = req["setor"]
            self._save_local_users()

            try:
                self._push_user_to_supabase(existing_u)
            except Exception as e:
                print(f"[AUTH] Falha ao persistir usuário aprovado no Supabase: {e}")
            user_res_id = str(existing_u.get("id"))
        else:
            new_uid = format_as_uuid(req.get("assigned_user_id") or req.get("user_id") or req.get("id") or secrets.token_hex(16))
            username = req["email"].split("@")[0] if "@" in str(req.get("email") or "") else req["matricula"].lower()
            novo_usuario = {
                "id": new_uid,
                "nome": req["nome"],
                "email": req["email"],
                "username": username,
                "matricula": req["matricula"],
                "telefone": req.get("telefone", ""),
                "regional": req.get("regional", ""),
                "setor": req.get("setor", ""),
                "password_hash": hash_password_pbkdf2(temp_pwd),
                "role": final_role,
                "status": "ativo",
                "precisa_trocar_senha": True,
                "origem": "solicitacao_aprovada",
                "created_at": datetime.now().isoformat(),
                "aprovado_por": operator_user.get("nome", "Gestor"),
                "aprovado_em": datetime.now().isoformat(),
                "last_login": None
            }
            self.users[new_uid] = novo_usuario
            self._save_local_users()

            try:
                self._push_user_to_supabase(novo_usuario)
            except Exception as e:
                print(f"[AUTH] Falha ao persistir novo usuário aprovado no Supabase: {e}")
            user_res_id = new_uid

        req["status"] = "aprovado"
        req["approved_by"] = operator_user.get("nome", "Gestor")
        req["approved_at"] = datetime.now().isoformat()
        req["assigned_user_id"] = user_res_id
        req["assigned_role"] = final_role
        self._save_access_requests()

        # Atualiza status na nuvem Supabase
        self._update_cloud_request_status(req, "COMPLETED", {
            "approved_by": operator_user.get("nome"),
            "approved_at": req["approved_at"]
        })

        return {
            "status": "success",
            "message": f"Acesso aprovado para {req['nome']} ({final_role.upper()})! Senha provisória: '{temp_pwd}' com troca obrigatória no 1º acesso.",
            "user": {
                "id": user_res_id,
                "nome": req["nome"],
                "email": req["email"],
                "role": final_role,
                "matricula": req["matricula"]
            }
        }

    def reject_access_request(self, request_id: str, reason: str, operator_user: dict) -> dict:
        """Rejeita uma solicitação de acesso com justificativa registrada e sincronizada."""
        op_role = str(operator_user.get("role") or "").lower()
        if op_role not in ["administrador", "gerente"]:
            return {"status": "error", "message": "Apenas Gerentes e Administradores podem recusar solicitações de acesso."}

        req = self.access_requests.get(request_id)
        if not req:
            self._sync_access_requests_from_cloud()
            req = self.access_requests.get(request_id)
        if not req:
            return {"status": "error", "message": "Solicitação não localizada."}
        if req.get("status") != "pendente":
            return {"status": "error", "message": f"Esta solicitação já foi {req.get('status')} anteriormente."}

        req["status"] = "recusado"
        req["rejected_by"] = operator_user.get("nome", "Gestor")
        req["rejected_at"] = datetime.now().isoformat()
        req["rejection_reason"] = str(reason or "Critérios operacionais não atendidos").strip()
        self._save_access_requests()

        # Atualiza status na nuvem Supabase
        self._update_cloud_request_status(req, "FAILED", {
            "rejected_by": operator_user.get("nome"),
            "reason": req["rejection_reason"]
        })

        return {
            "status": "success",
            "message": f"Solicitação #{req.get('protocolo')} recusada com sucesso."
        }

    def register_user(self, nome: str, email: str, matricula: str, password: str = "", role: str = "supervisor") -> dict:
        """Wrapper de compatibilidade para registro ou solicitação de usuário."""
        return self.request_access(nome=nome, email=email, matricula=matricula, role=role, justificativa="Cadastro direto via API")


auth_manager = AuthManager()
