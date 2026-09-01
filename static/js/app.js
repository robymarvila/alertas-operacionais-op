/**
 * PAINEL OPERACIONAL CCO - POWERON VS TRBONET (ULTRA PREMIUM)
 * Motor Reativo, Multi-Seleção Regional e de Bases, Sincronização PowerON e Auditoria
 */

// Configuração Regional Oficial
const REGION_CONFIG = {
    NORTE: {
        name: 'Região Norte',
        bases: ['ENL', 'ECL', 'EEL'],
        color: '#34d399'
    },
    LESTE: {
        name: 'Região Leste',
        bases: ['EML', 'EQL', 'EVL', 'ESL'],
        color: '#60a5fa'
    },
    OUTRAS: {
        name: 'Demais Bases (Outras)',
        bases: ['OUTRAS'],
        color: '#fbbf24'
    }
};

// Estado Global da Aplicação
const appState = {
    teams: [],
    bases: [],
    regions: {},
    summary: {},
    auditLog: [],
    
    // Visão Atual (Hub de Módulos vs Módulo Específico)
    currentView: 'hub', // 'hub' ou 'module'

    // Aba Principal Ativa dentro do Módulo
    currentMainTab: 'live', // 'live' ou 'dashboard'

    // Filtros Multi-seleção e Visualização
    selectedBases: new Set(['ALL']), // Set contendo 'ALL' ou códigos de bases selecionadas
    currentStatusFilter: 'ALL',
    searchQuery: '',
    historySearchQuery: '',
    viewMode: 'table', // 'table' ou 'cards'
    
    // Ordenação da Tabela
    sortField: 'code',
    sortAsc: true,
    
    // Auto-refresh Timer (2 Minutos = 120 segundos)
    refreshIntervalSeconds: 120,
    secondsRemaining: 120,
    timerId: null,
    isPaused: false,
    
    // Gráficos Chart.js
    donutChart: null,
    barChart: null
};

// ==========================================================================
// INICIALIZAÇÃO DO SISTEMA
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initClock();
    initIcons();
    initDropzone();
    fetchDashboardData(true);
    startAutoRefreshTimer();
    navigateToView('hub');
});

function initIcons() {
    if (window.lucide) {
        lucide.createIcons();
    }
}

// ==========================================================================
// GERENCIADOR DE TEMAS (MODO CLARO × MODO ESCURO)
// ==========================================================================
function initTheme() {
    const savedTheme = localStorage.getItem('cco_theme') || 'dark';
    applyTheme(savedTheme);
}

function toggleTheme() {
    const isCurrentlyLight = document.body.classList.contains('theme-light');
    const newTheme = isCurrentlyLight ? 'dark' : 'light';
    applyTheme(newTheme);
    localStorage.setItem('cco_theme', newTheme);
    showToast(`Tema alterado para: ${newTheme === 'light' ? 'Modo Claro' : 'Modo Escuro'}`, 'info');
}

function applyTheme(theme) {
    const textLabel = document.getElementById('themeToggleText');

    if (theme === 'light') {
        document.body.classList.remove('theme-dark');
        document.body.classList.add('theme-light');
        if (textLabel) textLabel.textContent = 'Modo Escuro';
    } else {
        document.body.classList.remove('theme-light');
        document.body.classList.add('theme-dark');
        if (textLabel) textLabel.textContent = 'Modo Claro';
    }

    // Se os gráficos estiverem inicializados, redesenha com as novas cores
    if (appState.currentMainTab === 'dashboard' && appState.donutChart) {
        setTimeout(renderCharts, 50);
    }
    initIcons();
}

