-- ==============================================================================
-- MÓDULO: EXTRAÇÃO TIBCO SPOTFIRE & CONCILIAÇÃO FORENSE DE EQUIPES (ENEL SP)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- TABELA: public.team_spotfire_records
-- ==============================================================================

-- 1. Tabela de Registros Oficiais Extraídos do Spotfire
CREATE TABLE IF NOT EXISTS public.team_spotfire_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data_referencia DATE NOT NULL,
    equipe TEXT NOT NULL,
    equipe_normalizada TEXT NOT NULL,
    inicio_intervalo TEXT,
    fim_intervalo TEXT,
    inicio_calibrado TEXT,      -- Login Real Oficial (ex: '06:12:00')
    fim_calibrado TEXT,         -- LogOff Real Oficial (ex: '16:45:00')
    qtd_os INT DEFAULT 0,
    improdutiva INT DEFAULT 0,
    verificacoes INT DEFAULT 0,
    produtivas INT DEFAULT 0,
    no_local INT DEFAULT 0,
    rejeita TEXT DEFAULT 'NÃO',
    raw_data JSONB DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_spotfire_date_team UNIQUE (data_referencia, equipe_normalizada)
);

-- 2. Índices de Alta Performance para Busca Rápida e Relatórios
CREATE INDEX IF NOT EXISTS idx_spotfire_date ON public.team_spotfire_records(data_referencia);
CREATE INDEX IF NOT EXISTS idx_spotfire_team ON public.team_spotfire_records(equipe_normalizada);
CREATE INDEX IF NOT EXISTS idx_spotfire_logoff ON public.team_spotfire_records(fim_calibrado);

-- 3. Habilita Row Level Security (RLS)
ALTER TABLE public.team_spotfire_records ENABLE ROW LEVEL SECURITY;

-- 4. Políticas de Acesso
DROP POLICY IF EXISTS "Allow anon select spotfire" ON public.team_spotfire_records;
CREATE POLICY "Allow anon select spotfire" ON public.team_spotfire_records FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert spotfire" ON public.team_spotfire_records;
CREATE POLICY "Allow anon insert spotfire" ON public.team_spotfire_records FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update spotfire" ON public.team_spotfire_records;
CREATE POLICY "Allow anon update spotfire" ON public.team_spotfire_records FOR UPDATE TO anon, authenticated USING (true);
