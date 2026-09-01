-- ==============================================================================
-- SISTEMA DE AUTENTICAÇÃO E CONTROLE DE ACESSO CORPORATIVO (E2EE)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- TABELA: public.system_users
-- ==============================================================================

-- 1. Criação da Tabela de Usuários do Sistema
CREATE TABLE IF NOT EXISTS public.system_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    matricula TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator' CHECK (role IN ('admin', 'supervisor', 'operator')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('approved', 'pending', 'rejected')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login TIMESTAMPTZ
);

-- 2. Índices de Alta Performance para Busca Rápida
CREATE INDEX IF NOT EXISTS idx_system_users_email ON public.system_users (email);
CREATE INDEX IF NOT EXISTS idx_system_users_matricula ON public.system_users (matricula);
CREATE INDEX IF NOT EXISTS idx_system_users_status ON public.system_users (status);

-- 3. Habilita Row Level Security (RLS)
ALTER TABLE public.system_users ENABLE ROW LEVEL SECURITY;

-- 4. Políticas de Acesso RLS para Leitura, Inserção, Atualização e Exclusão via REST API
DROP POLICY IF EXISTS "Allow anon select system_users" ON public.system_users;
CREATE POLICY "Allow anon select system_users" 
    ON public.system_users FOR SELECT 
    TO anon, authenticated 
    USING (true);

DROP POLICY IF EXISTS "Allow anon insert system_users" ON public.system_users;
CREATE POLICY "Allow anon insert system_users" 
    ON public.system_users FOR INSERT 
    TO anon, authenticated 
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update system_users" ON public.system_users;
CREATE POLICY "Allow anon update system_users" 
    ON public.system_users FOR UPDATE 
    TO anon, authenticated 
    USING (true) 
    WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon delete system_users" ON public.system_users;
CREATE POLICY "Allow anon delete system_users" 
    ON public.system_users FOR DELETE 
    TO anon, authenticated 
    USING (true);

-- 5. Inserção do Usuário Administrador Mestre (Senha: Tim@3021)
-- Hash PBKDF2-HMAC-SHA256 pré-computado para a senha Tim@3021
INSERT INTO public.system_users (
    id,
    nome,
    email,
    matricula,
    password_hash,
    role,
    status,
    created_at
) VALUES (
    '00000000-0000-0000-0000-000000000001',
    'ADMINISTRADOR CCO',
    'admin@alpitelbrasil.com.br',
    'BR0000000000',
    'pbkdf2:sha256:100000$c658f8b89c745b367d32c525f0e340a6$a7ebff0a451e59bc7adbe4c5ec70bb6aeecae1d556adbcab281229a43a0f7895',
    'admin',
    'approved',
    NOW()
) ON CONFLICT (email) DO UPDATE SET
    nome = EXCLUDED.nome,
    matricula = EXCLUDED.matricula,
    password_hash = EXCLUDED.password_hash,
    role = 'admin',
    status = 'approved';
