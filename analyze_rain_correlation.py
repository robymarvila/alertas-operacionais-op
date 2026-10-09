import urllib.request
import json
from collections import defaultdict

# 1. Obter clima real de São Paulo (Latitude: -23.5505, Longitude: -46.6333)
url = 'https://archive-api.open-meteo.com/v1/archive?latitude=-23.5505&longitude=-46.6333&start_date=2026-03-01&end_date=2026-09-30&daily=precipitation_sum,rain_sum&timezone=America%2FSao_Paulo'
req = urllib.request.urlopen(url)
weather_data = json.loads(req.read())

daily_rain = dict(zip(weather_data['daily']['time'], weather_data['daily']['precipitation_sum']))

# 2. Carregar registros de estoque
with open('data/estoque_clevel_consolidado.json', 'r', encoding='utf-8') as f:
    records = json.load(f)

daily_stock = defaultdict(lambda: {'qtde': 0, 'valor': 0.0, 'saidas': 0})
for r in records:
    d = r.get('data_saida')
    if d:
        daily_stock[d]['qtde'] += r.get('qtde', 0)
        daily_stock[d]['valor'] += r.get('valor_total', 0)
        daily_stock[d]['saidas'] += 1

# 3. Consolidar por mês
months = ['2026-03', '2026-04', '2026-05', '2026-06', '2026-07', '2026-08', '2026-09']
month_labels = {'2026-03': 'Mar/26', '2026-04': 'Abr/26', '2026-05': 'Mai/26', '2026-06': 'Jun/26', '2026-07': 'Jul/26', '2026-08': 'Ago/26', '2026-09': 'Set/26'}

print("=== CONSOLIDAÇÃO MENSAL: CHUVA REAL (SP) VS RETIRADAS ===")
for m in months:
    rain_sum = sum(v for d, v in daily_rain.items() if d.startswith(m) and v is not None)
    stock_vol = sum(daily_stock[d]['qtde'] for d in daily_stock if d.startswith(m))
    stock_cost = sum(daily_stock[d]['valor'] for d in daily_stock if d.startswith(m))
    stock_trans = sum(daily_stock[d]['saidas'] for d in daily_stock if d.startswith(m))
    print(f"{month_labels[m]}: Chuva = {rain_sum:6.1f} mm | Retiradas = {stock_vol:6.0f} un | Custo = R$ {stock_cost:11,.2f} | Transações = {stock_trans:5d}")