// ==========================================================================
// NAVEGAÇÃO ENTRE PORTAL HUB E MÓDULO OPERACIONAL
// ==========================================================================
function navigateToView(viewName) {
    appState.currentView = viewName;

    const portalHub = document.getElementById('portalHubView');
    const moduleView = document.getElementById('moduleAuditView');
    const btnBackHub = document.getElementById('btnBackToHub');
    const brandHub = document.getElementById('brandHubHeader');
    const brandModule = document.getElementById('brandModuleHeader');
    const headerSyncBox = document.getElementById('headerSyncBox');
    const moduleNavTabs = document.getElementById('moduleNavTabs');
    const moduleHeaderActions = document.getElementById('moduleHeaderActions');
    const moduleHeaderTools = document.getElementById('moduleHeaderTools');

    if (viewName === 'hub') {
        if (portalHub) portalHub.style.display = 'flex';
        if (moduleView) moduleView.style.display = 'none';
        if (btnBackHub) btnBackHub.style.display = 'none';
        if (brandHub) brandHub.style.display = 'flex';
        if (brandModule) brandModule.style.display = 'none';
        if (headerSyncBox) headerSyncBox.style.display = 'none';
        if (moduleNavTabs) moduleNavTabs.style.display = 'none';
        if (moduleHeaderActions) moduleHeaderActions.style.display = 'none';
        if (moduleHeaderTools) moduleHeaderTools.style.display = 'none';
        updateHubCard();
        window.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
        if (portalHub) portalHub.style.display = 'none';
        if (moduleView) moduleView.style.display = 'block';
        if (btnBackHub) btnBackHub.style.display = 'inline-flex';
        if (brandHub) brandHub.style.display = 'none';
        if (brandModule) brandModule.style.display = 'flex';
        if (headerSyncBox) headerSyncBox.style.display = 'flex';
        if (moduleNavTabs) moduleNavTabs.style.display = 'flex';
        if (moduleHeaderActions) moduleHeaderActions.style.display = 'flex';
        if (moduleHeaderTools) moduleHeaderTools.style.display = 'flex';
        switchMainTab(appState.currentMainTab || 'live');
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
    initIcons();
}

function updateHubCard() {
    const summary = appState.summary || {};
    
    // Timestamps
    const hubTrboEl = document.getElementById('hubCardSyncTrbonet');
    const hubPwEl = document.getElementById('hubCardSyncPoweron');
    if (hubTrboEl) hubTrboEl.textContent = summary.last_trbonet_sync || '--/--/---- --:--:--';
    if (hubPwEl) hubPwEl.textContent = summary.last_poweron_login || '--/--/---- --:--:--';

    const compRate = summary.compliance_rate !== undefined ? `${summary.compliance_rate}%` : '--%';

    // Mini KPIs no Card
    const miniComp = document.getElementById('hubMiniCompliance');
    const miniTrbo = document.getElementById('hubMiniTrbonet');
    const miniPw = document.getElementById('hubMiniPoweron');
    const miniOff = document.getElementById('hubMiniOffline');
    const miniRate = document.getElementById('hubMiniProgressRate');
    const miniBar = document.getElementById('hubMiniProgressBar');

    if (miniComp) miniComp.textContent = compRate;
    if (miniTrbo) miniTrbo.textContent = summary.total_trbonet !== undefined ? summary.total_trbonet : '0';
    if (miniPw) miniPw.textContent = summary.total_poweron !== undefined ? summary.total_poweron : '0';
    if (miniOff) miniOff.textContent = summary.offline !== undefined ? summary.offline : '0';
    if (miniRate) miniRate.textContent = compRate;

    if (miniBar && summary.compliance_rate !== undefined) {
        miniBar.style.width = `${Math.min(summary.compliance_rate, 100)}%`;
        miniBar.style.backgroundColor = getComplianceColor(summary.compliance_rate);
    }
}

// ==========================================================================
// NAVEGAÇÃO ENTRE JANELAS / ABAS DO MÓDULO (AO VIVO × DASHBOARD)
// ==========================================================================
function switchMainTab(tabName) {
    appState.currentMainTab = tabName;

    const btnLive = document.getElementById('tabBtnLive');
    const btnDash = document.getElementById('tabBtnDashboard');
    const paneLive = document.getElementById('tabViewLive');
    const paneDash = document.getElementById('tabViewDashboard');

    if (tabName === 'live') {
        if (btnLive) btnLive.classList.add('active');
        if (btnDash) btnDash.classList.remove('active');
        if (paneLive) paneLive.style.display = 'flex';
        if (paneDash) paneDash.style.display = 'none';
    } else {
        if (btnLive) btnLive.classList.remove('active');
        if (btnDash) btnDash.classList.add('active');
        if (paneLive) paneLive.style.display = 'none';
        if (paneDash) paneDash.style.display = 'flex';

        setTimeout(() => {
            renderCharts();
            renderHistoryTable();
        }, 100);
    }
    initIcons();
}

// ==========================================================================
// RELÓGIO DIGITAL EM TEMPO REAL
// ==========================================================================
function initClock() {
    const updateTime = () => {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('pt-BR', { hour12: false });
        const dateStr = now.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric' });
        
        const clockEl = document.getElementById('digitalClock');
        const dateEl = document.getElementById('digitalDate');
        const clockModuleEl = document.getElementById('digitalClockModule');

        if (clockEl) clockEl.textContent = timeStr;
        if (dateEl) dateEl.textContent = dateStr;
        if (clockModuleEl) clockModuleEl.textContent = timeStr;
    };
    updateTime();
    setInterval(updateTime, 1000);
}

// ==========================================================================
// BUSCA DE DADOS NA API
// ==========================================================================
async function fetchDashboardData(isInitial = false) {
    const refreshIcon = document.getElementById('refreshIcon');
    if (refreshIcon) refreshIcon.classList.add('spin-animation');
    
    const liveStatus = document.getElementById('liveStatusText');
    const liveBadge = document.getElementById('liveStatusBadge');

    try {
        const response = await fetch('/api/data');
        if (!response.ok) throw new Error(`HTTP Error: ${response.status}`);
        
        const result = await response.json();
        if (result.status === 'success') {
            appState.teams = result.data.teams || [];
            appState.bases = result.data.bases || [];
            appState.regions = result.data.regions || {};
            appState.summary = result.data.summary || {};
            appState.auditLog = result.data.audit_log || [];

            updateKPIs();
            renderRegionalBases();
            renderResults();
            updateFilterBadges();
            syncBaseUI();
            updateHubCard();

            if (appState.currentMainTab === 'dashboard') {
                renderCharts();
                renderHistoryTable();
            }

            const trboSyncEl = document.getElementById('headerSyncTrbonet');
            const pwSyncEl = document.getElementById('headerSyncPoweron');

            if (trboSyncEl) {
                trboSyncEl.textContent = appState.summary.last_trbonet_sync || '--/--/---- --:--:--';
            }
            if (pwSyncEl) {
                pwSyncEl.textContent = appState.summary.last_poweron_login || '--/--/---- --:--:--';
            }

            const navBadge = document.getElementById('navLiveBadge');
            if (navBadge) {
                navBadge.textContent = appState.summary.total_trbonet || appState.teams.length;
            }

            if (liveStatus) liveStatus.textContent = 'CONECTADO';
            if (liveBadge) liveBadge.className = 'live-pill';

            if (!isInitial) {
                showToast('Painel sincronizado com sucesso!', 'success');
            }
        }
    } catch (error) {
        console.error('Erro ao buscar dados do servidor:', error);
        if (liveStatus) liveStatus.textContent = 'RECONECTANDO';
        if (liveBadge) liveBadge.className = 'live-pill live-pill-warning';
        showToast('Falha na comunicação com o servidor local.', 'danger');
    } finally {
        if (refreshIcon) {
            setTimeout(() => refreshIcon.classList.remove('spin-animation'), 600);
        }
        initIcons();
    }
}

function manualRefresh() {
    appState.secondsRemaining = appState.refreshIntervalSeconds;
    fetchDashboardData(false);
}

// ==========================================================================
// SINCRONIZAÇÃO DO TRBONET ONE (LEITURA SILENCIOSA AO VIVO)
// ==========================================================================
async function captureTRBOnetLive() {
    const btn = document.getElementById('btnLiveCapture');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Lendo TRBOnet...</span>`;
    }
    initIcons();

    try {
        const response = await fetch('/api/capture/trbonet', { method: 'POST' });
        const result = await response.json();
        if (result.status === 'success') {
            showToast(result.message, 'success');
            fetchDashboardData(false);
        } else if (result.status === 'warning') {
            showToast(result.message, 'danger');
        } else {
            showToast(`Erro na captura: ${result.message}`, 'danger');
        }
    } catch (err) {
        showToast(`Falha ao conectar com o robô de captura: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="radio" id="liveCaptureIcon"></i> <span>Ler TRBOnet</span>`;
        }
        initIcons();
    }
}

// ==========================================================================
// SINCRONIZAÇÃO DO POWERON (ARQUIVO CALENDÁRIO)
// ==========================================================================
async function syncPowerOnCalendar() {
    const btn = document.getElementById('btnSyncPowerOn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Lendo PowerON...</span>`;
    }
    initIcons();

    try {
        const response = await fetch('/api/sync/poweron', { method: 'POST' });
        const result = await response.json();
        if (result.status === 'success') {
            showToast(result.message, 'success');
            fetchDashboardData(false);
        } else {
            showToast(`Erro ao carregar PowerON: ${result.message}`, 'danger');
        }
    } catch (err) {
        showToast(`Falha na sincronização do PowerON: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="clipboard-check" id="syncPowerOnIcon"></i> <span>Ler PowerON</span>`;
        }
        initIcons();
    }
}

// ==========================================================================
// TEMPORIZADOR CIRCULAR DE AUTO-REFRESH
// ==========================================================================
function startAutoRefreshTimer() {
    if (appState.timerId) clearInterval(appState.timerId);
    
    appState.secondsRemaining = appState.refreshIntervalSeconds;
    const circle = document.getElementById('timerProgressCircle');
    const label = document.getElementById('timerSeconds');
    const totalLength = 94.2;

    appState.timerId = setInterval(() => {
        if (appState.isPaused) return;

        appState.secondsRemaining--;
        const mins = Math.floor(appState.secondsRemaining / 60);
        const secs = appState.secondsRemaining % 60;
        if (label) label.textContent = `${mins}:${String(secs).padStart(2, '0')}`;

        if (circle) {
            const offset = totalLength - (appState.secondsRemaining / appState.refreshIntervalSeconds) * totalLength;
            circle.style.strokeDashoffset = offset;
        }

        if (appState.secondsRemaining <= 0) {
            appState.secondsRemaining = appState.refreshIntervalSeconds;
            fetchDashboardData(false);
        }
    }, 1000);
}

