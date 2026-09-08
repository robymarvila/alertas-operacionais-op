-- ==============================================================================
-- MÓDULO DE PLANEJAMENTO & METAS OPERACIONAIS (ENTREGA DE EQUIPES)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- TABELA: public.team_delivery_planning_targets
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.team_delivery_planning_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_month TEXT NOT NULL,         -- Formato: 'YYYY-MM' ou 'DEFAULT'
    region TEXT NOT NULL,               -- 'Norte' ou 'Leste' ou 'Geral'
    category_type TEXT NOT NULL,        -- 'base', 'turno', 'veiculo', 'daily_total'
    item_key TEXT NOT NULL,             -- Ex: 'Fagundes Filho', 'Manhã', 'Cesto Aéreo', 'daily_meta'
    target_val INT NOT NULL DEFAULT 0,
    updated_by TEXT DEFAULT 'admin@alpitelbrasil.com.br',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_planning_target UNIQUE (target_month, region, category_type, item_key)
);

-- Índices de Alta Performance
CREATE INDEX IF NOT EXISTS idx_plan_month ON public.team_delivery_planning_targets(target_month);
CREATE INDEX IF NOT EXISTS idx_plan_region ON public.team_delivery_planning_targets(region);

-- Habilita RLS
ALTER TABLE public.team_delivery_planning_targets ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow select planning_targets" ON public.team_delivery_planning_targets;
CREATE POLICY "Allow select planning_targets" ON public.team_delivery_planning_targets FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert planning_targets" ON public.team_delivery_planning_targets;
CREATE POLICY "Allow insert planning_targets" ON public.team_delivery_planning_targets FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update planning_targets" ON public.team_delivery_planning_targets;
CREATE POLICY "Allow update planning_targets" ON public.team_delivery_planning_targets FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

-- Valores Padrão Iniciais (Conforme Especificação Oficial dos Anexos)

-- 1. REGIÃO NORTE (Total TMA = 94 | Total LV + TMA = 109)
-- Bases
INSERT INTO public.team_delivery_planning_targets (target_month, region, category_type, item_key, target_val) VALUES
('DEFAULT', 'Norte', 'base', 'Fagundes Filho', 42),
('DEFAULT', 'Norte', 'base', 'Cajati', 24),
('DEFAULT', 'Norte', 'base', 'Vila Medeiros', 28),
('DEFAULT', 'Norte', 'base', 'LV', 10),
('DEFAULT', 'Norte', 'base', 'Munk', 5),
-- Turnos
('DEFAULT', 'Norte', 'turno', 'Manhã', 54),
('DEFAULT', 'Norte', 'turno', 'Tarde', 42),
('DEFAULT', 'Norte', 'turno', 'Noite', 13),
-- Veículos
('DEFAULT', 'Norte', 'veiculo', 'Cesto Aéreo', 68),
('DEFAULT', 'Norte', 'veiculo', 'Veículo Leve', 13),
('DEFAULT', 'Norte', 'veiculo', 'Moto', 13),
('DEFAULT', 'Norte', 'veiculo', 'LV', 10),
('DEFAULT', 'Norte', 'veiculo', 'Munk', 5)
ON CONFLICT (target_month, region, category_type, item_key) DO UPDATE SET target_val = EXCLUDED.target_val;

-- 2. REGIÃO LESTE (Total = 95)
-- Bases
INSERT INTO public.team_delivery_planning_targets (target_month, region, category_type, item_key, target_val) VALUES
('DEFAULT', 'Leste', 'base', 'Monte Santo', 33),
('DEFAULT', 'Leste', 'base', 'Catumbi', 21),
('DEFAULT', 'Leste', 'base', 'Aricanduva', 34),
('DEFAULT', 'Leste', 'base', 'Santo André', 7),
('DEFAULT', 'Leste', 'base', 'LV', 0),
('DEFAULT', 'Leste', 'base', 'Munk', 0),
-- Turnos
('DEFAULT', 'Leste', 'turno', 'Manhã', 35),
('DEFAULT', 'Leste', 'turno', 'Tarde', 35),
('DEFAULT', 'Leste', 'turno', 'Noite', 25),
-- Veículos
('DEFAULT', 'Leste', 'veiculo', 'Cesto Aéreo', 75),
('DEFAULT', 'Leste', 'veiculo', 'Veículo Leve', 15),
('DEFAULT', 'Leste', 'veiculo', 'Moto', 5),
('DEFAULT', 'Leste', 'veiculo', 'LV', 0),
('DEFAULT', 'Leste', 'veiculo', 'Munk', 0)
ON CONFLICT (target_month, region, category_type, item_key) DO UPDATE SET target_val = EXCLUDED.target_val;

-- 3. META GERAL DIÁRIA
INSERT INTO public.team_delivery_planning_targets (target_month, region, category_type, item_key, target_val) VALUES
('DEFAULT', 'Geral', 'daily_total', 'daily_meta', 226)
ON CONFLICT (target_month, region, category_type, item_key) DO UPDATE SET target_val = EXCLUDED.target_val;
