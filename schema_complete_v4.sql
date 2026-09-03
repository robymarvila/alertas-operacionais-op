-- ==============================================================================
-- SCRIPT OFICIAL SUPABASE (POSTGRESQL) - ARQUITETURA V4 CONSOLIDADA
-- ALERTA OPERACIONAIS OP: STATUS TRBONET & ENTREGA DE EQUIPES ENEL SP
-- ==============================================================================
-- 1. Elimina JSON genérico e cria colunas dedicadas e auditáveis
-- 2. Monitoramento de Saúde de Motores (Engine Health Monitor)
-- 3. Telemetria e Auditoria de Sessões de Usuários (Fingerprint, IP, Geo, Device)
-- 4. Índices de Alta Performance e Políticas RLS (Anon & Authenticated)
-- ==============================================================================

-- ------------------------------------------------------------------------------
-- PARTE 1: MÓDULO ENTREGA DE EQUIPES (ENEL SP) - COLUNAS DEDICADAS (SEM JSON)
-- ------------------------------------------------------------------------------

-- Tabela de Sessões Diárias da Enel SP
CREATE TABLE IF NOT EXISTS public.team_delivery_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_ref DATE NOT NULL DEFAULT CURRENT_DATE,
    total_teams INT NOT NULL DEFAULT 0,
    total_cesto INT NOT NULL DEFAULT 0,
    total_veiculo_leve INT NOT NULL DEFAULT 0,
    total_moto INT NOT NULL DEFAULT 0,
    total_munck INT NOT NULL DEFAULT 0,
    total_linha_viva INT NOT NULL DEFAULT 0,
    total_alpitel INT NOT NULL DEFAULT 0,
    total_propria INT NOT NULL DEFAULT 0,
    sync_source TEXT NOT NULL DEFAULT 'Enel CDP Autônomo'
);

-- Tabela de Registros de Equipes com Colunas 100% Relacionais e Tipadas
CREATE TABLE IF NOT EXISTS public.team_delivery_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES public.team_delivery_sessions(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_ref DATE NOT NULL DEFAULT CURRENT_DATE,
    team_code TEXT NOT NULL,
    base_code TEXT NOT NULL,
    base_name TEXT NOT NULL,
    base_display TEXT NOT NULL,
    region TEXT NOT NULL,
    company TEXT NOT NULL,
    vehicle_type TEXT NOT NULL,     -- 'Cesto Aéreo', 'Veículo Leve', 'Moto', 'Munck', 'Linha Viva'
    vehicle_category TEXT NOT NULL DEFAULT 'Pesado', -- 'Pesado', 'Leve', 'Moto', 'Apoio'
    unified_group TEXT NOT NULL DEFAULT 'Cesto Aéreo', -- 'Cesto Aéreo', 'Veículo Leve', 'Moto', 'Linha Viva + Munk'
    login_time TEXT,                -- Ex: '07:52'
    logoff_time TEXT,               -- Ex: '16:00'
    shift_slot TEXT NOT NULL,       -- 'Turno 06:00', 'Turno 08:00', etc.
    shift_code TEXT NOT NULL,       -- '06:00', '08:00', '12:00', '14:00', '20:00', '22:00'
    status TEXT NOT NULL DEFAULT 'Logada',
    driver TEXT NOT NULL DEFAULT '--',   -- Motorista / Eletricista nominal
    plate TEXT NOT NULL DEFAULT '--',    -- Placa do veículo
    ut TEXT NOT NULL DEFAULT '--',       -- Unidade Territorial
    filial TEXT NOT NULL DEFAULT '--',   -- Filial Enel (Norte, Leste)
    is_active BOOLEAN NOT NULL DEFAULT TRUE, -- TRUE = Logada ao vivo / FALSE = Turno Concluído
    sync_source TEXT NOT NULL DEFAULT 'Enel CDP'
);