// ==========================================================================
// ATUALIZAÇÃO DOS KPIS E RESUMO EXECUTIVO (REATIVO AOS FILTROS REGIONAIS/BASES)
// ==========================================================================
function updateKPIs() {
    let targetTeams = [...appState.teams];
    const isAll = appState.selectedBases.has('ALL') || appState.selectedBases.size === 0;

    // Filtrar equipes de acordo com as bases / regiões selecionadas
    if (!isAll) {
        targetTeams = targetTeams.filter(t => {
            if (appState.selectedBases.has(t.prefix)) return true;
            if (appState.selectedBases.has('OUTRAS') && t.is_other_base) return true;
            return false;
        });
    }

    // Cálculo dinâmico dos 5 indicadores
    const totalPowerOn = targetTeams.filter(t => t.poweron).length;
    const totalTrbo = targetTeams.filter(t => t.trbonet).length;
    const withGps = targetTeams.filter(t => t.trbonet && t.gps).length;
    const withoutGps = targetTeams.filter(t => t.trbonet && !t.gps).length;
    const totalOffline = targetTeams.filter(t => t.poweron && !t.trbonet).length;
    const totalTrboOnly = targetTeams.filter(t => !t.poweron && t.trbonet).length;
    const onlinePowerOn = targetTeams.filter(t => t.poweron && t.trbonet).length;

    const rate = totalPowerOn > 0 ? Math.round((onlinePowerOn / totalPowerOn) * 1000) / 10 : (totalTrbo > 0 ? 100 : 0);

    animateCount('kpi-poweron', totalPowerOn);
    animateCount('kpi-online', totalTrbo);
    animateCount('kpi-offline', totalOffline);
    animateCount('kpi-trbo-only', totalTrboOnly);

    const gpsEl = document.getElementById('kpi-gps-count');
    const nogpsEl = document.getElementById('kpi-nogps-count');
    if (gpsEl) gpsEl.textContent = withGps;
    if (nogpsEl) nogpsEl.textContent = withoutGps;

    const compRateEl = document.getElementById('kpi-compliance-rate');
    const compBadge = document.getElementById('complianceBadge');
    const compBar = document.getElementById('complianceProgressBar');
    const compSub = document.getElementById('complianceSubtext');
    const offlineCard = document.getElementById('cardOfflineAlert');

    if (compRateEl) compRateEl.textContent = `${rate}%`;
    if (compBar) compBar.style.width = `${Math.min(rate, 100)}%`;

    if (compBadge) {
        if (rate >= 90) {
            compBadge.textContent = 'EXCELENTE';
            compBadge.className = 'gauge-status-badge badge-high';
            if (compSub) compSub.textContent = `Aderência CCO no filtro (${onlinePowerOn}/${totalPowerOn})`;
        } else if (rate >= 70) {
            compBadge.textContent = 'ATENÇÃO';
            compBadge.className = 'gauge-status-badge badge-med';
            if (compSub) compSub.textContent = `Discrepâncias identificadas (${onlinePowerOn}/${totalPowerOn})`;
        } else {
            compBadge.textContent = 'CRÍTICO';
            compBadge.className = 'gauge-status-badge badge-low';
            if (compSub) compSub.textContent = `Equipes em escala sem rádio (${totalOffline} offline)`;
        }
    }

    if (offlineCard) {
        if (totalOffline > 0) {
            offlineCard.classList.add('pulse-alert');
        } else {
            offlineCard.classList.remove('pulse-alert');
        }
    }

    // Atualizar texto de escopo da barra de indicadores
    const scopeText = document.getElementById('kpiScopeText');
    if (scopeText) {
        if (isAll) {
            scopeText.textContent = `Todas as Regiões e Bases (Visão Global • ${targetTeams.length} equipes monitoradas)`;
        } else {
            const selectedLabels = [];
            const northAll = REGION_CONFIG.NORTE.bases.every(b => appState.selectedBases.has(b));
            const eastAll = REGION_CONFIG.LESTE.bases.every(b => appState.selectedBases.has(b));
            const otherActive = appState.selectedBases.has('OUTRAS');

            if (northAll && eastAll && otherActive) {
                scopeText.textContent = `Todas as Regiões (Norte + Leste + Outras)`;
            } else {
                if (northAll) {
                    selectedLabels.push('🟢 Região Norte');
                } else {
                    REGION_CONFIG.NORTE.bases.forEach(b => {
                        if (appState.selectedBases.has(b)) selectedLabels.push(`Norte (${b})`);
                    });
                }

                if (eastAll) {
                    selectedLabels.push('🔵 Região Leste');
                } else {
                    REGION_CONFIG.LESTE.bases.forEach(b => {
                        if (appState.selectedBases.has(b)) selectedLabels.push(`Leste (${b})`);
                    });
                }

                if (otherActive) {
                    selectedLabels.push('🟡 Outras Bases');
                }

                scopeText.textContent = `Filtrando: ${selectedLabels.join(', ')} (${targetTeams.length} equipes monitoradas)`;
            }
        }
    }

    // KPIs da aba de Analytics
    const anaAvgTime = document.getElementById('analyticsAvgOnlineTime');
    const anaDrops = document.getElementById('analyticsTotalDrops');
    const anaComp = document.getElementById('analyticsGlobalCompliance');

    if (anaAvgTime) {
        const totalOnlineMins = targetTeams.reduce((acc, t) => acc + (t.history ? t.history.online_minutes : 0), 0);
        const avgMins = targetTeams.length > 0 ? Math.round(totalOnlineMins / targetTeams.length) : 0;
        const h = Math.floor(avgMins / 60);
        const m = avgMins % 60;
        const mStr = String(m).padStart(2, '0');
        anaAvgTime.textContent = h > 0 ? `${h}h ${mStr}m` : `${m}m`;
    }

    if (anaDrops) {
        const totalDrops = targetTeams.reduce((acc, t) => acc + (t.history ? t.history.offline_incidents : 0), 0);
        anaDrops.textContent = totalDrops;
    }

    if (anaComp) {
        anaComp.textContent = `${rate}%`;
    }
}

function animateCount(elementId, targetValue) {
    const el = document.getElementById(elementId);
    if (!el) return;
    
    const startVal = parseInt(el.textContent.replace(/\D/g, '')) || 0;
    const duration = 300;
    const startTime = performance.now();

    const step = (currentTime) => {
        const progress = Math.min((currentTime - startTime) / duration, 1);
        const currentVal = Math.floor(startVal + (targetValue - startVal) * progress);
        el.textContent = currentVal.toLocaleString('pt-BR');
        if (progress < 1) {
            requestAnimationFrame(step);
        } else {
            el.textContent = targetValue.toLocaleString('pt-BR');
        }
    };
    requestAnimationFrame(step);
}

