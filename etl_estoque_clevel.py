"""
ETL Pipeline: NexusOps Executive Stock Analytics (C-Level)
Lê a planilha 'Saidas Estoque Consolidado.xlsx' (25.279 registros), realiza limpeza,
enriquecimento estatístico e prepara os dados para carga no Supabase e cache analítico local.
"""

import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
import requests

# Ajuste de Fuso Horário de Brasília
BR_TZ = timezone(timedelta(hours=-3))

EXCEL_PATH = r"C:\Users\robym\Desktop\Documentos\Analise de dados\Painel C Level Gualberto\Saidas Estoque Consolidado.xlsx"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CACHE_JSON_PATH = os.path.join(DATA_DIR, "estoque_clevel_consolidado.json")

# Configuração do Supabase
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xgfawbqllikosyngfvwa.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_uDfIgt5BLYkRJMU540FMcA_LbaubJox")
BASE_REST_URL = SUPABASE_URL.rstrip('/')
if not BASE_REST_URL.endswith('/rest/v1'):
    BASE_REST_URL = f"{BASE_REST_URL}/rest/v1"

def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

def inferir_categoria_analitica(descricao: str, grupo_original: str) -> str:
    desc = str(descricao or "").lower()
    grp = str(grupo_original or "").upper()
    
    if any(k in desc for k in ['chuva', 'bota pvc', 'capa de chuva', 'impermeav']):
        return 'EPI Chuva'
    if 'EPI' in grp:
        return 'EPI'
    if 'FERRAMENTAL' in grp:
        return 'Ferramental'
    if 'EPC' in grp:
        return 'EPC'
    if 'VEICULO' in grp or 'VEÍCULO' in grp or 'FROTA' in grp:
        return 'Frota'
    if 'CONSUMO' in grp or any(k in desc for k in ['fita', 'conector', 'cabo', 'parafuso', 'abraçadeira']):
        return 'Insumo'
    if any(k in desc for k in ['termovisor', 'megometro', 'megômetro', 'detector', 'dinamometro']):
        return 'Instrumentação Especial'
    return 'Geral'

def estimar_vida_util_teorica(descricao: str) -> int:
    d = str(descricao or "").lower()
    if 'disco' in d or 'fita' in d or 'fusivel' in d or 'fusível' in d:
        return 15
    if 'luva' in d:
        return 30
    if 'óculos' in d or 'oculos' in d:
        return 45
    if 'capa de chuva' in d or 'bota' in d:
        return 90
    if 'capacete' in d:
        return 180
    if 'alicate' in d or 'chave' in d:
        return 240
    if 'cinto' in d or 'talabarte' in d:
        return 360
    if any(k in d for k in ['guincho', 'vara de manobra', 'termovisor', 'megometro']):
        return 720
    return 45

