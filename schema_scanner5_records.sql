-- ==============================================================================
-- TABELA: public.team_scanner_records
-- FONTE: TIBCO Spotfire - Dashboard Scanner 5.0 (Tab Completa)
-- ESTRUTURA: 1 linha por equipe por dia (98 colunas analíticas oficiais)
-- ==============================================================================

CREATE TABLE IF NOT EXISTS public.team_scanner_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    data_referencia DATE NOT NULL,
    equipe TEXT NOT NULL,
    equipe_normalizada TEXT NOT NULL,
    
    -- 1. Identificação e Jornada
    inicio_calendario TEXT,
    login TEXT,
    fim_calendario TEXT,
    logoff TEXT,
    primeiro_login TEXT,
    inicio_intervalo TEXT,
    fim_intervalo TEXT,
    intervalo TEXT,
    base TEXT,
    periodo TEXT,
    origem TEXT,
    
    -- 2. Operação e Ordens
    nr_ordem TEXT,
    equipe1 TEXT,
    despachada TEXT,
    a_caminho TEXT,
    no_local TEXT,
    liberada TEXT,
    minutos NUMERIC DEFAULT 0,
    ups_executada TEXT,
    classe TEXT,
    descricao_classe TEXT,
    causa TEXT,
    descricao_causa TEXT,
    componente TEXT,
    estado_servico TEXT,
    fases TEXT,
    tipo_classe TEXT,
    qtd_task INT DEFAULT 0,
    tempo_padrao NUMERIC DEFAULT 0,
    observacao TEXT,
    qtd_servicos INT DEFAULT 0,
    verifica_repetidos_ht TEXT,
    
    -- 3. Deslocamentos e Tempos HT / TL / TR / HP
    hora_primeiro_deslocamento TEXT,
    hora_primeiro_despacho TEXT,
    qtd_deslocamentos INT DEFAULT 0,
    hora_ultima_ordem TEXT,
    ht_ordem NUMERIC DEFAULT 0,
    ht_total NUMERIC DEFAULT 0,
    tl_ordem NUMERIC DEFAULT 0,
    tl_total NUMERIC DEFAULT 0,
    tr_ordem NUMERIC DEFAULT 0,
    tr_total NUMERIC DEFAULT 0,
    hp_ordem NUMERIC DEFAULT 0,
    hp_total NUMERIC DEFAULT 0,
    qtd_equipes_os INT DEFAULT 0,
    soma_desl_ativ NUMERIC DEFAULT 0,
    conta_task_time_tr NUMERIC DEFAULT 0,
    conta_task_time_tl NUMERIC DEFAULT 0,
    task_time_total_tr NUMERIC DEFAULT 0,
    task_time_total_tl NUMERIC DEFAULT 0,
    media_qtd_servicos NUMERIC DEFAULT 0,
    tr_ordem_secundario NUMERIC DEFAULT 0,
    tr_ordem_imp_ss NUMERIC DEFAULT 0,
    tr_ordem_secundario_equipe NUMERIC DEFAULT 0,
    tr_ordem_imp_ss_equipe NUMERIC DEFAULT 0,
    
    -- 4. Tipologia de OS (Projeto, Poda, Recolha, TMA, Improdutiva, P2)
    os_projeto INT DEFAULT 0,
    os_poda INT DEFAULT 0,
    os_recolha INT DEFAULT 0,
    os_tma INT DEFAULT 0,
    os_projeto_total INT DEFAULT 0,
    os_poda_total INT DEFAULT 0,
    os_recolha_total INT DEFAULT 0,
    os_tma_total INT DEFAULT 0,
    atuacao TEXT,
    os_improdutiva INT DEFAULT 0,
    os_improdutiva_total INT DEFAULT 0,
    os_p2 INT DEFAULT 0,
    os_p2_total INT DEFAULT 0,
    
    -- 5. Veículo, Plataforma, Desvios e Filtros
    fonte TEXT,
    placa TEXT,
    tempo_plataforma NUMERIC DEFAULT 0,
    filtro_repetido_equipe_data TEXT,
    login_corrigido TEXT,
    logoff_corrigido TEXT,
    hd_total NUMERIC DEFAULT 0,
    primeiro_desloc TEXT,
    primeiro_despacho TEXT,
    plataforma TEXT,
    retorno_base TEXT,
    mes TEXT,
    desvios TEXT,
    ano INT,
    primeiro_login_corrigido TEXT,
    filtro_ordens TEXT,
    ht_p2 NUMERIC DEFAULT 0,
    ht_p2_total NUMERIC DEFAULT 0,
    horas_extras TEXT,
    filtro_palavra_chave TEXT,
    semana INT,
    base_responsavel TEXT,
    dia INT,
    tipo_equipe TEXT,
    empresa TEXT,
    tipo_empresa TEXT,
    ut TEXT,
    semana_mes TEXT,
    micro_regiao TEXT,
    tr_ordem_imp_m300 NUMERIC DEFAULT 0,
    
    -- 6. Armazenamento Bruto Integral e Metadados
    raw_data JSONB DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- CONSTRAINT ÚNICA: 1 linha por equipe por data de referência
    CONSTRAINT uq_scanner_date_team UNIQUE (data_referencia, equipe_normalizada)
);

-- Índices de Alta Performance
CREATE INDEX IF NOT EXISTS idx_scanner_date ON public.team_scanner_records(data_referencia);
CREATE INDEX IF NOT EXISTS idx_scanner_team ON public.team_scanner_records(equipe_normalizada);
CREATE INDEX IF NOT EXISTS idx_scanner_base ON public.team_scanner_records(base);
CREATE INDEX IF NOT EXISTS idx_scanner_periodo ON public.team_scanner_records(periodo);

-- Habilita Row Level Security (RLS) com políticas para anon e authenticated
ALTER TABLE public.team_scanner_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon select scanner" ON public.team_scanner_records;
CREATE POLICY "Allow anon select scanner" ON public.team_scanner_records FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert scanner" ON public.team_scanner_records;
CREATE POLICY "Allow anon insert scanner" ON public.team_scanner_records FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update scanner" ON public.team_scanner_records;
CREATE POLICY "Allow anon update scanner" ON public.team_scanner_records FOR UPDATE TO anon, authenticated USING (true);
