-- ==============================================================================
-- SCHEMA BID TECH - VISÃO OPERACIONAL (CHECKLISTS & RECONCILIAÇÃO)
-- Versão: 7.0 (Setembro/2026)
-- Descrição: Registra os dados extraídos via CDP da Visão Operacional BidTech
--            para auditoria e reconciliação com o Equipes Brasil.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS bid_visao_operacional_records (
    id BIGSERIAL PRIMARY KEY,
    date_ref DATE NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    team_code VARCHAR(30) NOT NULL,
    status_bid VARCHAR(50) NOT NULL, -- Planejada, Em Checklist, Em Operação, Retornada, Bloqueada
    col_title VARCHAR(50),
    base VARCHAR(100),
    tipo_operacional VARCHAR(100),
    turno VARCHAR(20),
    phone VARCHAR(50),
    driver VARCHAR(150),
    plate VARCHAR(20),
    vehicle_type VARCHAR(100),
    members JSONB DEFAULT '[]'::jsonb,
    timer_label VARCHAR(50),
    timer_value VARCHAR(50),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_bid_records UNIQUE (date_ref, team_code)
);

CREATE INDEX IF NOT EXISTS idx_bid_date_team ON bid_visao_operacional_records(date_ref, team_code);
CREATE INDEX IF NOT EXISTS idx_bid_status ON bid_visao_operacional_records(status_bid);
CREATE INDEX IF NOT EXISTS idx_bid_captured ON bid_visao_operacional_records(captured_at);

-- Habilitar Row Level Security (RLS)
ALTER TABLE bid_visao_operacional_records ENABLE ROW LEVEL SECURITY;

-- Políticas de Acesso
DROP POLICY IF EXISTS "Public Read BID Records" ON bid_visao_operacional_records;
CREATE POLICY "Public Read BID Records" 
ON bid_visao_operacional_records FOR SELECT 
USING (true);

DROP POLICY IF EXISTS "Service Role All BID Records" ON bid_visao_operacional_records;
CREATE POLICY "Service Role All BID Records" 
ON bid_visao_operacional_records FOR ALL 
USING (true);

-- Habilitar Supabase Realtime (WebSocket CDC)
ALTER TABLE public.bid_visao_operacional_records REPLICA IDENTITY FULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables 
        WHERE pubname = 'supabase_realtime' 
        AND schemaname = 'public' 
        AND tablename = 'bid_visao_operacional_records'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.bid_visao_operacional_records;
    END IF;
END $$;

