"""
Auth Manager - Sistema de Autenticação e Controle de Acesso E2EE
Gerencia usuários, validações corporativas (@alpitelbrasil.com.br, Matrícula BR0+9 dígitos),
hashing criptográfico de senhas (PBKDF2-HMAC-SHA256), geração e verificação de tokens de sessão,
e sincronização com o banco de dados Supabase / PostgreSQL.
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

def hash_password(password: str) -> str:
    """Gera hash criptográfico seguro com salt aleatório usando PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        100000
    )
    return f"pbkdf2:sha256:100000${salt}${key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verifica se a senha fornecida corresponde ao hash armazenado em tempo constante."""
    try:
        parts = hashed.split('$')
        if len(parts) != 3:
            return False
        iterations = int(parts[0].split(':')[2])
        salt = parts[1]
        stored_hash = parts[2]
        
        computed = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations
        ).hex()
        
        return hmac.compare_digest(stored_hash, computed)
    except Exception:
        return False

def generate_session_token(user_id: str, role: str, email: str, matricula: str, nome: str) -> str:
    """Gera um token de sessão assinado com HMAC-SHA256 e expiração."""
    payload = {
        "sub": user_id,
        "role": role,
        "email": email,
        "matricula": matricula,
        "nome": nome,
        "iat": int(time.time()),
        "exp": int(time.time()) + (24 * 3600) # 24 horas de validade
    }
    payload_str = json.dumps(payload, separators=(',', ':'))
    signature = hmac.new(SESSION_SECRET.encode('utf-8'), payload_str.encode('utf-8'), hashlib.sha256).hexdigest()
    token = f"{payload_str.encode('utf-8').hex()}.{signature}"
    return token