// ==========================================================================
// RENDERIZAÇÃO DAS BASES OPERACIONAIS POR REGIÃO (NORTE, LESTE, OUTRAS)
// ==========================================================================
function renderRegionalBases() {
    const northGrid = document.getElementById('northBasesGrid');
    const eastGrid = document.getElementById('eastBasesGrid');
    const otherGrid = document.getElementById('otherBasesGrid');
    const otherSubGrid = document.getElementById('otherSubBasesGrid');

    const regions = appState.regions || {};
    const northBases = regions.norte ? regions.norte.bases : [];
    const eastBases = regions.leste ? regions.leste.bases : [];
    const otherConsolidado = regions.outras ? regions.outras.summary : null;
    const otherSubBases = regions.outras ? regions.outras.sub_bases : [];

    // 1. Região Norte
    if (northGrid) {
        northGrid.innerHTML = northBases.map(b => createBaseCardHTML(b)).join('');
    }

    // 2. Região Leste
    if (eastGrid) {
        eastGrid.innerHTML = eastBases.map(b => createBaseCardHTML(b)).join('');
    }

    // 3. Card Consolidado de Outras
    if (otherGrid && otherConsolidado) {
        const isOtherActive = appState.selectedBases.has('OUTRAS');
        otherGrid.innerHTML = `
            <div class="base-card-premium base-card-other ${isOtherActive ? 'active-filter' : ''}" data-base-code="OUTRAS" onclick="toggleBaseFilter('OUTRAS')">
                <div class="base-card-top">
                    <div>
                        <span class="base-code-pill" style="color: #fbbf24; border-color: rgba(245, 158, 11, 0.4); background: rgba(245, 158, 11, 0.12);">OUTRAS</span>
                        <h5 class="base-name-title">Demais Bases (${otherConsolidado.sub_bases_count} Frotas)</h5>
                    </div>
                    <span class="base-compliance-badge ${getComplianceBadgeClass(otherConsolidado.compliance_rate)}">
                        ${otherConsolidado.compliance_rate}%
                    </span>
                </div>

                <div class="base-metrics-grid">
                    <div class="base-metric-col">
                        <span class="metric-col-label">PowerON</span>
                        <span class="metric-col-val">${otherConsolidado.total_poweron}</span>
                    </div>
                    <div class="base-metric-col">
                        <span class="metric-col-label">TRBOnet</span>
                        <span class="metric-col-val text-emerald">${otherConsolidado.total_trbonet}</span>
                    </div>
                    <div class="base-metric-col">
                        <span class="metric-col-label">Offline</span>
                        <span class="metric-col-val ${otherConsolidado.offline > 0 ? 'text-rose' : ''}">${otherConsolidado.offline}</span>
                    </div>
                </div>

                <div class="card-other-action">
                    <i data-lucide="layers" style="width: 13px;"></i>
                    <span>Clique para marcar/desmarcar e ver detalhes</span>
                </div>
            </div>
        `;
    }

    // 4. Sub-bases na Gaveta de Outras
    if (otherSubGrid) {
        otherSubGrid.innerHTML = otherSubBases.map(sb => {
            const isSubActive = appState.selectedBases.has(sb.prefix);
            return `
                <div class="sub-base-card ${isSubActive ? 'active-sub' : ''}" data-base-code="${sb.prefix}" onclick="toggleBaseFilter('${sb.prefix}')">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <strong style="color: #38bdf8; font-family: var(--font-mono); font-size: 0.84rem;">${sb.prefix}</strong>
                        <span style="font-size: 0.76rem; font-weight: 700; color: #34d399;">${sb.total_trbonet} rádios</span>
                    </div>
                    <div style="font-size: 0.76rem; color: var(--text-muted); margin-top: 4px;">
                        PowerON: ${sb.total_poweron} | Offline: ${sb.offline}
                    </div>
                </div>
            `;
        }).join('');
    }

    initIcons();
}

function createBaseCardHTML(b) {
    const isSelected = appState.selectedBases.has(b.prefix);
    return `
        <div class="base-card-premium ${isSelected ? 'active-filter' : ''}" data-base-code="${b.prefix}" onclick="toggleBaseFilter('${b.prefix}')">
            <div class="base-card-top">
                <div>
                    <span class="base-code-pill">${b.prefix}</span>
                    <h5 class="base-name-title">${b.name}</h5>
                </div>
                <span class="base-compliance-badge ${getComplianceBadgeClass(b.compliance_rate)}">
                    ${b.compliance_rate}%
                </span>
            </div>

            <div class="base-metrics-grid">
                <div class="base-metric-col">
                    <span class="metric-col-label">PowerON</span>
                    <span class="metric-col-val">${b.total_poweron}</span>
                </div>
                <div class="base-metric-col">
                    <span class="metric-col-label">TRBOnet</span>
                    <span class="metric-col-val text-emerald">${b.total_trbonet || b.online_trbo}</span>
                </div>
                <div class="base-metric-col">
                    <span class="metric-col-label">Offline</span>
                    <span class="metric-col-val ${b.offline > 0 ? 'text-rose' : ''}">${b.offline}</span>
                </div>
            </div>

            <div class="base-card-progress">
                <div class="base-card-progress-bar" style="width: ${Math.min(b.compliance_rate, 100)}%; background-color: ${getComplianceColor(b.compliance_rate)};"></div>
            </div>
        </div>
    `;
}

function getComplianceBadgeClass(rate) {
    if (rate >= 90) return 'badge-comp-high';
    if (rate >= 70) return 'badge-comp-med';
    return 'badge-comp-low';
}

function getComplianceColor(rate) {
    if (rate >= 90) return '#10b981';
    if (rate >= 70) return '#f59e0b';
    return '#f43f5e';
}

function toggleOtherBasesDrawer(show) {
    const drawer = document.getElementById('otherBasesDrawer');
    if (drawer) {
        drawer.style.display = show ? 'block' : 'none';
    }
}

// ==========================================================================
// FILTRAGEM MULTI-SELEÇÃO DINÂMICA DE REGIÕES, BASES E STATUS
// ==========================================================================
function toggleRegionFilter(regionCode, element) {
    if (regionCode === 'ALL') {
        appState.selectedBases.clear();
        appState.selectedBases.add('ALL');
        toggleOtherBasesDrawer(false);
    } else if (regionCode === 'NORTE') {
        const northBases = REGION_CONFIG.NORTE.bases;
        const allPresent = northBases.every(b => appState.selectedBases.has(b));

        if (allPresent) {
            // Desmarcar todas as bases do Norte
            northBases.forEach(b => appState.selectedBases.delete(b));
            if (appState.selectedBases.size === 0) appState.selectedBases.add('ALL');
        } else {
            // Marcar todas as bases do Norte
            appState.selectedBases.delete('ALL');
            northBases.forEach(b => appState.selectedBases.add(b));
        }
    } else if (regionCode === 'LESTE') {
        const eastBases = REGION_CONFIG.LESTE.bases;
        const allPresent = eastBases.every(b => appState.selectedBases.has(b));

        if (allPresent) {
            // Desmarcar todas as bases do Leste
            eastBases.forEach(b => appState.selectedBases.delete(b));
            if (appState.selectedBases.size === 0) appState.selectedBases.add('ALL');
        } else {
            // Marcar todas as bases do Leste
            appState.selectedBases.delete('ALL');
            eastBases.forEach(b => appState.selectedBases.add(b));
        }
    } else if (regionCode === 'OUTRAS') {
        if (appState.selectedBases.has('OUTRAS')) {
            appState.selectedBases.delete('OUTRAS');
            if (appState.selectedBases.size === 0) appState.selectedBases.add('ALL');
            toggleOtherBasesDrawer(false);
        } else {
            appState.selectedBases.delete('ALL');
            appState.selectedBases.add('OUTRAS');
            toggleOtherBasesDrawer(true);
        }
    }

    syncBaseUI();
    updateKPIs();
    renderResults();
}

