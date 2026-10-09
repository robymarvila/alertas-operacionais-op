import json
from collections import defaultdict
from datetime import datetime
import numpy as np

with open('data/estoque_clevel_consolidado.json', 'r', encoding='utf-8') as f:
    records = json.load(f)

# Vida útil teórica estimada por categoria ou tipo de material (dias)
THEORETICAL_LIFETIME = {
    'Linha Viva': 180,
    'EPI/EPC': 90,
    'Ferramentas': 180,
    'Conectores/Ferragens': 60,
    'Cabos e Fios': 90,
    'Iluminação Pública': 120,
    'Transformadores/Chaves': 365,
    'Combustível/Insumos Frota': 15,
    'Materiais de Consumo/Geral': 45
}

# Agrupar retiradas por Material e por Colaborador
user_item_dates = defaultdict(lambda: defaultdict(set))
item_all_dates = defaultdict(set)
item_metadata = {}

for r in records:
    mat = r.get('descricao', '').strip()
    resp = r.get('responsavel_saida', '').strip()
    dt_str = r.get('data_saida', '')
    cat = r.get('categoria_analitica', 'Materiais de Consumo/Geral')
    if not mat or not dt_str:
        continue
    
    dt = datetime.strptime(dt_str, '%Y-%m-%d')
    item_all_dates[mat].add(dt)
    if resp and resp.lower() != 'sem dados':
        user_item_dates[mat][resp].add(dt)
    
    if mat not in item_metadata:
        item_metadata[mat] = {
            'categoria': cat,
            'total_volume': 0,
            'total_custo': 0.0,
            'ocorrencias': 0
        }
    item_metadata[mat]['total_volume'] += r.get('qtde', 0)
    item_metadata[mat]['total_custo'] += r.get('valor_total', 0)
    item_metadata[mat]['ocorrencias'] += 1

results = []
for mat, users in user_item_dates.items():
    meta = item_metadata[mat]
    theo_days = THEORETICAL_LIFETIME.get(meta['categoria'], 60)
    
    # 1. Coletar intervalos entre re-trocas do mesmo colaborador
    user_intervals = []
    for resp, dt_set in users.items():
        if len(dt_set) > 1:
            sorted_dts = sorted(list(dt_set))
            for i in range(1, len(sorted_dts)):
                diff = (sorted_dts[i] - sorted_dts[i-1]).days
                if diff > 0:
                    user_intervals.append(diff)
    
    # 2. Se temos dados de re-troca de usuários, usamos a média
    if user_intervals:
        mtbr_real = float(np.median(user_intervals))  # mediana ou média robusta
        sample_type = f"Re-trocas ({len(user_intervals)} ciclos)"
    else:
        # Fallback: se nenhum colaborador pegou 2x, calcular intervalo entre dias de demanda do item
        distinct_days = sorted(list(item_all_dates[mat]))
        if len(distinct_days) > 1:
            diffs = [(distinct_days[i] - distinct_days[i-1]).days for i in range(1, len(distinct_days))]
            diffs_pos = [d for d in diffs if d > 0]
            mtbr_real = float(np.mean(diffs_pos)) if diffs_pos else 30.0
            sample_type = f"Ciclo Demanda ({len(distinct_days)} dias)"
        else:
            mtbr_real = float(theo_days)
            sample_type = "Saída Única"

    # Degradação / Stress
    degradacao = round(((theo_days - mtbr_real) / theo_days) * 100, 1)
    
    results.append({
        'material': mat,
        'categoria': meta['categoria'],
        'mtbr_real': round(mtbr_real, 1),
        'vida_util_teorica': theo_days,
        'degradacao_pct': degradacao,
        'total_events': meta['ocorrencias'],
        'volume': meta['total_volume'],
        'reincidentes': len(user_intervals),
        'sample_type': sample_type,
        'diagnostico': 'Desgaste Crítico / Re-troca Acelerada' if degradacao > 50 else ('Atenção Operacional' if degradacao > 20 else 'Ciclo Sustentável')
    })

print(f"Total materiais analisados: {len(results)}")
print("\nTop 5 Menores MTBR (Maior Stress / Troca Frequente com >= 3 reincidentes):")
stress_items = [r for r in results if r['reincidentes'] >= 3]
stress_items.sort(key=lambda x: x['mtbr_real'])
for r in stress_items[:10]:
    print(f"- {r['material'][:35]}: MTBR = {r['mtbr_real']:4.1f} dias | Teórico = {r['vida_util_teorica']}d | Degradação = {r['degradacao_pct']:+5.1f}% ({r['sample_type']})")

print("\nTop 5 Maiores MTBR (Ciclo Longo / Alta Durabilidade):")
durable_items = [r for r in results if r['total_events'] >= 3]
durable_items.sort(key=lambda x: x['mtbr_real'], reverse=True)
for r in durable_items[:5]:
    print(f"- {r['material'][:35]}: MTBR = {r['mtbr_real']:4.1f} dias | Teórico = {r['vida_util_teorica']}d | Degradação = {r['degradacao_pct']:+5.1f}%")
