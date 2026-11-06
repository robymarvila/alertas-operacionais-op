-- ==============================================================================
-- SCHEMA GESTÃO DE ATRASOS & JUSTIFICATIVAS DE LOGIN (INTEGRIDADE RELACIONAL)
-- Versão: 11.0 (Novembro/2026)
--
-- INSTRUÇÕES DE EXECUÇÃO:
-- 1. Acesse o Supabase Dashboard do projeto (https://supabase.com/dashboard/project/xgfawbqllikosyngfvwa)
-- 2. No menu lateral, clique em "SQL Editor"
-- 3. Cole todo o conteúdo deste arquivo e clique em "RUN"
-- ==============================================================================

-- 1. TABELA PRINCIPAL DE JUSTIFICATIVAS DE ATRASO
CREATE TABLE IF NOT EXISTS public.team_delay_justifications (
    id BIGSERIAL PRIMARY KEY,
    date_ref DATE NOT NULL,
    team_code VARCHAR(30) NOT NULL,
    shift_code VARCHAR(20),
    delay_minutes INT DEFAULT 0,
    user_name VARCHAR(150) NOT NULL,
    macro_reason VARCHAR(100) NOT NULL,
    sub_reason VARCHAR(150) NOT NULL,
    observation TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_delay_justification UNIQUE (date_ref, team_code)
);

-- Índices de Performance e Consulta Forense
CREATE INDEX IF NOT EXISTS idx_delay_date_team ON public.team_delay_justifications(date_ref, team_code);
CREATE INDEX IF NOT EXISTS idx_delay_macro ON public.team_delay_justifications(macro_reason);
CREATE INDEX IF NOT EXISTS idx_delay_shift ON public.team_delay_justifications(shift_code);
CREATE INDEX IF NOT EXISTS idx_delay_date_ref ON public.team_delay_justifications(date_ref);

-- Habilitar Row Level Security (RLS)
ALTER TABLE public.team_delay_justifications ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public Read Delay Justifications" ON public.team_delay_justifications;
CREATE POLICY "Public Read Delay Justifications" 
ON public.team_delay_justifications FOR SELECT 
USING (true);

DROP POLICY IF EXISTS "Public Write Delay Justifications" ON public.team_delay_justifications;
CREATE POLICY "Public Write Delay Justifications" 
ON public.team_delay_justifications FOR ALL 
USING (true);

-- Habilitar Realtime CDC para Supabase
ALTER TABLE public.team_delay_justifications REPLICA IDENTITY FULL;
DO $$
BEGIN
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.team_delay_justifications;
    EXCEPTION
        WHEN duplicate_object THEN
            NULL;
    END;
END $$;

-- 2. ADIÇÃO DAS COLUNAS DE JUSTIFICATIVA NA TABELA DE REGISTROS DE ENTREGA
ALTER TABLE public.team_delivery_records 
    ADD COLUMN IF NOT EXISTS delay_macro_reason TEXT DEFAULT '--',
    ADD COLUMN IF NOT EXISTS delay_sub_reason TEXT DEFAULT '--',
    ADD COLUMN IF NOT EXISTS delay_user_name TEXT DEFAULT '--',
    ADD COLUMN IF NOT EXISTS delay_observation TEXT DEFAULT '--';

CREATE INDEX IF NOT EXISTS idx_delivery_delay_macro ON public.team_delivery_records(delay_macro_reason);
