# 📡 ALERTAS OPERACIONAIS OP (PowerON × TRBOnet)

Sistema corporativo CCO para **auditoria, conciliação e monitoramento em tempo real** entre a escala ativa do **PowerON** e os rádios e telemetria GPS conectados no **TRBOnet One**.

---

## 🏗️ Arquitetura do Sistema

```text
alertas-operacionais-op/
├── app.py                      # Servidor Flask com rotas web e APIs RESTful
├── data_manager.py             # Conciliação em memória, histórico e agrupamento regional
├── coletar_trbonet_completo.py # Leitor silencioso UIA em segundo plano (TRBOnet One)
├── run_server.py               # Script auxiliar para inicialização com verificação de ambiente
├── run_server.bat              # Script Batch para inicialização com 1 clique no Windows
├── requirements.txt            # Dependências Python (Flask, Pandas, UIAutomation, etc.)
├── templates/
│   └── index.html              # Interface Web Glassmorphism Ultra-Premium CCO
└── static/
    ├── css/
    │   └── dashboard.css       # Design system CCO (Dark Glassmorphism, Neon Glows)
    └── js/
        └── app.js              # Motor reativo, filtros multi-seleção e gráficos Chart.js
```

---

## 🚀 Como Executar em um Novo Computador

### 1. Pré-requisitos:
* **Python 3.8+** instalado no Windows.
* O software **TRBOnet One** aberto (caso deseje capturar rádios em tempo real).

### 2. Instalação das Dependências:
Abra o Prompt de Comando (CMD) ou PowerShell na pasta do projeto e execute:
```bash
pip install -r requirements.txt
```

### 3. Iniciar o Servidor:
Execute via Python ou dê um duplo clique no arquivo `run_server.bat`:
```bash
python app.py
```
O painel estará disponível em: **`http://127.0.0.1:5000`** (ou no IP da máquina na rede local).

---

## ⚙️ Configurações e Caminhos de Arquivos

### Pasta Padrão do Arquivo Calendário (PowerON):
No arquivo `data_manager.py` (linha ~86), configure o caminho da pasta onde são salvas as escalas diárias do PowerON:
```python
folder = r"C:\Users\SEU_USUARIO\Caminho\Arquivo Calendário"
```

### Regras de Negócio Aplicadas:
1. **Filtro de LOGOFF:** Equipes com a coluna `LOGOFF` preenchida são consideradas deslogadas (fora de operação) e não entram na contagem.
2. **Filtro CML:** Equipes iniciadas por `CML` são desconsideradas.
3. **Bases Oficiais:**
   * **Região Norte:** `ENL` (Base Fagundes), `ECL` (Base Cajati), `EEL` (Base Vila Medeiros).
   * **Região Leste:** `EML` (Base Monte Santo), `EQL` (Base Aricanduva), `EVL` (Base Catumbi), `ESL` (Base Santo André).
   * **Outras:** Todas as demais bases operacionais consolidadas com drill-down.

---

## 🗄️ Próximos Passos: Integração com Banco de Dados

Para persistência histórica de longo prazo (PostgreSQL, MySQL, SQL Server ou SQLite):
1. No `data_manager.py`, substitua os dicionários `self.team_history` por tabelas de banco de dados (`equipes_historico`, `logs_sincronizacao`).
2. Utilize o **SQLAlchemy** para mapeamento objeto-relacional (ORM).

---

© 2026 Alertas Operacionais OP • Centro de Controle Operacional
