// ==============================================================================
// ROBÔ AUTÔNOMO CCO - EXTRAÇÃO CONTÍNUA DO PORTAL ENEL (TEAMS-LIST)
// Executa em segundo plano no navegador sem intervenção humana:
// 1. Atualiza a página (F5 / reload) periodicamente.
// 2. Muda o seletor de paginação para 500 linhas (setPageSize(500)).
// 3. Extrai todas as equipes e envia para o Painel Local CCO (http://127.0.0.1:5000).
// 4. Exibe widget flutuante translúcido com contagem regressiva.
// ==============================================================================

(function iniciarRoboAutonomoEnel() {
    const LOCAL_SERVER_URL = 'http://127.0.0.1:5000/api/teams/sync';
    const INTERVAL_SECONDS = 120; // Intervalo de 2 minutos entre coletas

    // Cria ou recupera o widget flutuante no DOM da Enel
    let widget = document.getElementById('cco-daemon-widget');
    if (!widget) {
        widget = document.createElement('div');
        widget.id = 'cco-daemon-widget';
        widget.style.cssText = `
            position: fixed;
            bottom: 20px;
            right: 20px;
            z-index: 999999;
            background: rgba(15, 23, 42, 0.92);
            color: #f8fafc;
            border: 1px solid rgba(0, 242, 254, 0.4);
            border-radius: 16px;
            padding: 14px 20px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 20px rgba(0, 242, 254, 0.2);
            font-family: 'Segoe UI', system-ui, sans-serif;
            font-size: 13px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            backdrop-filter: blur(16px);
            min-width: 280px;
        `;
        document.body.appendChild(widget);
    }

    function updateWidgetStatus(statusText, isRunning = true) {
        widget.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <strong style="color:#00f2fe; display:flex; align-items:center; gap:6px;">
                    <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#10b981; box-shadow:0 0 8px #10b981;"></span>
                    CCO AUTONOMOUS ROBOT
                </strong>
                <span style="font-size:11px; color:#94a3b8; font-family:monospace;">ENEL SP</span>
            </div>
            <div style="color:#e2e8f0; font-size:12px; margin-top:2px;">${statusText}</div>
            <div style="display:flex; justify-content:space-between; font-size:11px; color:#94a3b8; margin-top:4px; border-top:1px solid rgba(255,255,255,0.1); padding-top:4px;">
                <span>Modo: 100% Autônomo</span>
                <span id="cco-daemon-timer">Próximo ciclo: ${INTERVAL_SECONDS}s</span>
            </div>
        `;
    }

    async function executarCicloExtracao() {
        updateWidgetStatus('🔍 Ajustando para 500 linhas por página...');
        
        // 1. Localiza e altera o seletor para 500 linhas
        const select = document.querySelector('select[onchange*="setPageSize"]') || document.querySelector('select');
        if (select && select.value !== '500') {
            select.value = '500';
            select.dispatchEvent(new Event('change', { bubbles: true }));
            if (typeof window.setPageSize === 'function') {
                try { window.setPageSize(500); } catch(e) {}
            }
            // Aguarda 2 segundos para o carregamento assíncrono das 500 linhas
            await new Promise(r => setTimeout(r, 2200));
        }

        updateWidgetStatus('📋 Extraindo registros da tabela...');

        // 2. Extrai cabeçalhos e linhas da tabela
        const ths = Array.from(document.querySelectorAll('table thead th, [role="columnheader"]')).map(th => th.innerText.trim().replace(' ↕', ''));
        const trs = Array.from(document.querySelectorAll('table tbody tr, [role="row"]')).filter(r => r.querySelectorAll('td, [role="cell"]').length >= 5);

        const records = trs.map(tr => {
            const tds = Array.from(tr.querySelectorAll('td, [role="cell"]')).map(td => td.innerText.trim());
            const rowObj = {};
            ths.forEach((h, idx) => {
                if (h && tds[idx] !== undefined) rowObj[h] = tds[idx];
            });
            // Fallbacks posicionais
            if (!rowObj['EQUIPE'] && tds[4]) rowObj['EQUIPE'] = tds[4];
            if (!rowObj['TURNO'] && tds[7]) rowObj['TURNO'] = tds[7];
            if (!rowObj['MOTORISTA'] && tds[6]) rowObj['MOTORISTA'] = tds[6];
            if (!rowObj['PLACA'] && tds[11]) rowObj['PLACA'] = tds[11];
            if (!rowObj['STATUS'] && tds[9]) rowObj['STATUS'] = tds[9];
            if (!rowObj['BASE'] && tds[1]) rowObj['BASE'] = tds[1];
            if (!rowObj['UT'] && tds[0]) rowObj['UT'] = tds[0];
            if (!rowObj['FILIAL'] && tds[2]) rowObj['FILIAL'] = tds[2];
            if (!rowObj['TIPO'] && tds[5]) rowObj['TIPO'] = tds[5];
            return rowObj;
        });

        if (records.length === 0) {
            updateWidgetStatus('⚠️ Nenhuma linha encontrada. Aguardando...');
            return;
        }

        updateWidgetStatus(`🚀 Enviando ${records.length} equipes para o CCO...`);

        // 3. Envia para o servidor local CCO
        try {
            const resp = await fetch(LOCAL_SERVER_URL, {
                method: 'POST',
                mode: 'cors',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    records: records,
                    source: `Extrator Autônomo Enel (teams-list - ${records.length} equipes)`
                })
            });
            const res = await resp.json();
            if (res.status === 'success') {
                const now = new Date().toLocaleTimeString('pt-BR');
                sessionStorage.setItem('cco_daemon_last_sync', now);
                sessionStorage.setItem('cco_daemon_count', records.length);
                updateWidgetStatus(`✅ Sincronizado às <strong>${now}</strong> (${records.length} equipes)`);
            } else {
                updateWidgetStatus(`⚠️ Resposta do CCO: ${res.message}`);
            }
        } catch (err) {
            updateWidgetStatus(`❌ Erro CCO: Servidor local 127.0.0.1:5000 inacessível`);
        }
    }

    // Marca o robô como ativo nesta aba
    sessionStorage.setItem('cco_daemon_active', 'true');

    // Executa a extração inicial
    executarCicloExtracao();

    // Contagem regressiva e auto-reload contínuo
    let secondsLeft = INTERVAL_SECONDS;
    setInterval(() => {
        secondsLeft--;
        const timerEl = document.getElementById('cco-daemon-timer');
        if (timerEl) {
            timerEl.textContent = `Próximo ciclo: ${secondsLeft}s`;
        }

        if (secondsLeft <= 0) {
            updateWidgetStatus('🔄 Atualizando página para obter dados mais recentes...');
            window.location.reload();
        }
    }, 1000);
})();
