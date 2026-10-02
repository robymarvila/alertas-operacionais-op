-- ==============================================================================
-- MÓDULO: PRIORIZADOR - ORDENS CRÍTICAS (TIBCO SPOTFIRE & CCO ENEL SP)
-- BANCO DE DADOS: SUPABASE (POSTGRESQL)
-- TABELAS:
--   1. public.priorizador_active_orders        (Snapshot das ordens ativas)
--   2. public.priorizador_supervisor_timeline  (Linha do tempo e notas de supervisão)
--   3. public.priorizador_order_history        (Auditoria de mutações sem redundância)
--   4. public.priorizador_sync_sessions        (Histórico de coletas do robô CDP)
-- ==============================================================================

-- 1. TABELA DE SNAPSHOT ATUAL DE ORDENS CRÍTICAS (UPSERT A CADA 2-3 MINUTOS)
CREATE TABLE IF NOT EXISTS public.priorizador_active_orders (
    ordem TEXT PRIMARY KEY,                             -- Código da OS (ex: '16908554-1')
    control_desp TEXT DEFAULT '--',                     -- AGUARD_DESP, LOCAL_>=80min, CAMI_<40min, etc.
    data_desligamento TEXT,                             -- Data/Hora do desligamento
    qtd_reinc_60 INT DEFAULT 0,                         -- Reincidência nos últimos 60 dias
    eq TEXT DEFAULT '--',                               -- Categoria de equipamento (DJ, RA, CF, BF, CH, RM, ET...)
    facility TEXT DEFAULT '--',                         -- Código do equipamento na rede
    alimentador TEXT DEFAULT '--',                      -- Circuito / Alimentador
    interrupcoes INT DEFAULT 0,                         -- Clientes potenciais interrompidos
    ci INT DEFAULT 0,                                   -- Clientes interrompidos atuais
    chi NUMERIC(14, 4) DEFAULT 0.0,                     -- CHI acumulado
    dm_parcial NUMERIC(10, 2) DEFAULT 0.0,              -- DM Parcial
    num_recla INT DEFAULT 0,                            -- Quantidade de chamados abertos
    base_op TEXT DEFAULT '--',                          -- Base Operacional (BASE VILA MEDEIROS, etc.)
    situacao_conjunto TEXT DEFAULT '--',                -- Risco da Meta, Abaixo da Meta, etc.
    organizacao TEXT DEFAULT '--',                      -- Posto / Centro de Despacho
    aval_dif TEXT DEFAULT '--',                         -- Avaliação diferencial
    regiao TEXT DEFAULT '--',                           -- NORTE, LESTE, SUL, OESTE
    tempo_ult_recla_min INT DEFAULT 0,                  -- Tempo desde a última reclamação em minutos
    meta_dm NUMERIC(10, 2) DEFAULT 0.0,                 -- Meta DM
    dur_min INT DEFAULT 0,                              -- Duração total em minutos
    chi_projetado NUMERIC(14, 4) DEFAULT 0.0,           -- CHI projetado
    num_equipes INT DEFAULT 0,                          -- Quantidade de equipes no evento
    tp TEXT DEFAULT '--',                               -- TP
    tp_1e TEXT DEFAULT '--',                            -- TP 1ª Equipe
    tp_2e TEXT DEFAULT '--',                            -- TP 2ª Equipe

    -- Campos Calculados de Regras de Criticidade Estrita (DJ, RA, CF, CA, BF, CH, RM)
    -- Hierarquia Estrita (Independente de CONTROL_DESP):
    --   1. PRIORIDADE ELEVADA: Equipamento Crítico + CI > 200 clientes (ex: BF com 500 desligados)
    --   2. REDE CRÍTICA: Equipamento Crítico (DJ, RA, CF, CA, BF, CH, RM) com CI <= 200
    --   3. GRANDE CI: Qualquer outro equipamento fora da lista com CI >= 200 clientes
    --   4. CONVENCIONAL: Demais ordens (CI < 200)
    nivel_criticidade TEXT NOT NULL DEFAULT 'CONVENCIONAL', 
    prioridade_rank INT NOT NULL DEFAULT 4,             -- 1: Elevada, 2: EQ Crítico, 3: Grande CI, 4: Convencional
    prioridade_codigo TEXT DEFAULT 'PRIO_4_CONVENCIONAL', -- PRIO_1_ELEVADA, PRIO_2_EQ_CRITICO, PRIO_3_CI_ALTO, PRIO_4_CONVENCIONAL
    is_urgencia_critica BOOLEAN DEFAULT FALSE,          -- Flag direta para filtros rápidos (True se Rank 1)
    
    -- Cruzamento em Tempo Real com Módulo de Entrega de Equipes
    equipe_codigo TEXT DEFAULT NULL,                    -- Ex: 'EEL-204'
    equipe_motorista TEXT DEFAULT NULL,                 -- Nome do motorista
    equipe_veiculo TEXT DEFAULT NULL,                   -- Cesto Aéreo, Veículo Leve, etc.
    equipe_status TEXT DEFAULT NULL,                    -- Status da equipe no EquipesBrasil
    equipe_base TEXT DEFAULT NULL,                      -- Base da equipe
    equipe_vinculada_em TIMESTAMPTZ DEFAULT NULL,

    -- Supervisão e Logbook Ativo
    supervisor_responsavel TEXT DEFAULT NULL,           -- Nome do supervisor que assumiu a OS
    status_supervisao TEXT DEFAULT 'Pendente',          -- Pendente, Em Análise, No Ponto de Falha, etc.
    ultima_nota_supervisao TEXT DEFAULT NULL,           -- Última anotação registrada
    ultima_atualizacao_supervisao TIMESTAMPTZ DEFAULT NULL,
    total_notas_supervisao INT DEFAULT 0,

    -- Controle de Coleta e Auditoria
    hash_dados TEXT,                                    -- Hash SHA-256 para detecção atômica de mutações
    is_active BOOLEAN DEFAULT TRUE,                     -- Se a ordem ainda consta na tabela do Spotfire
    primeira_coleta_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    atualizado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices de Alta Performance para o Snapshot Ativo
CREATE INDEX IF NOT EXISTS idx_priorizador_active_ordem ON public.priorizador_active_orders(ordem);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_criticidade ON public.priorizador_active_orders(nivel_criticidade);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_control_desp ON public.priorizador_active_orders(control_desp);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_eq ON public.priorizador_active_orders(eq);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_ci ON public.priorizador_active_orders(ci);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_base ON public.priorizador_active_orders(base_op);
CREATE INDEX IF NOT EXISTS idx_priorizador_active_supervisor ON public.priorizador_active_orders(supervisor_responsavel);


-- 2. TABELA DE LINHA DO TEMPO & NOTAS DA SUPERVISÃO (LOGBOOK PASSO A PASSO)
CREATE TABLE IF NOT EXISTS public.priorizador_supervisor_timeline (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ordem TEXT NOT NULL REFERENCES public.priorizador_active_orders(ordem) ON DELETE CASCADE,
    supervisor_nome TEXT NOT NULL,                      -- Nome do supervisor que fez o apontamento
    status_etapa TEXT NOT NULL,                         -- Etapa operacional da OS
    observacao TEXT NOT NULL,                           -- Nota descritiva do que está acontecendo
    ci_momento INT DEFAULT 0,                           -- CI congelado no momento da anotação
    chi_momento NUMERIC(14, 4) DEFAULT 0.0,             -- CHI congelado no momento
    equipe_momento TEXT DEFAULT NULL,                   -- Equipe que estava associada
    registrado_em TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices para a Timeline de Supervisão
CREATE INDEX IF NOT EXISTS idx_priorizador_timeline_ordem ON public.priorizador_supervisor_timeline(ordem);
CREATE INDEX IF NOT EXISTS idx_priorizador_timeline_data ON public.priorizador_supervisor_timeline(registrado_em DESC);
CREATE INDEX IF NOT EXISTS idx_priorizador_timeline_supervisor ON public.priorizador_supervisor_timeline(supervisor_nome);


-- 3. TABELA DE AUDITORIA & HISTÓRICO DE MUTAÇÕES DE DADOS (SEM REDUNDÂNCIAS)
-- Só insere quando houver mutação em CI, CHI, CONTROL_DESP ou EQUIPE
CREATE TABLE IF NOT EXISTS public.priorizador_order_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ordem TEXT NOT NULL,
    coletado_em TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    campo_alterado TEXT NOT NULL,                       -- 'CI', 'CHI', 'CONTROL_DESP', 'EQUIPE', 'PRIMEIRO_REGISTRO'
    valor_anterior TEXT,
    valor_novo TEXT,
    ci_atual INT DEFAULT 0,
    chi_atual NUMERIC(14, 4) DEFAULT 0.0,
    control_desp_atual TEXT,
    equipe_atual TEXT,
    motivo_resumo TEXT,                                 -- Ex: "CI alterado de 4793 para 2100 (-2693 clientes)"
    snapshot_completo JSONB DEFAULT '{}'::jsonb
);

-- Índices para Histórico de Mutações
CREATE INDEX IF NOT EXISTS idx_priorizador_hist_ordem ON public.priorizador_order_history(ordem);
CREATE INDEX IF NOT EXISTS idx_priorizador_hist_data ON public.priorizador_order_history(coletado_em DESC);
CREATE INDEX IF NOT EXISTS idx_priorizador_hist_campo ON public.priorizador_order_history(campo_alterado);


-- 4. TABELA DE SESSÕES DE COLETA DO ROBÔ CDP
CREATE TABLE IF NOT EXISTS public.priorizador_sync_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    total_ordens INT DEFAULT 0,
    total_ci INT DEFAULT 0,
    total_chi NUMERIC(14, 4) DEFAULT 0.0,
    qtd_urgencia_critica INT DEFAULT 0,
    qtd_aguard_desp INT DEFAULT 0,
    qtd_local_80min INT DEFAULT 0,
    qtd_com_equipe INT DEFAULT 0,
    tempo_coleta_segundos NUMERIC(8, 2) DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'SUCCESS',              -- 'SUCCESS', 'WARNING', 'ERROR'
    origem_disparo TEXT DEFAULT 'Robô CDP Automático',
    mensagem_erro TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_priorizador_sess_data ON public.priorizador_sync_sessions(captured_at DESC);


-- 5. HABILITAÇÃO DE ROW LEVEL SECURITY (RLS)
ALTER TABLE public.priorizador_active_orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.priorizador_supervisor_timeline ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.priorizador_order_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.priorizador_sync_sessions ENABLE ROW LEVEL SECURITY;


-- 6. POLÍTICAS RLS (ANON E AUTHENTICATED) PARA ACESSO VIA REST API DO SUPABASE
-- active_orders
DROP POLICY IF EXISTS "Allow anon select priorizador_active_orders" ON public.priorizador_active_orders;
CREATE POLICY "Allow anon select priorizador_active_orders" ON public.priorizador_active_orders FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert priorizador_active_orders" ON public.priorizador_active_orders;
CREATE POLICY "Allow anon insert priorizador_active_orders" ON public.priorizador_active_orders FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update priorizador_active_orders" ON public.priorizador_active_orders;
CREATE POLICY "Allow anon update priorizador_active_orders" ON public.priorizador_active_orders FOR UPDATE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon delete priorizador_active_orders" ON public.priorizador_active_orders;
CREATE POLICY "Allow anon delete priorizador_active_orders" ON public.priorizador_active_orders FOR DELETE TO anon, authenticated USING (true);

-- supervisor_timeline
DROP POLICY IF EXISTS "Allow anon select priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline;
CREATE POLICY "Allow anon select priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline;
CREATE POLICY "Allow anon insert priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline;
CREATE POLICY "Allow anon update priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline FOR UPDATE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon delete priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline;
CREATE POLICY "Allow anon delete priorizador_supervisor_timeline" ON public.priorizador_supervisor_timeline FOR DELETE TO anon, authenticated USING (true);

-- order_history
DROP POLICY IF EXISTS "Allow anon select priorizador_order_history" ON public.priorizador_order_history;
CREATE POLICY "Allow anon select priorizador_order_history" ON public.priorizador_order_history FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert priorizador_order_history" ON public.priorizador_order_history;
CREATE POLICY "Allow anon insert priorizador_order_history" ON public.priorizador_order_history FOR INSERT TO anon, authenticated WITH CHECK (true);

-- sync_sessions
DROP POLICY IF EXISTS "Allow anon select priorizador_sync_sessions" ON public.priorizador_sync_sessions;
CREATE POLICY "Allow anon select priorizador_sync_sessions" ON public.priorizador_sync_sessions FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert priorizador_sync_sessions" ON public.priorizador_sync_sessions;
CREATE POLICY "Allow anon insert priorizador_sync_sessions" ON public.priorizador_sync_sessions FOR INSERT TO anon, authenticated WITH CHECK (true);

-- 7. VISÕES ANALÍTICAS (VISÃO 1: PRIORIDADE PURA | VISÃO 2: OPERACIONAL COM CONTROL_DESP)

-- VISÃO 1: Visão Pura de Prioridade (Equipamento & CI) - Estrita e Independente de CONTROL_DESP
CREATE OR REPLACE VIEW public.vw_priorizador_prioridade_pura AS
SELECT 
    o.ordem,
    CASE 
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200 THEN 1
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') THEN 2
        WHEN o.ci >= 200 THEN 3
        ELSE 4
    END AS prioridade_rank,
    CASE 
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200 THEN '⚡ PRIORIDADE ELEVADA (EQ + CI > 200)'
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') THEN '🔴 EQUIPAMENTO CRÍTICO DE REDE'
        WHEN o.ci >= 200 THEN '🟠 GRANDE CI (CI ≥ 200)'
        ELSE '⚪ CONVENCIONAL'
    END AS prioridade_label,
    o.eq,
    o.facility,
    o.alimentador,
    o.ci,
    o.chi,
    o.num_recla,
    o.base_op,
    o.regiao,
    o.dur_min,
    o.equipe_codigo,
    o.supervisor_responsavel,
    o.status_supervisao,
    o.is_active,
    o.atualizado_em
FROM public.priorizador_active_orders o
WHERE o.is_active = TRUE
ORDER BY prioridade_rank ASC, o.ci DESC, o.chi DESC;

-- VISÃO 2: Visão Operacional com a coluna CONTROL_DESP atrelada às Prioridades
CREATE OR REPLACE VIEW public.vw_priorizador_operacional_despacho AS
SELECT 
    o.ordem,
    CASE 
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200 THEN 1
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') THEN 2
        WHEN o.ci >= 200 THEN 3
        ELSE 4
    END AS prioridade_rank,
    CASE 
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200 THEN '⚡ ELEVADA'
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') THEN '🔴 EQ CRÍTICO'
        WHEN o.ci >= 200 THEN '🟠 GRANDE CI'
        ELSE '⚪ CONVENCIONAL'
    END AS prioridade_curta,
    o.control_desp,
    CASE
        WHEN o.control_desp ILIKE '%AGUARD%' THEN 'AGUARDANDO_DESPACHO'
        WHEN o.control_desp ILIKE '%CAMI%' THEN 'A_CAMINHO'
        WHEN o.control_desp ILIKE '%>=80%' THEN 'NO_LOCAL_MAIOR_80MIN'
        WHEN o.control_desp ILIKE '%LOCAL_%' THEN 'NO_LOCAL_MENOR_80MIN'
        ELSE 'OUTROS'
    END AS status_despacho_tipo,
    CASE
        WHEN (UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200) AND o.control_desp ILIKE '%AGUARD%' 
            THEN '🚨 CRÍTICO SEM DESPACHO'
        WHEN (UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.ci > 200) AND o.control_desp ILIKE '%>=80%' 
            THEN '⏱️ CRÍTICO PRESO NO LOCAL (>=80MIN)'
        WHEN UPPER(o.eq) IN ('DJ', 'RA', 'CF', 'CA', 'BF', 'CH', 'RM') AND o.control_desp ILIKE '%AGUARD%' 
            THEN '⏳ REDE AGUARDANDO DESPACHO'
        WHEN o.ci >= 200 AND o.control_desp ILIKE '%AGUARD%' 
            THEN '⏳ GRANDE CI AGUARDANDO DESPACHO'
        WHEN o.control_desp ILIKE '%>=80%' 
            THEN '⏱️ LOCAL >= 80 MIN'
        ELSE o.control_desp
    END AS cruzamento_operacional_label,
    o.eq,
    o.facility,
    o.alimentador,
    o.ci,
    o.chi,
    o.num_recla,
    o.base_op,
    o.regiao,
    o.dur_min,
    o.equipe_codigo,
    o.supervisor_responsavel,
    o.status_supervisao,
    o.is_active,
    o.atualizado_em
FROM public.priorizador_active_orders o
WHERE o.is_active = TRUE
ORDER BY prioridade_rank ASC, o.ci DESC, o.chi DESC;

-- Permissões para as Views
GRANT SELECT ON public.vw_priorizador_prioridade_pura TO anon, authenticated;
GRANT SELECT ON public.vw_priorizador_operacional_despacho TO anon, authenticated;

-- 8. HABILITAÇÃO OPCIONAL PARA SUPABASE REALTIME (NOTIFICAÇÕES EM TEMPO REAL)
DO $$
BEGIN
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.priorizador_active_orders;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
    BEGIN
        ALTER PUBLICATION supabase_realtime ADD TABLE public.priorizador_supervisor_timeline;
    EXCEPTION WHEN OTHERS THEN NULL;
    END;
END $$;

-- 9. RECARREGAMENTO DO CACHE DO POSTGREST NO SUPABASE
NOTIFY pgrst, 'reload schema';
