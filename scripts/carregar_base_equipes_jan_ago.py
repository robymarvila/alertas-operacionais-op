"""
Script de Carga e Saneamento das Equipes Históricas (Janeiro a Agosto de 2026)
Fonte: C:\\Users\\robym\\Desktop\\Documentos\\Base_Equipes\\Equipe

Regras de Negócio Aplicadas:
1. Filtro estrito pelas 7 bases operacionais oficiais da Alpitel:
   ENL, ECL, EEL (Norte) | EML, EQL, EVL, ESL (Leste)
2. Regras Mandatórias de Presença / Log In e Log Off:
   - Se 'Log In Corrigido' e 'Log Off Corrigido' estiverem ambos vazios -> DESCARTADA (equipe não logada).
   - Se 'Log In Corrigido' vazio e 'Log Off Corrigido' preenchido -> usa 'Inicio Calendario'.
   - Se 'Log Off Corrigido' vazio e 'Log In Corrigido' preenchido -> usa 'Fim Calendario'.
3. Normalização estrita de data: DD/MM/YYYY -> ISO YYYY-MM-DD.
4. Deduplicação atômica por (data_referencia, equipe_normalizada).
5. Persistência no Supabase via UPSERT atômico em lotes de 500 registros.
"""

import os
import sys
import glob
import time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import requests
import pandas as pd
from datetime import datetime
from supabase_client import BASE_REST_URL, get_headers
from coletor_spotfire_cdp import (
    TARGET_PREFIXES, normalize_team_code, to_str, to_int, to_float,
    get_col_val, format_date_str
)

FOLDER_PATH = r"C:\Users\robym\Desktop\Documentos\Base_Equipes\Equipe"

def tentar_limpar_dados_anteriores_a_setembro():
    """Tenta excluir registros anteriores a 01/09/2026 via REST API do Supabase."""
    headers = get_headers()
    print("[SUPABASE CLEANUP] Verificando registros para data_referencia < 2026-09-01...")
    try:
        r_chk = requests.get(
            f"{BASE_REST_URL}/team_scanner_records?data_referencia=lt.2026-09-01&select=data_referencia",
            headers={**headers, "Prefer": "count=exact"},
            timeout=10
        )
        total_old = r_chk.headers.get("content-range", "").split("/")[-1]
        print(f"[SUPABASE CLEANUP] Total de registros anteriores a Setembro encontrados: {total_old}")

        r_del = requests.delete(
            f"{BASE_REST_URL}/team_scanner_records?data_referencia=lt.2026-09-01",
            headers=headers,
            timeout=15
        )
        print(f"[SUPABASE CLEANUP] Resposta DELETE: Status {r_del.status_code}")
    except Exception as e:
        print(f"[SUPABASE CLEANUP WARN] Erro ao tentar DELETE: {e}")

