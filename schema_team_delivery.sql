-- ==============================================================================
-- MÓDULO 2: ENTREGA DE EQUIPES (ENEL SP)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- TABELAS: public.team_delivery_sessions & public.team_delivery_records
-- ==============================================================================

-- 1. Tabela de Sessões de Entrega Diária (Cabeçalho da Batelada)
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
    sync_source TEXT NOT NULL DEFAULT 'Enel Portal'
);

-- 2. Tabela de Registros Linha a Linha de Equipes Entregues
CREATE TABLE IF NOT EXISTS public.team_delivery_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES public.team_delivery_sessions(id) ON DELETE CASCADE,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_ref DATE NOT NULL DEFAULT CURRENT_DATE,
    team_code TEXT NOT NULL,
    base_code TEXT NOT NULL,
    base_name TEXT NOT NULL,
    region TEXT NOT NULL,
    company TEXT NOT NULL,
    vehicle_type TEXT NOT NULL, -- 'Cesto Aéreo', 'Veículo Leve', 'Moto', 'Munck', 'Linha Viva', 'Outros'
    login_time TEXT,            -- Ex: '07:52'
    logoff_time TEXT,           -- Ex: '16:00'
    shift_slot TEXT NOT NULL,   -- '06:00', '08:00', '12:00', '14:00', '20:00', '22:00'
    status TEXT,
    raw_info JSONB DEFAULT '{}'::jsonb
);

-- 3. Índices de Alta Performance para Busca Rápida
CREATE INDEX IF NOT EXISTS idx_delivery_date ON public.team_delivery_records(date_ref);
CREATE INDEX IF NOT EXISTS idx_delivery_base ON public.team_delivery_records(base_code);
CREATE INDEX IF NOT EXISTS idx_delivery_vehicle ON public.team_delivery_records(vehicle_type);
CREATE INDEX IF NOT EXISTS idx_delivery_shift ON public.team_delivery_records(shift_slot);
CREATE INDEX IF NOT EXISTS idx_delivery_team ON public.team_delivery_records(team_code);

-- 4. Habilita Row Level Security (RLS)
ALTER TABLE public.team_delivery_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.team_delivery_records ENABLE ROW LEVEL SECURITY;

-- 5. Políticas RLS para Acesso via REST API (Anon & Authenticated)
DROP POLICY IF EXISTS "Allow anon select delivery_sessions" ON public.team_delivery_sessions;
CREATE POLICY "Allow anon select delivery_sessions" ON public.team_delivery_sessions FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert delivery_sessions" ON public.team_delivery_sessions;
CREATE POLICY "Allow anon insert delivery_sessions" ON public.team_delivery_sessions FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon select delivery_records" ON public.team_delivery_records;
CREATE POLICY "Allow anon select delivery_records" ON public.team_delivery_records FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert delivery_records" ON public.team_delivery_records;
CREATE POLICY "Allow anon insert delivery_records" ON public.team_delivery_records FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon delete delivery_records" ON public.team_delivery_records;
CREATE POLICY "Allow anon delete delivery_records" ON public.team_delivery_records FOR DELETE TO anon, authenticated USING (true);
