-- ==============================================================================
-- SCHEMA MIGRATION V5: COLETA CDP EQUIPES BRASIL & INVENTÁRIO DE FROTAS
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- ==============================================================================
-- 1. Criação da tabela de inventário de veículos (espelho do sist-operacao-norte)
-- 2. Novas colunas relacionais na tabela team_delivery_records (SEM JSON)
-- 3. Índices de performance e políticas RLS
-- ==============================================================================

-- 1. Tabela de Inventário de Veículos da Frota (Controle Operacional / Alpitel)
CREATE TABLE IF NOT EXISTS public.fleet_vehicles_inventory (
    id BIGINT PRIMARY KEY,
    placa TEXT NOT NULL,
    placa_clean TEXT NOT NULL UNIQUE,
    situacao TEXT NOT NULL DEFAULT 'ATIVO',       -- 'ATIVO', 'RODANDO', 'PARADO'
    status TEXT,                                 -- 'OPERACIONAL', 'MANUTENÇÃO', 'ANÁLISE FROTA', etc.
    tipo TEXT,                                   -- 'Pesado', 'Leve', 'Moto', etc.
    sub_tipo TEXT,                               -- 'Cesto Aéreo', 'Furgão', etc.
    tipo_op TEXT,                                -- 'TMA', 'Emergência', etc.
    marca TEXT,
    locadora TEXT,
    regional TEXT,                               -- 'Norte', 'Leste'
    turno TEXT,
    dt_inicio_contrato TEXT,
    valor_contrato TEXT,
    tipo_contrato TEXT,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para consultas ultra-rápidas no cruzamento de placas
CREATE INDEX IF NOT EXISTS idx_fleet_placa_clean ON public.fleet_vehicles_inventory(placa_clean);
CREATE INDEX IF NOT EXISTS idx_fleet_situacao ON public.fleet_vehicles_inventory(situacao);
CREATE INDEX IF NOT EXISTS idx_fleet_status ON public.fleet_vehicles_inventory(status);
CREATE INDEX IF NOT EXISTS idx_fleet_regional ON public.fleet_vehicles_inventory(regional);

-- Habilita RLS e políticas de leitura/escrita
ALTER TABLE public.fleet_vehicles_inventory ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon all fleet_vehicles_inventory" ON public.fleet_vehicles_inventory;
CREATE POLICY "Allow anon all fleet_vehicles_inventory" ON public.fleet_vehicles_inventory
    FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);


-- 2. Novas Colunas Estruturadas na Tabela team_delivery_records (Coleta CDP Equipes Brasil)
ALTER TABLE public.team_delivery_records
    ADD COLUMN IF NOT EXISTS veiculo_portal TEXT,
    ADD COLUMN IF NOT EXISTS gps_update_str TEXT,
    ADD COLUMN IF NOT EXISTS gps_update_minutes INT,
    ADD COLUMN IF NOT EXISTS status_equipes_brasil TEXT,
    ADD COLUMN IF NOT EXISTS data_inicio_descanso TEXT,
    ADD COLUMN IF NOT EXISTS hora_inicio_descanso TEXT,
    ADD COLUMN IF NOT EXISTS ordem_servico TEXT,
    ADD COLUMN IF NOT EXISTS plate_clean TEXT,
    ADD COLUMN IF NOT EXISTS plate_cadastrada BOOLEAN DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS situacao_veiculo_cadastrado TEXT DEFAULT 'NÃO CADASTRADO',
    ADD COLUMN IF NOT EXISTS status_veiculo_cadastrado TEXT;

-- Índices de Alta Performance para Auditoria e Telas de Alerta
CREATE INDEX IF NOT EXISTS idx_delivery_plate_clean ON public.team_delivery_records(plate_clean);
CREATE INDEX IF NOT EXISTS idx_delivery_plate_cadastrada ON public.team_delivery_records(plate_cadastrada);
CREATE INDEX IF NOT EXISTS idx_delivery_situacao_veiculo ON public.team_delivery_records(situacao_veiculo_cadastrado);
CREATE INDEX IF NOT EXISTS idx_delivery_ordem_servico ON public.team_delivery_records(ordem_servico);
CREATE INDEX IF NOT EXISTS idx_delivery_status_eb ON public.team_delivery_records(status_equipes_brasil);