function toggleBaseFilter(baseCode) {
    if (baseCode === 'ALL') {
        appState.selectedBases.clear();
        appState.selectedBases.add('ALL');
        toggleOtherBasesDrawer(false);
    } else if (baseCode === 'OUTRAS') {
        if (appState.selectedBases.has('OUTRAS')) {
            appState.selectedBases.delete('OUTRAS');
            if (appState.selectedBases.size === 0) appState.selectedBases.add('ALL');
            toggleOtherBasesDrawer(false);
        } else {
            appState.selectedBases.delete('ALL');
            // Remove qualquer sub-base individual selecionada para aplicar o bloco OUTRAS
            const subBases = (appState.regions?.outras?.sub_bases || []).map(sb => sb.prefix);
            subBases.forEach(p => appState.selectedBases.delete(p));
            appState.selectedBases.add('OUTRAS');
            toggleOtherBasesDrawer(true);
        }
    } else {
        // Seleção de uma base específica (ex: EMA, ECL, ENL, ECA, EDE, etc.)
        appState.selectedBases.delete('ALL');

        // Se OUTRAS genérico estava ativo, removemos para filtrar estritamente a sub-base clicada
        if (appState.selectedBases.has('OUTRAS')) {
            appState.selectedBases.delete('OUTRAS');
        }

        if (appState.selectedBases.has(baseCode)) {
            appState.selectedBases.delete(baseCode);
            if (appState.selectedBases.size === 0) {
                appState.selectedBases.add('ALL');
            }
        } else {
            appState.selectedBases.add(baseCode);
        }
    }

    syncBaseUI();
    updateKPIs();
    renderResults();
}

function setBaseFilter(baseCode, element) {
    toggleBaseFilter(baseCode);
}

function syncBaseUI() {
    const isAll = appState.selectedBases.has('ALL');

    const northAll = REGION_CONFIG.NORTE.bases.every(b => appState.selectedBases.has(b));
    const eastAll = REGION_CONFIG.LESTE.bases.every(b => appState.selectedBases.has(b));
    const otherActive = appState.selectedBases.has('OUTRAS');

    // 1. Sincronizar Botões da Barra de Escopo Rápido (Acima dos KPIs)
    const btnQAll = document.getElementById('btnQuickRegAll');
    const btnQNorth = document.getElementById('btnQuickRegNorth');
    const btnQEast = document.getElementById('btnQuickRegEast');
    const btnQOther = document.getElementById('btnQuickRegOther');

    if (btnQAll) btnQAll.classList.toggle('active', isAll);
    if (btnQNorth) btnQNorth.classList.toggle('active', !isAll && northAll);
    if (btnQEast) btnQEast.classList.toggle('active', !isAll && eastAll);
    if (btnQOther) btnQOther.classList.toggle('active', !isAll && otherActive);

    // 2. Sincronizar Chips de Região
    const regionChips = document.querySelectorAll('#regionFiltersContainer .chip-filter');
    regionChips.forEach(chip => {
        const reg = chip.getAttribute('data-region');
        if (reg === 'ALL') chip.classList.toggle('active', isAll);
        if (reg === 'NORTE') chip.classList.toggle('active', !isAll && northAll);
        if (reg === 'LESTE') chip.classList.toggle('active', !isAll && eastAll);
        if (reg === 'OUTRAS') chip.classList.toggle('active', !isAll && otherActive);
    });

    // 3. Sincronizar Chips de Base
    const baseChips = document.querySelectorAll('#baseFiltersContainer .chip-filter');
    baseChips.forEach(chip => {
        const code = chip.getAttribute('data-base');
        if (isAll) {
            chip.classList.toggle('active', code === 'ALL');
        } else {
            chip.classList.toggle('active', appState.selectedBases.has(code));
        }
    });

    // 4. Sincronizar Cards de Base
    const baseCards = document.querySelectorAll('.base-card-premium');
    baseCards.forEach(card => {
        const code = card.getAttribute('data-base-code');
        if (isAll) {
            card.classList.remove('active-filter');
        } else {
            card.classList.toggle('active-filter', appState.selectedBases.has(code));
        }
    });

    // 5. Sincronizar Blocos Regionais
    const blockNorth = document.getElementById('blockRegionNorth');
    const blockEast = document.getElementById('blockRegionEast');
    const blockOther = document.getElementById('blockRegionOther');

    if (blockNorth) blockNorth.classList.toggle('active-region', !isAll && northAll);
    if (blockEast) blockEast.classList.toggle('active-region', !isAll && eastAll);
    if (blockOther) blockOther.classList.toggle('active-region', !isAll && otherActive);

    // 6. Sincronizar Sub-bases na gaveta
    const subCards = document.querySelectorAll('.sub-base-card');
    subCards.forEach(card => {
        const code = card.getAttribute('data-base-code');
        if (isAll) {
            card.classList.remove('active-sub');
        } else {
            card.classList.toggle('active-sub', appState.selectedBases.has(code));
        }
    });
}

function setStatusFilter(statusCode, element) {
    appState.currentStatusFilter = statusCode;

    const chips = element ? element.parentElement.querySelectorAll('.chip-filter') : document.querySelectorAll('.filter-cluster:nth-child(3) .chip-filter');
    chips.forEach(chip => chip.classList.remove('active'));
    if (element) element.classList.add('active');

    renderResults();
}

function handleSearchChange() {
    const input = document.getElementById('searchInput');
    const btnClear = document.getElementById('btnClearSearch');
    appState.searchQuery = (input ? input.value : '').trim().toUpperCase();

    if (btnClear) {
        btnClear.style.display = appState.searchQuery ? 'flex' : 'none';
    }

    renderResults();
}

function clearSearch() {
    const input = document.getElementById('searchInput');
    if (input) input.value = '';
    handleSearchChange();
}

function setViewMode(mode) {
    appState.viewMode = mode;

    const btnTable = document.getElementById('btnViewTable');
    const btnCards = document.getElementById('btnViewCards');
    const tableContainer = document.getElementById('tableViewContainer');
    const cardsContainer = document.getElementById('cardsViewContainer');

    if (mode === 'table') {
        if (btnTable) btnTable.classList.add('active');
        if (btnCards) btnCards.classList.remove('active');
        if (tableContainer) tableContainer.style.display = 'block';
        if (cardsContainer) cardsContainer.style.display = 'none';
    } else {
        if (btnTable) btnTable.classList.remove('active');
        if (btnCards) btnCards.classList.add('active');
        if (tableContainer) tableContainer.style.display = 'none';
        if (cardsContainer) cardsContainer.style.display = 'block';
    }
}

