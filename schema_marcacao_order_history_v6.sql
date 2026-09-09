-- ==============================================================================
-- SCHEMA MIGRATION V6: MARCAÇÃO, DESVIO E HISTÓRICO DE ORDENS DE SERVIÇO
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- ==============================================================================
-- 1. Novas colunas na tabela de registros de equipes entregues (team_delivery_records)
-- 2. Tabela dedicada para Histórico de Ordens de Serviço por Equipe (team_order_history)
-- 3. Índices de alta performance e políticas RLS
-- ==============================================================================

-- 1. Novas Colunas na Tabela team_delivery_records
ALTER TABLE public.team_delivery_records
    ADD COLUMN IF NOT EXISTS marcacao TEXT,
    ADD COLUMN IF NOT EXISTS desvio TEXT,
    ADD COLUMN IF NOT EXISTS desvio_minutos INT,
    ADD COLUMN IF NOT EXISTS order_history JSONB DEFAULT '[]'::jsonb;

-- Índices para buscas e filtros rápidos
CREATE INDEX IF NOT EXISTS idx_delivery_marcacao ON public.team_delivery_records(marcacao);
CREATE INDEX IF NOT EXISTS idx_delivery_desvio_minutos ON public.team_delivery_records(desvio_minutos);

-- 2. Tabela Dedicada de Histórico de Ordens de Serviço Atendidas por Equipe no Dia
CREATE TABLE IF NOT EXISTS public.team_order_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    date_ref DATE NOT NULL DEFAULT CURRENT_DATE,
    team_code TEXT NOT NULL,
    ordem_servico TEXT NOT NULL,
    status TEXT,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    cycles_count INT NOT NULL DEFAULT 1,
    raw_info JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT unique_team_order_day UNIQUE (date_ref, team_code, ordem_servico)
);

-- Índices de Performance para a Tabela de Histórico de Ordens
CREATE INDEX IF NOT EXISTS idx_order_hist_date ON public.team_order_history(date_ref);
CREATE INDEX IF NOT EXISTS idx_order_hist_team ON public.team_order_history(team_code);
CREATE INDEX IF NOT EXISTS idx_order_hist_ordem ON public.team_order_history(ordem_servico);

-- 3. Habilita Row Level Security (RLS)
ALTER TABLE public.team_order_history ENABLE ROW LEVEL SECURITY;

-- 4. Políticas RLS (Acesso Total para anon e authenticated via REST API)
DROP POLICY IF EXISTS "Allow anon all team_order_history" ON public.team_order_history;
CREATE POLICY "Allow anon all team_order_history" ON public.team_order_history
    FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
