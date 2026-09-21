-- ==============================================================================
-- SCHEMA V8: ARQUITETURA DE AUDITORIA FORENSE MENSAL POR EQUIPE
-- SUPABASE / POSTGRESQL: ÍNDICES E FUNÇÃO RPC ANTI-TIMEOUT
-- ==============================================================================

-- 1. Índices Compostos de Alta Performance (B-Tree)
CREATE INDEX IF NOT EXISTS idx_team_logs_code_date ON public.team_operational_logs(team_code, date_ref);
CREATE INDEX IF NOT EXISTS idx_team_logs_date_code ON public.team_operational_logs(date_ref, team_code);
CREATE INDEX IF NOT EXISTS idx_deliv_team_date ON public.team_delivery_records(team_code, date_ref);

-- 2. Função RPC de Agregação Server-Side (get_team_monthly_audit)
CREATE OR REPLACE FUNCTION public.get_team_monthly_audit(
    p_team_code TEXT,
    p_month TEXT -- Formato esperado: 'YYYY-MM' (Ex: '2026-09')
)
RETURNS TABLE (
    date_ref DATE,
    was_in_poweron BOOLEAN,
    was_online_trbonet BOOLEAN,
    times_seen_online BIGINT,
    times_with_gps BIGINT,
    times_without_gps BIGINT,
    total_sync_checks BIGINT,
    uptime_percentage NUMERIC,
    first_seen_online TIMESTAMPTZ,
    last_seen_online TIMESTAMPTZ,
    poweron_login_time TEXT,
    poweron_vehicle TEXT,
    base_code TEXT,
    region TEXT
)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_start_date DATE;
    v_end_date DATE;
BEGIN
    v_start_date := (p_month || '-01')::DATE;
    v_end_date := (v_start_date + INTERVAL '1 month - 1 day')::DATE;

    RETURN QUERY
    WITH logs_agg AS (
        SELECT 
            l.date_ref,
            BOOL_OR(l.in_poweron) AS was_in_poweron,
            BOOL_OR(l.in_trbonet) AS was_online_trbonet,
            COUNT(*) FILTER (WHERE l.in_trbonet = TRUE) AS times_seen_online,
            COUNT(*) FILTER (WHERE l.in_trbonet = TRUE AND l.has_gps = TRUE) AS times_with_gps,
            COUNT(*) FILTER (WHERE l.in_trbonet = TRUE AND (l.has_gps = FALSE OR l.has_gps IS NULL)) AS times_without_gps,
            COUNT(*) AS total_sync_checks,
            ROUND(
                (COUNT(*) FILTER (WHERE l.in_trbonet = TRUE)::NUMERIC / NULLIF(COUNT(*), 0)::NUMERIC) * 100, 
                1
            ) AS uptime_percentage,
            MIN(l.captured_at) FILTER (WHERE l.in_trbonet = TRUE) AS first_seen_online,
            MAX(l.captured_at) FILTER (WHERE l.in_trbonet = TRUE) AS last_seen_online,
            MAX(NULLIF(l.poweron_login_time, '--')) AS log_login_time,
            MAX(NULLIF(l.poweron_vehicle, '--')) AS log_vehicle,
            MAX(l.base_code) AS base_code,
            MAX(l.region) AS region
        FROM public.team_operational_logs l
        WHERE l.team_code = UPPER(TRIM(p_team_code))
          AND l.date_ref >= v_start_date
          AND l.date_ref <= v_end_date
        GROUP BY l.date_ref
    ),
    delivery_info AS (
        SELECT 
            d.date_ref,
            MIN(NULLIF(d.login_time, '--')) AS poweron_login_time,
            MAX(NULLIF(d.vehicle_type, '--')) AS poweron_vehicle
        FROM public.team_delivery_records d
        WHERE d.team_code = UPPER(TRIM(p_team_code))
          AND d.date_ref >= v_start_date
          AND d.date_ref <= v_end_date
        GROUP BY d.date_ref
    )
    SELECT 
        COALESCE(l.date_ref, d.date_ref) AS date_ref,
        COALESCE(l.was_in_poweron, (COALESCE(d.poweron_login_time, l.log_login_time) IS NOT NULL AND COALESCE(d.poweron_login_time, l.log_login_time) != '--'), FALSE) AS was_in_poweron,
        COALESCE(l.was_online_trbonet, FALSE) AS was_online_trbonet,
        COALESCE(l.times_seen_online, 0::BIGINT) AS times_seen_online,
        COALESCE(l.times_with_gps, 0::BIGINT) AS times_with_gps,
        COALESCE(l.times_without_gps, 0::BIGINT) AS times_without_gps,
        COALESCE(l.total_sync_checks, 0::BIGINT) AS total_sync_checks,
        COALESCE(l.uptime_percentage, 0.0) AS uptime_percentage,
        l.first_seen_online,
        l.last_seen_online,
        COALESCE(d.poweron_login_time, l.log_login_time, '--') AS poweron_login_time,
        COALESCE(d.poweron_vehicle, l.log_vehicle, '--') AS poweron_vehicle,
        COALESCE(l.base_code, '--') AS base_code,
        COALESCE(l.region, '--') AS region
    FROM logs_agg l
    FULL OUTER JOIN delivery_info d ON d.date_ref = l.date_ref
    ORDER BY date_ref ASC;
END;
$$;

-- Permissões para que o PostgREST do Supabase enxergue a função
GRANT EXECUTE ON FUNCTION public.get_team_monthly_audit(TEXT, TEXT) TO anon, authenticated, service_role;

-- Recarrega o cache do PostgREST
NOTIFY pgrst, 'reload schema';
