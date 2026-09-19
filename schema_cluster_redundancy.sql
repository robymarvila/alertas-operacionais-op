-- ==============================================================================
-- SCHEMA MIGRATION: CLUSTER DE REDUNDÂNCIA DE SERVIDORES LOCAIS (CDP)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- ==============================================================================
-- Gerencia os nós (Máquina 1 - Primária e Máquina 2 - Backup)
-- Registra telemetria de cada computador, porta CDP 9222 e eleição de quem alimenta o banco.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.system_cluster_nodes (
    node_id TEXT PRIMARY KEY,                       -- Ex: 'MAQUINA_1_PRINCIPAL', 'MAQUINA_2_BACKUP'
    node_label TEXT NOT NULL,                       -- Ex: 'Servidor CCO Primário', 'Servidor CCO Redundante'
    role TEXT NOT NULL DEFAULT 'PRIMARY',           -- 'PRIMARY' ou 'STANDBY'
    is_feeding_db BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE se for a máquina que está ativamente enviando dados ao banco
    status TEXT NOT NULL DEFAULT 'ONLINE',          -- 'ONLINE', 'DEGRADED', 'OFFLINE'
    cdp_port_status TEXT NOT NULL DEFAULT 'UNKNOWN',-- 'OPEN', 'CLOSED', 'UNKNOWN'
    ip_address TEXT,                                -- IP local na rede da empresa
    hostname TEXT,                                  -- Nome da máquina no Windows
    os_info TEXT DEFAULT 'Windows',
    last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_collection_sync TIMESTAMPTZ,
    engines_status JSONB DEFAULT '{}'::jsonb,       -- Resumo de cada motor (trbonet, enel, spotfire, bid)
    details_json JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Registros iniciais para os dois servidores (Primário e Secundário)
INSERT INTO public.system_cluster_nodes (
    node_id, node_label, role, is_feeding_db, status, cdp_port_status, last_heartbeat
) VALUES 
    ('MAQUINA_1_PRINCIPAL', 'Servidor CCO Principal (Máquina 1)', 'PRIMARY', TRUE, 'ONLINE', 'OPEN', NOW()),
    ('MAQUINA_2_BACKUP', 'Servidor CCO Redundante (Máquina 2)', 'STANDBY', FALSE, 'STANDBY', 'OPEN', NOW())
ON CONFLICT (node_id) DO UPDATE SET
    node_label = EXCLUDED.node_label,
    role = EXCLUDED.role,
    updated_at = NOW();

-- Índices de performance
CREATE INDEX IF NOT EXISTS idx_cluster_nodes_feeding ON public.system_cluster_nodes(is_feeding_db);
CREATE INDEX IF NOT EXISTS idx_cluster_nodes_last_hb ON public.system_cluster_nodes(last_heartbeat);
CREATE INDEX IF NOT EXISTS idx_cluster_nodes_status ON public.system_cluster_nodes(status);

-- Habilitar RLS e políticas de leitura/escrita aberta
ALTER TABLE public.system_cluster_nodes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon all cluster_nodes" ON public.system_cluster_nodes;
CREATE POLICY "Allow anon all cluster_nodes" ON public.system_cluster_nodes
    FOR ALL TO anon, authenticated USING (true) WITH CHECK (true);