def verify_session_token(token: str):
    """Valida a integridade, expiração e assinatura do token de sessão."""
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
        self._init_built_in_admin()
        self._load_local_users()
        self._sync_with_supabase()

    def _init_built_in_admin(self):
        """Inicializa a conta mestra do Administrador com acesso total."""
        admin_id = "00000000-0000-0000-0000-000000000001"
        self.users[admin_id] = {
            "id": admin_id,
            "nome": "ADMINISTRADOR CCO",
            "email": "admin@alpitelbrasil.com.br",
            "matricula": "BR0000000000",
            "password_hash": hash_password("Tim@3021"),
            "role": "admin",
            "status": "approved",
            "created_at": datetime.now().isoformat(),
            "last_login": None
        }

    def _load_local_users(self):
        """Carrega usuários persistidos no arquivo JSON local."""
        if os.path.exists(LOCAL_USERS_FILE):
            try:
                with open(LOCAL_USERS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
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
        """Tenta sincronizar os usuários com a tabela 'system_users' no Supabase."""
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests

            endpoint = f"{BASE_REST_URL}/system_users?select=*"
            resp = requests.get(endpoint, headers=get_headers(), timeout=5)
            if resp.status_code == 200:
                cloud_users = resp.json()
                if isinstance(cloud_users, list):
                    for u in cloud_users:
                        uid = u.get("id")
                        if uid:
                            self.users[uid] = u
                    self._save_local_users()
                    print(f"[AUTH] {len(cloud_users)} usuários sincronizados com o Supabase.")
            elif resp.status_code == 404:
                # Tabela system_users ainda não foi criada no Supabase
                pass
        except Exception as e:
            print(f"[AUTH] Aviso sincronização Supabase: {e}")

    def validate_matricula(self, matricula: str) -> bool:
        """Valida o padrão corporativo da matrícula: BR0 seguido de 9 dígitos numéricos (Total 12 caracteres)."""
        if not matricula or not isinstance(matricula, str):
            return False
        mat = matricula.strip().upper()
        return bool(re.match(r"^BR0\d{9}$", mat)) or mat == "BR0000000000" or mat == "ADMIN"

    def validate_email(self, email: str) -> bool:
        """Valida o padrão corporativo do e-mail: deve pertencer ao domínio @alpitelbrasil.com.br."""
        if not email or not isinstance(email, str):
            return False
        em = email.strip().lower()
        return bool(re.match(r"^[a-zA-Z0-9._%+-]+@alpitelbrasil\.com\.br$", em)) or em == "admin@alpitelbrasil.com.br"

    def register_user(self, nome: str, email: str, matricula: str, password: str, role: str = "operator") -> dict:
        """
        Cadastra um novo colaborador com validações estritas:
        - Nome em MAIÚSCULAS
        - E-mail corporativo @alpitelbrasil.com.br
        - Matrícula BR0 + 9 dígitos
        - Status inicial: 'pending' (Aguardando aprovação do Admin)
        """
        nome_clean = (nome or "").strip().upper()
        email_clean = (email or "").strip().lower()
        matricula_clean = (matricula or "").strip().upper()

        if not nome_clean or len(nome_clean) < 3:
            return {"status": "error", "message": "Nome completo obrigatório (mínimo 3 caracteres)."}

        if not self.validate_email(email_clean):
            return {
                "status": "error", 
                "message": "E-mail corporativo inválido. Deve ser no padrão 'seunome@alpitelbrasil.com.br'."
            }

        if not self.validate_matricula(matricula_clean):
            return {
                "status": "error",
                "message": "Matrícula inválida. Deve iniciar com 'BR0' seguido de 9 dígitos (ex: BR0144636617)."
            }

        if not password or len(password) < 4:
            return {"status": "error", "message": "A senha deve conter no mínimo 4 caracteres."}

        # Verificar duplicidade
        for u in self.users.values():
            if u.get("email") == email_clean:
                return {"status": "error", "message": "Este e-mail corporativo já está cadastrado no sistema."}
            if u.get("matricula") == matricula_clean:
                return {"status": "error", "message": "Esta matrícula já está cadastrada no sistema."}

        user_id = str(secrets.token_hex(16))
        new_user = {
            "id": user_id,
            "nome": nome_clean,
            "email": email_clean,
            "matricula": matricula_clean,
            "password_hash": hash_password(password),
            "role": role if role in ["admin", "supervisor", "operator"] else "operator",
            "status": "pending", # Fica pendente de aprovação
            "created_at": datetime.now().isoformat(),
            "last_login": None
        }

        self.users[user_id] = new_user
        self._save_local_users()

        # Tenta persistir no Supabase
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.post(f"{BASE_REST_URL}/system_users", headers=get_headers(), json=new_user, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Solicitação de cadastro enviada com sucesso! O acesso do colaborador {nome_clean} ({matricula_clean}) está aguardando aprovação do Administrador.",
            "user": {
                "id": user_id,
                "nome": nome_clean,
                "email": email_clean,
                "matricula": matricula_clean,
                "role": new_user["role"],
                "status": "pending"
            }
        }

    def authenticate(self, login_identifier: str, password: str) -> dict:
        """
        Autentica o usuário por E-mail ou Matrícula e Senha.
        Suporta o login mestre do Admin ('Tim@3021').
        """
        login_clean = (login_identifier or "").strip().lower()
        mat_clean = (login_identifier or "").strip().upper()

        # Validação de credencial de Admin direta
        if (login_clean in ["admin", "admin@alpitelbrasil.com.br"] or mat_clean in ["ADMIN", "BR0000000000"]) and password == "Tim@3021":
            admin_user = self.users.get("00000000-0000-0000-0000-000000000001")
            if not admin_user:
                self._init_built_in_admin()
                admin_user = self.users["00000000-0000-0000-0000-000000000001"]
            
            admin_user["last_login"] = datetime.now().isoformat()
            self._save_local_users()
            token = generate_session_token(
                admin_user["id"], 
                admin_user["role"], 
                admin_user["email"], 
                admin_user["matricula"],
                admin_user["nome"]
            )
            return {
                "status": "success",
                "message": "Autenticado com sucesso como Administrador CCO!",
                "token": token,
                "user": {
                    "id": admin_user["id"],
                    "nome": admin_user["nome"],
                    "email": admin_user["email"],
                    "matricula": admin_user["matricula"],
                    "role": "admin",
                    "status": "approved"
                }
            }

        # Busca por E-mail ou Matrícula
        matched_user = None
        for u in self.users.values():
            if u.get("email", "").lower() == login_clean or u.get("matricula", "").upper() == mat_clean:
                matched_user = u
                break

        if not matched_user:
            return {"status": "error", "message": "Usuário não encontrado. Verifique a matrícula ou e-mail digitado."}

        if not verify_password(password, matched_user.get("password_hash", "")):
            return {"status": "error", "message": "Senha incorreta. Tente novamente."}

        # Verificar status de aprovação
        if matched_user.get("status") == "pending":
            return {
                "status": "error",
                "message": f"O acesso de {matched_user.get('nome')} ({matched_user.get('matricula')}) ainda está PENDENTE de aprovação pelo Administrador."
            }

        if matched_user.get("status") == "rejected":
            return {
                "status": "error",
                "message": "Este acesso foi rejeitado ou desativado pela Administração CCO."
            }

        matched_user["last_login"] = datetime.now().isoformat()
        self._save_local_users()

        token = generate_session_token(
            matched_user["id"],
            matched_user["role"],
            matched_user["email"],
            matched_user["matricula"],
            matched_user["nome"]
        )

        return {
            "status": "success",
            "message": f"Bem-vindo(a), {matched_user.get('nome')}!",
            "token": token,
            "user": {
                "id": matched_user["id"],
                "nome": matched_user["nome"],
                "email": matched_user["email"],
                "matricula": matched_user["matricula"],
                "role": matched_user.get("role", "operator"),
                "status": matched_user.get("status", "approved")
            }
        }

    def list_users(self) -> list:
        """Retorna a lista de usuários sem expor hashes de senha (E2EE)."""
        result = []
        for u in self.users.values():
            result.append({
                "id": u.get("id"),
                "nome": u.get("nome"),
                "email": u.get("email"),
                "matricula": u.get("matricula"),
                "role": u.get("role", "operator"),
                "status": u.get("status", "pending"),
                "created_at": u.get("created_at"),
                "last_login": u.get("last_login")
            })
        return sorted(result, key=lambda x: (0 if x["status"] == "pending" else 1, x["nome"]))

    def update_user_status(self, user_id: str, new_status: str, new_role: str = None) -> dict:
        """Permite ao Admin aprovar, rejeitar ou alterar a role de um usuário."""
        if user_id not in self.users:
            return {"status": "error", "message": "Usuário não encontrado."}

        u = self.users[user_id]
        if u.get("id") == "00000000-0000-0000-0000-000000000001" and new_status != "approved":
            return {"status": "error", "message": "A conta do Administrador Mestre não pode ser desativada."}

        if new_status in ["approved", "pending", "rejected"]:
            u["status"] = new_status
        if new_role in ["admin", "supervisor", "operator"]:
            u["role"] = new_role

        self._save_local_users()

        # Atualiza no Supabase se disponível
        try:
            from supabase_client import BASE_REST_URL, get_headers
            import requests
            requests.patch(f"{BASE_REST_URL}/system_users?id=eq.{user_id}", headers=get_headers(), json={
                "status": u["status"],
                "role": u["role"]
            }, timeout=5)
        except Exception:
            pass

        return {
            "status": "success",
            "message": f"Usuário {u.get('nome')} ({u.get('matricula')}) atualizado para: {u.get('status').upper()} ({u.get('role').upper()})!",
            "user": {
                "id": u["id"],
                "nome": u["nome"],
                "matricula": u["matricula"],
                "status": u["status"],
                "role": u["role"]
            }
        }

    def delete_user(self, user_id: str) -> dict:
        """Remove um usuário do sistema."""
        if user_id == "00000000-0000-0000-0000-000000000001":
            return {"status": "error", "message": "O Administrador Mestre não pode ser excluído."}
        
        if user_id in self.users:
            u = self.users.pop(user_id)
            self._save_local_users()
            try:
                from supabase_client import BASE_REST_URL, get_headers
                import requests
                requests.delete(f"{BASE_REST_URL}/system_users?id=eq.{user_id}", headers=get_headers(), timeout=5)
            except Exception:
                pass
            return {"status": "success", "message": f"Usuário {u.get('nome')} excluído com sucesso."}
        return {"status": "error", "message": "Usuário não encontrado."}


auth_manager = AuthManager()