def processar_arquivo_mensal(fpath: str) -> list:
    """Processa um arquivo mensal do Scanner 4.0 aplicando as regras mandatórias."""
    fname = os.path.basename(fpath)
    print(f"\n[PROCESSANDO] {fname}...")
    
    try:
        df = pd.read_csv(fpath, sep='\t', encoding='utf-16', low_memory=False)
    except Exception:
        df = pd.read_csv(fpath, sep='\t', encoding='utf-8', low_memory=False)
        
    date_col = next((c for c in df.columns if 'data' in c.lower() or 'refer' in c.lower()), 'Data Referência')
    
    seen = {}
    
    for row in df.to_dict('records'):
        raw_team = to_str(get_col_val(row, 'Equipe', 'equipe'))
        if not raw_team or raw_team.lower() in ['equipe', 'nan', 'total', 'subtotal']:
            continue
            
        norm_team = normalize_team_code(raw_team)
        if not norm_team or norm_team[:3] not in TARGET_PREFIXES:
            continue
            
        # Regras de Login e Logoff
        login_c = to_str(get_col_val(row, 'Log In Corrigido', 'Login Corrigido'))
        logoff_c = to_str(get_col_val(row, 'Log Off Corrigido', 'Logoff Corrigido'))
        inicio_cal = to_str(get_col_val(row, 'Inicio Calendario', 'Inicio Calendário', 'Início Calendário'))
        fim_cal = to_str(get_col_val(row, 'Fim Calendario', 'Fim Calendário'))
        
        # Regra 1: Descartar se ambos vazios
        if not login_c and not logoff_c:
            continue
            
        # Regra 2: Login vazio com logoff -> usa inicio_calendario
        if not login_c and logoff_c:
            login_c = inicio_cal
            
        # Regra 3: Logoff vazio com login -> usa fim_calendario
        if not logoff_c and login_c:
            logoff_c = fim_cal
            
        # Data estrita como DD/MM/YYYY -> YYYY-MM-DD
        raw_dt = str(row.get(date_col, '')).strip()
        pts = raw_dt.split('/')
        if len(pts) == 3:
            day, mo, yr = int(pts[0]), int(pts[1]), int(pts[2][:4])
            iso_dt = f"{yr:04d}-{mo:02d}-{day:02d}"
        else:
            iso_dt = format_date_str(raw_dt)
            
        k = (iso_dt, norm_team)
        
        rec = {
            "data_referencia": iso_dt,
            "equipe": raw_team,
            "equipe_normalizada": norm_team,
            "inicio_calendario": inicio_cal,
            "login": to_str(get_col_val(row, 'Log In', 'Login')) or login_c,
            "fim_calendario": fim_cal,
            "logoff": to_str(get_col_val(row, 'Log Off', 'Logoff')) or logoff_c,
            "primeiro_login": to_str(get_col_val(row, '1º Login', '1o Login', '1 Login')),
            "inicio_intervalo": to_str(get_col_val(row, 'Inicio Intervalo', 'Início Intervalo')),
            "fim_intervalo": to_str(get_col_val(row, 'Fim Intervalo')),
            "intervalo": to_str(get_col_val(row, 'Intervalo')),
            "base": to_str(get_col_val(row, 'BASE', 'Base')),
            "periodo": to_str(get_col_val(row, 'Período', 'Periodo', 'Perodo')),
            "origem": to_str(get_col_val(row, 'Origem')),
            "nr_ordem": to_str(get_col_val(row, 'Nr_Ordem', 'Nr Ordem')),
            "equipe1": to_str(get_col_val(row, 'Equipe1')),
            "despachada": to_str(get_col_val(row, 'Despachada')),
            "a_caminho": to_str(get_col_val(row, 'A_Caminho', 'A Caminho')),
            "no_local": to_str(get_col_val(row, 'No_Local', 'No Local')),
            "liberada": to_str(get_col_val(row, 'Liberada')),
            "minutos": to_float(get_col_val(row, 'Minutos')),
            "ups_executada": to_str(get_col_val(row, 'UPSExecutada')),
            "classe": to_str(get_col_val(row, 'Classe')),
            "descricao_classe": to_str(get_col_val(row, 'Descrição_Classe', 'Descricao_Classe', 'Descrio_Classe')),
            "causa": to_str(get_col_val(row, 'Causa')),
            "descricao_causa": to_str(get_col_val(row, 'Descrição_Causa', 'Descricao_Causa', 'Descrio_Causa')),
            "componente": to_str(get_col_val(row, 'Componente')),
            "estado_servico": to_str(get_col_val(row, 'Estado+Servico', 'Estado Servico')),
            "fases": to_str(get_col_val(row, 'Fases')),
            "tipo_classe": to_str(get_col_val(row, 'Tipo_Classe', 'Tipo Classe')),
            "qtd_task": to_int(get_col_val(row, 'Qtd Task')),
            "tempo_padrao": to_float(get_col_val(row, 'Tempo Padrao', 'Tempo Padrão')),
            "observacao": to_str(get_col_val(row, 'Observação', 'Observacao', 'Observao')),
            "qtd_servicos": to_int(get_col_val(row, 'Qtd Serviços', 'Qtd Servicos', 'Qtd Servios')),
            "verifica_repetidos_ht": to_str(get_col_val(row, 'VerificaRepetidosHT')),
            "hora_primeiro_deslocamento": to_str(get_col_val(row, 'Hora 1º Deslocamento', 'Hora 1o Deslocamento', 'Hora 1 Deslocamento')),
            "hora_primeiro_despacho": to_str(get_col_val(row, 'Hora 1º Despacho', 'Hora 1o Despacho', 'Hora 1 Despacho')),
            "qtd_deslocamentos": to_int(get_col_val(row, 'Qtd Deslocamentos')),
            "hora_ultima_ordem": to_str(get_col_val(row, 'Hora Ultima Ordem', 'Hora Última Ordem')),
            "ht_ordem": to_float(get_col_val(row, 'HT Ordem')),
            "ht_total": to_float(get_col_val(row, 'HT total', 'HT Total')),
            "tl_ordem": to_float(get_col_val(row, 'TL Ordem')),
            "tl_total": to_float(get_col_val(row, 'TL Total', 'TL total')),
            "tr_ordem": to_float(get_col_val(row, 'TR Ordem')),
            "tr_total": to_float(get_col_val(row, 'TR Total', 'TR total')),
            "hp_ordem": to_float(get_col_val(row, 'HP Ordem')),
            "hp_total": to_float(get_col_val(row, 'HP Total', 'HP total')),
            "qtd_equipes_os": to_int(get_col_val(row, 'Qtd Equipes OS')),
            "soma_desl_ativ": to_float(get_col_val(row, 'Soma De Desl/Ativ')),
            "conta_task_time_tr": to_float(get_col_val(row, 'Conta Task Time tr', 'Conta Task Time TR')),
            "conta_task_time_tl": to_float(get_col_val(row, 'Conta task Time TL', 'Conta Task Time TL')),
            "task_time_total_tr": to_float(get_col_val(row, 'Task Time Total TR')),
            "task_time_total_tl": to_float(get_col_val(row, 'Task Time Total TL')),
            "media_qtd_servicos": to_float(get_col_val(row, 'Média Qtd Serviços', 'Media Qtd Servicos', 'Mdia Qtd Servios')),
            "tr_ordem_secundario": to_float(get_col_val(row, 'TR Ordem Secundário', 'TR Ordem Secundario', 'TR Ordem Secundrio')),
            "tr_ordem_imp_ss": to_float(get_col_val(row, 'TR Ordem Imp SS')),
            "tr_ordem_secundario_equipe": to_float(get_col_val(row, 'TR Ordem Sencundário equipe', 'TR Ordem Secundario equipe', 'TR Ordem Sencundrio equipe')),
            "tr_ordem_imp_ss_equipe": to_float(get_col_val(row, 'TR Ordem Imp SS equipe')),
            "os_projeto": to_int(get_col_val(row, 'OS Projeto')),
            "os_poda": to_int(get_col_val(row, 'OS PODA', 'OS Poda')),
            "os_recolha": to_int(get_col_val(row, 'OS Recolha')),
            "os_tma": to_int(get_col_val(row, 'OS TMA')),
            "os_projeto_total": to_int(get_col_val(row, 'OS Projeto Total')),
            "os_poda_total": to_int(get_col_val(row, 'OS Poda Total')),
            "os_recolha_total": to_int(get_col_val(row, 'OS Recolha Total')),
            "os_tma_total": to_int(get_col_val(row, 'OS TMA Total')),
            "atuacao": to_str(get_col_val(row, 'Atuação', 'Atuacao', 'Atuao')),
            "os_improdutiva": to_int(get_col_val(row, 'OS improdutiva', 'OS Improdutiva')),
            "os_improdutiva_total": to_int(get_col_val(row, 'OS  Improdutivda Total', 'OS Improdutiva Total')),
            "os_p2": to_int(get_col_val(row, 'OS P2')),
            "os_p2_total": to_int(get_col_val(row, 'OS P2 Total')),
            "fonte": to_str(get_col_val(row, 'Fonte')),
            "placa": to_str(get_col_val(row, 'Placa')),
            "tempo_plataforma": to_float(get_col_val(row, 'Tempo_Plataforma', 'Tempo Plataforma')),
            "filtro_repetido_equipe_data": to_str(get_col_val(row, 'FiltroRepetidoEquipeData')),
            "login_corrigido": login_c,
            "logoff_corrigido": logoff_c,
            "hd_total": to_float(get_col_val(row, 'HD Total')),
            "primeiro_desloc": to_str(get_col_val(row, '1º Desloc', '1o Desloc', '1 Desloc')),
            "primeiro_despacho": to_str(get_col_val(row, '1º Despacho', '1o Despacho', '1 Despacho')),
            "plataforma": to_str(get_col_val(row, 'Plataforma')),
            "retorno_base": to_str(get_col_val(row, 'Retorno a base', 'Retorno a Base')),
            "mes": to_str(get_col_val(row, 'Mês', 'Mes', 'Ms')),
            "desvios": to_str(get_col_val(row, 'Desvios')),
            "ano": to_int(get_col_val(row, 'Ano')),
            "primeiro_login_corrigido": to_str(get_col_val(row, '1º Login Corrigido', '1o Login Corrigido', '1 Login Corrigido')),
            "filtro_ordens": to_str(get_col_val(row, 'FiltroOrdens')),
            "ht_p2": to_float(get_col_val(row, 'HT P2')),
            "ht_p2_total": to_float(get_col_val(row, 'HT P2 Total')),
            "horas_extras": to_str(get_col_val(row, 'Horas Extras')),
            "filtro_palavra_chave": to_str(get_col_val(row, 'FiltroPalavraChave')),
            "semana": to_int(get_col_val(row, 'Semana')),
            "base_responsavel": to_str(get_col_val(row, 'BaseResponsavel', 'Base Responsavel')),
            "dia": to_int(get_col_val(row, 'DIA', 'Dia')),
            "tipo_equipe": to_str(get_col_val(row, 'TIPO_EQUIPE', 'Tipo Equipe')),
            "empresa": to_str(get_col_val(row, 'EMPRESA', 'Empresa')),
            "tipo_empresa": to_str(get_col_val(row, 'TIPO_EMPRESA', 'Tipo Empresa')),
            "ut": to_str(get_col_val(row, 'UT', 'Ut')),
            "semana_mes": to_str(get_col_val(row, 'SEMANA_MES', 'Semana Mes')),
            "micro_regiao": to_str(get_col_val(row, 'MICRO_REGIAO', 'Micro Regiao')),
            "tr_ordem_imp_m300": to_float(get_col_val(row, 'TR Ordem Imp M300'))
        }
        seen[k] = rec
        
    records = list(seen.values())
    print(f"  -> {len(records)} equipes operacionais validadas e deduplicadas.")
    return records

