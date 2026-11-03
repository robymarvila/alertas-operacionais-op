-- ==============================================================================
-- SCHEMA MIGRATION V10: ADIÇÃO DA COLUNA HORA_A_CAMINHO
-- ==============================================================================
-- Tabela: team_delivery_records
-- Descrição: Registra o horário da 15ª coluna extraída do portal Equipes Brasil
--            ("HORA A CAMINHO ↕") para histórico operacional e auditoria.

ALTER TABLE public.team_delivery_records 
    ADD COLUMN IF NOT EXISTS hora_a_caminho TEXT DEFAULT '--';

CREATE INDEX IF NOT EXISTS idx_delivery_hora_a_caminho 
    ON public.team_delivery_records(hora_a_caminho);

COMMENT ON COLUMN public.team_delivery_records.hora_a_caminho IS 'Horário de deslocamento a caminho da OS extraído do portal Equipes Brasil';