def processar_planilha_estoque(excel_file_path=EXCEL_PATH):
    print(f"[*] Iniciando leitura da planilha: {excel_file_path}")
    if not os.path.exists(excel_file_path):
        raise FileNotFoundError(f"Arquivo Excel não encontrado: {excel_file_path}")

    df = pd.read_excel(excel_file_path)
    total_linhas = len(df)
    print(f"[+] Total de linhas lidas: {total_linhas:,}")

    # Garante diretório data/
    os.makedirs(DATA_DIR, exist_ok=True)

    registros = []
    
    for idx, row in df.iterrows():
        # 1. Sistema
        sistema = str(row.get('Sistema', 'SAP')).strip()
        
        # 2. Data de Saída
        val_data = row.get('Data de Saida')
        if pd.isna(val_data):
            dt_obj = datetime(2026, 6, 15)
        elif isinstance(val_data, datetime):
            dt_obj = val_data
        else:
            try:
                dt_obj = pd.to_datetime(val_data).to_pydatetime()
            except Exception:
                dt_obj = datetime(2026, 6, 15)

        ano = dt_obj.year
        mes = dt_obj.month
        dia = dt_obj.day
        # Regime Pluvial SP: Nov, Dez, Jan, Fev, Mar
        is_rain = mes in [11, 12, 1, 2, 3]

        # 3. Descrição / Material
        descricao = str(row.get('Descrição', 'ITEM SEM DESCRIÇÃO')).strip()
        
        # 4. Grupo
        grupo = str(row.get('Grupo', 'GERAL')).strip()
        categoria_analitica = inferir_categoria_analitica(descricao, grupo)

        # 5. Quantidade
        try:
            val_qtd = row.get('Qtde', 1)
            qtde = float(val_qtd) if pd.notna(val_qtd) and float(val_qtd) > 0 else 1.0
        except Exception:
            qtde = 1.0

        # 6. Preço Unitário
        try:
            val_punit = row.get('Preço Unitario', 0.0)
            preco_unitario = float(val_punit) if pd.notna(val_punit) and float(val_punit) >= 0 else 0.0
        except Exception:
            preco_unitario = 0.0

        # 7. Valor Total
        try:
            val_total = row.get('Valor', 0.0)
            valor_total = float(val_total) if pd.notna(val_total) and float(val_total) >= 0 else (qtde * preco_unitario)
        except Exception:
            valor_total = qtde * preco_unitario

        # 8. Responsável Saída
        responsavel = str(row.get('REPONSAVEL SAIDA', 'COLABORADOR NÃO IDENTIFICADO')).strip()

        # 9. Matrícula
        val_mat = row.get('Matricula', '')
        matricula = str(val_mat).strip() if pd.notna(val_mat) else ''

        # 10. Setor
        setor = str(row.get('Setor', 'OPERAÇÃO')).strip()
        if setor.lower() == 'nan' or not setor:
            setor = 'NÃO INFORMADO'

        # 11. Base
        base_raw = str(row.get('Base', '')).strip().upper()
        if 'ITAQUERA' in base_raw:
            base = 'BASE ITAQUERA'
        elif 'IPIRANGA' in base_raw:
            base = 'BASE IPIRANGA'
        else:
            base = 'BASE IPIRANGA'  # Fallback para as 10 linhas sem base especificada

        # 12. Função
        funcao = str(row.get('Função', '')).strip()
        if funcao.lower() == 'nan':
            funcao = ''

        vida_util = estimar_vida_util_teorica(descricao)

        registro = {
            "id": idx + 1,
            "sistema": sistema,
            "data_saida": dt_obj.strftime("%Y-%m-%d"),
            "data_iso": dt_obj.isoformat(),
            "ano": ano,
            "mes": mes,
            "dia": dia,
            "descricao": descricao,
            "grupo": grupo,
            "categoria_analitica": categoria_analitica,
            "qtde": round(qtde, 2),
            "preco_unitario": round(preco_unitario, 2),
            "valor_total": round(valor_total, 2),
            "responsavel_saida": responsavel,
            "matricula": matricula,
            "setor": setor,
            "base": base,
            "funcao": funcao,
            "is_rain_season": is_rain,
            "vida_util_teorica_dias": vida_util
        }
        registros.append(registro)

    print(f"[✓] {len(registros):,} registros estruturados com sucesso!")

    # Salva cache JSON local com todos os 25.279 registros
    print(f"[*] Gravando cache consolidado em: {CACHE_JSON_PATH}")
    with open(CACHE_JSON_PATH, 'w', encoding='utf-8') as f:
        json.dump(registros, f, ensure_ascii=False, indent=None)

    file_size_mb = os.path.getsize(CACHE_JSON_PATH) / (1024 * 1024)
    print(f"[✓] Cache local gerado: {file_size_mb:.2f} MB")

    return registros

def sincronizar_com_supabase(registros=None, chunk_size=1000):
    """
    Insere os registros na tabela 'saidas_estoque_consolidado' do Supabase via PostgREST.
    """
    if not registros:
        if not os.path.exists(CACHE_JSON_PATH):
            print("[!] Cache local não encontrado. Executando processamento primeiro...")
            registros = processar_planilha_estoque()
        else:
            with open(CACHE_JSON_PATH, 'r', encoding='utf-8') as f:
                registros = json.load(f)

    endpoint = f"{BASE_REST_URL}/saidas_estoque_consolidado"
    headers = get_supabase_headers()

    print(f"[*] Tentando enviar {len(registros):,} linhas para o Supabase: {endpoint}")

    # Prepara payload compatível com Supabase
    sucessos = 0
    total = len(registros)

    for i in range(0, total, chunk_size):
        chunk = registros[i:i + chunk_size]
        payload = []
        for r in chunk:
            payload.append({
                "sistema": r["sistema"],
                "data_saida": r["data_iso"],
                "ano": r["ano"],
                "mes": r["mes"],
                "dia": r["dia"],
                "descricao": r["descricao"],
                "grupo": r["grupo"],
                "categoria_analitica": r["categoria_analitica"],
                "qtde": r["qtde"],
                "preco_unitario": r["preco_unitario"],
                "valor_total": r["valor_total"],
                "responsavel_saida": r["responsavel_saida"],
                "matricula": r["matricula"],
                "setor": r["setor"],
                "base": r["base"],
                "funcao": r["funcao"],
                "is_rain_season": r["is_rain_season"],
                "vida_util_teorica_dias": r["vida_util_teorica_dias"]
            })

        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=30)
            if resp.status_code in [200, 201]:
                sucessos += len(chunk)
                print(f"    [+] Lote inserido: {sucessos:,}/{total:,} linhas...")
            elif resp.status_code == 404:
                print(f"[!] Tabela 'saidas_estoque_consolidado' não localizada no Supabase (código 404).")
                print("    Execute o script 'schema_saidas_estoque_c_level.sql' no SQL Editor do Supabase primeiro.")
                return False
            else:
                print(f"[!] Erro ao inserir lote {i}-{i+chunk_size}: HTTP {resp.status_code} - {resp.text[:200]}")
        except Exception as e:
            print(f"[!] Exceção na inserção de lote: {e}")
            break

    if sucessos > 0:
        print(f"[✓] Sincronização com Supabase concluída: {sucessos:,} linhas enviadas!")
        return True
    return False

if __name__ == "__main__":
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    registros = processar_planilha_estoque()
    sincronizar_com_supabase(registros)