def upload_lote_supabase(records: list):
    """Realiza o UPSERT atômico em blocos de 500 registros."""
    endpoint = f"{BASE_REST_URL}/team_scanner_records?on_conflict=data_referencia,equipe_normalizada"
    headers = get_headers().copy()
    headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    
    total = len(records)
    chunk_size = 500
    saved = 0
    
    for i in range(0, total, chunk_size):
        chunk = records[i:i+chunk_size]
        for attempt in range(3):
            try:
                resp = requests.post(endpoint, headers=headers, json=chunk, timeout=30)
                if resp.status_code in [200, 201]:
                    saved += len(chunk)
                    print(f"  [UPSERT] Progresso: {saved}/{total} registros salvos ({int(saved/total*100)}%)...", flush=True)
                    break
                else:
                    print(f"  [UPSERT WARN] Tentativa {attempt+1} falhou: HTTP {resp.status_code} - {resp.text[:100]}", flush=True)
                    time.sleep(2)
            except Exception as ex:
                print(f"  [UPSERT ERROR] Tentativa {attempt+1} exceção: {ex}", flush=True)
                time.sleep(2)
                
    return saved

def main():
    print("=" * 70)
    print("INICIANDO SANEAMENTO E CARGA HISTÓRICA DO SCANNER (JAN A AGO 2026)")
    print("=" * 70)
    
    tentar_limpar_dados_anteriores_a_setembro()
    
    files = sorted(glob.glob(os.path.join(FOLDER_PATH, "*.csv")))
    if not files:
        print(f"[ERRO] Nenhum arquivo CSV encontrado em {FOLDER_PATH}!")
        return
        
    total_geral = 0
    for fpath in files:
        recs = processar_arquivo_mensal(fpath)
        if recs:
            salvos = upload_lote_supabase(recs)
            total_geral += salvos
            
    print("\n" + "=" * 70)
    print(f"CONCLUÍDO! Total de equipes históricas enviadas com sucesso: {total_geral}")
    print("=" * 70)

if __name__ == '__main__':
    main()