-- Migração Segura: Adiciona colunas se a tabela já existir previamente
DO $$ 
BEGIN
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS base_display TEXT NOT NULL DEFAULT '';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS vehicle_category TEXT NOT NULL DEFAULT 'Pesado';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS unified_group TEXT NOT NULL DEFAULT 'Cesto Aéreo';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS shift_code TEXT NOT NULL DEFAULT '08:00';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS driver TEXT NOT NULL DEFAULT '--';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS plate TEXT NOT NULL DEFAULT '--';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS ut TEXT NOT NULL DEFAULT '--';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS filial TEXT NOT NULL DEFAULT '--';
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
    ALTER TABLE public.team_delivery_records ADD COLUMN IF NOT EXISTS sync_source TEXT NOT NULL DEFAULT 'Enel CDP';
END $$;

-- Índices de Alta Performance
CREATE INDEX IF NOT EXISTS idx_deliv_date_ref ON public.team_delivery_records(date_ref);
CREATE INDEX IF NOT EXISTS idx_deliv_team_code ON public.team_delivery_records(team_code);
CREATE INDEX IF NOT EXISTS idx_deliv_base_code ON public.team_delivery_records(base_code);
CREATE INDEX IF NOT EXISTS idx_deliv_shift_code ON public.team_delivery_records(shift_code);
CREATE INDEX IF NOT EXISTS idx_deliv_vehicle_type ON public.team_delivery_records(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_deliv_driver ON public.team_delivery_records(driver);
CREATE INDEX IF NOT EXISTS idx_deliv_plate ON public.team_delivery_records(plate);
CREATE INDEX IF NOT EXISTS idx_deliv_active ON public.team_delivery_records(is_active);

-- ------------------------------------------------------------------------------
-- PARTE 2: MONITOR DE SAÚDE DOS MOTORES (ENGINE HEALTH MONITOR)
-- ------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS public.system_engine_health (
    engine_name TEXT PRIMARY KEY,       -- 'trbonet_collector', 'enel_cdp_collector', 'cloud_sync_listener'
    engine_label TEXT NOT NULL,         -- 'Motor TRBOnet One', 'Robô CDP Enel SP', 'Sincronizador Nuvem'
    status TEXT NOT NULL DEFAULT 'OPERATIONAL', -- 'OPERATIONAL', 'ERROR_CONNECTION', 'STOPPED', 'WARNING'
    is_running BOOLEAN NOT NULL DEFAULT TRUE,
    error_type TEXT NOT NULL DEFAULT 'NONE',    -- 'NONE', 'CONNECTION_REFUSED', 'TIMEOUT', 'PROCESS_STOPPED'
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_success_sync TIMESTAMPTZ,
    last_error_message TEXT,
    consecutive_errors INT NOT NULL DEFAULT 0,
    records_count INT NOT NULL DEFAULT 0,
    restart_count INT NOT NULL DEFAULT 0,
    details_json JSONB DEFAULT '{}'::jsonb
);

-- Linhas Iniciais para os 3 Motores Principais
INSERT INTO public.system_engine_health (engine_name, engine_label, status, is_running, error_type, last_heartbeat, records_count)
VALUES 
    ('trbonet_collector', 'Motor TRBOnet One (Rádios & GPS)', 'OPERATIONAL', TRUE, 'NONE', NOW(), 150),
    ('enel_cdp_collector', 'Robô CDP Enel SP (Equipes & Turnos)', 'OPERATIONAL', TRUE, 'NONE', NOW(), 50),
    ('cloud_sync_listener', 'Sincronizador e Listener Supabase', 'OPERATIONAL', TRUE, 'NONE', NOW(), 0)
ON CONFLICT (engine_name) DO UPDATE SET 
    engine_label = EXCLUDED.engine_label,
    last_heartbeat = NOW();

-- ------------------------------------------------------------------------------
-- PARTE 3: TELEMETRIA E AUDITORIA DE SESSÕES (FINGERPRINT, IP, DISPOSITIVO, GEO)
-- ------------------------------------------------------------------------------

-- Tabela de Sessões Ativas e Históricas dos Usuários
CREATE TABLE IF NOT EXISTS public.system_user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL UNIQUE,
    username TEXT NOT NULL DEFAULT 'Colaborador',
    user_id UUID REFERENCES public.system_users(id) ON DELETE SET NULL,
    fingerprint TEXT NOT NULL,
    ip_address TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'Desktop',   -- 'Desktop', 'Mobile', 'Tablet'
    device_brand TEXT,
    os_name TEXT NOT NULL DEFAULT 'Windows',       -- 'Windows', 'macOS', 'Android', 'iOS', 'Linux'
    browser_name TEXT NOT NULL DEFAULT 'Chrome',   -- 'Chrome', 'Edge', 'Firefox', 'Safari'
    geo_city TEXT NOT NULL DEFAULT 'São Paulo',
    geo_region TEXT NOT NULL DEFAULT 'SP',
    geo_country TEXT NOT NULL DEFAULT 'Brasil',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    page_views INT NOT NULL DEFAULT 1
);

