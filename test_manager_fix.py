from estoque_clevel_manager import estoque_clevel_manager

kpis = estoque_clevel_manager.get_kpis()
print("=== KPIS ===")
print("Top ofensor:", kpis['top_ofensor'])
print(f"MTBR Avg: {kpis['mtbr_avg']} | Critical count: {kpis['mtbr_critical_count']}")

rain = estoque_clevel_manager.get_rain_analysis()
print("\n=== RAIN TIMELINE ===")
for t in rain['timeline']:
    print(f"{t['mes']}: Chuva {t['chuva_mm']:5.1f}mm | Retiradas {t['retiradas']:5d} un | R$ {t['custo']:10,.2f}")

mtbr = estoque_clevel_manager.get_mtbr_analysis()
print("\n=== MTBR LOWEST (STRESS) ===")
for m in mtbr['mtbr_lowest'][:5]:
    print(f"- {m['material'][:35]}: MTBR={m['mtbr_days']}d (Teor={m['theoretical_days']}d, Degr={m['degradacao_pct']}%, Reinc={m['reincidentes']})")

ofensores = estoque_clevel_manager.get_ofensores()
print("\n=== SCATTER (DISPERSÃO) ===")
print("Total pontos no scatter:", len(ofensores['scatter']))
print("Primeiros 3 pontos:", ofensores['scatter'][:3])

bases = estoque_clevel_manager.get_bases_segmentos()
print("\n=== SEGMENT RADAR ===")
print(bases['segment_radar'])