function clearAllFilters() {
    appState.selectedBases.clear();
    appState.selectedBases.add('ALL');
    appState.currentStatusFilter = 'ALL';
    appState.searchQuery = '';
    
    const input = document.getElementById('searchInput');
    if (input) input.value = '';
    
    const btnClear = document.getElementById('btnClearSearch');
    if (btnClear) btnClear.style.display = 'none';

    document.querySelectorAll('.filter-chips .chip-filter').forEach((c) => {
        const isAll = c.getAttribute('data-status') === 'ALL' || c.getAttribute('data-base') === 'ALL' || c.getAttribute('data-region') === 'ALL';
        c.classList.toggle('active', isAll);
    });

    toggleOtherBasesDrawer(false);
    syncBaseUI();
    updateKPIs();
    renderResults();
    showToast('Filtros redefinidos para o estado padrão.', 'info');
}

// ==========================================================================
// RENDERIZAÇÃO DOS RESULTADOS (TABELA & CARDS)
// ==========================================================================
function getFilteredTeams() {
    let filtered = [...appState.teams];

    // Filtro por Multi-seleção de Bases / Regiões
    if (!appState.selectedBases.has('ALL') && appState.selectedBases.size > 0) {
        filtered = filtered.filter(t => {
            if (appState.selectedBases.has(t.prefix)) return true;
            if (appState.selectedBases.has('OUTRAS') && t.is_other_base) return true;
            return false;
        });
    }

    // Filtro por Status
    if (appState.currentStatusFilter === 'ONLINE') {
        filtered = filtered.filter(t => t.trbonet);
    } else if (appState.currentStatusFilter === 'OFFLINE') {
        filtered = filtered.filter(t => t.status_code === 'OFFLINE');
    } else if (appState.currentStatusFilter === 'TRBO_ONLY') {
        filtered = filtered.filter(t => t.status_code === 'TRBO_ONLY');
    } else if (appState.currentStatusFilter === 'GPS_ONLY') {
        filtered = filtered.filter(t => t.gps);
    }

    // Filtro por Texto de Busca
    if (appState.searchQuery) {
        const q = appState.searchQuery;
        filtered = filtered.filter(t => 
            t.code.toUpperCase().includes(q) ||
            t.base.toUpperCase().includes(q) ||
            (t.radio_id && t.radio_id.toUpperCase().includes(q)) ||
            (t.channel && t.channel.toUpperCase().includes(q))
        );
    }

    // Ordenação
    filtered.sort((a, b) => {
        let valA = a[appState.sortField];
        let valB = b[appState.sortField];

        if (typeof valA === 'string') valA = valA.toLowerCase();
        if (typeof valB === 'string') valB = valB.toLowerCase();

        if (valA < valB) return appState.sortAsc ? -1 : 1;
        if (valA > valB) return appState.sortAsc ? 1 : -1;
        return 0;
    });

    return filtered;
}

function renderResults() {
    const filteredTeams = getFilteredTeams();

    const counter = document.getElementById('resultsCounter');
    if (counter) {
        counter.innerHTML = `Exibindo <strong>${filteredTeams.length}</strong> de <strong>${appState.teams.length}</strong> equipes monitoradas`;
    }

    renderTableView(filteredTeams);
    renderCardsView(filteredTeams);
    initIcons();
}