-- Tabela de Logs de Auditoria Temporal (Acessos Diários, Semanais e Mensais)
CREATE TABLE IF NOT EXISTS public.system_user_access_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT 'Colaborador',
    ip_address TEXT NOT NULL,
    device_type TEXT NOT NULL DEFAULT 'Desktop',
    os_name TEXT NOT NULL DEFAULT 'Windows',
    browser_name TEXT NOT NULL DEFAULT 'Chrome',
    geo_city TEXT NOT NULL DEFAULT 'São Paulo',
    endpoint TEXT NOT NULL DEFAULT '/',
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_ref DATE NOT NULL DEFAULT CURRENT_DATE
);

-- Índices de Performance para Auditoria e Telemetria
CREATE INDEX IF NOT EXISTS idx_sessions_session_id ON public.system_user_sessions(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_fingerprint ON public.system_user_sessions(fingerprint);
CREATE INDEX IF NOT EXISTS idx_sessions_ip ON public.system_user_sessions(ip_address);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON public.system_user_sessions(is_active);
CREATE INDEX IF NOT EXISTS idx_sessions_last_hb ON public.system_user_sessions(last_heartbeat);

CREATE INDEX IF NOT EXISTS idx_access_logs_date_ref ON public.system_user_access_logs(date_ref);
CREATE INDEX IF NOT EXISTS idx_access_logs_fingerprint ON public.system_user_access_logs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_access_logs_accessed_at ON public.system_user_access_logs(accessed_at);

-- ------------------------------------------------------------------------------
-- PARTE 4: POLÍTICAS DE SEGURANÇA ROW LEVEL SECURITY (RLS)
-- ------------------------------------------------------------------------------

ALTER TABLE public.team_delivery_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.team_delivery_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_engine_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.system_user_access_logs ENABLE ROW LEVEL SECURITY;

-- 1. team_delivery_sessions
DROP POLICY IF EXISTS "allow_all_delivery_sessions" ON public.team_delivery_sessions;
CREATE POLICY "allow_all_delivery_sessions" ON public.team_delivery_sessions FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- 2. team_delivery_records
DROP POLICY IF EXISTS "allow_all_delivery_records" ON public.team_delivery_records;
CREATE POLICY "allow_all_delivery_records" ON public.team_delivery_records FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- 3. system_engine_health
DROP POLICY IF EXISTS "allow_all_engine_health" ON public.system_engine_health;
CREATE POLICY "allow_all_engine_health" ON public.system_engine_health FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- 4. system_user_sessions
DROP POLICY IF EXISTS "allow_all_user_sessions" ON public.system_user_sessions;
CREATE POLICY "allow_all_user_sessions" ON public.system_user_sessions FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- 5. system_user_access_logs
DROP POLICY IF EXISTS "allow_all_user_access_logs" ON public.system_user_access_logs;
CREATE POLICY "allow_all_user_access_logs" ON public.system_user_access_logs FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);

-- ==============================================================================
-- SCRIPT CONCLUÍDO COM SUCESSO!
-- ==============================================================================
