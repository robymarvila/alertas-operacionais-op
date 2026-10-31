-- ==============================================================================
-- SCHEMA V9: Novas Colunas TÉRMINO e TURNO x LOGIN na Tabela team_delivery_records
-- ==============================================================================
-- 1. termino: Horário de término previsto/efetivo de logoff da equipe (HH:MM)
-- 2. turno_x_login: Diferença calculada entre a MARCAÇÃO da equipe e o início do TURNO PROGRAMADO (Ex: "+15 min", "Pontual", "-5 min")
-- 3. turno_x_login_minutos: Valor numérico inteiro em minutos para ordenação e filtros analíticos
-- ==============================================================================

ALTER TABLE public.team_delivery_records 
    ADD COLUMN IF NOT EXISTS termino TEXT DEFAULT '--',
    ADD COLUMN IF NOT EXISTS turno_x_login TEXT DEFAULT '--',
    ADD COLUMN IF NOT EXISTS turno_x_login_minutos INT DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_delivery_termino ON public.team_delivery_records(termino);
CREATE INDEX IF NOT EXISTS idx_delivery_turno_x_login_min ON public.team_delivery_records(turno_x_login_minutos);