function renderTableView(teams) {
    const tbody = document.getElementById('teamsTableBody');
    if (!tbody) return;

    if (teams.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="7" class="empty-state-cell">
                    <div class="empty-state-wrap">
                        <i data-lucide="search-x" class="empty-icon"></i>
                        <p>Nenhuma equipe encontrada com os filtros selecionados.</p>
                        <button class="btn btn-secondary btn-sm" onclick="clearAllFilters()">Limpar Filtros</button>
                    </div>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = teams.map(t => {
        const gpsIcon = t.trbonet 
            ? (t.gps ? '<span class="status-indicator-pill pill-gps"><i data-lucide="navigation"></i> Com GPS</span>' 
                     : '<span class="status-indicator-pill pill-nogps"><i data-lucide="radio-tower"></i> Sem GPS</span>')
            : '<span class="text-muted">--</span>';

        const powerOnBadge = t.poweron 
            ? '<span class="badge-status badge-success"><i data-lucide="check"></i> Em Turno</span>'
            : '<span class="badge-status badge-muted"><i data-lucide="minus"></i> Fora de Escala</span>';

        const trboBadge = t.trbonet 
            ? '<span class="badge-status badge-success"><i data-lucide="radio"></i> Conectado</span>'
            : '<span class="badge-status badge-danger"><i data-lucide="x"></i> Desconectado</span>';

        return `
            <tr>
                <td>
                    <div class="team-code-cell">
                        <strong class="team-code-text">${t.code}</strong>
                    </div>
                </td>
                <td>
                    <div class="base-cell">
                        <span>${t.base}</span>
                    </div>
                </td>
                <td>${powerOnBadge}</td>
                <td>${trboBadge}</td>
                <td>${gpsIcon}</td>
                <td>
                    <span class="badge-status ${t.badge_class}">
                        ${t.status_label}
                    </span>
                </td>
                <td>
                    <button class="btn-action-view" onclick="openTeamModal('${t.code}')" title="Ver Diagnóstico e Histórico">
                        <i data-lucide="eye"></i>
                        <span>Ver</span>
                    </button>
                </td>
            </tr>
        `;
    }).join('');
}

function renderCardsView(teams) {
    const grid = document.getElementById('teamsCardsGrid');
    if (!grid) return;

    if (teams.length === 0) {
        grid.innerHTML = `
            <div class="empty-state-wrap glass-card" style="grid-column: 1 / -1; padding: 40px;">
                <i data-lucide="search-x" class="empty-icon"></i>
                <p>Nenhuma equipe encontrada com os filtros selecionados.</p>
                <button class="btn btn-secondary btn-sm" onclick="clearAllFilters()">Limpar Filtros</button>
            </div>
        `;
        return;
    }

    grid.innerHTML = teams.map(t => {
        return `
            <div class="team-card-item glass-card card-status-${t.severity}" onclick="openTeamModal('${t.code}')">
                <div class="team-card-header">
                    <div class="team-card-code-wrap">
                        <span class="team-card-code">${t.code}</span>
                        <span class="team-card-base">${t.base}</span>
                    </div>
                    <span class="badge-status ${t.badge_class}" style="font-size: 0.72rem;">
                        ${t.status_label}
                    </span>
                </div>

                <div class="team-card-body">
                    <div class="team-card-row">
                        <span class="card-row-label"><i data-lucide="clipboard-check" class="mini-icon"></i> PowerON</span>
                        <span class="card-row-val ${t.poweron ? 'text-emerald' : 'text-muted'}">${t.poweron ? 'Em Turno' : 'Fora de Escala'}</span>
                    </div>
                    <div class="team-card-row">
                        <span class="card-row-label"><i data-lucide="radio" class="mini-icon"></i> TRBOnet</span>
                        <span class="card-row-val ${t.trbonet ? 'text-emerald' : 'text-rose'}">${t.trbonet ? 'Conectado' : 'Offline'}</span>
                    </div>
                    <div class="team-card-row">
                        <span class="card-row-label"><i data-lucide="navigation" class="mini-icon"></i> Telemetria</span>
                        <span class="card-row-val">${t.trbonet ? (t.gps ? '🟢 GPS Ativo' : '🟡 Sem GPS') : '⚪ Sem Sinal'}</span>
                    </div>
                </div>

                <div class="team-card-footer">
                    <span class="card-footer-signal"><i data-lucide="clock" class="mini-icon"></i> Sinal: ${t.last_signal || '--:--:--'}</span>
                    <button class="btn-card-details"><i data-lucide="chevron-right"></i></button>
                </div>
            </div>
        `;
    }).join('');
}

function updateFilterBadges() {
    const s = appState.summary;
    const allEl = document.getElementById('count-all');
    const onlineEl = document.getElementById('count-online');
    const offlineEl = document.getElementById('count-offline');
    const trboEl = document.getElementById('count-trbo-only');
    const gpsEl = document.getElementById('count-gps');

    if (allEl) allEl.textContent = appState.teams.length;
    if (onlineEl) onlineEl.textContent = s.total_trbonet || 0;
    if (offlineEl) offlineEl.textContent = s.total_offline || 0;
    if (trboEl) trboEl.textContent = s.total_trbo_only || 0;
    if (gpsEl) gpsEl.textContent = s.online_with_gps || 0;
}

function sortTable(field) {
    if (appState.sortField === field) {
        appState.sortAsc = !appState.sortAsc;
    } else {
        appState.sortField = field;
        appState.sortAsc = true;
    }
    renderResults();
}

// ==========================================================================
// ABA DASHBOARD: GRÁFICOS ANALÍTICOS (CHART.JS)
// ==========================================================================
function renderCharts() {
    const s = appState.summary;
    const bases = appState.bases || [];

    const isLight = document.body.classList.contains('theme-light');
    const chartTextColor = isLight ? '#475569' : '#94a3b8';
    const chartGridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.05)';
    const chartDonutBorder = isLight ? '#ffffff' : '#0e1526';

    // 1. Gráfico de Rosca: Distribuição dos Rádios
    const donutCtx = document.getElementById('statusDonutChart');
    if (donutCtx) {
        if (appState.donutChart) appState.donutChart.destroy();

        const onlineGps = s.online_with_gps || 0;
        const onlineNoGps = s.online_without_gps || 0;
        const offline = s.total_offline || 0;
        const trboOnly = s.total_trbo_only || 0;

        appState.donutChart = new Chart(donutCtx, {
            type: 'doughnut',
            data: {
                labels: ['Online com GPS', 'Online sem GPS', 'Offline Crítico', 'Apenas TRBOnet'],
                datasets: [{
                    data: [onlineGps, onlineNoGps, offline, trboOnly],
                    backgroundColor: ['#10b981', '#06b6d4', '#f43f5e', '#f59e0b'],
                    borderColor: chartDonutBorder,
                    borderWidth: 3,
                    hoverOffset: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: chartTextColor,
                            font: { family: 'Plus Jakarta Sans', size: 12 },
                            padding: 14,
                            usePointStyle: true
                        }
                    }
                },
                cutout: '70%'
            }
        });
    }

    // 2. Gráfico de Barras: Comparativo por Base
    const barCtx = document.getElementById('basesBarChart');
    if (barCtx) {
        if (appState.barChart) appState.barChart.destroy();

        const labels = bases.map(b => b.name ? b.name.replace('Base ', '') : b.prefix);
        const powerOnData = bases.map(b => b.total_poweron || 0);
        const trboData = bases.map(b => b.total_trbonet || b.online_trbo || 0);

        appState.barChart = new Chart(barCtx, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'Escala PowerON',
                        data: powerOnData,
                        backgroundColor: 'rgba(59, 130, 246, 0.75)',
                        borderColor: '#3b82f6',
                        borderWidth: 1,
                        borderRadius: 6
                    },
                    {
                        label: 'Rádio TRBOnet Ativo',
                        data: trboData,
                        backgroundColor: 'rgba(16, 185, 129, 0.75)',
                        borderColor: '#10b981',
                        borderWidth: 1,
                        borderRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: {
                        ticks: { color: chartTextColor, font: { family: 'Plus Jakarta Sans', size: 11 } },
                        grid: { color: chartGridColor }
                    },
                    y: {
                        beginAtZero: true,
                        ticks: { color: chartTextColor, font: { family: 'JetBrains Mono', size: 11 } },
                        grid: { color: chartGridColor }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                        labels: {
                            color: chartTextColor,
                            font: { family: 'Plus Jakarta Sans', size: 12 },
                            usePointStyle: true
                        }
                    }
                }
            }
        });
    }
}

