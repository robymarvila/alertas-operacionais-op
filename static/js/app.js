/**
 * PAINEL OPERACIONAL CCO - POWERON VS TRBONET (ULTRA PREMIUM)
 * Motor Reativo, Multi-Seleção Regional e de Bases, Sincronização PowerON e Auditoria
 */

// Configuração das 4 Regiões Oficiais (14 Bases Oficiais)
const REGION_CONFIG = {
    NORTE_ALPITEL: {
        name: 'Região Norte Alpitel',
        bases: ['ENL', 'ECL', 'EEL'],
        color: '#10b981'
    },
    LESTE_ALPITEL: {
        name: 'Região Leste Alpitel',
        bases: ['EML', 'EQL', 'EVL', 'ESL'],
        color: '#3b82f6'
    },
    NORTE_PROPRIA: {
        name: 'Região Norte Própria',
        bases: ['ENA', 'ECA', 'EEA'],
        color: '#8b5cf6'
    },
    LESTE_PROPRIA: {
        name: 'Região Leste Própria',
        bases: ['EMA', 'EQA', 'EVA', 'ESA'],
        color: '#ec4899'
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
    
    // Auto-refresh Timer (5 Minutos = 300 segundos)
    refreshIntervalSeconds: 300,
    secondsRemaining: 300,
    timerId: null,
    isPaused: false,
    
    // Gráficos Chart.js
    donutChart: null,
    barChart: null
};

// Estado de Autenticação e Controle de Acesso (E2EE)
const authState = {
    token: sessionStorage.getItem('cco_auth_token') || null,
    user: JSON.parse(sessionStorage.getItem('cco_auth_user') || 'null'),
    isAuthenticated: false,
    activeTab: 'login',
    adminUsers: []
};

// ==========================================================================
// INICIALIZAÇÃO DO SISTEMA
// ==========================================================================
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initClock();
    initIcons();
    initDropzone();
    initAuth();
    fetchDashboardData(false);
    startAutoRefreshTimer();
    navigateToView('hub');

    // Ao voltar para a aba do navegador, atualiza instantaneamente
    window.addEventListener('focus', () => {
        fetchDashboardData(false);
        if (appState.currentMainTab === 'audit') {
            loadAuditData(true);
        }
    });
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
// NAVEGAÇÃO ENTRE JANELAS / ABAS DO MÓDULO (AO VIVO × DASHBOARD × AUDITORIA)
// ==========================================================================
function switchMainTab(tabName) {
    appState.currentMainTab = tabName;

    const btnLive = document.getElementById('tabBtnLive');
    const btnDash = document.getElementById('tabBtnDashboard');
    const btnAudit = document.getElementById('tabBtnAudit');
    const paneLive = document.getElementById('tabViewLive');
    const paneDash = document.getElementById('tabViewDashboard');
    const paneAudit = document.getElementById('tabViewAudit');

    // Remove estado ativo de todos os botões
    if (btnLive) btnLive.classList.remove('active');
    if (btnDash) btnDash.classList.remove('active');
    if (btnAudit) btnAudit.classList.remove('active');

    // Oculta todos os painéis
    if (paneLive) paneLive.style.display = 'none';
    if (paneDash) paneDash.style.display = 'none';
    if (paneAudit) paneAudit.style.display = 'none';

    if (tabName === 'live') {
        if (btnLive) btnLive.classList.add('active');
        if (paneLive) paneLive.style.display = 'flex';
    } else if (tabName === 'dashboard') {
        if (btnDash) btnDash.classList.add('active');
        if (paneDash) paneDash.style.display = 'flex';

        setTimeout(() => {
            renderCharts();
            renderHistoryTable();
        }, 100);
    } else if (tabName === 'audit') {
        if (btnAudit) btnAudit.classList.add('active');
        if (paneAudit) paneAudit.style.display = 'flex';

        initAuditTab();
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
// BUSCA DE DADOS NA API (TEMPO REAL)
// ==========================================================================
async function fetchDashboardData(isManual = false) {
    const refreshIcon = document.getElementById('refreshIcon');
    if (refreshIcon && isManual) refreshIcon.classList.add('spin-animation');
    
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

            if (isManual) {
                showToast('Painel sincronizado em tempo real!', 'success');
            }
        }
    } catch (error) {
        console.error('Erro ao buscar dados do servidor:', error);
        if (liveStatus) liveStatus.textContent = 'RECONECTANDO';
        if (liveBadge) liveBadge.className = 'live-pill live-pill-warning';
        if (isManual) {
            showToast('Falha na comunicação com o servidor.', 'danger');
        }
    } finally {
        if (refreshIcon && isManual) {
            setTimeout(() => refreshIcon.classList.remove('spin-animation'), 600);
        }
        initIcons();
    }
}

function manualRefresh() {
    appState.secondsRemaining = appState.refreshIntervalSeconds;
    fetchDashboardData(true);
    if (appState.currentMainTab === 'audit') {
        loadAuditData(false);
    }
}

// ==========================================================================
// SINCRONIZAÇÃO DO TRBONET ONE (LEITURA SILENCIOSA AO VIVO)
// ==========================================================================
async function captureTRBOnetLive() {
    if (!authState.isAuthenticated) {
        showToast('Ação Restrita: Efetue o login no Cadeado para ler o TRBOnet One.', 'warning');
        openAuthModal();
        return;
    }

    const btn = document.getElementById('btnLiveCapture');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Lendo TRBOnet...</span>`;
    }
    initIcons();

    try {
        const response = await fetch('/api/capture/trbonet', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authState.token || ''}`
            }
        });
        const result = await response.json();
        if (response.status === 401) {
            showToast('Sessão expirada ou não autorizada. Faça login novamente.', 'danger');
            handleLogout(false);
            openAuthModal();
            return;
        }

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
    if (!authState.isAuthenticated) {
        showToast('Ação Restrita: Efetue o login no Cadeado para sincronizar o PowerON.', 'warning');
        openAuthModal();
        return;
    }

    const btn = document.getElementById('btnSyncPowerOn');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Lendo PowerON...</span>`;
    }
    initIcons();

    try {
        const response = await fetch('/api/sync/poweron', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${authState.token || ''}`
            }
        });
        const result = await response.json();
        if (response.status === 401) {
            showToast('Sessão expirada ou não autorizada. Faça login novamente.', 'danger');
            handleLogout(false);
            openAuthModal();
            return;
        }

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
            if (appState.currentMainTab === 'audit') {
                loadAuditData(true);
            }
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
        targetTeams = targetTeams.filter(t => appState.selectedBases.has(t.prefix));
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
            scopeText.textContent = `Todas as 14 Bases Oficiais (Visão Global • ${targetTeams.length} equipes monitoradas)`;
        } else {
            const selectedLabels = [];
            Object.keys(REGION_CONFIG).forEach(key => {
                const conf = REGION_CONFIG[key];
                const allInReg = conf.bases.every(b => appState.selectedBases.has(b));
                if (allInReg) {
                    selectedLabels.push(conf.name);
                } else {
                    conf.bases.forEach(b => {
                        if (appState.selectedBases.has(b)) selectedLabels.push(b);
                    });
                }
            });
            scopeText.textContent = `Filtrando: ${selectedLabels.join(', ')} (${targetTeams.length} equipes monitoradas)`;
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
// RENDERIZAÇÃO DAS 14 BASES OPERACIONAIS POR REGIÃO & EMPRESA
// ==========================================================================
function renderRegionalBases() {
    const northAlpitelGrid = document.getElementById('northAlpitelBasesGrid');
    const eastAlpitelGrid = document.getElementById('eastAlpitelBasesGrid');
    const northPropriaGrid = document.getElementById('northPropriaBasesGrid');
    const eastPropriaGrid = document.getElementById('eastPropriaBasesGrid');

    const regions = appState.regions || {};
    const northAlpitelBases = regions.NORTE_ALPITEL ? regions.NORTE_ALPITEL.bases : [];
    const eastAlpitelBases = regions.LESTE_ALPITEL ? regions.LESTE_ALPITEL.bases : [];
    const northPropriaBases = regions.NORTE_PROPRIA ? regions.NORTE_PROPRIA.bases : [];
    const eastPropriaBases = regions.LESTE_PROPRIA ? regions.LESTE_PROPRIA.bases : [];

    if (northAlpitelGrid) northAlpitelGrid.innerHTML = northAlpitelBases.map(b => createBaseCardHTML(b)).join('');
    if (eastAlpitelGrid) eastAlpitelGrid.innerHTML = eastAlpitelBases.map(b => createBaseCardHTML(b)).join('');
    if (northPropriaGrid) northPropriaGrid.innerHTML = northPropriaBases.map(b => createBaseCardHTML(b)).join('');
    if (eastPropriaGrid) eastPropriaGrid.innerHTML = eastPropriaBases.map(b => createBaseCardHTML(b)).join('');

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

// ==========================================================================
// FILTRAGEM MULTI-SELEÇÃO DINÂMICA DE REGIÕES, BASES E STATUS
// ==========================================================================
function toggleRegionFilter(regionCode, element) {
    if (regionCode === 'ALL') {
        appState.selectedBases.clear();
        appState.selectedBases.add('ALL');
    } else if (REGION_CONFIG[regionCode]) {
        const regionBases = REGION_CONFIG[regionCode].bases;
        const allPresent = regionBases.every(b => appState.selectedBases.has(b));

        if (allPresent) {
            regionBases.forEach(b => appState.selectedBases.delete(b));
            if (appState.selectedBases.size === 0) appState.selectedBases.add('ALL');
        } else {
            appState.selectedBases.delete('ALL');
            regionBases.forEach(b => appState.selectedBases.add(b));
        }

        // Se todas as 14 bases forem selecionadas, simplifica para 'ALL'
        const all14Bases = [
            ...REGION_CONFIG.NORTE_ALPITEL.bases,
            ...REGION_CONFIG.LESTE_ALPITEL.bases,
            ...REGION_CONFIG.NORTE_PROPRIA.bases,
            ...REGION_CONFIG.LESTE_PROPRIA.bases
        ];
        if (all14Bases.every(b => appState.selectedBases.has(b))) {
            appState.selectedBases.clear();
            appState.selectedBases.add('ALL');
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
    } else {
        appState.selectedBases.delete('ALL');
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

    const northAlpitelAll = REGION_CONFIG.NORTE_ALPITEL.bases.every(b => appState.selectedBases.has(b));
    const eastAlpitelAll = REGION_CONFIG.LESTE_ALPITEL.bases.every(b => appState.selectedBases.has(b));
    const northPropriaAll = REGION_CONFIG.NORTE_PROPRIA.bases.every(b => appState.selectedBases.has(b));
    const eastPropriaAll = REGION_CONFIG.LESTE_PROPRIA.bases.every(b => appState.selectedBases.has(b));

    // 1. Sincronizar Chips de Região (Barra de Filtros)
    const regionChips = document.querySelectorAll('#regionFiltersContainer .chip-filter');
    regionChips.forEach(chip => {
        const reg = chip.getAttribute('data-region');
        if (reg === 'ALL') chip.classList.toggle('active', isAll);
        if (reg === 'NORTE_ALPITEL') chip.classList.toggle('active', !isAll && northAlpitelAll);
        if (reg === 'LESTE_ALPITEL') chip.classList.toggle('active', !isAll && eastAlpitelAll);
        if (reg === 'NORTE_PROPRIA') chip.classList.toggle('active', !isAll && northPropriaAll);
        if (reg === 'LESTE_PROPRIA') chip.classList.toggle('active', !isAll && eastPropriaAll);
    });

    // 2. Sincronizar Botões Rápidos de Região (Barra de KPIs)
    const quickRegBtns = document.querySelectorAll('.kpi-quick-regions .btn-quick-region');
    quickRegBtns.forEach(btn => {
        const reg = btn.getAttribute('data-region');
        if (reg === 'ALL') btn.classList.toggle('active', isAll);
        if (reg === 'NORTE_ALPITEL') btn.classList.toggle('active', !isAll && northAlpitelAll);
        if (reg === 'LESTE_ALPITEL') btn.classList.toggle('active', !isAll && eastAlpitelAll);
        if (reg === 'NORTE_PROPRIA') btn.classList.toggle('active', !isAll && northPropriaAll);
        if (reg === 'LESTE_PROPRIA') btn.classList.toggle('active', !isAll && eastPropriaAll);
    });

    // 3. Atualizar Texto do Escopo dos KPIs
    const scopeText = document.getElementById('kpiScopeText');
    if (scopeText) {
        if (isAll) {
            scopeText.textContent = 'Todas as Regiões e Bases (Visão Global Consolidada)';
        } else {
            const activeRegs = [];
            if (northAlpitelAll) activeRegs.push('Norte Alpitel');
            if (northPropriaAll) activeRegs.push('Norte Própria');
            if (eastAlpitelAll) activeRegs.push('Leste Alpitel');
            if (eastPropriaAll) activeRegs.push('Leste Própria');
            
            if (activeRegs.length > 0) {
                scopeText.textContent = `Regiões Ativas: ${activeRegs.join(' + ')}`;
            } else {
                scopeText.textContent = `Bases Ativas: ${Array.from(appState.selectedBases).join(', ')}`;
            }
        }
    }

    // 4. Sincronizar Chips de Base
    const baseChips = document.querySelectorAll('#baseFiltersContainer .chip-filter');
    baseChips.forEach(chip => {
        const code = chip.getAttribute('data-base');
        if (isAll) {
            chip.classList.toggle('active', code === 'ALL');
        } else {
            chip.classList.toggle('active', appState.selectedBases.has(code));
        }
    });

    // 5. Sincronizar Cards de Base
    const baseCards = document.querySelectorAll('.base-card-premium');
    baseCards.forEach(card => {
        const code = card.getAttribute('data-base-code');
        if (isAll) {
            card.classList.remove('active-filter');
        } else {
            card.classList.toggle('active-filter', appState.selectedBases.has(code));
        }
    });

    // 6. Sincronizar Blocos Regionais
    const blockNorthAlpitel = document.getElementById('blockRegionNorthAlpitel');
    const blockEastAlpitel = document.getElementById('blockRegionEastAlpitel');
    const blockNorthPropria = document.getElementById('blockRegionNorthPropria');
    const blockEastPropria = document.getElementById('blockRegionEastPropria');

    if (blockNorthAlpitel) blockNorthAlpitel.classList.toggle('active-region', !isAll && northAlpitelAll);
    if (blockEastAlpitel) blockEastAlpitel.classList.toggle('active-region', !isAll && eastAlpitelAll);
    if (blockNorthPropria) blockNorthPropria.classList.toggle('active-region', !isAll && northPropriaAll);
    if (blockEastPropria) blockEastPropria.classList.toggle('active-region', !isAll && eastPropriaAll);
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
    if (!authState.isAuthenticated) {
        showToast('Ação Restrita: Efetue o login no Cadeado para importar planilhas.', 'warning');
        openAuthModal();
        return;
    }

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
            headers: {
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: formData
        });
        const result = await response.json();
        if (response.status === 401) {
            showToast('Sessão expirada ou não autorizada. Faça login novamente.', 'danger');
            handleLogout(false);
            openAuthModal();
            return;
        }

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

function exportLiveTeamsExcel() {
    const teams = appState.teams || [];
    const timestamp = new Date().toISOString().replace(/[-:T]/g, '_').slice(0, 15);
    const filename = `Alertas_Operacionais_PowerON_vs_TRBOnet_${timestamp}.xlsx`;

    // 1. Tenta geração client-side instantânea via SheetJS
    if (window.XLSX && teams.length > 0) {
        try {
            const summary = appState.summary || {};
            const lastPwLogin = summary.last_poweron_login || '--';
            const lastTrboSync = summary.last_trbonet_sync || '--';

            const rows = teams.map(t => ({
                "Código Equipe": t.code || '',
                "Base Operacional": t.base || '',
                "Sigla Base": t.prefix || '',
                "Região / Empresa": t.region || '',
                "Status de Conformidade": t.status_label || t.status_code || '',
                "Escala PowerON": t.poweron ? 'SIM (ESCALADA)' : 'NÃO (FORA DA ESCALA)',
                "Conexão TRBOnet": t.trbonet ? 'ONLINE (CONECTADO)' : 'DESCONECTADO',
                "Sinal GPS": t.gps ? 'COM SINAL GPS' : 'SEM SINAL GPS',
                "ID do Rádio": t.radio_id || '--',
                "Canal TRBOnet": t.channel || '--',
                "Último Sinal Registrado": t.last_signal || lastTrboSync || '--',
                "Horário Login PowerON": t.login_time || lastPwLogin || '--',
                "Diagnóstico CCO": t.details_text || ''
            }));

            const ws = XLSX.utils.json_to_sheet(rows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Painel_Operacional_CCO");
            XLSX.writeFile(wb, filename);

            const exportMenu = document.getElementById('exportMenu');
            if (exportMenu) exportMenu.classList.remove('active');

            showToast(`Planilha Excel (.xlsx) exportada com sucesso (${teams.length} equipes)!`, 'success');
            return;
        } catch (err) {
            console.warn('Falha na exportação client-side via SheetJS, redirecionando para backend:', err);
        }
    }

    // 2. Fallback via rota backend
    const exportMenu = document.getElementById('exportMenu');
    if (exportMenu) exportMenu.classList.remove('active');
    window.location.href = '/api/export/excel';
    showToast('Download da Planilha Excel (.xlsx) iniciado!', 'success');
}

window.exportLiveTeamsExcel = exportLiveTeamsExcel;

function exportLiveTeamsCSV() {
    const teams = appState.teams || [];
    if (!teams || teams.length === 0) {
        showToast('Nenhum dado operacional disponível para exportação no momento.', 'warning');
        return;
    }

    const summary = appState.summary || {};
    const lastPwLogin = summary.last_poweron_login || '--';
    const lastTrboSync = summary.last_trbonet_sync || '--';

    let csv = '\uFEFF'; // UTF-8 BOM para o Microsoft Excel abrir com acentuação perfeita
    csv += 'Equipe;Base;Prefixo;Regiao;Status_Operacional;Categoria;Escala_PowerON;Conexao_TRBOnet;Sinal_GPS;Radio_ID;Canal;Ultimo_Sinal_TRBOnet;Ultimo_Login_PowerON;Diagnostico_CCO\n';

    teams.forEach(t => {
        const code = (t.code || '').replace(/"/g, '""');
        const base = (t.base || '').replace(/"/g, '""');
        const prefix = (t.prefix || '').replace(/"/g, '""');
        const region = (t.region || '').replace(/"/g, '""');
        const statusLabel = (t.status_label || t.status_code || '').replace(/"/g, '""');
        const category = (t.status_category || '').replace(/"/g, '""');
        const poweron = t.poweron ? 'SIM (ESCALADA)' : 'NAO (FORA DA ESCALA)';
        const trbonet = t.trbonet ? 'SIM (CONECTADO)' : 'NAO (DESCONECTADO)';
        const gps = t.gps ? 'SIM (COM GPS)' : 'NAO (SEM GPS)';
        const radioId = (t.radio_id || '--').replace(/"/g, '""');
        const channel = (t.channel || '--').replace(/"/g, '""');
        const lastSignal = (t.last_signal || lastTrboSync || '--').replace(/"/g, '""');
        const lastLogin = (t.login_time || lastPwLogin || '--').replace(/"/g, '""');
        const details = (t.details_text || '').replace(/"/g, '""');

        csv += `"${code}";"${base}";"${prefix}";"${region}";"${statusLabel}";"${category}";"${poweron}";"${trbonet}";"${gps}";"${radioId}";"${channel}";"${lastSignal}";"${lastLogin}";"${details}"\n`;
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[-:T]/g, '_').slice(0, 15);
    link.setAttribute('href', url);
    link.setAttribute('download', `Alertas_Operacionais_PowerON_vs_TRBOnet_${timestamp}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    const exportMenu = document.getElementById('exportMenu');
    if (exportMenu) exportMenu.classList.remove('active');

    showToast(`Arquivo CSV exportado com sucesso (${teams.length} equipes)!`, 'success');
}

window.exportLiveTeamsCSV = exportLiveTeamsCSV;

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

// ==========================================================================
// EXPORTAÇÃO CSV / EXCEL DA OPERAÇÃO AO VIVO (100% DAS EQUIPES CONCILIADAS)
// ==========================================================================
function exportLiveTeamsCSV() {
    const teams = appState.teams || [];
    if (teams.length === 0) {
        showToast('Nenhum dado disponível para exportação no momento.', 'warning');
        return;
    }

    const headers = [
        "Código Equipe",
        "Base Operacional",
        "Sigla Base",
        "Região / Empresa",
        "Status Conciliação CCO",
        "Escala PowerON",
        "Conexão TRBOnet",
        "Sinal GPS",
        "ID do Rádio",
        "Canal TRBOnet",
        "Último Sinal Registrado",
        "Horário Login PowerON",
        "Diagnóstico CCO"
    ];

    const rows = teams.map(t => [
        t.code || '',
        t.base || '',
        t.prefix || '',
        t.region || '',
        t.status_label || t.status_code || '',
        t.poweron ? 'SIM (ESCALADA)' : 'NÃO (FORA DA ESCALA)',
        t.trbonet ? 'ONLINE (CONECTADO)' : 'DESCONECTADO',
        t.gps ? 'COM SINAL GPS' : 'SEM SINAL GPS',
        t.radio_id || '--',
        t.channel || '--',
        t.last_signal || '--',
        t.login_time || appState.summary.last_poweron_login || '--',
        `"${(t.details_text || '').replace(/"/g, '""')}"`
    ]);

    const csvContent = "\uFEFF" + [headers.join(';')].concat(rows.map(r => r.join(';'))).join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const timeStr = now.toTimeString().slice(0, 5).replace(':', '-');
    link.setAttribute('href', url);
    link.setAttribute('download', `Alertas_Operacionais_PowerON_vs_TRBOnet_${dateStr}_${timeStr}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    showToast(`Planilha exportada com sucesso (${teams.length} equipes conciliadas)!`, 'success');
}

// ==========================================================================
// EXPORTAÇÃO CSV DA ABA AUDITORIA & HISTÓRICO (RESPONDE AOS FILTROS DA TELA)
// ==========================================================================
function exportAuditTableCSV() {
    const list = auditState.filteredData || [];
    if (list.length === 0) {
        showToast('Nenhum registro de auditoria filtrado para exportar.', 'warning');
        return;
    }

    const isDaily = auditState.mode === 'daily';
    let headers = [];
    let rows = [];

    if (isDaily) {
        headers = [
            "Data Referência",
            "Código Equipe",
            "Base Operacional",
            "Região / Empresa",
            "Escala PowerON",
            "Presença no TRBOnet",
            "Status no Dia",
            "Tempo Online (minutos)",
            "Percentual Uptime",
            "Coletas Online",
            "Total Coletas Auditadas",
            "Primeiro Sinal",
            "Último Sinal"
        ];

        rows = list.map(item => [
            item.date_ref || '',
            item.team_code || '',
            item.base_code || '',
            item.region || '',
            item.was_in_poweron ? 'SIM' : 'NÃO',
            item.was_online_trbonet ? 'SIM' : 'NÃO',
            (item.was_in_poweron && item.was_online_trbonet) ? 'CONFORME' : (item.was_in_poweron ? 'OFFLINE' : 'APENAS TRBONET'),
            item.online_minutes || 0,
            `${item.uptime_percentage || 0}%`,
            item.online_sync_checks || 0,
            item.total_sync_checks || 0,
            item.first_signal || '--',
            item.last_signal || '--'
        ]);
    } else {
        headers = [
            "Data / Hora Captura",
            "Data Referência",
            "Código Equipe",
            "Base Operacional",
            "Região",
            "Status CCO",
            "Escala PowerON",
            "Conexão TRBOnet",
            "Sinal GPS",
            "ID do Rádio",
            "Canal",
            "Último Sinal",
            "Horário Login PowerON"
        ];

        rows = list.map(item => [
            item.captured_at ? new Date(item.captured_at).toLocaleString('pt-BR') : '--',
            item.date_ref || '',
            item.team_code || '',
            item.base_code || '',
            item.region || '',
            item.status || '',
            item.in_poweron ? 'SIM' : 'NÃO',
            item.in_trbonet ? 'ONLINE' : 'DESCONECTADO',
            item.has_gps ? 'COM GPS' : 'SEM GPS',
            item.radio_id || '--',
            item.channel || '--',
            item.last_signal || '--',
            item.poweron_login_time || '--'
        ]);
    }

    const csvContent = "\uFEFF" + [headers.join(';')].concat(rows.map(r => r.join(';'))).join('\r\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const modeLabel = isDaily ? 'Consolidado_Dia' : 'Logs_Coletas';
    const dateVal = document.getElementById('auditFilterDate')?.value || new Date().toISOString().slice(0, 10);
    link.setAttribute('href', url);
    link.setAttribute('download', `Auditoria_Historico_${modeLabel}_${dateVal}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    showToast(`Relatório de auditoria exportado com sucesso (${list.length} registros)!`, 'success');
}

// ==========================================================================
// TELA CHEIA (CROSS-BROWSER)
// ==========================================================================
function toggleFullscreen() {
    const isFull = document.fullscreenElement || document.webkitFullscreenElement || document.mozFullScreenElement || document.msFullscreenElement;
    const btn = document.getElementById('btnFullscreen');

    if (!isFull) {
        const docEl = document.documentElement;
        const requestMethod = docEl.requestFullscreen || docEl.webkitRequestFullscreen || docEl.mozRequestFullScreen || docEl.msRequestFullscreen;
        if (requestMethod) {
            requestMethod.call(docEl).then(() => {
                showToast('Modo Tela Cheia ativado.', 'info');
                if (btn) {
                    const span = btn.querySelector('span');
                    if (span) span.textContent = 'Sair Tela Cheia';
                }
            }).catch(err => {
                console.warn('Erro ao ativar tela cheia:', err);
            });
        }
    } else {
        const exitMethod = document.exitFullscreen || document.webkitExitFullscreen || document.mozCancelFullScreen || document.msExitFullscreen;
        if (exitMethod) {
            exitMethod.call(document).then(() => {
                showToast('Modo Tela Cheia desativado.', 'info');
                if (btn) {
                    const span = btn.querySelector('span');
                    if (span) span.textContent = 'Tela Cheia';
                }
            }).catch(err => {
                console.warn('Erro ao sair de tela cheia:', err);
            });
        }
    }
}

document.addEventListener('fullscreenchange', () => {
    const isFull = !!document.fullscreenElement;
    const btn = document.getElementById('btnFullscreen');
    if (btn) {
        const span = btn.querySelector('span');
        if (span) span.textContent = isFull ? 'Sair Tela Cheia' : 'Tela Cheia';
        const icon = btn.querySelector('i');
        if (icon) {
            icon.setAttribute('data-lucide', isFull ? 'minimize' : 'maximize');
            initIcons();
        }
    }
});

// ==========================================================================
// MÓDULO DE AUDITORIA & HISTÓRICO RELACIONAL (POSTGRESQL / SUPABASE)
// ==========================================================================

const auditState = {
    mode: 'daily', // 'daily' (consolidado do dia) ou 'logs' (coletas brutas)
    rawData: [],
    filteredData: [],
    searchTimer: null
};

/**
 * Inicializa a aba de Auditoria definindo a data de hoje e disparando a primeira consulta.
 */
function initAuditTab() {
    const dateInput = document.getElementById('auditFilterDate');
    if (dateInput && !dateInput.value) {
        const today = new Date().toISOString().split('T')[0];
        dateInput.value = today;
    }
    loadAuditData();
}

/**
 * Alterna entre modo 'daily' (Consolidado do Dia) e 'logs' (Logs por Coleta).
 */
function setAuditViewMode(mode) {
    auditState.mode = mode;

    const btnDaily = document.getElementById('btnAuditModeDaily');
    const btnLogs = document.getElementById('btnAuditModeLogs');
    const titleEl = document.getElementById('auditTableTitle');
    const subtitleEl = document.getElementById('auditTableSubtitle');

    if (mode === 'daily') {
        if (btnDaily) btnDaily.classList.add('active');
        if (btnLogs) btnLogs.classList.remove('active');
        if (titleEl) titleEl.textContent = 'Consolidado Diário de Auditoria';
        if (subtitleEl) subtitleEl.textContent = 'Resumo de conexões e presença por equipe na data selecionada';
    } else {
        if (btnDaily) btnDaily.classList.remove('active');
        if (btnLogs) btnLogs.classList.add('active');
        if (titleEl) titleEl.textContent = 'Logs Detalhados por Coleta';
        if (subtitleEl) subtitleEl.textContent = 'Histórico individual de cada transmissão de rádio/GPS registrada pelo sistema';
    }

    loadAuditData();
}

/**
 * Consulta a API local (que consulta o Supabase / PostgreSQL) para carregar os dados de auditoria.
 */
async function loadAuditData(isSilent = false) {
    const refreshIcon = document.getElementById('btnAuditRefreshIcon');
    if (refreshIcon && !isSilent) refreshIcon.classList.add('spin-animation');

    const dateVal = document.getElementById('auditFilterDate')?.value || '';
    const baseVal = document.getElementById('auditFilterBase')?.value || 'ALL';
    const statusVal = document.getElementById('auditFilterStatus')?.value || 'ALL';
    const teamVal = (document.getElementById('auditSearchTeam')?.value || '').trim();

    try {
        let endpoint = '';
        if (auditState.mode === 'daily') {
            const params = new URLSearchParams();
            if (dateVal) params.append('date', dateVal);
            if (baseVal && baseVal !== 'ALL') params.append('base', baseVal);
            endpoint = `/api/audit/daily_summary?${params.toString()}`;
        } else {
            const params = new URLSearchParams();
            if (dateVal) params.append('date', dateVal);
            if (baseVal && baseVal !== 'ALL') params.append('base', baseVal);
            if (statusVal && statusVal !== 'ALL') params.append('status', statusVal);
            if (teamVal) params.append('team', teamVal);
            params.append('limit', '300');
            endpoint = `/api/audit/logs?${params.toString()}`;
        }

        const res = await fetch(endpoint);
        const data = await res.json();

        if (data.status === 'success') {
            auditState.rawData = data.data || [];
            applyAuditFilters();
        } else {
            auditState.rawData = [];
            applyAuditFilters();
            if (!isSilent) {
                showToast(`Supabase: ${data.message || 'Nenhum registro encontrado'}`, 'info');
            }
        }
    } catch (err) {
        console.error('Erro ao carregar auditoria:', err);
        if (!isSilent) {
            showToast('Falha na comunicação com o banco de dados Supabase.', 'danger');
        }
    } finally {
        if (refreshIcon && !isSilent) {
            setTimeout(() => refreshIcon.classList.remove('spin-animation'), 400);
        }
    }
}

/**
 * Aplica os filtros locais de status e texto sobre os dados brutos recebidos.
 */
function applyAuditFilters() {
    const statusVal = document.getElementById('auditFilterStatus')?.value || 'ALL';
    const teamVal = (document.getElementById('auditSearchTeam')?.value || '').trim().toUpperCase();

    let filtered = [...auditState.rawData];

    // Filtro por equipe (busca parcial)
    if (teamVal) {
        filtered = filtered.filter(item => {
            const code = (item.team_code || '').toUpperCase();
            return code.includes(teamVal);
        });
    }

    // Filtro por status no modo diário
    if (auditState.mode === 'daily' && statusVal !== 'ALL') {
        filtered = filtered.filter(item => {
            if (statusVal === 'CONFORME') return item.was_in_poweron && item.was_online_trbonet;
            if (statusVal === 'APENAS_POWERON') return item.was_in_poweron && !item.was_online_trbonet;
            if (statusVal === 'APENAS_TRBONET') return !item.was_in_poweron && item.was_online_trbonet;
            if (statusVal === 'OFFLINE') return !item.was_online_trbonet;
            return true;
        });
    }

    auditState.filteredData = filtered;
    updateAuditKPIs();
    renderAuditTable();
}

/**
 * Atualiza os 4 cards de KPIs com base nos dados filtrados.
 */
function updateAuditKPIs() {
    const totalTeamsEl = document.getElementById('auditKpiTotalTeams');
    const onlineTeamsEl = document.getElementById('auditKpiOnlineTeams');
    const onlinePercentEl = document.getElementById('auditKpiOnlinePercent');
    const uptimeEl = document.getElementById('auditKpiUptime');
    const totalBatchesEl = document.getElementById('auditKpiTotalBatches');
    const countBadge = document.getElementById('auditResultsCountBadge');

    const list = auditState.filteredData;
    if (countBadge) countBadge.textContent = `${list.length} registros`;

    if (auditState.mode === 'daily') {
        const total = list.length;
        const onlineCount = list.filter(i => i.was_online_trbonet).length;
        const percent = total > 0 ? ((onlineCount / total) * 100).toFixed(1) : '0.0';
        
        let avgUptime = 0;
        if (total > 0) {
            const sumUptime = list.reduce((acc, curr) => acc + (parseFloat(curr.uptime_percentage) || 0), 0);
            avgUptime = (sumUptime / total).toFixed(1);
        }

        const maxChecks = list.length > 0 ? Math.max(...list.map(i => i.total_sync_checks || 0)) : 0;

        if (totalTeamsEl) totalTeamsEl.textContent = total;
        if (onlineTeamsEl) onlineTeamsEl.textContent = onlineCount;
        if (onlinePercentEl) onlinePercentEl.textContent = `${percent}% de presença no dia`;
        if (uptimeEl) uptimeEl.textContent = `${avgUptime}%`;
        if (totalBatchesEl) totalBatchesEl.textContent = maxChecks;
    } else {
        const total = list.length;
        const uniqueTeams = new Set(list.map(i => i.team_code)).size;
        const onlineEvents = list.filter(i => i.in_trbonet).length;

        if (totalTeamsEl) totalTeamsEl.textContent = uniqueTeams;
        if (onlineTeamsEl) onlineTeamsEl.textContent = onlineEvents;
        if (onlinePercentEl) onlinePercentEl.textContent = `${total} eventos registrados`;
        if (uptimeEl) uptimeEl.textContent = total > 0 ? `${((onlineEvents / total) * 100).toFixed(1)}%` : '0%';
        if (totalBatchesEl) totalBatchesEl.textContent = list.length;
    }
}

/**
 * Renderiza o cabeçalho e o corpo da tabela de auditoria.
 */
function renderAuditTable() {
    const thead = document.getElementById('auditTableHeader');
    const tbody = document.getElementById('auditTableBody');
    if (!thead || !tbody) return;

    if (auditState.mode === 'daily') {
        thead.innerHTML = `
            <tr>
                <th>Código Equipe</th>
                <th>Base Operacional</th>
                <th>Região</th>
                <th>Escala PowerON</th>
                <th>Conectou no TRBOnet Hoje?</th>
                <th>Coletas Online / Total</th>
                <th>% Uptime no Dia</th>
                <th>1º Sinal Registrado</th>
                <th>Último Sinal</th>
                <th style="text-align: center;">Auditoria Forense</th>
            </tr>
        `;

        if (auditState.filteredData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="10" class="empty-table-cell">
                        <div class="empty-state-box">
                            <i data-lucide="inbox"></i>
                            <p>Nenhum registro de auditoria encontrado para os filtros selecionados.</p>
                        </div>
                    </td>
                </tr>
            `;
            initIcons();
            return;
        }

        tbody.innerHTML = auditState.filteredData.map(item => {
            const wasOnline = item.was_online_trbonet;
            const wasPw = item.was_in_poweron;
            
            let statusBadge = '';
            if (wasPw && wasOnline) {
                statusBadge = '<span class="status-badge badge-online-gps"><i data-lucide="check-circle"></i> CONECTOU HOJE</span>';
            } else if (wasPw && !wasOnline) {
                statusBadge = '<span class="status-badge badge-offline-critical"><i data-lucide="alert-triangle"></i> NUNCA CONECTOU</span>';
            } else if (!wasPw && wasOnline) {
                statusBadge = '<span class="status-badge badge-trbo-only"><i data-lucide="radio"></i> APENAS TRBONET</span>';
            } else {
                statusBadge = '<span class="status-badge badge-offline-gray">OFFLINE</span>';
            }

            const pwBadge = wasPw 
                ? '<span class="text-emerald font-bold"><i data-lucide="check"></i> Em Escala</span>' 
                : '<span class="text-secondary">--</span>';

            const formatTime = (ts) => {
                if (!ts) return '--';
                try {
                    const d = new Date(ts);
                    return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                } catch {
                    return ts;
                }
            };

            const firstSeen = formatTime(item.first_seen_online);
            const lastSeen = formatTime(item.last_seen_online);

            return `
                <tr>
                    <td><strong class="team-code-cell">${item.team_code}</strong></td>
                    <td><span class="base-badge">${item.base_code || '--'}</span></td>
                    <td><span class="text-secondary">${item.region || 'Outras Bases'}</span></td>
                    <td>${pwBadge}</td>
                    <td>${statusBadge}</td>
                    <td><strong>${item.times_seen_online || 0}</strong> / ${item.total_sync_checks || 0} coletas</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div class="table-progress-bar">
                                <div class="table-progress-fill" style="width: ${Math.min(item.uptime_percentage || 0, 100)}%; background-color: ${getComplianceColor(item.uptime_percentage || 0)}"></div>
                            </div>
                            <span class="font-bold">${item.uptime_percentage || 0}%</span>
                        </div>
                    </td>
                    <td><span class="time-cell">${firstSeen}</span></td>
                    <td><span class="time-cell">${lastSeen}</span></td>
                    <td style="text-align: center;">
                        <button class="btn btn-sm btn-secondary" onclick="openTeamTimelineModal('${item.team_code}')" title="Ver linha do tempo de transmissões do dia">
                            <i data-lucide="activity"></i>
                            <span>Linha do Tempo</span>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

    } else {
        // Modo 'logs' (Coletas brutas)
        thead.innerHTML = `
            <tr>
                <th>Data / Hora Coleta</th>
                <th>Código Equipe</th>
                <th>Base</th>
                <th>Região</th>
                <th>Status na Coleta</th>
                <th>PowerON</th>
                <th>TRBOnet</th>
                <th>GPS</th>
                <th>ID Rádio / Canal</th>
                <th>Último Sinal</th>
                <th style="text-align: center;">Linha do Tempo</th>
            </tr>
        `;

        if (auditState.filteredData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="11" class="empty-table-cell">
                        <div class="empty-state-box">
                            <i data-lucide="inbox"></i>
                            <p>Nenhum log de coleta encontrado para a data e filtros selecionados.</p>
                        </div>
                    </td>
                </tr>
            `;
            initIcons();
            return;
        }

        tbody.innerHTML = auditState.filteredData.map(item => {
            const capturedTime = item.captured_at ? new Date(item.captured_at).toLocaleTimeString('pt-BR') : '--:--:--';
            
            let stBadge = '';
            if (item.status === 'CONFORME') {
                stBadge = '<span class="status-badge badge-online-gps">Conforme</span>';
            } else if (item.status === 'APENAS_POWERON') {
                stBadge = '<span class="status-badge badge-offline-critical">Apenas PowerON</span>';
            } else if (item.status === 'APENAS_TRBONET') {
                stBadge = '<span class="status-badge badge-trbo-only">Apenas TRBOnet</span>';
            } else {
                stBadge = '<span class="status-badge badge-offline-gray">Offline</span>';
            }

            return `
                <tr>
                    <td><span class="time-cell font-bold text-cyan">${capturedTime}</span></td>
                    <td><strong class="team-code-cell">${item.team_code}</strong></td>
                    <td><span class="base-badge">${item.base_code || '--'}</span></td>
                    <td><span class="text-secondary">${item.region || 'Outras Bases'}</span></td>
                    <td>${stBadge}</td>
                    <td>${item.in_poweron ? '<span class="text-emerald font-bold">Sim</span>' : '<span class="text-secondary">Não</span>'}</td>
                    <td>${item.in_trbonet ? '<span class="text-emerald font-bold">Sim</span>' : '<span class="text-danger font-bold">Não</span>'}</td>
                    <td>${item.has_gps ? '<span class="badge-gps-active"><i data-lucide="map-pin"></i> GPS</span>' : '<span class="text-secondary">Sem GPS</span>'}</td>
                    <td><span class="text-secondary">${item.radio_id || '--'} / ${item.channel || '--'}</span></td>
                    <td><span class="time-cell">${item.last_signal || '--'}</span></td>
                    <td style="text-align: center;">
                        <button class="btn btn-sm btn-secondary" onclick="openTeamTimelineModal('${item.team_code}')" title="Ver histórico completo da equipe">
                            <i data-lucide="activity"></i>
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    }

    initIcons();
}

/**
 * Abre o Modal da Linha do Tempo com todos os eventos registrados daquela equipe no dia.
 */
async function openTeamTimelineModal(teamCode) {
    const modal = document.getElementById('auditTimelineModal');
    const teamTitle = document.getElementById('timelineModalTeam');
    const subtitle = document.getElementById('timelineModalSubtitle');
    const stream = document.getElementById('timelineEventsContainer');

    const dateVal = document.getElementById('auditFilterDate')?.value || '';

    if (teamTitle) teamTitle.textContent = `LINHA DO TEMPO: EQUIPE ${teamCode}`;
    if (subtitle) subtitle.textContent = `Histórico de transmissões e coletas registradas no dia ${dateVal || 'hoje'}`;
    if (stream) stream.innerHTML = '<div style="text-align: center; padding: 30px;"><i data-lucide="loader" class="spin-animation" style="width: 32px; height: 32px; color: var(--brand-cyan);"></i><p style="margin-top: 10px; color: var(--text-secondary);">Consultando histórico no Supabase...</p></div>';
    
    if (modal) modal.classList.add('active');
    initIcons();

    try {
        const res = await fetch(`/api/audit/team_timeline?team=${encodeURIComponent(teamCode)}&date=${dateVal}`);
        const data = await res.json();

        if (data.status === 'success' && data.data && data.data.length > 0) {
            const events = data.data;
            stream.innerHTML = events.map(ev => {
                const timeStr = ev.captured_at ? new Date(ev.captured_at).toLocaleTimeString('pt-BR') : '--:--:--';
                const isOnline = ev.in_trbonet;
                const dotClass = isOnline ? 'dot-online' : 'dot-offline';
                const statusColor = isOnline ? 'text-emerald' : 'text-danger';
                const statusText = isOnline ? 'TRANSMITINDO (ONLINE)' : 'SEM SINAL (OFFLINE)';

                return `
                    <div class="timeline-event-item">
                        <span class="timeline-event-dot ${dotClass}"></span>
                        <div class="timeline-event-card">
                            <div class="timeline-time-info">
                                <span class="timeline-time">${timeStr} - <span class="${statusColor}">${statusText}</span></span>
                                <span class="timeline-meta">Base: ${ev.base_code || '--'} • Região: ${ev.region || '--'} • PowerON: ${ev.in_poweron ? 'Em Escala' : 'Não Escalada'}</span>
                            </div>
                            <div style="display: flex; gap: 8px; align-items: center;">
                                ${ev.has_gps ? '<span class="status-badge badge-online-gps"><i data-lucide="map-pin"></i> GPS Ativo</span>' : '<span class="status-badge badge-offline-gray">Sem GPS</span>'}
                                <span class="status-badge badge-secondary">Rádio ${ev.radio_id || '--'}</span>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            stream.innerHTML = `
                <div style="text-align: center; padding: 40px;">
                    <i data-lucide="info" style="width: 36px; height: 36px; color: var(--text-secondary); margin-bottom: 10px;"></i>
                    <p style="color: var(--text-secondary);">Nenhuma transmissão registrada para a equipe <strong>${teamCode}</strong> na data selecionada.</p>
                </div>
            `;
        }
    } catch (err) {
        stream.innerHTML = `<p class="text-danger" style="text-align: center; padding: 20px;">Falha ao carregar linha do tempo: ${err.message}</p>`;
    }
    initIcons();
}

/**
 * Debounce para busca rápida de equipe na aba de auditoria.
 */
function debounceAuditSearch() {
    clearTimeout(auditState.searchTimer);
    auditState.searchTimer = setTimeout(() => {
        applyAuditFilters();
    }, 250);
}

/**
 * Exporta a tabela filtrada atual para um arquivo CSV estruturado.
 */
function exportAuditTableExcel() {
    const list = auditState.filteredData;
    const dateVal = document.getElementById('auditFilterDate')?.value || 'hoje';
    const filename = `Auditoria_TRBOnet_PowerON_${dateVal}_${auditState.mode}.xlsx`;

    // 1. Tenta geração client-side instantânea via SheetJS
    if (window.XLSX && list && list.length > 0) {
        try {
            let rows = [];
            if (auditState.mode === 'daily') {
                rows = list.map(i => ({
                    "Data": i.date_ref || dateVal,
                    "Equipe": i.team_code || '',
                    "Base": i.base_code || '',
                    "Região": i.region || '',
                    "Escala PowerON": i.was_in_poweron ? 'SIM' : 'NÃO',
                    "Conectou TRBOnet": i.was_online_trbonet ? 'SIM' : 'NÃO',
                    "Coletas Online": i.times_seen_online || 0,
                    "Total Coletas": i.total_sync_checks || 0,
                    "Uptime (%)": `${i.uptime_percentage || 0}%`,
                    "Primeiro Sinal": i.first_seen_online || '--',
                    "Último Sinal": i.last_seen_online || '--'
                }));
            } else {
                rows = list.map(i => ({
                    "Data e Hora Coleta": i.captured_at || '',
                    "Data Ref": i.date_ref || '',
                    "Equipe": i.team_code || '',
                    "Base": i.base_code || '',
                    "Região": i.region || '',
                    "Status": i.status || '',
                    "PowerON": i.in_poweron ? 'SIM' : 'NÃO',
                    "TRBOnet": i.in_trbonet ? 'SIM' : 'NÃO',
                    "GPS": i.has_gps ? 'SIM' : 'NÃO',
                    "ID Rádio": i.radio_id || '',
                    "Canal": i.channel || '',
                    "Último Sinal": i.last_signal || ''
                }));
            }

            const ws = XLSX.utils.json_to_sheet(rows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Auditoria_CCO");
            XLSX.writeFile(wb, filename);

            showToast(`Relatório de auditoria (.xlsx) exportado com sucesso (${list.length} registros)!`, 'success');
            return;
        } catch (err) {
            console.warn('Falha na exportação client-side de auditoria, usando rota backend:', err);
        }
    }

    // 2. Fallback via backend endpoint
    const baseVal = document.getElementById('auditFilterBase')?.value || 'ALL';
    window.location.href = `/api/export/audit_excel?date=${encodeURIComponent(dateVal)}&base=${encodeURIComponent(baseVal)}&mode=${auditState.mode}`;
    showToast('Download da Planilha de Auditoria (.xlsx) iniciado!', 'success');
}

window.exportAuditTableExcel = exportAuditTableExcel;

function exportAuditTableCSV() {
    const list = auditState.filteredData;
    if (!list || list.length === 0) {
        showToast('Nenhum dado disponível para exportação.', 'info');
        return;
    }

    const dateVal = document.getElementById('auditFilterDate')?.value || 'hoje';
    let csvContent = '\uFEFF'; // UTF-8 BOM

    if (auditState.mode === 'daily') {
        csvContent += 'Data;Equipe;Base;Regiao;Escala_PowerON;Conectou_TRBOnet;Coletas_Online;Total_Coletas;Uptime_Percentual;Primeiro_Sinal;Ultimo_Sinal\n';
        list.forEach(i => {
            csvContent += `"${i.date_ref || dateVal}";"${i.team_code}";"${i.base_code || ''}";"${i.region || ''}";"${i.was_in_poweron ? 'SIM' : 'NAO'}";"${i.was_online_trbonet ? 'SIM' : 'NAO'}";"${i.times_seen_online || 0}";"${i.total_sync_checks || 0}";"${i.uptime_percentage || 0}%";"${i.first_seen_online || ''}";"${i.last_seen_online || ''}"\n`;
        });
    } else {
        csvContent += 'Data_Hora_Coleta;Data_Ref;Equipe;Base;Regiao;Status;PowerON;TRBOnet;GPS;Radio_ID;Canal;Ultimo_Sinal\n';
        list.forEach(i => {
            csvContent += `"${i.captured_at || ''}";"${i.date_ref || ''}";"${i.team_code}";"${i.base_code || ''}";"${i.region || ''}";"${i.status || ''}";"${i.in_poweron ? 'SIM' : 'NAO'}";"${i.in_trbonet ? 'SIM' : 'NAO'}";"${i.has_gps ? 'SIM' : 'NAO'}";"${i.radio_id || ''}";"${i.channel || ''}";"${i.last_signal || ''}"\n`;
        });
    }

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.setAttribute('href', url);
    link.setAttribute('download', `Auditoria_TRBOnet_PowerON_${dateVal}_${auditState.mode}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    showToast('Relatório de auditoria exportado com sucesso!', 'success');
}

window.exportAuditTableCSV = exportAuditTableCSV;

// ==========================================================================
// MÓDULO DE AUTENTICAÇÃO E CONTROLE DE ACESSO (E2EE)
// ==========================================================================

async function initAuth() {
    if (authState.token) {
        try {
            const resp = await fetch('/api/auth/session', {
                headers: { 'Authorization': `Bearer ${authState.token}` }
            });
            const data = await resp.json();
            if (data.status === 'success' && data.authenticated) {
                authState.isAuthenticated = true;
                authState.user = data.user;
                sessionStorage.setItem('cco_auth_user', JSON.stringify(data.user));
            } else {
                handleLogout(false);
            }
        } catch {
            authState.isAuthenticated = !!authState.token;
        }
    } else {
        authState.isAuthenticated = false;
    }
    updateAuthUI();
}

function updateAuthUI() {
    const isAuth = authState.isAuthenticated && !!authState.user;
    const isAdmin = isAuth && authState.user.role === 'admin';
    const userName = isAuth ? (authState.user.nome || 'AUTENTICADO') : 'Acesso Restrito';

    // 1. Alterna classe no body para exibir/ocultar badges de bloqueio
    document.body.classList.toggle('unlocked-ops', isAuth);

    // 2. Atualiza Botão do Hub Central
    const btnHub = document.getElementById('btnAuthHub');
    const labelHub = document.getElementById('authLockTextHub');
    const iconHub = document.getElementById('authLockIconHub');
    if (btnHub) {
        btnHub.classList.toggle('locked', !isAuth);
        btnHub.classList.toggle('unlocked', isAuth);
    }
    if (labelHub) {
        labelHub.textContent = isAuth ? `🔓 ${userName.split(' ')[0]}` : 'Acesso Restrito';
    }
    if (iconHub) {
        iconHub.setAttribute('data-lucide', isAuth ? 'lock-open' : 'lock');
    }

    // 3. Atualiza Botão do Módulo
    const btnMod = document.getElementById('btnAuthModule');
    const labelMod = document.getElementById('authLockTextModule');
    const iconMod = document.getElementById('authLockIconModule');
    if (btnMod) {
        btnMod.classList.toggle('locked', !isAuth);
        btnMod.classList.toggle('unlocked', isAuth);
    }
    if (labelMod) {
        labelMod.textContent = isAuth ? `🔓 ${userName.split(' ')[0]}` : 'Bloqueado';
    }
    if (iconMod) {
        iconMod.setAttribute('data-lucide', isAuth ? 'lock-open' : 'lock');
    }

    // 4. Modal de Autenticação - Mostra sessão ativa ou formulário de login
    const loginForm = document.getElementById('formAuthLogin');
    const activeBox = document.getElementById('authActiveSessionBox');
    const adminTabBtn = document.getElementById('tabBtnAdminUsers');
    const manageShortBtn = document.getElementById('btnManageUsersShort');

    if (isAuth) {
        if (loginForm) loginForm.style.display = 'none';
        if (activeBox) activeBox.style.display = 'flex';
        
        const nameEl = document.getElementById('activeUserName');
        const emailEl = document.getElementById('activeUserEmail');
        const matEl = document.getElementById('activeUserMatricula');
        const roleEl = document.getElementById('activeUserRole');

        if (nameEl) nameEl.textContent = authState.user.nome || 'COLABORADOR';
        if (emailEl) emailEl.textContent = authState.user.email || '--';
        if (matEl) matEl.textContent = authState.user.matricula || '--';
        if (roleEl) roleEl.textContent = (authState.user.role || 'OPERADOR').toUpperCase();

        if (adminTabBtn) adminTabBtn.style.display = isAdmin ? 'inline-flex' : 'none';
        if (manageShortBtn) manageShortBtn.style.display = isAdmin ? 'inline-flex' : 'none';
    } else {
        if (loginForm) loginForm.style.display = 'block';
        if (activeBox) activeBox.style.display = 'none';
        if (adminTabBtn) adminTabBtn.style.display = 'none';
        if (manageShortBtn) manageShortBtn.style.display = 'none';
    }

    initIcons();
}

function handleRestrictedAction(fn) {
    if (!authState.isAuthenticated) {
        showToast('Ação Restrita: Efetue o login no Cadeado para executar esta função.', 'warning');
        openAuthModal();
        return;
    }
    if (typeof fn === 'function') {
        fn();
    }
}

function openAuthModal() {
    const modal = document.getElementById('authModal');
    if (modal) {
        switchAuthTab('login');
        modal.classList.add('active');
        initIcons();
    }
}

function switchAuthTab(tab) {
    authState.activeTab = tab;
    
    document.querySelectorAll('.auth-tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.auth-tab-pane').forEach(pane => pane.classList.remove('active'));

    if (tab === 'login') {
        document.getElementById('tabBtnLogin')?.classList.add('active');
        document.getElementById('authPaneLogin')?.classList.add('active');
    } else if (tab === 'register') {
        document.getElementById('tabBtnRegister')?.classList.add('active');
        document.getElementById('authPaneRegister')?.classList.add('active');
    } else if (tab === 'admin_users') {
        document.getElementById('tabBtnAdminUsers')?.classList.add('active');
        document.getElementById('authPaneAdminUsers')?.classList.add('active');
        loadAdminUsersList();
    }
    initIcons();
}

async function handleLoginSubmit(event) {
    event.preventDefault();
    const loginInput = document.getElementById('loginIdentifier');
    const passwordInput = document.getElementById('loginPassword');
    const btn = document.getElementById('btnSubmitLogin');

    const loginVal = (loginInput?.value || '').trim();
    const passVal = passwordInput?.value || '';

    if (!loginVal || !passVal) {
        showToast('Preencha o identificador (matrícula/e-mail) e a senha.', 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> Autenticando...`;
    }
    initIcons();

    try {
        const resp = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login: loginVal, password: passVal })
        });
        const result = await resp.json();

        if (result.status === 'success') {
            authState.token = result.token;
            authState.user = result.user;
            authState.isAuthenticated = true;

            sessionStorage.setItem('cco_auth_token', result.token);
            sessionStorage.setItem('cco_auth_user', JSON.stringify(result.user));

            showToast(result.message || 'Desbloqueio efetuado com sucesso!', 'success');
            updateAuthUI();
            closeModal('authModal');
            if (passwordInput) passwordInput.value = '';
        } else {
            showToast(result.message || 'Credenciais inválidas.', 'danger');
        }
    } catch (err) {
        showToast(`Erro na autenticação: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="unlock"></i> Entrar e Desbloquear Painel`;
        }
        initIcons();
    }
}

async function handleRegisterSubmit(event) {
    event.preventDefault();
    const nome = (document.getElementById('regNome')?.value || '').trim().toUpperCase();
    const email = (document.getElementById('regEmail')?.value || '').trim().toLowerCase();
    const matricula = (document.getElementById('regMatricula')?.value || '').trim().toUpperCase();
    const password = document.getElementById('regPassword')?.value || '';
    const btn = document.getElementById('btnSubmitRegister');

    // Validações Client-side
    if (!nome || nome.length < 3) {
        showToast('Informe o nome completo do colaborador.', 'warning');
        return;
    }

    if (!email.endsWith('@alpitelbrasil.com.br')) {
        showToast('O e-mail deve pertencer ao domínio @alpitelbrasil.com.br', 'danger');
        return;
    }

    const matriculaRegex = /^BR0\d{9}$/;
    if (!matriculaRegex.test(matricula)) {
        showToast('Matrícula inválida! Padrão obrigatório: BR0 seguido de 9 dígitos numéricos (ex: BR0144636617).', 'danger');
        return;
    }

    if (!password || password.length < 4) {
        showToast('A senha deve conter no mínimo 4 caracteres.', 'warning');
        return;
    }

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> Enviando solicitação...`;
    }
    initIcons();

    try {
        const resp = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nome, email, matricula, password })
        });
        const result = await resp.json();

        if (result.status === 'success') {
            showToast(result.message, 'success');
            document.getElementById('formAuthRegister')?.reset();
            switchAuthTab('login');
        } else {
            showToast(result.message || 'Falha ao solicitar cadastro.', 'danger');
        }
    } catch (err) {
        showToast(`Erro no envio do cadastro: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="send"></i> Enviar Solicitação de Acesso`;
        }
        initIcons();
    }
}

function handleLogout(showNotification = true) {
    authState.token = null;
    authState.user = null;
    authState.isAuthenticated = false;

    sessionStorage.removeItem('cco_auth_token');
    sessionStorage.removeItem('cco_auth_user');

    updateAuthUI();
    closeModal('authModal');
    if (showNotification) {
        showToast('Painel bloqueado com sucesso (Logout efetuado).', 'info');
    }
}

async function loadAdminUsersList() {
    const tbody = document.getElementById('adminUsersTableBody');
    const iconReload = document.getElementById('iconReloadUsers');
    if (iconReload) iconReload.classList.add('spin-animation');

    try {
        const resp = await fetch('/api/auth/users', {
            headers: { 'Authorization': `Bearer ${authState.token || ''}` }
        });
        const data = await resp.json();

        if (data.status === 'success' && Array.isArray(data.users)) {
            authState.adminUsers = data.users;
            renderAdminUsersTable(data.users);
        } else {
            if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">${data.message || 'Erro ao carregar usuários.'}</td></tr>`;
        }
    } catch (err) {
        if (tbody) tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger">Falha na consulta: ${err.message}</td></tr>`;
    } finally {
        if (iconReload) setTimeout(() => iconReload.classList.remove('spin-animation'), 400);
        initIcons();
    }
}

function renderAdminUsersTable(users) {
    const tbody = document.getElementById('adminUsersTableBody');
    if (!tbody) return;

    if (users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" class="text-center text-secondary">Nenhum usuário cadastrado além do Administrador.</td></tr>`;
        return;
    }

    tbody.innerHTML = users.map(u => {
        let statusBadge = `<span class="status-badge-pending">PENDENTE</span>`;
        if (u.status === 'approved') statusBadge = `<span class="status-badge-approved">APROVADO</span>`;
        if (u.status === 'rejected') statusBadge = `<span class="status-badge-rejected">REJEITADO</span>`;

        const isMasterAdmin = u.id === '00000000-0000-0000-0000-000000000001' || u.matricula === 'BR0000000000';

        let actionButtons = '';
        if (!isMasterAdmin) {
            actionButtons = `
                <div style="display: flex; gap: 8px; justify-content: center; align-items: center;">
                    ${u.status !== 'approved' ? `<button class="btn-action-icon btn-approve" title="Aprovar Acesso" onclick="window.approveUser('${u.id}')"><i data-lucide="check"></i></button>` : ''}
                    ${u.status !== 'rejected' ? `<button class="btn-action-icon btn-reject" title="Rejeitar / Desativar" onclick="window.rejectUser('${u.id}')"><i data-lucide="x"></i></button>` : ''}
                    <button class="btn-action-icon btn-delete" title="Excluir Usuário" onclick="window.deleteUser('${u.id}', '${u.nome}')"><i data-lucide="trash-2"></i></button>
                </div>
            `;
        } else {
            actionButtons = `<span class="text-secondary" style="font-size: 0.78rem;">Conta Mestra</span>`;
        }

        return `
            <tr>
                <td><strong class="text-cyan">${u.nome}</strong></td>
                <td><span class="badge-tag badge-matricula">${u.matricula}</span></td>
                <td><span class="text-secondary">${u.email}</span></td>
                <td><span class="badge-tag badge-role">${(u.role || 'OPERADOR').toUpperCase()}</span></td>
                <td>${statusBadge}</td>
                <td style="text-align: center;">${actionButtons}</td>
            </tr>
        `;
    }).join('');

    initIcons();
}

window.approveUser = async function(userId) {
    try {
        const resp = await fetch('/api/auth/approve_user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: JSON.stringify({ user_id: userId, status: 'approved' })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'success');
            await loadAdminUsersList();
        } else {
            showToast(data.message, 'danger');
        }
    } catch (err) {
        showToast(`Erro ao aprovar usuário: ${err.message}`, 'danger');
    }
};

window.rejectUser = async function(userId) {
    try {
        const resp = await fetch('/api/auth/reject_user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message, 'info');
            await loadAdminUsersList();
        } else {
            showToast(data.message, 'danger');
        }
    } catch (err) {
        showToast(`Erro ao rejeitar usuário: ${err.message}`, 'danger');
    }
};

window.deleteUser = async function(userId, userName = '') {
    try {
        const resp = await fetch('/api/auth/delete_user', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await resp.json();
        if (data.status === 'success') {
            showToast(data.message || `Usuário ${userName || ''} excluído com sucesso!`, 'success');
            await loadAdminUsersList();
        } else {
            showToast(data.message || 'Erro ao excluir usuário.', 'danger');
        }
    } catch (err) {
        showToast(`Erro ao excluir usuário: ${err.message}`, 'danger');
    }
};

