-- ==============================================================================
-- SCHEMA SUPABASE: PAINEL EXECUTIVO C-LEVEL - GESTÃO ESTRATÉGICA DE ESTOQUE
-- MÓDULO: NEXUSOPS EXECUTIVE STOCK ANALYTICS (BASES IPIRANGA & ITAQUERA)
-- ==============================================================================

-- 1. Criação da Tabela Consolidada de Saídas de Estoque (25.279 registros)
CREATE TABLE IF NOT EXISTS public.saidas_estoque_consolidado (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sistema VARCHAR(50) DEFAULT 'SAP',
    data_saida TIMESTAMPTZ NOT NULL,
    ano INT NOT NULL,
    mes INT NOT NULL,
    dia INT NOT NULL,
    descricao TEXT NOT NULL,
    grupo VARCHAR(100) NOT NULL,
    categoria_analitica VARCHAR(100) NOT NULL DEFAULT 'Geral',
    qtde NUMERIC(12, 2) NOT NULL DEFAULT 1.0,
    preco_unitario NUMERIC(12, 2) NOT NULL DEFAULT 0.0,
    valor_total NUMERIC(12, 2) NOT NULL DEFAULT 0.0,
    responsavel_saida VARCHAR(255) NOT NULL,
    matricula VARCHAR(50) DEFAULT '',
    setor VARCHAR(255) DEFAULT '',
    base VARCHAR(100) NOT NULL,
    funcao VARCHAR(150) DEFAULT '',
    is_rain_season BOOLEAN NOT NULL DEFAULT FALSE,
    vida_util_teorica_dias INT DEFAULT 45,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Índices de Alta Performance para Consultas e Agregações Instantâneas
CREATE INDEX IF NOT EXISTS idx_saidas_data ON public.saidas_estoque_consolidado (data_saida DESC);
CREATE INDEX IF NOT EXISTS idx_saidas_base ON public.saidas_estoque_consolidado (base);
CREATE INDEX IF NOT EXISTS idx_saidas_grupo ON public.saidas_estoque_consolidado (grupo);
CREATE INDEX IF NOT EXISTS idx_saidas_categoria ON public.saidas_estoque_consolidado (categoria_analitica);
CREATE INDEX IF NOT EXISTS idx_saidas_responsavel ON public.saidas_estoque_consolidado (responsavel_saida);
CREATE INDEX IF NOT EXISTS idx_saidas_descricao ON public.saidas_estoque_consolidado (descricao);
CREATE INDEX IF NOT EXISTS idx_saidas_rain ON public.saidas_estoque_consolidado (is_rain_season);
CREATE INDEX IF NOT EXISTS idx_saidas_base_grupo ON public.saidas_estoque_consolidado (base, grupo);
CREATE INDEX IF NOT EXISTS idx_saidas_resp_data ON public.saidas_estoque_consolidado (responsavel_saida, data_saida);
CREATE INDEX IF NOT EXISTS idx_saidas_material_data ON public.saidas_estoque_consolidado (descricao, data_saida);

-- 3. Habilitação de RLS (Row Level Security) e Políticas de Acesso
ALTER TABLE public.saidas_estoque_consolidado ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow anon select saidas_estoque_consolidado" ON public.saidas_estoque_consolidado;
CREATE POLICY "Allow anon select saidas_estoque_consolidado" 
    ON public.saidas_estoque_consolidado FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon insert saidas_estoque_consolidado" ON public.saidas_estoque_consolidado;
CREATE POLICY "Allow anon insert saidas_estoque_consolidado" 
    ON public.saidas_estoque_consolidado FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow anon update saidas_estoque_consolidado" ON public.saidas_estoque_consolidado;
CREATE POLICY "Allow anon update saidas_estoque_consolidado" 
    ON public.saidas_estoque_consolidado FOR UPDATE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow anon delete saidas_estoque_consolidado" ON public.saidas_estoque_consolidado;
CREATE POLICY "Allow anon delete saidas_estoque_consolidado" 
    ON public.saidas_estoque_consolidado FOR DELETE TO anon, authenticated USING (true);

-- 4. Comentários Documentais na Tabela
COMMENT ON TABLE public.saidas_estoque_consolidado IS 'Tabela consolidada de saídas de materiais das bases Ipiranga e Itaquera para o Painel C-Level';
COMMENT ON COLUMN public.saidas_estoque_consolidado.is_rain_season IS 'Indica se a saída ocorreu no período de alta pluviosidade em SP (Nov a Mar)';
COMMENT ON COLUMN public.saidas_estoque_consolidado.vida_util_teorica_dias IS 'Vida útil estimada em dias para cálculo de MTBR e desgaste precoce';