// ==========================================================================
// ABA DASHBOARD: TABELA DE AUDITORIA HISTÓRICA DE EQUIPES
// ==========================================================================
function renderHistoryTable() {
    const tbody = document.getElementById('historyTableBody');
    if (!tbody) return;

    let teams = [...appState.teams];

    if (appState.historySearchQuery) {
        const q = appState.historySearchQuery;
        teams = teams.filter(t => 
            t.code.toUpperCase().includes(q) ||
            t.base.toUpperCase().includes(q) ||
            t.region.toUpperCase().includes(q)
        );
    }

    if (teams.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="8" class="empty-state-cell">
                    <p style="padding: 20px; color: var(--text-muted);">Nenhum histórico encontrado para a busca.</p>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = teams.map(t => {
        const h = t.history || {};
        const compRate = h.compliance_rate !== undefined ? h.compliance_rate : 100;
        const compClass = getComplianceBadgeClass(compRate);

        return `
            <tr>
                <td>
                    <strong style="color: #ffffff; font-family: var(--font-mono); font-size: 0.95rem;">${t.code}</strong>
                </td>
                <td>
                    <div>${t.base}</div>
                    <span style="font-size: 0.72rem; color: var(--text-muted);">${t.region}</span>
                </td>
                <td>
                    <span class="badge-status ${t.poweron ? 'badge-success' : 'badge-muted'}">
                        ${h.poweron_days_count || (t.poweron ? 1 : 0)} dia(s)
                    </span>
                </td>
                <td>
                    <span class="badge-status ${t.trbonet ? 'badge-success' : 'badge-muted'}">
                        ${h.trbonet_days_count || (t.trbonet ? 1 : 0)} dia(s)
                    </span>
                </td>
                <td>
                    <strong style="color: #38bdf8; font-family: var(--font-mono);">${h.online_duration_str || '1h 30m'}</strong>
                </td>
                <td>
                    <span class="${h.offline_incidents > 0 ? 'text-rose font-bold' : 'text-muted'}">
                        ${h.offline_incidents || 0} ocorrência(s)
                    </span>
                </td>
                <td>
                    <span class="base-compliance-badge ${compClass}">
                        ${compRate}%
                    </span>
                </td>
                <td>
                    <span class="badge-status ${t.badge_class}">
                        ${t.status_label}
                    </span>
                </td>
            </tr>
        `;
    }).join('');
}

function handleHistorySearch() {
    const input = document.getElementById('historySearchInput');
    appState.historySearchQuery = (input ? input.value : '').trim().toUpperCase();
    renderHistoryTable();
}

// ==========================================================================
// MODAL DE DETALHES DA EQUIPE
// ==========================================================================
function openTeamModal(code) {
    const team = appState.teams.find(t => t.code === code);
    if (!team) return;

    const modal = document.getElementById('teamDetailModal');
    if (!modal) return;

    const codeEl = document.getElementById('modalTeamCode');
    const baseEl = document.getElementById('modalTeamBase');
    const banner = document.getElementById('modalStatusBanner');
    const title = document.getElementById('modalStatusTitle');
    const desc = document.getElementById('modalStatusDescription');

    const pwStatus = document.getElementById('modalPowerOnStatus');
    const trboStatus = document.getElementById('modalTrboStatus');
    const gpsStatus = document.getElementById('modalGpsStatus');
    const lastSig = document.getElementById('modalLastSignal');
    const onlineTime = document.getElementById('modalOnlineTime');
    const dropCount = document.getElementById('modalDropCount');
    const rec = document.getElementById('modalRecommendation');

    if (codeEl) codeEl.textContent = `EQUIPE ${team.code}`;
    if (baseEl) baseEl.textContent = `${team.base} • ${team.region}`;

    if (banner) banner.className = `team-diagnostic-banner banner-${team.severity}`;
    if (title) title.textContent = team.status_label;
    if (desc) desc.textContent = team.details_text;

    if (pwStatus) pwStatus.innerHTML = team.poweron ? '<span class="text-emerald font-bold">✔ Logada no Turno</span>' : '<span class="text-muted">Fora de Escala</span>';
    if (trboStatus) trboStatus.innerHTML = team.trbonet ? '<span class="text-emerald font-bold">✔ Rádio Conectado</span>' : '<span class="text-rose font-bold">✖ Rádio Desligado</span>';
    if (gpsStatus) gpsStatus.innerHTML = team.trbonet ? (team.gps ? '<span class="text-cyan font-bold">✔ Satélite Fixado</span>' : '<span class="text-amber font-bold">⚠ Sem Fixação GPS</span>') : '<span class="text-muted">--</span>';
    if (lastSig) lastSig.textContent = team.last_signal || 'Sem sinal hoje';

    const h = team.history || {};
    if (onlineTime) onlineTime.textContent = h.online_duration_str || '1h 30m';
    if (dropCount) dropCount.innerHTML = `<span class="${h.offline_incidents > 0 ? 'text-rose font-bold' : 'text-emerald'}">${h.offline_incidents || 0} falha(s) de conexão</span>`;

    if (rec) {
        if (team.status_code === 'OFFLINE') {
            rec.textContent = 'Acionar supervisão de campo para ligar o terminal Motorola ou verificar fusível de alimentação da viatura.';
        } else if (team.status_code === 'ONLINE_NOGPS') {
            rec.textContent = 'Orientar a equipe a posicionar o rádio próximo ao para-brisa para fixação do sinal de satélite GPS.';
        } else if (team.status_code === 'TRBO_ONLY') {
            rec.textContent = 'Verificar se a equipe está prestando serviço extra ou se esqueceu de efetuar o login de início de turno no PowerON.';
        } else {
            rec.textContent = 'Operação em perfeita conformidade. Nenhuma intervenção necessária.';
        }
    }

    openModal('teamDetailModal');
    initIcons();
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('active');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('active');
}

// ==========================================================================
// UPLOAD DE ARQUIVOS (EXCEL / CSV)
// ==========================================================================
function initDropzone() {
    const dropzone = document.getElementById('dropzoneBox');
    if (!dropzone) return;

    ['dragenter', 'dragover'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
    });

    ['dragleave', 'drop'].forEach(eventName => {
        dropzone.addEventListener(eventName, (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        const dt = e.dataTransfer;
        const files = dt.files;
        if (files.length > 0) {
            const input = document.getElementById('fileInput');
            if (input) {
                input.files = files;
                handleFileSelect(input);
            }
        }
    });
}

function handleFileSelect(input) {
    const label = document.getElementById('selectedFileName');
    if (input.files && input.files[0]) {
        const file = input.files[0];
        if (label) {
            label.textContent = `Arquivo selecionado: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
            label.style.display = 'inline-block';
        }
    }
}

async function handleFileUpload(e) {
    e.preventDefault();
    const form = document.getElementById('uploadForm');
    const formData = new FormData(form);

    const fileInput = document.getElementById('fileInput');
    if (!fileInput || !fileInput.files[0]) {
        showToast('Por favor, selecione um arquivo para importar.', 'danger');
        return;
    }

    const btn = document.getElementById('btnSubmitUpload');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> Processando...`;
    }
    initIcons();

    try {
        const response = await fetch('/api/upload', {
            method: 'POST',
            body: formData
        });
        const result = await response.json();
        if (result.status === 'success') {
            showToast(result.message, 'success');
            closeModal('uploadModal');
            fetchDashboardData(false);
        } else {
            showToast(result.message, 'danger');
        }
    } catch (err) {
        showToast(`Erro no envio do arquivo: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="check"></i> Processar e Atualizar Painel`;
        }
        initIcons();
    }
}

// ==========================================================================
// EXPORTAÇÃO & TOASTS
// ==========================================================================
function toggleExportMenu() {
    const menu = document.getElementById('exportMenu');
    if (menu) menu.classList.toggle('active');
}

document.addEventListener('click', (e) => {
    const exportBtn = document.getElementById('btnExport');
    const exportMenu = document.getElementById('exportMenu');
    if (exportBtn && exportMenu && !exportBtn.contains(e.target) && !exportMenu.contains(e.target)) {
        exportMenu.classList.remove('active');
    }
});

function copySummaryToClipboard() {
    const s = appState.summary;
    const text = `=== ALERTAS OPERACIONAIS OP (POWERON × TRBONET) ===
Data: ${s.last_update}
Total PowerON: ${s.total_poweron} equipes
Total TRBOnet: ${s.total_trbonet} rádios
Online com GPS: ${s.online_with_gps}
Online sem GPS: ${s.online_without_gps}
Offline Crítico: ${s.total_offline} equipes
Apenas TRBOnet: ${s.total_trbo_only} rádios
Índice de Conformidade CCO: ${s.compliance_rate}%`;

    navigator.clipboard.writeText(text).then(() => {
        showToast('Resumo executivo copiado para a área de transferência!', 'success');
    });
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconName = 'info';
    if (type === 'success') iconName = 'check-circle-2';
    if (type === 'danger') iconName = 'alert-octagon';

    toast.innerHTML = `<i data-lucide="${iconName}"></i> <span>${message}</span>`;
    container.appendChild(toast);
    initIcons();

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function toggleFullscreen() {
    if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().catch(() => {});
    } else {
        document.exitFullscreen().catch(() => {});
    }
}
