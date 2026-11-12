"""
Auth Manager - Sistema Corporativo de Autenticação, Criptografia e RBAC (Zero-Knowledge)
Suporta 4 perfis estritos de acesso: Supervisor, Coordenador, Gerente e Administrador.
Gerencia usuário master 'administrado', troca obrigatória de senha e importação do Fleet.
"""

import os
import re
import json
import time
import hmac
import hashlib
import secrets
from datetime import datetime

# Segredo de assinatura de tokens de sessão (E2EE)
SESSION_SECRET = os.environ.get("SESSION_SECRET", "alpitel-cco-secret-auth-key-2026")
LOCAL_USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "system_users.json")
FLEET_SALT = "alpitel_fleet_salt_2026"

VALID_ROLES = ["supervisor", "coordenador", "gerente", "administrador"]

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
        self._load_local_users()
        self._ensure_built_in_admin()
        self._sync_with_supabase()

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
        """Carrega usuários persistidos no cache JSON local."""
        if os.path.exists(LOCAL_USERS_FILE):
            try:
                with open(LOCAL_USERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
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

                            self.users[k] = v
            except Exception as e:
                print(f"[AUTH] Falha ao carregar cache local de usuários: {e}")

    def _save_local_users(self):
        """Salva usuários no arquivo JSON local de backup."""
        try:
            with open(LOCAL_USERS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.users, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[AUTH] Falha ao salvar cache local de usuários: {e}")

    def _sync_with_supabase(self):
        """Sincroniza usuários com a tabela 'system_users' no Supabase."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests

            endpoint = f"{BASE_REST_URL}/system_users?select=*"
            resp = requests.get(endpoint, headers=get_headers(), timeout=5)
            if resp.status_code == 200:
                cloud_users = resp.json()
                if isinstance(cloud_users, list) and len(cloud_users) > 0:
                    for u in cloud_users:
                        uid = u.get("id")
                        if uid:
                            # Converte role legada se necessário
                            r = str(u.get("role") or "").lower()
                            if r in ["admin", "administrador"]:
                                u["role"] = "administrador"
                            elif r == "gerente":
                                u["role"] = "gerente"
                            elif r == "coordenador":
                                u["role"] = "coordenador"
                            else:
                                u["role"] = "supervisor"
                            self.users[uid] = u
                    self._save_local_users()
            # Garante que o administrador mestre esteja salvo no Supabase
            admin = self.users.get("00000000-0000-0000-0000-000000000001")
            if admin:
                try:
                    requests.post(f"{BASE_REST_URL}/system_users?on_conflict=id", headers=get_headers(), json=admin, timeout=5)
                except Exception:
                    pass
        except Exception as e:
            print(f"[AUTH] Aviso sincronização Supabase: {e}")

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

        # 2. Busca entre todos os usuários registrados
        matched_user = None
        for u in self.users.values():
            u_email = str(u.get("email") or "").lower()
            u_username = str(u.get("username") or "").lower()
            u_login = str(u.get("login") or "").lower()
            u_mat = str(u.get("matricula") or "").upper()

            if (login_clean and login_clean in [u_email, u_username, u_login]) or (mat_clean and mat_clean == u_mat):
                matched_user = u
                break

        if not matched_user:
            return {"status": "error", "message": "Usuário não encontrado. Verifique seu login ou e-mail."}

        # Verificar se está inativo
        if str(matched_user.get("status") or "").lower() == "inativo":
            return {"status": "error", "message": "Este usuário está inativo no sistema. Procure a Administração."}

        # Verificar senha
        stored_hash = matched_user.get("password_hash") or matched_user.get("senha") or ""
        is_pwd_valid = verify_password(pwd_clean, stored_hash)

        if not is_pwd_valid:
            return {"status": "error", "message": "Senha incorreta. Verifique os dados digitados."}

        # Atualiza último login
        matched_user["last_login"] = datetime.now().isoformat()
        self._save_local_users()

        role = str(matched_user.get("role") or "supervisor").lower()
        if role not in VALID_ROLES:
            role = "supervisor"

        precisa_trocar = bool(matched_user.get("precisa_trocar_senha", False))

        token = generate_session_token(
            matched_user["id"],
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
                "id": matched_user["id"],
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
        if not user_id or user_id not in self.users:
            return {"status": "error", "message": "Usuário não localizado."}

        new_password = str(new_password or "").strip()
        if len(new_password) < 6:
            return {"status": "error", "message": "A nova senha deve ter no mínimo 6 caracteres."}

        u = self.users[user_id]
        u["password_hash"] = hash_password_pbkdf2(new_password)
        u["precisa_trocar_senha"] = False
        u["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        # Atualiza no Supabase
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{user_id}", headers=get_headers(), json={
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

        if target_user_id not in self.users:
            return {"status": "error", "message": "Usuário não encontrado."}

        target = self.users[target_user_id]
        
        # Gerente não pode alterar senha de Administrador
        if op_role == "gerente" and target.get("role") == "administrador":
            return {"status": "error", "message": "Gerente não possui permissão para redefinir senha de Administrador."}

        temp_password = str(temp_password or "").strip()
        if len(temp_password) < 6:
            return {"status": "error", "message": "A senha provisória deve conter no mínimo 6 caracteres."}

        target["password_hash"] = hash_password_pbkdf2(temp_password)
        target["precisa_trocar_senha"] = True
        target["updated_at"] = datetime.now().isoformat()
        target["senha_alterada_por"] = operator_user.get("nome", "Gestor")
        self._save_local_users()

        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target_user_id}", headers=get_headers(), json={
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

        if target_user_id not in self.users:
            return {"status": "error", "message": "Usuário não localizado."}

        target = self.users[target_user_id]
        
        # Proteção do Administrador Master 'administrado'
        if target.get("is_master") or target.get("username") == "administrado" or target_user_id == "00000000-0000-0000-0000-000000000001":
            return {"status": "error", "message": "O perfil do Administrador Master não pode ser alterado."}

        target["role"] = new_role
        target["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target_user_id}", headers=get_headers(), json={
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

        if target_user_id not in self.users:
            return {"status": "error", "message": "Usuário não localizado."}

        target = self.users[target_user_id]
        if target.get("is_master") or target.get("username") == "administrado" or target_user_id == "00000000-0000-0000-0000-000000000001":
            return {"status": "error", "message": "O Administrador Master não pode ser desativado."}

        new_status = "ativo" if str(new_status).lower() in ["ativo", "approved", "active"] else "inativo"
        target["status"] = new_status
        target["updated_at"] = datetime.now().isoformat()
        self._save_local_users()

        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{target_user_id}", headers=get_headers(), json={
                "status": new_status,
                "updated_at": target["updated_at"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Usuário {target.get('nome')} definido como {new_status.upper()}!"
        }

    def import_fleet_users(self) -> dict:
        """
        Importa os 75 usuários da tabela 'usuarios' do sistema Fleet (Supabase Fleet)
        para o nosso sistema com perfis mapeados, senha provisória padrão e troca obrigatória.
        """
        import requests
        fleet_url = "https://dbamnuezlbmmxhxpxtiu.supabase.co/rest/v1/usuarios"
        fleet_headers = {
            "apikey": "sb_publishable_NArb5o1nWAQcPcen4pwzJQ_KG7Vb6hd",
            "Authorization": "Bearer sb_publishable_NArb5o1nWAQcPcen4pwzJQ_KG7Vb6hd"
        }

        try:
            resp = requests.get(fleet_url, headers=fleet_headers, timeout=10)
            if resp.status_code != 200:
                return {"status": "error", "message": f"Falha ao conectar no Fleet: HTTP {resp.status_code}"}
            
            fleet_users = resp.json() or []
            if not isinstance(fleet_users, list):
                return {"status": "error", "message": "Formato inválido de retorno do Fleet."}

            imported_count = 0
            updated_count = 0

            # Senha provisória padrão para todos os importados: Alpitel@2026
            default_temp_hash = hash_password_pbkdf2("Alpitel@2026")

            for fu in fleet_users:
                email = str(fu.get("login") or fu.get("email") or "").strip().lower()
                nome = str(fu.get("nome") or "").strip().upper()
                if not email or not nome:
                    continue

                username = email.split("@")[0] if "@" in email else email.lower()
                matricula = str(fu.get("matricula") or "").strip().upper()
                telefone = str(fu.get("telefone") or "").strip()
                regional = str(fu.get("regional") or "").strip()
                setor = str(fu.get("setor") or "").strip()

                fleet_perfil = str(fu.get("perfil") or "").strip().upper()
                # Mapeia perfil inicial compatível
                if "COORDENADOR" in fleet_perfil:
                    role = "coordenador"
                elif "GERENTE" in fleet_perfil:
                    role = "gerente"
                elif "ADMINISTRADOR" in fleet_perfil:
                    role = "administrador"
                else:
                    role = "supervisor"

                # Procura se já existe pelo e-mail ou username
                existing_uid = None
                for uid, u in self.users.items():
                    if u.get("is_master"):
                        continue
                    if (u.get("email") or "").lower() == email or (u.get("username") or "").lower() == username:
                        existing_uid = uid
                        break

                if existing_uid:
                    # Atualiza dados cadastrais sem sobrescrever senha se já personalizada
                    u = self.users[existing_uid]
                    u["nome"] = nome
                    u["matricula"] = matricula or u.get("matricula", "")
                    u["telefone"] = telefone or u.get("telefone", "")
                    u["regional"] = regional or u.get("regional", "")
                    u["setor"] = setor or u.get("setor", "")
                    updated_count += 1
                else:
                    new_id = str(fu.get("id") or secrets.token_hex(16))
                    self.users[new_id] = {
                        "id": new_id,
                        "nome": nome,
                        "email": email,
                        "username": username,
                        "matricula": matricula,
                        "telefone": telefone,
                        "regional": regional,
                        "setor": setor,
                        "password_hash": default_temp_hash,
                        "role": role,
                        "status": "ativo",
                        "precisa_trocar_senha": True,
                        "origem": "importado_fleet",
                        "created_at": datetime.now().isoformat(),
                        "last_login": None
                    }
                    imported_count += 1

            self._save_local_users()

            # Tenta sincronizar lote no Supabase em background de forma silenciosa
            try:
                from supabase_client import BASE_REST_URL, get_headers
                payload_batch = [u for u in self.users.values() if not u.get("is_master")]
                if payload_batch:
                    # Envia em blocos de até 50 registros com prefer=resolution=merge-duplicates
                    headers_upsert = get_headers().copy()
                    headers_upsert["Prefer"] = "resolution=merge-duplicates"
                    for i in range(0, len(payload_batch), 50):
                        chunk = payload_batch[i:i+50]
                        requests.post(f"{BASE_REST_URL}/system_users", headers=headers_upsert, json=chunk, timeout=5)
            except Exception:
                pass

            return {
                "status": "success",
                "message": f"Importação concluída com sucesso! {imported_count} novos usuários importados do Fleet e {updated_count} cadastros atualizados. Senha provisória padrão: 'Alpitel@2026' (com troca obrigatória no 1º login).",
                "imported": imported_count,
                "updated": updated_count,
                "total": len(self.users)
            }
        except Exception as e:
            return {"status": "error", "message": f"Erro durante a importação do Fleet: {str(e)}"}

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


auth_manager = AuthManager()
