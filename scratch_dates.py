import json
from collections import defaultdict

with open('data/estoque_clevel_consolidado.json', 'r', encoding='utf-8') as f:
    records = json.load(f)

print(f"Total records: {len(records)}")
dates = [r['data_saida'] for r in records if r.get('data_saida')]
dates.sort()
print(f"Min date: {dates[0]} | Max date: {dates[-1]}")

by_year_month = defaultdict(lambda: {'count': 0, 'volume': 0, 'cost': 0.0})
for r in records:
    dt = r.get('data_saida', '')
    if len(dt) >= 7:
        ym = dt[:7]
        by_year_month[ym]['count'] += 1
        by_year_month[ym]['volume'] += r.get('qtde', 0)
        by_year_month[ym]['cost'] += r.get('valor_total', 0)

print("\nDistribuição Ano-Mês:")
for ym in sorted(by_year_month.keys()):
    v = by_year_month[ym]
    print(f"{ym}: {v['count']:5d} transações | {int(v['volume']):6d} un | R$ {v['cost']:12,.2f}")
