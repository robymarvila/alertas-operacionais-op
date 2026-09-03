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
    
    // Auto-refresh Timer (2 Minutos = 120 segundos)
    refreshIntervalSeconds: 120,
    secondsRemaining: 120,
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
    loadDeliveryData(false);
    startAutoRefreshTimer();
    initSupabaseRealtime(); // WebSocket Realtime com Supabase (Padrão Fleet Operação)
    sendTelemetryHeartbeat();
    setInterval(sendTelemetryHeartbeat, 60000);

    // Roteamento dinâmico por Hash da URL
    const hash = window.location.hash.replace('#', '');
    if (hash === 'delivery') {
        navigateToView('delivery');
    } else if (hash === 'module' || hash === 'trbonet') {
        navigateToView('module');
    } else if (hash === 'admin') {
        navigateToView('admin');
    } else {
        navigateToView('hub');
    }

    window.addEventListener('hashchange', () => {
        const currentHash = window.location.hash.replace('#', '');
        if (currentHash === 'delivery') {
            navigateToView('delivery');
        } else if (currentHash === 'module' || currentHash === 'trbonet') {
            navigateToView('module');
        } else if (currentHash === 'admin') {
            navigateToView('admin');
        } else {
            navigateToView('hub');
        }
    });

    // Ao voltar para a aba do navegador, atualiza instantaneamente todos os módulos
    window.addEventListener('focus', () => {
        refreshAllRealtimeData(false);
    });

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) {
            refreshAllRealtimeData(false);
        }
    });
});

function initIcons() {
    if (window.lucide) {
        lucide.createIcons();
    }
}

function initClock() {
    function updateClock() {
        const now = new Date();
        const timeStr = now.toLocaleTimeString('pt-BR', { hour12: false });
        const dateStr = now.toLocaleDateString('pt-BR');

        const elDigital = document.getElementById('digitalClock');
        const elDate = document.getElementById('digitalDate');
        const elDeliveryClock = document.getElementById('digitalClockDelivery');
        const elModuleClock = document.getElementById('digitalClockModule');

        if (elDigital) elDigital.textContent = timeStr;
        if (elDate) elDate.textContent = dateStr;
        if (elDeliveryClock) elDeliveryClock.textContent = timeStr;
        if (elModuleClock) elModuleClock.textContent = timeStr;
    }
    updateClock();
    setInterval(updateClock, 1000);
}

function initDropzone() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('poweronFileInput');
    if (dropzone && fileInput) {
        dropzone.addEventListener('click', () => fileInput.click());
        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('dragover');
        });
        dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                handlePowerOnFileUpload(e.dataTransfer.files[0]);
            }
        });
        fileInput.addEventListener('change', (e) => {
            if (e.target.files.length) {
                handlePowerOnFileUpload(e.target.files[0]);
            }
        });
    }
}

function initAuth() {
    if (authState.token && authState.user) {
        authState.isAuthenticated = true;
    }
    updateAuthUI();
}

function updateAuthUI() {
    const isAuth = authState.isAuthenticated;
    const user = authState.user;

    const btns = [
        { btn: document.getElementById('btnAuthHub'), icon: document.getElementById('authLockIconHub'), text: document.getElementById('authLockTextHub') },
        { btn: document.getElementById('btnAuthModule'), icon: document.getElementById('authLockIconModule'), text: document.getElementById('authLockTextModule') },
        { btn: document.getElementById('btnAuthDelivery'), icon: document.getElementById('authLockIconDelivery'), text: document.getElementById('authLockTextDelivery') }
    ];

    btns.forEach(item => {
        if (item.btn) {
            if (isAuth) {
                item.btn.classList.remove('locked');
                item.btn.classList.add('unlocked');
                if (item.text) item.text.textContent = user ? user.nome.split(' ')[0] : 'Desbloqueado';
                if (item.icon) item.icon.setAttribute('data-lucide', 'unlock');
            } else {
                item.btn.classList.remove('unlocked');
                item.btn.classList.add('locked');
                if (item.text) item.text.textContent = 'Bloqueado';
                if (item.icon) item.icon.setAttribute('data-lucide', 'lock');
            }
        }
    });

    document.querySelectorAll('.locked-action').forEach(el => {
        const lockBadge = el.querySelector('.lock-mini-badge');
        if (isAuth) {
            el.classList.remove('action-locked');
            if (lockBadge) lockBadge.style.display = 'none';
        } else {
            el.classList.add('action-locked');
            if (lockBadge) lockBadge.style.display = 'inline-flex';
        }
    });

    initIcons();
}

function handleRestrictedAction(actionCallback) {
    if (!authState.isAuthenticated) {
        showToast('Ação restrita. Autentique-se com sua matrícula para continuar.', 'warning');
        openAuthModal();
        return;
    }
    if (typeof actionCallback === 'function') {
        actionCallback();
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

window.handleRestrictedAction = handleRestrictedAction;
window.openAuthModal = openAuthModal;

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
    if (appState.currentView === 'delivery') {
        setTimeout(renderDeliveryCharts, 50);
    }
    initIcons();
}

// ==========================================================================
// NAVEGAÇÃO ENTRE PORTAL HUB E MÓDULO OPERACIONAL
// ==========================================================================
function navigateToView(viewName) {
    if (viewName === 'admin') {
        if (!authState.isAuthenticated) {
            showToast('Acesso Restrito: Autentique-se com sua matrícula e senha para acessar o Painel de Gerenciamento.', 'warning');
            openAuthModal();
            return;
        }
    }

    appState.currentView = viewName;
    if (window.location.hash !== `#${viewName}`) {
        window.history.replaceState(null, '', `#${viewName}`);
    }

    // Atualiza classes no elemento raiz HTML para consistência absoluta de CSS
    document.documentElement.classList.remove('route-hub', 'route-module', 'route-delivery', 'route-admin');
    if (viewName === 'delivery') {
        document.documentElement.classList.add('route-delivery');
    } else if (viewName === 'module' || viewName === 'trbonet') {
        document.documentElement.classList.add('route-module');
    } else if (viewName === 'admin') {
        document.documentElement.classList.add('route-admin');
    } else {
        document.documentElement.classList.add('route-hub');
    }

    appState.currentView = viewName;
    const portalHub = document.getElementById('portalHubView');
    const moduleView = document.getElementById('moduleAuditView');
    const deliveryView = document.getElementById('moduleDeliveryView');
    const adminView = document.getElementById('systemAdminViewContainer');

    if (portalHub) portalHub.style.display = (viewName === 'hub') ? 'flex' : 'none';
    if (moduleView) moduleView.style.display = (viewName === 'module' || viewName === 'trbonet') ? 'flex' : 'none';
    if (deliveryView) deliveryView.style.display = (viewName === 'delivery') ? 'flex' : 'none';
    if (adminView) adminView.style.display = (viewName === 'admin') ? 'block' : 'none';

    if (viewName === 'hub') {
        updateHubCard();
        updateDeliveryHubCard();
    } else if (viewName === 'delivery') {
        applyDeliveryFilters();
        loadDeliveryData(false);
    } else if (viewName === 'admin') {
        switchAdminTab('engines');
        loadAdminEngineStatus();
    } else {
        switchMainTab(appState.currentMainTab || 'live');
    }

    window.scrollTo({ top: 0, behavior: 'smooth' });
    setTimeout(initIcons, 50);
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
        const clockDeliveryEl = document.getElementById('digitalClockDelivery');

        if (clockEl) clockEl.textContent = timeStr;
        if (dateEl) dateEl.textContent = dateStr;
        if (clockModuleEl) clockModuleEl.textContent = timeStr;
        if (clockDeliveryEl) clockDeliveryEl.textContent = timeStr;
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
            refreshAllRealtimeData(false);
        }
    }, 1000);
}

// Sincronização Unificada em Tempo Real de Todos os Módulos
async function refreshAllRealtimeData(isManual = false) {
    try {
        await Promise.allSettled([
            fetchDashboardData(isManual),
            loadDeliveryData(isManual)
        ]);
        if (appState.currentMainTab === 'audit') {
            loadAuditData(true);
        }
        updateHubCard();
        updateDeliveryHubCard();
    } catch (e) {
        console.warn('[REALTIME] Erro no ciclo de atualização:', e);
    }
}

// ==========================================================================
// SUPABASE REALTIME CLIENT (WEBSOCKETS PUSH - PADRÃO FLEET OPERAÇÃO)
// ==========================================================================
const SUPABASE_REALTIME_CONFIG = {
    url: "https://xgfawbqllikosyngfvwa.supabase.co",
    anonKey: "sb_publishable_uDfIgt5BLYkRJMU540FMcA_LbaubJox"
};

let supabaseClient = null;
let realtimeSyncChannel = null;

function setRealtimeBadgeStatus(status) {
    const badges = [
        { pill: document.getElementById('realtimeModuleBadge'), pulse: document.getElementById('realtimeModulePulse'), text: document.getElementById('realtimeModuleText') },
        { pill: document.getElementById('realtimeDeliveryBadge'), pulse: document.getElementById('realtimeDeliveryPulse'), text: document.getElementById('realtimeDeliveryText') }
    ];

    badges.forEach(b => {
        if (!b.pill) return;
        if (status === 'SUBSCRIBED') {
            b.pill.classList.remove('reconnecting');
            if (b.pulse) { b.pulse.className = 'status-pulse-dot'; }
            if (b.text) { b.text.textContent = 'REALTIME ATIVO'; }
        } else if (status === 'CONNECTING') {
            b.pill.classList.add('reconnecting');
            if (b.pulse) { b.pulse.className = 'status-pulse-dot yellow'; }
            if (b.text) { b.text.textContent = 'CONECTANDO...'; }
        } else {
            b.pill.classList.add('reconnecting');
            if (b.pulse) { b.pulse.className = 'status-pulse-dot yellow'; }
            if (b.text) { b.text.textContent = 'RECONECTANDO...'; }
        }
    });
}

function initSupabaseRealtime(retryCount = 0) {
    if (!window.supabase || typeof window.supabase.createClient !== 'function') {
        if (retryCount < 6) {
            setTimeout(() => initSupabaseRealtime(retryCount + 1), 400);
            return;
        }
        console.warn('[REALTIME] SDK Supabase JS não encontrado após tentativas.');
        return;
    }

    try {
        setRealtimeBadgeStatus('CONNECTING');
        supabaseClient = window.supabase.createClient(SUPABASE_REALTIME_CONFIG.url, SUPABASE_REALTIME_CONFIG.anonKey);

        realtimeSyncChannel = supabaseClient
            .channel('cco-realtime-engine-sync')
            .on(
                'postgres_changes',
                { event: 'INSERT', schema: 'public', table: 'operational_sync_sessions' },
                (payload) => {
                    console.log('[REALTIME WS] Nova coleta TRBOnet One gravada no Supabase!', payload);
                    fetchDashboardData(false);
                    updateHubCard();
                    showRealtimeIndicator('TRBOnet Atualizado ao Vivo');
                }
            )
            .on(
                'postgres_changes',
                { event: 'INSERT', schema: 'public', table: 'team_delivery_sessions' },
                (payload) => {
                    console.log('[REALTIME WS] Nova coleta Enel SP gravada no Supabase!', payload);
                    loadDeliveryData(false);
                    updateDeliveryHubCard();
                    showRealtimeIndicator('Entrega de Equipes Atualizada ao Vivo');
                }
            )
            .on(
                'postgres_changes',
                { event: '*', schema: 'public', table: 'system_engine_health' },
                (payload) => {
                    console.log('[REALTIME WS] Estado do motor operacional atualizado:', payload);
                    if (appState.currentView === 'admin') {
                        loadAdminEngineStatus();
                    }
                }
            )
            .subscribe((status, err) => {
                console.log(`[REALTIME WS] Conexão WebSocket: ${status}`, err || '');
                setRealtimeBadgeStatus(status);
            });

    } catch (err) {
        console.error('[REALTIME WS] Erro ao inicializar conexão WebSocket:', err);
        setRealtimeBadgeStatus('ERROR');
    }
}

function showRealtimeIndicator(message) {
    const toasts = document.getElementById('toastContainer');
    if (!toasts) return;
    const toast = document.createElement('div');
    toast.className = 'toast-notification toast-realtime';
    toast.style.cssText = 'background: rgba(16, 185, 129, 0.95); color: #ffffff; border: 1px solid #10b981; border-radius: 8px; padding: 8px 16px; font-weight: 700; font-size: 0.8rem; box-shadow: 0 10px 25px rgba(0,0,0,0.3); display: flex; align-items: center; gap: 8px; margin-bottom: 8px; animation: slideInRight 0.3s ease;';
    toast.innerHTML = `<span class="status-pulse-dot" style="background:#fff; box-shadow:0 0 6px #fff;"></span> ${message}`;
    toasts.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.4s ease';
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

window.initSupabaseRealtime = initSupabaseRealtime;

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
        const btnHubAdmin = document.getElementById('btnHubAdminPanel');
        const btnGoToAdmin = document.getElementById('btnGoToAdminPanel');
        if (btnHubAdmin) btnHubAdmin.style.display = 'inline-flex';
        if (btnGoToAdmin) btnGoToAdmin.style.display = 'inline-flex';
    } else {
        if (loginForm) loginForm.style.display = 'block';
        if (activeBox) activeBox.style.display = 'none';
        if (adminTabBtn) adminTabBtn.style.display = 'none';
        if (manageShortBtn) manageShortBtn.style.display = 'none';
        const btnHubAdmin = document.getElementById('btnHubAdminPanel');
        const btnGoToAdmin = document.getElementById('btnGoToAdminPanel');
        if (btnHubAdmin) btnHubAdmin.style.display = 'none';
        if (btnGoToAdmin) btnGoToAdmin.style.display = 'none';
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
    if (appState.currentView === 'admin') {
        navigateToView('hub');
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

// ==============================================================================
// MÓDULO 2: ENTREGA DE EQUIPES (ENEL SP) - CONTROLLER
// ==============================================================================

const DEFAULT_OFFICIAL_BASES = {
    'ENL': { code: 'ENL', name: 'Base Fagundes Filho', company: 'Alpitel', region: 'Região Norte Alpitel' },
    'ECL': { code: 'ECL', name: 'Base Cajati', company: 'Alpitel', region: 'Região Norte Alpitel' },
    'EEL': { code: 'EEL', name: 'Base Vila Medeiros', company: 'Alpitel', region: 'Região Norte Alpitel' },
    'EML': { code: 'EML', name: 'Base Monte Santo', company: 'Alpitel', region: 'Região Leste Alpitel' },
    'EQL': { code: 'EQL', name: 'Base Aricanduva', company: 'Alpitel', region: 'Região Leste Alpitel' },
    'EVL': { code: 'EVL', name: 'Base Catumbi', company: 'Alpitel', region: 'Região Leste Alpitel' },
    'ESL': { code: 'ESL', name: 'Base Santo André', company: 'Alpitel', region: 'Região Leste Alpitel' },
    'ENA': { code: 'ENA', name: 'Base Fagundes Filho', company: 'Própria', region: 'Região Norte Própria' },
    'ECA': { code: 'ECA', name: 'Base Cajati', company: 'Própria', region: 'Região Norte Própria' },
    'EEA': { code: 'EEA', name: 'Base Vila Medeiros', company: 'Própria', region: 'Região Norte Própria' },
    'EMA': { code: 'EMA', name: 'Base Monte Santo', company: 'Própria', region: 'Região Leste Própria' },
    'EQA': { code: 'EQA', name: 'Base Aricanduva', company: 'Própria', region: 'Região Leste Própria' },
    'EVA': { code: 'EVA', name: 'Base Catumbi', company: 'Própria', region: 'Região Leste Própria' },
    'ESA': { code: 'ESA', name: 'Base Santo André', company: 'Própria', region: 'Região Leste Própria' }
};

const deliveryState = {
    currentScreen: 'online', // 'online' | 'history'
    activeTeams: [],
    dailyTotalTeams: [],
    summaryActive: {},
    summaryTotal: {},
    intradayCurve: {},
    geoGroups: {},
    lastSync: '--:--:--',
    filters: {
        regions: new Set(),
        bases: new Set(),
        shifts: new Set(),
        vehicles: new Set(),
        search: ''
    },
    regionalViewMode: 'active', // 'active' (Equipes Ativas) | 'total' (Total do Dia)
    filteredTeams: [],
    isTableCollapsed: true,
    shiftChart: null,
    fleetPieChart: null,
    searchTimer: null,
    historyMode: 'day',
    historyDate: new Date().toISOString().split('T')[0],
    historyMonth: new Date().toISOString().slice(0, 7),
    historyDayData: null,
    historyMonthData: null,
    historyMonthlyChart: null,
    datePickerInstance: null,
    selectedAuditDates: [new Date().toISOString().split('T')[0]],
    comparisonData: [],
    comparisonChart: null
};

// Alternador de Telas (ONLINE vs AUDITORIA & HISTÓRICO)
function switchDeliveryScreen(screenName) {
    deliveryState.currentScreen = screenName;
    const btnOnline = document.getElementById('btnSwitchOnline');
    const btnHist = document.getElementById('btnSwitchHistory');
    const scrOnline = document.getElementById('deliveryScreenOnline');
    const scrHist = document.getElementById('deliveryScreenHistory');

    if (screenName === 'online') {
        if (btnOnline) btnOnline.classList.add('active');
        if (btnHist) btnHist.classList.remove('active');
        if (scrOnline) scrOnline.style.display = 'block';
        if (scrHist) scrHist.style.display = 'none';
        renderDeliveryCharts();
    } else {
        if (btnOnline) btnOnline.classList.remove('active');
        if (btnHist) btnHist.classList.add('active');
        if (scrOnline) scrOnline.style.display = 'none';
        if (scrHist) scrHist.style.display = 'block';

        // Inicializa seletores de data/mês
        initHistoryDatePicker();
        const monthInput = document.getElementById('histMonthInput');
        if (monthInput && !monthInput.value) monthInput.value = deliveryState.historyMonth;

        if (deliveryState.historyMode === 'day') {
            if (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates.length > 1) {
                loadComparisonAudit(deliveryState.selectedAuditDates);
            } else {
                const target = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates[0]) || deliveryState.historyDate;
                loadDailyHistoryAudit(target);
            }
        } else {
            loadMonthlyHistoryAudit();
        }
    }
}

// Carregamento de Dados ao Vivo (Módulo 2)
async function loadDeliveryData(forceRefresh = false) {
    const refreshBtn = document.getElementById('btnRefreshDelivery');
    if (refreshBtn) refreshBtn.classList.add('loading-pulse');

    try {
        const resp = await fetch('/api/delivery/data');
        const result = await resp.json();

        if (result.status === 'success') {
            deliveryState.activeTeams = result.active_teams || [];
            deliveryState.dailyTotalTeams = result.daily_total_teams || [];
            deliveryState.summaryActive = result.summary_active || {};
            deliveryState.summaryTotal = result.summary_total || {};
            deliveryState.intradayCurve = result.intraday_curve || {};
            deliveryState.geoGroups = result.geo_groups || {};
            deliveryState.lastSync = result.timestamp || '--:--:--';

            applyDeliveryFilters();
            updateDeliveryHubCard();

            if (forceRefresh) {
                showToast(`Entrega atualizada: ${deliveryState.activeTeams.length} ativas no momento (${deliveryState.dailyTotalTeams.length} acumuladas no dia)!`, 'success');
            }
        }
    } catch (err) {
        console.error('Falha ao sincronizar entrega de equipes:', err);
    } finally {
        if (refreshBtn) refreshBtn.classList.remove('loading-pulse');
        initIcons();
    }
}

// Atualização do Card do Hub Central
function updateDeliveryHubCard() {
    const activeTotal = deliveryState.activeTeams.length;
    const dayTotal = deliveryState.dailyTotalTeams.length;
    const sumActive = deliveryState.summaryActive || {};

    const elActive = document.getElementById('hubDeliveryActiveCount');
    const elTotal = document.getElementById('hubMiniDeliveredTotal');
    const elCesto = document.getElementById('hubMiniCesto');
    const elLeve = document.getElementById('hubMiniLeve');
    const elPesado = document.getElementById('hubMiniPesado');
    const elLastSync = document.getElementById('hubDeliveryLastSync');

    if (elActive) elActive.textContent = `${activeTotal} em turno`;
    if (elTotal) elTotal.textContent = dayTotal;
    if (elCesto) elCesto.textContent = sumActive.cesto || 0;
    if (elLeve) elLeve.textContent = sumActive.leve || 0;
    if (elPesado) elPesado.textContent = sumActive.linhaviva_munck || 0;
    if (elLastSync) elLastSync.textContent = deliveryState.lastSync || '--:--:--';
}

// Alternador do Modo de Visualização dos Cards Regionais (Ativas vs Total do Dia)
function setRegionalViewMode(mode) {
    deliveryState.regionalViewMode = mode; // 'active' | 'total'

    // Atualiza todos os botões seletores da tela
    document.querySelectorAll('.region-mode-btn').forEach(btn => {
        if (btn.getAttribute('data-mode') === mode) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    const hintEl = document.getElementById('regionalModeStatusHint');
    if (hintEl) {
        hintEl.textContent = mode === 'active'
            ? 'Mostrando apenas equipes em turno ativo'
            : 'Mostrando total acumulado do dia (ativas + encerradas)';
    }

    applyDeliveryFilters();
}
window.setRegionalViewMode = setRegionalViewMode;

// Aplicação de Filtros Múltiplos (Regiões, Bases, Turnos, Frotas e Busca)
function applyDeliveryFilters() {
    const { regions, bases, shifts, vehicles, search } = deliveryState.filters;
    const q = (search || '').trim().toUpperCase();
    const isModeActive = deliveryState.regionalViewMode !== 'total';

    // Se o modo for 'active', o universo base são as equipes ativas agora
    // Se o modo for 'total', o universo base são todas as equipes acumuladas no dia
    const sourceList = isModeActive
        ? (deliveryState.activeTeams.length > 0 ? deliveryState.activeTeams : deliveryState.dailyTotalTeams.filter(t => t.is_active !== false))
        : (deliveryState.dailyTotalTeams.length > 0 ? deliveryState.dailyTotalTeams : deliveryState.activeTeams);

    // 1. Escopo de Turno, Frota e Busca (usado para alimentar os cards da Região Norte, Região Leste e Bases)
    const scopeFiltered = sourceList.filter(t => {
        if (isModeActive && t.is_active === false) return false;

        // Filtro por Turnos Múltiplos
        if (shifts.size > 0 && !shifts.has(t.shift_code)) return false;

        // Filtro por Frota / Veículos Múltiplos
        if (vehicles.size > 0) {
            let matchVehicle = false;
            for (const v of vehicles) {
                if (v === 'Linha Viva + Munk') {
                    if (t.vehicle_type === 'Linha Viva' || t.vehicle_type === 'Munck' || t.unified_group === 'Linha Viva + Munk') {
                        matchVehicle = true;
                        break;
                    }
                } else if (t.vehicle_type === v || t.unified_group === v) {
                    matchVehicle = true;
                    break;
                }
            }
            if (!matchVehicle) return false;
        }

        // Filtro por Busca Textual
        if (q) {
            const matchCode = (t.team_code || '').toUpperCase().includes(q);
            const matchBase = (t.base_name || '').toUpperCase().includes(q);
            const matchDriver = (t.driver || '').toUpperCase().includes(q);
            const matchPlate = (t.plate || '').toUpperCase().includes(q);
            const matchType = (t.vehicle_type || '').toUpperCase().includes(q);
            if (!matchCode && !matchBase && !matchDriver && !matchPlate && !matchType) return false;
        }

        return true;
    });

    // 2. Filtro Completo incluindo Regiões e Bases Múltiplas (para tabela e gráficos)
    deliveryState.filteredTeams = scopeFiltered.filter(t => {
        // Filtro por Região Múltipla
        if (regions.size > 0) {
            let matchRegion = false;
            for (const r of regions) {
                if (t.geo === r || (t.region && t.region.toLowerCase().includes(r.toLowerCase()))) {
                    matchRegion = true;
                    break;
                }
            }
            if (!matchRegion) return false;
        }

        // Filtro por Base Múltipla com correspondência resiliente
        if (bases.size > 0) {
            let matchBase = false;
            const bDisp = (t.base_display || '').toLowerCase();
            const bName = (t.base_name || '').toLowerCase();
            const bCode = (t.base_code || t.prefix || '').toLowerCase();
            for (const b of bases) {
                const bLower = b.toLowerCase();
                if (bDisp === bLower || bName === bLower || bCode === bLower ||
                    (bLower.includes('fagundes') && (bDisp.includes('fagundes') || bCode === 'enl' || bCode === 'ena')) ||
                    (bLower.includes('cajati') && (bDisp.includes('cajati') || bCode === 'ecl' || bCode === 'eca')) ||
                    (bLower.includes('medeiros') && (bDisp.includes('medeiros') || bCode === 'eel' || bCode === 'eea')) ||
                    (bLower.includes('monte') && (bDisp.includes('monte') || bCode === 'eml' || bCode === 'ema')) ||
                    (bLower.includes('aricanduva') && (bDisp.includes('aricanduva') || bCode === 'eql' || bCode === 'eqa')) ||
                    (bLower.includes('catumbi') && (bDisp.includes('catumbi') || bCode === 'evl' || bCode === 'eva')) ||
                    (bLower.includes('andr') && (bDisp.includes('andr') || bCode === 'esl' || bCode === 'esa'))
                ) {
                    matchBase = true;
                    break;
                }
            }
            if (!matchBase) return false;
        }

        return true;
    });

    renderDeliveryKPIs();
    renderGroupedBasesMetrics(scopeFiltered);
    renderDeliveryCharts();
    renderDeliveryTable();
}

// Renderização dos KPIs do Deck Superior
function renderDeliveryKPIs() {
    const activeList = deliveryState.activeTeams;
    const totalDayList = deliveryState.dailyTotalTeams;

    const elHeroActive = document.getElementById('delHeroActive');
    const elHeroTotalDay = document.getElementById('delHeroTotalDay');

    if (elHeroActive) elHeroActive.textContent = activeList.length;
    if (elHeroTotalDay) elHeroTotalDay.textContent = totalDayList.length;

    // Métricas por tipo de veículo (Ativas vs Total Dia)
    const sumActive = deliveryState.summaryActive || {};
    const sumTotal = deliveryState.summaryTotal || {};

    const elCestoAct = document.getElementById('delFleetCestoActive');
    const elCestoTot = document.getElementById('delFleetCestoTotal');
    if (elCestoAct) elCestoAct.textContent = sumActive.cesto || 0;
    if (elCestoTot) elCestoTot.textContent = sumTotal.cesto || 0;

    const elLeveAct = document.getElementById('delFleetLeveActive');
    const elLeveTot = document.getElementById('delFleetLeveTotal');
    if (elLeveAct) elLeveAct.textContent = sumActive.leve || 0;
    if (elLeveTot) elLeveTot.textContent = sumTotal.leve || 0;

    const elMotoAct = document.getElementById('delFleetMotoActive');
    const elMotoTot = document.getElementById('delFleetMotoTotal');
    if (elMotoAct) elMotoAct.textContent = sumActive.moto || 0;
    if (elMotoTot) elMotoTot.textContent = sumTotal.moto || 0;

    const elPesadoAct = document.getElementById('delFleetPesadoActive');
    const elPesadoTot = document.getElementById('delFleetPesadoTotal');
    if (elPesadoAct) elPesadoAct.textContent = sumActive.linhaviva_munck || 0;
    if (elPesadoTot) elPesadoTot.textContent = sumTotal.linhaviva_munck || 0;
}

// Cálculo Dinâmico e Reativo dos Cards de Regiões e Bases
function computeRegionalBreakdown(teamList) {
    const list = teamList || [];
    const breakdown = {
        regiao_norte: {
            total_block: { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
            bases: {
                'Base Fagundes Filho': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
                'Base Cajati': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
                'Base Vila Medeiros': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 }
            }
        },
        regiao_leste: {
            total_block: { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
            bases: {
                'Base Monte Santo': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
                'Base Aricanduva': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
                'Base Catumbi': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 },
                'Base Santo André': { total: 0, cesto: 0, leve: 0, moto: 0, linhaviva_munck: 0 }
            }
        }
    };

    const normalizeBase = (name, code) => {
        const n = String(name || '').trim().toLowerCase();
        const c = String(code || '').trim().toUpperCase();
        if (n.includes('fagundes') || c === 'ENL' || c === 'ENA') return 'Base Fagundes Filho';
        if (n.includes('cajati') || c === 'ECL' || c === 'ECA') return 'Base Cajati';
        if (n.includes('medeiros') || c === 'EEL' || c === 'EEA') return 'Base Vila Medeiros';
        if (n.includes('monte') || c === 'EML' || c === 'EMA') return 'Base Monte Santo';
        if (n.includes('aricanduva') || c === 'EQL' || c === 'EQA') return 'Base Aricanduva';
        if (n.includes('catumbi') || c === 'EVL' || c === 'EVA') return 'Base Catumbi';
        if (n.includes('andr') || c === 'ESL' || c === 'ESA') return 'Base Santo André';
        return name;
    };

    list.forEach(t => {
        const isPesado = t.vehicle_type === 'Linha Viva' || t.vehicle_type === 'Munck' || t.unified_group === 'Linha Viva + Munk';
        const isCesto = t.vehicle_type === 'Cesto Aéreo';
        const isLeve = t.vehicle_type === 'Veículo Leve';
        const isMoto = t.vehicle_type === 'Moto';

        const baseKey = normalizeBase(t.base_display || t.base_name, t.base_code || t.prefix);
        let targetReg = null;

        if (t.geo === 'Norte' || ['Base Fagundes Filho', 'Base Cajati', 'Base Vila Medeiros'].includes(baseKey)) {
            targetReg = breakdown.regiao_norte;
        } else if (t.geo === 'Leste' || ['Base Monte Santo', 'Base Aricanduva', 'Base Catumbi', 'Base Santo André'].includes(baseKey)) {
            targetReg = breakdown.regiao_leste;
        }

        if (targetReg) {
            targetReg.total_block.total++;
            if (isCesto) targetReg.total_block.cesto++;
            if (isLeve) targetReg.total_block.leve++;
            if (isMoto) targetReg.total_block.moto++;
            if (isPesado) targetReg.total_block.linhaviva_munck++;

            if (targetReg.bases[baseKey]) {
                targetReg.bases[baseKey].total++;
                if (isCesto) targetReg.bases[baseKey].cesto++;
                if (isLeve) targetReg.bases[baseKey].leve++;
                if (isMoto) targetReg.bases[baseKey].moto++;
                if (isPesado) targetReg.bases[baseKey].linhaviva_munck++;
            }
        }
    });

    return breakdown;
}

// Renderização das Métricas dos Cards Agrupados (Região Norte & Região Leste)
function renderGroupedBasesMetrics(customTeamList) {
    let breakdown;
    if (customTeamList && Array.isArray(customTeamList)) {
        breakdown = computeRegionalBreakdown(customTeamList);
    } else {
        const sumTotal = deliveryState.summaryTotal || {};
        breakdown = {
            regiao_norte: sumTotal.regiao_norte || { total_block: {}, bases: {} },
            regiao_leste: sumTotal.regiao_leste || { total_block: {}, bases: {} }
        };
    }

    const regNorte = breakdown.regiao_norte;
    const regLeste = breakdown.regiao_leste;

    // Atualiza rótulos com o modo visualizado (ATIVAS vs TOTAL DIA)
    const isModeActive = deliveryState.regionalViewMode !== 'total';
    const modeSuffix = isModeActive ? '(ATIVAS)' : '(TOTAL DIA)';
    const elNorteLabel = document.querySelector('#filterCardTotalNorte .region-total-label');
    const elLesteLabel = document.querySelector('#filterCardTotalLeste .region-total-label');
    if (elNorteLabel) elNorteLabel.textContent = `TOTAL REGIÃO NORTE ${modeSuffix}`;
    if (elLesteLabel) elLesteLabel.textContent = `TOTAL REGIÃO LESTE ${modeSuffix}`;

    // Totalizador Norte
    const nb = regNorte.total_block || {};
    const elNorteNum = document.getElementById('delNorteTotalNum');
    const elNorteCesto = document.getElementById('delNorteTotalCesto');
    const elNorteLeve = document.getElementById('delNorteTotalLeve');
    const elNorteMoto = document.getElementById('delNorteTotalMoto');
    const elNortePesado = document.getElementById('delNorteTotalPesado');

    if (elNorteNum) elNorteNum.textContent = nb.total || 0;
    if (elNorteCesto) elNorteCesto.textContent = nb.cesto || 0;
    if (elNorteLeve) elNorteLeve.textContent = nb.leve || 0;
    if (elNorteMoto) elNorteMoto.textContent = nb.moto || 0;
    if (elNortePesado) elNortePesado.textContent = nb.linhaviva_munck || 0;

    // Bases do Norte
    const nbBases = regNorte.bases || {};
    const bFag = nbBases['Base Fagundes Filho'] || {};
    const elBFagTot = document.getElementById('delBaseFagundesTotal');
    const elBFagCesto = document.getElementById('delBaseFagundesCesto');
    const elBFagLeve = document.getElementById('delBaseFagundesLeve');
    const elBFagMoto = document.getElementById('delBaseFagundesMoto');
    const elBFagPesado = document.getElementById('delBaseFagundesPesado');
    if (elBFagTot) elBFagTot.textContent = bFag.total || 0;
    if (elBFagCesto) elBFagCesto.textContent = bFag.cesto || 0;
    if (elBFagLeve) elBFagLeve.textContent = bFag.leve || 0;
    if (elBFagMoto) elBFagMoto.textContent = bFag.moto || 0;
    if (elBFagPesado) elBFagPesado.textContent = bFag.linhaviva_munck || 0;

    const bCaj = nbBases['Base Cajati'] || {};
    const elBCajTot = document.getElementById('delBaseCajatiTotal');
    const elBCajCesto = document.getElementById('delBaseCajatiCesto');
    const elBCajLeve = document.getElementById('delBaseCajatiLeve');
    const elBCajMoto = document.getElementById('delBaseCajatiMoto');
    const elBCajPesado = document.getElementById('delBaseCajatiPesado');
    if (elBCajTot) elBCajTot.textContent = bCaj.total || 0;
    if (elBCajCesto) elBCajCesto.textContent = bCaj.cesto || 0;
    if (elBCajLeve) elBCajLeve.textContent = bCaj.leve || 0;
    if (elBCajMoto) elBCajMoto.textContent = bCaj.moto || 0;
    if (elBCajPesado) elBCajPesado.textContent = bCaj.linhaviva_munck || 0;

    const bMed = nbBases['Base Vila Medeiros'] || {};
    const elBMedTot = document.getElementById('delBaseVilaMedeirosTotal');
    const elBMedCesto = document.getElementById('delBaseVilaMedeirosCesto');
    const elBMedLeve = document.getElementById('delBaseVilaMedeirosLeve');
    const elBMedMoto = document.getElementById('delBaseVilaMedeirosMoto');
    const elBMedPesado = document.getElementById('delBaseVilaMedeirosPesado');
    if (elBMedTot) elBMedTot.textContent = bMed.total || 0;
    if (elBMedCesto) elBMedCesto.textContent = bMed.cesto || 0;
    if (elBMedLeve) elBMedLeve.textContent = bMed.leve || 0;
    if (elBMedMoto) elBMedMoto.textContent = bMed.moto || 0;
    if (elBMedPesado) elBMedPesado.textContent = bMed.linhaviva_munck || 0;

    // Totalizador Leste
    const lb = regLeste.total_block || {};
    const elLesteNum = document.getElementById('delLesteTotalNum');
    const elLesteCesto = document.getElementById('delLesteTotalCesto');
    const elLesteLeve = document.getElementById('delLesteTotalLeve');
    const elLesteMoto = document.getElementById('delLesteTotalMoto');
    const elLestePesado = document.getElementById('delLesteTotalPesado');

    if (elLesteNum) elLesteNum.textContent = lb.total || 0;
    if (elLesteCesto) elLesteCesto.textContent = lb.cesto || 0;
    if (elLesteLeve) elLesteLeve.textContent = lb.leve || 0;
    if (elLesteMoto) elLesteMoto.textContent = lb.moto || 0;
    if (elLestePesado) elLestePesado.textContent = lb.linhaviva_munck || 0;

    // Bases do Leste
    const lbBases = regLeste.bases || {};
    const bMS = lbBases['Base Monte Santo'] || {};
    const elBMSTot = document.getElementById('delBaseMonteSantoTotal');
    const elBMSCesto = document.getElementById('delBaseMonteSantoCesto');
    const elBMSLeve = document.getElementById('delBaseMonteSantoLeve');
    const elBMSMoto = document.getElementById('delBaseMonteSantoMoto');
    const elBMSPesado = document.getElementById('delBaseMonteSantoPesado');
    if (elBMSTot) elBMSTot.textContent = bMS.total || 0;
    if (elBMSCesto) elBMSCesto.textContent = bMS.cesto || 0;
    if (elBMSLeve) elBMSLeve.textContent = bMS.leve || 0;
    if (elBMSMoto) elBMSMoto.textContent = bMS.moto || 0;
    if (elBMSPesado) elBMSPesado.textContent = bMS.linhaviva_munck || 0;

    const bAri = lbBases['Base Aricanduva'] || {};
    const elBAriTot = document.getElementById('delBaseAricanduvaTotal');
    const elBAriCesto = document.getElementById('delBaseAricanduvaCesto');
    const elBAriLeve = document.getElementById('delBaseAricanduvaLeve');
    const elBAriMoto = document.getElementById('delBaseAricanduvaMoto');
    const elBAriPesado = document.getElementById('delBaseAricanduvaPesado');
    if (elBAriTot) elBAriTot.textContent = bAri.total || 0;
    if (elBAriCesto) elBAriCesto.textContent = bAri.cesto || 0;
    if (elBAriLeve) elBAriLeve.textContent = bAri.leve || 0;
    if (elBAriMoto) elBAriMoto.textContent = bAri.moto || 0;
    if (elBAriPesado) elBAriPesado.textContent = bAri.linhaviva_munck || 0;

    const bCat = lbBases['Base Catumbi'] || {};
    const elBCatTot = document.getElementById('delBaseCatumbiTotal');
    const elBCatCesto = document.getElementById('delBaseCatumbiCesto');
    const elBCatLeve = document.getElementById('delBaseCatumbiLeve');
    const elBCatMoto = document.getElementById('delBaseCatumbiMoto');
    const elBCatPesado = document.getElementById('delBaseCatumbiPesado');
    if (elBCatTot) elBCatTot.textContent = bCat.total || 0;
    if (elBCatCesto) elBCatCesto.textContent = bCat.cesto || 0;
    if (elBCatLeve) elBCatLeve.textContent = bCat.leve || 0;
    if (elBCatMoto) elBCatMoto.textContent = bCat.moto || 0;
    if (elBCatPesado) elBCatPesado.textContent = bCat.linhaviva_munck || 0;

    const bSA = lbBases['Base Santo André'] || {};
    const elBSATot = document.getElementById('delBaseSantoAndreTotal');
    const elBSACesto = document.getElementById('delBaseSantoAndreCesto');
    const elBSALeve = document.getElementById('delBaseSantoAndreLeve');
    const elBSAMoto = document.getElementById('delBaseSantoAndreMoto');
    const elBSAPesado = document.getElementById('delBaseSantoAndrePesado');
    if (elBSATot) elBSATot.textContent = bSA.total || 0;
    if (elBSACesto) elBSACesto.textContent = bSA.cesto || 0;
    if (elBSALeve) elBSALeve.textContent = bSA.leve || 0;
    if (elBSAMoto) elBSAMoto.textContent = bSA.moto || 0;
    if (elBSAPesado) elBSAPesado.textContent = bSA.linhaviva_munck || 0;
}

// Filtros Interativos Múltiplos por Região
function toggleRegionFilter(regionName) {
    const cardId = regionName === 'Norte' ? 'filterCardTotalNorte' : 'filterCardTotalLeste';
    const cardEl = document.getElementById(cardId);

    if (deliveryState.filters.regions.has(regionName)) {
        deliveryState.filters.regions.delete(regionName);
        if (cardEl) cardEl.classList.remove('filter-active');
    } else {
        deliveryState.filters.regions.add(regionName);
        if (cardEl) cardEl.classList.add('filter-active');
        // Expande a tabela automaticamente para que o operador veja a relação filtrada
        if (deliveryState.isTableCollapsed) {
            toggleDeliveryTableCollapse();
        }
    }

    applyDeliveryFilters();
}

// Filtros Interativos Múltiplos por Base
function toggleBaseFilter(baseName, el) {
    if (deliveryState.filters.bases.has(baseName)) {
        deliveryState.filters.bases.delete(baseName);
        if (el) el.classList.remove('filter-active');
    } else {
        deliveryState.filters.bases.add(baseName);
        if (el) el.classList.add('filter-active');
        // Expande a tabela automaticamente para que o operador veja a relação filtrada
        if (deliveryState.isTableCollapsed) {
            toggleDeliveryTableCollapse();
        }
    }

    applyDeliveryFilters();
}

// Limpeza de Todos os Filtros de Bases e Regiões
function clearDeliveryBaseFilters() {
    deliveryState.filters.regions.clear();
    deliveryState.filters.bases.clear();

    const nCard = document.getElementById('filterCardTotalNorte');
    const lCard = document.getElementById('filterCardTotalLeste');
    if (nCard) nCard.classList.remove('filter-active');
    if (lCard) lCard.classList.remove('filter-active');

    document.querySelectorAll('.base-interactive-card').forEach(c => c.classList.remove('filter-active'));

    applyDeliveryFilters();
    showToast('Filtros de bases e regiões reiniciados!', 'info');
}

// Filtros por Turno com Multi-Seleção Interativa
function setDeliveryShiftFilter(shift, el) {
    const container = document.getElementById('deliveryShiftPills');
    const allBtn = container ? container.querySelector('[data-shift="ALL"]') : null;

    if (shift === 'ALL') {
        deliveryState.filters.shifts.clear();
        if (container) {
            container.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
        }
        if (allBtn) allBtn.classList.add('active');
    } else {
        if (allBtn) allBtn.classList.remove('active');
        if (deliveryState.filters.shifts.has(shift)) {
            deliveryState.filters.shifts.delete(shift);
            if (el) el.classList.remove('active');
        } else {
            deliveryState.filters.shifts.add(shift);
            if (el) el.classList.add('active');
        }

        // Se nenhum turno estiver selecionado, volta para TODOS
        if (deliveryState.filters.shifts.size === 0) {
            if (allBtn) allBtn.classList.add('active');
        }
    }

    applyDeliveryFilters();
}

// Filtros por Frota com Multi-Seleção Interativa
function setDeliveryVehicleFilter(vehicle, el) {
    const container = document.getElementById('deliveryVehiclePills');
    const allBtn = container ? container.querySelector('[data-vehicle="ALL"]') : null;

    if (vehicle === 'ALL') {
        deliveryState.filters.vehicles.clear();
        if (container) {
            container.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
        }
        if (allBtn) allBtn.classList.add('active');
    } else {
        if (allBtn) allBtn.classList.remove('active');
        if (deliveryState.filters.vehicles.has(vehicle)) {
            deliveryState.filters.vehicles.delete(vehicle);
            if (el) el.classList.remove('active');
        } else {
            deliveryState.filters.vehicles.add(vehicle);
            if (el) el.classList.add('active');
        }

        // Se nenhum veículo estiver selecionado, volta para TODAS
        if (deliveryState.filters.vehicles.size === 0) {
            if (allBtn) allBtn.classList.add('active');
        }
    }

    applyDeliveryFilters();
}

// Busca rápida com debounce
function debounceDeliverySearch() {
    clearTimeout(deliveryState.searchTimer);
    deliveryState.searchTimer = setTimeout(() => {
        const input = document.getElementById('deliverySearchInput');
        deliveryState.filters.search = input ? input.value : '';
        applyDeliveryFilters();
    }, 200);
}

// Renderização dos Gráficos com Cores e Contraste Otimizados
function renderDeliveryCharts() {
    try {
        if (!window.Chart) return;
        const isLight = document.body.classList.contains('theme-light');
        const textColor = isLight ? '#0f172a' : '#f8fafc';
        const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.06)';
        const labelColor = isLight ? '#0f172a' : '#ffffff';

        // 1. Gráfico de Curva de Entrada ao Longo do Dia (Barras Empilhadas com Rótulos de Quantidade)
        const shiftCanvas = document.getElementById('deliveryShiftChart');
        if (shiftCanvas) {
            if (deliveryState.shiftChart) {
                deliveryState.shiftChart.destroy();
            }

            // Apenas o horário na legenda/eixo x conforme solicitado
            const shifts = ['06:00', '08:00', '12:00', '14:00', '20:00', '22:00'];
            const shiftLabels = ['06:00', '08:00', '12:00', '14:00', '20:00', '22:00'];

            // No painel ONLINE, a Curva de Entrada ao Longo do Dia exibe as equipes EM TURNO NO MOMENTO
            const isOnlineScreen = deliveryState.currentScreen === 'online';
            const list = isOnlineScreen
                ? deliveryState.filteredTeams.filter(t => t.is_active)
                : deliveryState.filteredTeams;

            const dataCesto = shifts.map(s => list.filter(t => t.shift_code === s && t.vehicle_type === 'Cesto Aéreo').length);
            const dataLeve = shifts.map(s => list.filter(t => t.shift_code === s && t.vehicle_type === 'Veículo Leve').length);
            const dataMoto = shifts.map(s => list.filter(t => t.shift_code === s && t.vehicle_type === 'Moto').length);
            const dataPesado = shifts.map(s => list.filter(t => t.shift_code === s && (t.vehicle_type === 'Linha Viva' || t.vehicle_type === 'Munck')).length);

            // Calcula o maior total para dar folga no topo do eixo Y
            const totalsPerShift = shifts.map((_, i) => dataCesto[i] + dataLeve[i] + dataMoto[i] + dataPesado[i]);
            const maxShiftTotal = Math.max(...totalsPerShift, 5);

            // Plugin para desenhar as quantidades no topo da coluna e dentro dos blocos
            const stackedDataLabelsPlugin = {
                id: 'stackedDataLabels',
                afterDatasetsDraw(chart) {
                    const { ctx, scales: { x, y } } = chart;
                    const isLightMode = document.body.classList.contains('theme-light');
                    const textTopColor = isLightMode ? '#0f172a' : '#00f2fe';

                    // Rótulo com o Total no topo de cada coluna de turno
                    chart.data.labels.forEach((_, i) => {
                        const total = totalsPerShift[i];
                        if (total > 0) {
                            const xPos = x.getPixelForValue(i);
                            const yPos = y.getPixelForValue(total);
                            ctx.save();
                            ctx.fillStyle = textTopColor;
                            ctx.font = 'bold 12px "JetBrains Mono", monospace';
                            ctx.textAlign = 'center';
                            ctx.textBaseline = 'bottom';
                            ctx.fillText(total, xPos, yPos - 4);
                            ctx.restore();
                        }
                    });

                    // Rótulo interno dentro de cada segmento colorido se houver altura suficiente
                    chart.data.datasets.forEach((dataset, dsIdx) => {
                        const meta = chart.getDatasetMeta(dsIdx);
                        meta.data.forEach((bar, i) => {
                            const val = dataset.data[i];
                            if (val > 0) {
                                const barHeight = Math.abs(bar.base - bar.y);
                                if (barHeight >= 16) {
                                    ctx.save();
                                    ctx.fillStyle = '#ffffff';
                                    ctx.font = 'bold 11px "JetBrains Mono", monospace';
                                    ctx.textAlign = 'center';
                                    ctx.textBaseline = 'middle';
                                    const midY = (bar.y + bar.base) / 2;
                                    ctx.fillText(val, bar.x, midY);
                                    ctx.restore();
                                }
                            }
                        });
                    });
                }
            };

            deliveryState.shiftChart = new Chart(shiftCanvas, {
                type: 'bar',
                data: {
                    labels: shiftLabels,
                    datasets: [
                        { label: 'Cesto Aéreo', data: dataCesto, backgroundColor: 'rgba(0, 242, 254, 0.85)', borderRadius: 6 },
                        { label: 'Veículo Leve', data: dataLeve, backgroundColor: 'rgba(59, 130, 246, 0.85)', borderRadius: 6 },
                        { label: 'Moto', data: dataMoto, backgroundColor: 'rgba(16, 185, 129, 0.85)', borderRadius: 6 },
                        { label: 'Linha Viva / Munck', data: dataPesado, backgroundColor: 'rgba(192, 132, 252, 0.85)', borderRadius: 6 }
                    ]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            stacked: true,
                            grid: { display: false },
                            ticks: { color: textColor, font: { family: 'JetBrains Mono', weight: '700', size: 12 } }
                        },
                        y: {
                            stacked: true,
                            suggestedMax: Math.ceil(maxShiftTotal * 1.18) + 1,
                            grid: { color: gridColor },
                            ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 11 } }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleColor: '#00f2fe',
                            bodyColor: '#f8fafc',
                            padding: 12,
                            cornerRadius: 10
                        }
                    }
                },
                plugins: [stackedDataLabelsPlugin]
            });
        }

        // 2. Gráfico de Composição da Frota Entregue (Barras com Rótulos de Quantidade)
        const pieCanvas = document.getElementById('deliveryFleetPieChart');
        if (pieCanvas) {
            if (deliveryState.fleetPieChart) {
                deliveryState.fleetPieChart.destroy();
            }

            const isOnlineScreen = deliveryState.currentScreen === 'online';
            const list = isOnlineScreen
                ? deliveryState.filteredTeams.filter(t => t.is_active)
                : deliveryState.filteredTeams;

            const fleetCategories = ['Cesto Aéreo', 'Veículo Leve', 'Moto', 'Linha Viva + Munk'];
            const fleetCounts = [
                list.filter(t => t.vehicle_type === 'Cesto Aéreo').length,
                list.filter(t => t.vehicle_type === 'Veículo Leve').length,
                list.filter(t => t.vehicle_type === 'Moto').length,
                list.filter(t => t.vehicle_type === 'Linha Viva' || t.vehicle_type === 'Munck').length
            ];

            const maxFleetCount = Math.max(...fleetCounts, 5);

            // Plugin para desenhar o rótulo de quantidade no topo de cada barra
            const fleetBarDataLabelsPlugin = {
                id: 'fleetBarDataLabels',
                afterDatasetsDraw(chart) {
                    const { ctx, scales: { x, y } } = chart;
                    const isLightMode = document.body.classList.contains('theme-light');
                    const textTopColor = isLightMode ? '#0f172a' : '#ffffff';

                    const meta = chart.getDatasetMeta(0);
                    meta.data.forEach((bar, i) => {
                        const val = fleetCounts[i];
                        const xPos = bar.x;
                        const yPos = bar.y;
                        ctx.save();
                        ctx.fillStyle = textTopColor;
                        ctx.font = 'bold 12px "JetBrains Mono", monospace';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'bottom';
                        ctx.fillText(val, xPos, yPos - 4);
                        ctx.restore();
                    });
                }
            };

            deliveryState.fleetPieChart = new Chart(pieCanvas, {
                type: 'bar',
                data: {
                    labels: fleetCategories,
                    datasets: [{
                        label: 'Equipes Entregues',
                        data: fleetCounts,
                        backgroundColor: [
                            'rgba(0, 242, 254, 0.85)',
                            'rgba(59, 130, 246, 0.85)',
                            'rgba(16, 185, 129, 0.85)',
                            'rgba(192, 132, 252, 0.85)'
                        ],
                        borderColor: [
                            '#00f2fe',
                            '#3b82f6',
                            '#10b981',
                            '#c084fc'
                        ],
                        borderWidth: 1.5,
                        borderRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        x: {
                            grid: { display: false },
                            ticks: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '700', size: 11 } }
                        },
                        y: {
                            suggestedMax: Math.ceil(maxFleetCount * 1.18) + 1,
                            grid: { color: gridColor },
                            ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 11 } }
                        }
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            backgroundColor: 'rgba(15, 23, 42, 0.95)',
                            titleColor: '#00f2fe',
                            bodyColor: '#f8fafc',
                            padding: 12,
                            cornerRadius: 10
                        }
                    }
                },
                plugins: [fleetBarDataLabelsPlugin]
            });
        }
    } catch (e) {
        console.warn('Falha ao renderizar gráficos de entrega:', e);
    }
}

// Controle de Recolhimento da Tabela
function toggleDeliveryTableCollapse() {
    deliveryState.isTableCollapsed = !deliveryState.isTableCollapsed;
    const bodyEl = document.getElementById('deliveryTableCollapseBody');
    const textEl = document.getElementById('textToggleDeliveryTable');
    const subEl = document.getElementById('deliveryTableStateSubtitle');

    if (deliveryState.isTableCollapsed) {
        if (bodyEl) bodyEl.classList.add('table-collapsed');
        if (textEl) textEl.textContent = 'EXPANDIR TABELA';
        if (subEl) subEl.textContent = 'Tabela recolhida por padrão para máxima performance. Clique em Expandir para visualizar.';
    } else {
        if (bodyEl) bodyEl.classList.remove('table-collapsed');
        if (textEl) textEl.textContent = 'RECOLHER TABELA';
        if (subEl) subEl.textContent = 'Exibindo relação nominal detalhada das equipes filtradas.';
    }
}

// Renderização da Tabela Nominal de Equipes
function renderDeliveryTable() {
    const tbody = document.getElementById('deliveryTableBody');
    const countBadge = document.getElementById('deliveryResultsCountBadge');
    const subEl = document.getElementById('deliveryTableStateSubtitle');
    const list = deliveryState.filteredTeams;

    const isModeActive = deliveryState.regionalViewMode !== 'total';
    const modeLabel = isModeActive ? 'Equipes Ativas' : 'Total Acumulado do Dia';

    if (countBadge) {
        countBadge.textContent = `${list.length} equipes filtradas (${modeLabel})`;
    }

    if (subEl && !deliveryState.isTableCollapsed) {
        const parts = [modeLabel];
        if (deliveryState.filters.regions.size > 0) parts.push(`Região: ${Array.from(deliveryState.filters.regions).join(', ')}`);
        if (deliveryState.filters.bases.size > 0) parts.push(`Base: ${Array.from(deliveryState.filters.bases).join(', ')}`);
        if (deliveryState.filters.shifts.size > 0) parts.push(`Turno: ${Array.from(deliveryState.filters.shifts).join(', ')}`);
        if (deliveryState.filters.vehicles.size > 0) parts.push(`Frota: ${Array.from(deliveryState.filters.vehicles).join(', ')}`);
        if (deliveryState.filters.search) parts.push(`Busca: "${deliveryState.filters.search}"`);
        subEl.textContent = `Exibindo ${list.length} equipes | ${parts.join(' | ')}`;
    }

    if (!tbody) return;

    if (!list || list.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; padding: 32px; color: var(--text-secondary);">
                    <p style="font-weight: 700; margin: 0;">Nenhuma equipe encontrada para os filtros selecionados.</p>
                </td>
            </tr>
        `;
        return;
    }

    tbody.innerHTML = list.map(t => {
        const isAct = t.is_active;
        const statusBadge = isAct
            ? `<span class="badge-status-active" style="background: rgba(16, 185, 129, 0.14); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.35); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;"><span class="live-status-dot" style="width:6px;height:6px;"></span> Logada</span>`
            : `<span style="background: rgba(148, 163, 184, 0.14); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 700;">Turno Concluído</span>`;

        return `
            <tr>
                <td>
                    <span class="team-badge" style="font-weight: 800;">${t.team_code}</span>
                </td>
                <td>
                    <div style="font-weight: 800; color: var(--text-primary);">${t.base_display || t.base_name}</div>
                    <small style="color: var(--text-secondary); font-family: 'JetBrains Mono', monospace; font-weight: 700;">${t.base_code}</small>
                </td>
                <td>
                    <div style="font-weight: 700;">${t.region}</div>
                    <small style="font-weight: 800; color: ${t.company === 'Alpitel' ? '#0284c7' : '#8b5cf6'};">${t.company}</small>
                </td>
                <td>
                    <span style="font-size: 0.75rem; font-weight: 800; color: var(--text-primary);">${t.vehicle_type}</span>
                </td>
                <td>
                    <strong style="font-family: 'JetBrains Mono', monospace; color: #10b981;">${t.login_time || '--:--'}</strong>
                </td>
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; color: var(--text-secondary); font-weight: 600;">${t.logoff_time || '--:--'}</span>
                </td>
                <td>
                    <span class="shift-pill ${t.shift_pill_class}" style="font-size: 0.74rem;">${t.shift_slot}</span>
                </td>
                <td>${statusBadge}</td>
                <td>
                    <div style="font-weight: 600; color: var(--text-primary);">${t.driver || '--'}</div>
                </td>
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; color: var(--text-secondary);">${t.plate || '--'}</span>
                </td>
            </tr>
        `;
    }).join('');
}

// Exportação Excel (.xlsx) Sensível aos Filtros Ativos
function exportDeliveryExcelFiltered() {
    const list = deliveryState.filteredTeams;
    if (!list || list.length === 0) {
        showToast('Nenhuma equipe para exportar com os filtros atuais.', 'warning');
        return;
    }

    const rows = list.map(t => ({
        "Código Equipe": t.team_code || "",
        "Base Operacional": t.base_display || t.base_name || "",
        "Sigla Base": t.base_code || "",
        "Região": t.region || "",
        "Empresa": t.company || "",
        "Frota / Veículo": t.vehicle_type || "",
        "Categoria": t.vehicle_category || "",
        "Horário Login": t.login_time || "",
        "Horário Logoff": t.logoff_time || "",
        "Turno": t.shift_slot || "",
        "Status Atual": t.is_active ? "Logada / Ativa" : (t.status || "Turno Concluído"),
        "Motorista": t.driver || "",
        "Placa": t.plate || "",
        "UT": t.ut || "",
        "Filial": t.filial || ""
    }));

    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Equipes Entregues");
        const dateStr = new Date().toISOString().split('T')[0];
        XLSX.writeFile(wb, `Entrega_Equipes_Enel_${dateStr}.xlsx`);
        showToast(`Planilha gerada com sucesso (${rows.length} equipes filtradas)!`, 'success');
    } else {
        // Fallback para endpoint nativo
        window.location.href = '/api/delivery/export_excel';
    }
}

function exportDeliveryExcel() {
    exportDeliveryExcelFiltered();
}

// ==========================================================================
// TELA 2: AUDITORIA & HISTÓRICO FORENSE
// ==========================================================================
function setHistoryAuditMode(mode) {
    deliveryState.historyMode = mode;
    const btnDay = document.getElementById('btnHistModeDay');
    const btnMonth = document.getElementById('btnHistModeMonth');
    const wrapDay = document.getElementById('histDaySelectorWrap');
    const wrapMonth = document.getElementById('histMonthSelectorWrap');
    const viewDay = document.getElementById('histViewDayContainer');
    const viewMonth = document.getElementById('histViewMonthContainer');

    if (mode === 'day') {
        if (btnDay) btnDay.classList.add('active');
        if (btnMonth) btnMonth.classList.remove('active');
        if (wrapDay) wrapDay.style.display = 'block';
        if (wrapMonth) wrapMonth.style.display = 'none';
        if (viewDay) viewDay.style.display = 'block';
        if (viewMonth) viewMonth.style.display = 'none';
        loadDailyHistoryAudit();
    } else {
        if (btnDay) btnDay.classList.remove('active');
        if (btnMonth) btnMonth.classList.add('active');
        if (wrapDay) wrapDay.style.display = 'none';
        if (wrapMonth) wrapMonth.style.display = 'block';
        if (viewDay) viewDay.style.display = 'none';
        if (viewMonth) viewMonth.style.display = 'block';
        loadMonthlyHistoryAudit();
    }
}

// Inicialização do Flatpickr para Múltiplas Datas de Auditoria
function initHistoryDatePicker() {
    const input = document.getElementById('histDateInput');
    if (!input || !window.flatpickr) return;
    if (deliveryState.datePickerInstance) return;

    const todayStr = new Date().toISOString().split('T')[0];
    if (!deliveryState.selectedAuditDates || deliveryState.selectedAuditDates.length === 0) {
        deliveryState.selectedAuditDates = [todayStr];
    }

    deliveryState.datePickerInstance = flatpickr(input, {
        mode: "multiple",
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        conjunction: "  |  ",
        defaultDate: deliveryState.selectedAuditDates,
        locale: {
            weekdays: {
                shorthand: ["Dom", "Seg", "Ter", "Qua", "Qui", "Sex", "Sáb"],
                longhand: ["Domingo", "Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado"]
            },
            months: {
                shorthand: ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
                longhand: ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
            }
        },
        onChange: function(selectedDates) {
            const dates = selectedDates.map(d => {
                const y = d.getFullYear();
                const m = String(d.getMonth() + 1).padStart(2, '0');
                const day = String(d.getDate()).padStart(2, '0');
                return `${y}-${m}-${day}`;
            });
            deliveryState.selectedAuditDates = dates;
            const clearBtn = document.getElementById('btnHistClearDates');
            if (clearBtn) clearBtn.style.display = dates.length > 0 ? 'inline-block' : 'none';
            handleAuditDatesSelected(dates);
        }
    });
}

function handleAuditDatesSelected(dates) {
    if (!dates || dates.length === 0) return;

    const viewDay = document.getElementById('histViewDayContainer');
    const viewComp = document.getElementById('histViewComparisonContainer');
    const viewMonth = document.getElementById('histViewMonthContainer');

    if (viewMonth) viewMonth.style.display = 'none';

    if (dates.length === 1) {
        if (viewDay) viewDay.style.display = 'block';
        if (viewComp) viewComp.style.display = 'none';
        loadDailyHistoryAudit(dates[0]);
    } else {
        if (viewDay) viewDay.style.display = 'none';
        if (viewComp) viewComp.style.display = 'block';
        loadComparisonAudit(dates);
    }
}

function clearSelectedAuditDates() {
    if (deliveryState.datePickerInstance) {
        const todayStr = new Date().toISOString().split('T')[0];
        deliveryState.datePickerInstance.setDate([todayStr], true);
    }
}

function refreshCurrentHistoryAudit() {
    if (deliveryState.historyMode === 'day') {
        if (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates.length > 1) {
            loadComparisonAudit(deliveryState.selectedAuditDates);
        } else {
            const target = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates[0]) || deliveryState.historyDate;
            loadDailyHistoryAudit(target);
        }
    } else {
        loadMonthlyHistoryAudit();
    }
}

// Consulta Histórica por Dia (1 Data Selecionada)
async function loadDailyHistoryAudit(targetDate = null) {
    let dateVal = targetDate;
    if (!dateVal) {
        const input = document.getElementById('histDateInput');
        dateVal = input && input.value ? input.value : deliveryState.historyDate;
    }
    if (dateVal && dateVal.includes(',')) dateVal = dateVal.split(',')[0].trim();
    if (dateVal && dateVal.includes('|')) dateVal = dateVal.split('|')[0].trim();
    deliveryState.historyDate = dateVal;

    const elLabel = document.getElementById('histDayDateLabel');
    if (elLabel) elLabel.textContent = `Auditando dados do dia: ${dateVal}`;

    try {
        const resp = await fetch(`/api/delivery/history?date=${dateVal}`);
        const data = await resp.json();
        deliveryState.historyDayData = data;

        const summary = data.summary || {};
        const elTotal = document.getElementById('histDayTotalNum');
        const elCesto = document.getElementById('histDayCestoNum');
        const elLeve = document.getElementById('histDayLeveNum');
        const elMoto = document.getElementById('histDayMotoNum');
        const elPesado = document.getElementById('histDayPesadoNum');

        if (elTotal) elTotal.textContent = data.total_delivered || 0;
        if (elCesto) elCesto.textContent = summary.cesto || 0;
        if (elLeve) elLeve.textContent = summary.leve || 0;
        if (elMoto) elMoto.textContent = summary.moto || 0;
        if (elPesado) elPesado.textContent = summary.linhaviva_munck || 0;

        // Preenche a tabela nominal do dia
        const tbody = document.getElementById('histDayTableBody');
        const teams = data.teams || [];
        if (tbody) {
            if (teams.length === 0) {
                tbody.innerHTML = `<tr><td colspan="10" style="text-align: center; padding: 30px; color: var(--text-secondary);">Nenhum registro encontrado para esta data.</td></tr>`;
            } else {
                tbody.innerHTML = teams.map(t => `
                    <tr>
                        <td><span class="team-badge" style="font-weight: 800;">${t.team_code}</span></td>
                        <td><strong style="color: var(--text-primary);">${t.base_display || t.base_name}</strong></td>
                        <td>${t.region} / <small style="font-weight: 800;">${t.company}</small></td>
                        <td><strong>${t.vehicle_type}</strong></td>
                        <td><strong style="color:#10b981; font-family:'JetBrains Mono', monospace;">${t.login_time || '--:--'}</strong></td>
                        <td><span style="color:var(--text-secondary); font-family:'JetBrains Mono', monospace;">${t.logoff_time || '--:--'}</span></td>
                        <td><span class="shift-pill">${t.shift_slot}</span></td>
                        <td><span style="font-size: 0.72rem; font-weight: 800; color: #10b981;">${t.status || 'Entregue'}</span></td>
                        <td>${t.driver || '--'}</td>
                        <td><span style="font-family:'JetBrains Mono', monospace;">${t.plate || '--'}</span></td>
                    </tr>
                `).join('');
            }
        }
    } catch (err) {
        console.error('Falha ao carregar histórico diário:', err);
    }
}

// Consulta e Renderização do Comparativo (2 ou mais Datas)
async function loadComparisonAudit(dates) {
    if (!dates || dates.length === 0) return;

    // Badges das datas selecionadas no topo
    const badgesContainer = document.getElementById('histComparisonSelectedBadges');
    if (badgesContainer) {
        badgesContainer.innerHTML = dates.map(d => {
            const formatted = d.split('-').reverse().join('/');
            return `<span class="date-comparison-badge">${formatted}</span>`;
        }).join('');
    }

    try {
        const promises = dates.map(d => fetch(`/api/delivery/history?date=${d}`).then(r => r.json()));
        const results = await Promise.all(promises);

        const validResults = results.map((res, i) => {
            const dateStr = dates[i];
            const summary = res.summary || {};
            return {
                date: dateStr,
                dateFormatted: dateStr.split('-').reverse().join('/'),
                total: res.total_delivered || 0,
                cesto: summary.cesto || 0,
                leve: summary.leve || 0,
                moto: summary.moto || 0,
                linhaviva: summary.linhaviva_munck || 0,
                shifts: summary.shifts || {},
                teams: res.teams || []
            };
        });

        deliveryState.comparisonData = validResults;

        // 1. KPI Cards comparativos para cada data
        const kpiGrid = document.getElementById('histComparisonKpiGrid');
        if (kpiGrid) {
            kpiGrid.innerHTML = validResults.map(r => `
                <div class="hero-liquid-card" style="padding: 16px; min-height: 110px;">
                    <span class="hero-tag" style="font-size: 0.72rem;">DATA: ${r.dateFormatted}</span>
                    <div class="hero-number-row" style="margin: 4px 0;">
                        <span class="hero-big-number text-cyan" style="font-size: 1.8rem;">${r.total}</span>
                        <span class="hero-unit">equipes</span>
                    </div>
                    <div style="display: flex; gap: 8px; font-size: 0.72rem; color: var(--text-secondary); margin-top: 4px;">
                        <span>C: <strong>${r.cesto}</strong></span>
                        <span>L: <strong>${r.leve}</strong></span>
                        <span>M: <strong>${r.moto}</strong></span>
                        <span>LV: <strong>${r.linhaviva}</strong></span>
                    </div>
                </div>
            `).join('');
        }

        // 2. Gráfico Comparativo de Barras Agrupadas
        renderComparisonBarChart(validResults);

        // 3. Tabela Comparativa Analítica
        const tbody = document.getElementById('histComparisonTableBody');
        if (tbody) {
            tbody.innerHTML = validResults.map(r => {
                let topShift = '--';
                let maxShiftVal = 0;
                for (const [sh, cnt] of Object.entries(r.shifts)) {
                    if (cnt > maxShiftVal) {
                        maxShiftVal = cnt;
                        topShift = sh;
                    }
                }
                const topShiftDisplay = maxShiftVal > 0 ? `${topShift} (${maxShiftVal})` : '--';

                return `
                    <tr>
                        <td><strong style="color: var(--text-primary); font-family: 'JetBrains Mono', monospace;">${r.dateFormatted}</strong></td>
                        <td><span class="team-badge" style="font-size: 0.9rem; font-weight: 800; color: #00f2fe;">${r.total}</span></td>
                        <td><strong style="color: #00f2fe; font-family: 'JetBrains Mono';">${r.cesto}</strong></td>
                        <td><strong style="color: #60a5fa; font-family: 'JetBrains Mono';">${r.leve}</strong></td>
                        <td><strong style="color: #10b981; font-family: 'JetBrains Mono';">${r.moto}</strong></td>
                        <td><strong style="color: #c084fc; font-family: 'JetBrains Mono';">${r.linhaviva}</strong></td>
                        <td><span class="shift-pill">${topShiftDisplay}</span></td>
                    </tr>
                `;
            }).join('');
        }

    } catch (err) {
        console.error('Falha ao processar comparativo:', err);
    }
}

function renderComparisonBarChart(results) {
    const canvas = document.getElementById('histComparisonChart');
    if (!canvas || !window.Chart) return;

    if (deliveryState.comparisonChart) {
        deliveryState.comparisonChart.destroy();
    }

    const isLight = document.body.classList.contains('theme-light');
    const textColor = isLight ? '#0f172a' : '#f8fafc';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.06)';

    const dateColors = [
        { bg: 'rgba(0, 242, 254, 0.85)', border: '#00f2fe' },
        { bg: 'rgba(16, 185, 129, 0.85)', border: '#10b981' },
        { bg: 'rgba(59, 130, 246, 0.85)', border: '#3b82f6' },
        { bg: 'rgba(192, 132, 252, 0.85)', border: '#c084fc' },
        { bg: 'rgba(245, 158, 11, 0.85)', border: '#f59e0b' },
        { bg: 'rgba(239, 68, 68, 0.85)', border: '#ef4444' }
    ];

    const labels = ['Total Entregue', 'Cesto Aéreo', 'Veículo Leve', 'Moto', 'Linha Viva + Munk'];

    const datasets = results.map((r, idx) => {
        const color = dateColors[idx % dateColors.length];
        return {
            label: r.dateFormatted,
            data: [r.total, r.cesto, r.leve, r.moto, r.linhaviva],
            backgroundColor: color.bg,
            borderColor: color.border,
            borderWidth: 1.5,
            borderRadius: 6
        };
    });

    const comparisonBarLabelsPlugin = {
        id: 'comparisonBarLabels',
        afterDatasetsDraw(chart) {
            const { ctx } = chart;
            const isLightMode = document.body.classList.contains('theme-light');
            const labelCol = isLightMode ? '#0f172a' : '#ffffff';

            chart.data.datasets.forEach((dataset, dsIdx) => {
                const meta = chart.getDatasetMeta(dsIdx);
                meta.data.forEach((bar, i) => {
                    const val = dataset.data[i];
                    if (val > 0) {
                        ctx.save();
                        ctx.fillStyle = labelCol;
                        ctx.font = 'bold 11px "JetBrains Mono", monospace';
                        ctx.textAlign = 'center';
                        ctx.textBaseline = 'bottom';
                        ctx.fillText(val, bar.x, bar.y - 3);
                        ctx.restore();
                    }
                });
            });
        }
    };

    let maxVal = 0;
    results.forEach(r => {
        if (r.total > maxVal) maxVal = r.total;
    });

    deliveryState.comparisonChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '700', size: 11 } }
                },
                y: {
                    suggestedMax: Math.ceil(maxVal * 1.18) + 1,
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 11 } }
                }
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '700', size: 12 }, boxWidth: 14 }
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 23, 42, 0.95)',
                    titleColor: '#00f2fe',
                    bodyColor: '#f8fafc',
                    padding: 12,
                    cornerRadius: 10
                }
            }
        },
        plugins: [comparisonBarLabelsPlugin]
    });
}

function exportComparisonExcel() {
    const list = deliveryState.comparisonData;
    if (!list || list.length === 0) {
        showToast('Nenhum dado comparativo para exportar.', 'warning');
        return;
    }
    const rows = list.map(r => ({
        "Data": r.dateFormatted,
        "Total Entregue": r.total,
        "Cesto Aéreo": r.cesto,
        "Veículo Leve": r.leve,
        "Moto": r.moto,
        "Linha Viva + Munk": r.linhaviva
    }));
    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Comparativo");
        XLSX.writeFile(wb, `Comparativo_Entregas_${new Date().toISOString().split('T')[0]}.xlsx`);
        showToast('Planilha de comparativo gerada com sucesso!', 'success');
    }
}

// Consulta Histórica por Mês
async function loadMonthlyHistoryAudit() {
    const input = document.getElementById('histMonthInput');
    const monthVal = input && input.value ? input.value : deliveryState.historyMonth;
    deliveryState.historyMonth = monthVal;

    try {
        const resp = await fetch(`/api/delivery/monthly?month=${monthVal}`);
        const data = await resp.json();
        deliveryState.historyMonthData = data;

        const elAvgTot = document.getElementById('histMonthAvgTotal');
        const elDays = document.getElementById('histMonthOperatingDays');
        const elAvgCesto = document.getElementById('histMonthAvgCesto');
        const elAvgLeve = document.getElementById('histMonthAvgLeve');
        const elAvgMoto = document.getElementById('histMonthAvgMoto');
        const elAvgPesado = document.getElementById('histMonthAvgPesado');

        if (elAvgTot) elAvgTot.textContent = (data.avg_total || 0).toFixed(1);
        if (elDays) elDays.textContent = `Calculado sobre ${data.operating_days || 0} dias com operação registrada`;
        if (elAvgCesto) elAvgCesto.textContent = (data.avg_cesto || 0).toFixed(1);
        if (elAvgLeve) elAvgLeve.textContent = (data.avg_leve || 0).toFixed(1);
        if (elAvgMoto) elAvgMoto.textContent = (data.avg_moto || 0).toFixed(1);
        if (elAvgPesado) elAvgPesado.textContent = (data.avg_linhaviva_munck || 0).toFixed(1);

        // Gráfico Mensal de Barras Diárias com Linha de Média
        renderMonthlyBarChart(data);
    } catch (err) {
        console.error('Falha ao carregar auditoria mensal:', err);
    }
}

function renderMonthlyBarChart(data) {
    const canvas = document.getElementById('histMonthlyBarChart');
    if (!canvas || !window.Chart) return;

    if (deliveryState.historyMonthlyChart) {
        deliveryState.historyMonthlyChart.destroy();
    }

    const isLight = document.body.classList.contains('theme-light');
    const textColor = isLight ? '#0f172a' : '#f8fafc';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.06)';

    const days = data.days || [];
    const labels = days.map(d => d.date.slice(8) + '/' + d.date.slice(5, 7));
    const totalData = days.map(d => d.total_teams);
    const avgValue = data.avg_total || 0;
    const avgLineData = days.map(() => avgValue);

    deliveryState.historyMonthlyChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    type: 'line',
                    label: `Média Mensal (${avgValue.toFixed(1)})`,
                    data: avgLineData,
                    borderColor: '#f59e0b',
                    borderWidth: 2,
                    borderDash: [6, 4],
                    pointRadius: 0,
                    fill: false
                },
                {
                    type: 'bar',
                    label: 'Total Entregue',
                    data: totalData,
                    backgroundColor: 'rgba(0, 242, 254, 0.75)',
                    borderRadius: 6
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '700', size: 10 } }
                },
                y: {
                    grid: { color: gridColor },
                    ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 11 } }
                }
            },
            plugins: {
                legend: {
                    labels: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '700' } }
                }
            }
        }
    });
}

function exportHistoryExcel() {
    const data = deliveryState.historyDayData;
    if (!data || !data.teams || data.teams.length === 0) {
        showToast('Nenhum dado auditado para exportar.', 'warning');
        return;
    }
    const rows = data.teams.map(t => ({
        "Data": data.date,
        "Código Equipe": t.team_code,
        "Base Operacional": t.base_display || t.base_name,
        "Região": t.region,
        "Empresa": t.company,
        "Frota": t.vehicle_type,
        "Login": t.login_time,
        "Logoff": t.logoff_time,
        "Turno": t.shift_slot,
        "Motorista": t.driver,
        "Placa": t.plate
    }));
    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Auditoria");
        XLSX.writeFile(wb, `Auditoria_Entrega_${data.date}.xlsx`);
        showToast(`Auditoria do dia ${data.date} exportada!`, 'success');
    }
}

// Disparo do Robô CDP
async function triggerEnelCdpCapture() {
    const btn = document.getElementById('btnTriggerEnelCdp');
    const btnText = document.getElementById('triggerEnelCdpText');
    const originalText = btnText ? btnText.textContent : 'Disparar Coleta Imediata Agora (Robô CDP)';
    
    if (btnText) btnText.textContent = 'Robô CDP: Lendo 500 linhas na Enel...';
    if (btn) btn.disabled = true;

    try {
        showToast('Robô CDP acionado! Coletando dados do portal Enel...', 'info');
        const resp = await fetch('/api/capture/enel', { method: 'POST' });
        const data = await resp.json();
        
        if (data.status === 'success') {
            showToast(`Sucesso! ${data.message || 'Dados sincronizados com o Supabase!'}`, 'success');
            await loadDeliveryData(false);
            closeModal('deliveryCollectModal');
        } else {
            showToast(data.message || 'Aviso durante a coleta da Enel.', 'warning');
        }
    } catch (err) {
        showToast('Erro ao comunicar com o Robô CDP: ' + err.message, 'danger');
    } finally {
        if (btnText) btnText.textContent = originalText;
        if (btn) btn.disabled = false;
        initIcons();
    }
}

function openDeliveryCollectModal() {
    const modal = document.getElementById('deliveryCollectModal');
    if (modal) {
        modal.classList.add('active');
        initIcons();
    }
}

async function copyDaemonScriptToClipboard() {
    const daemonCode = `// Script autônomo Enel SP
(function iniciarRoboAutonomoEnel() {
    const LOCAL_SERVER_URL = 'http://127.0.0.1:5000/api/delivery/sync';
    const INTERVAL_SECONDS = 120;
    // ...
})();`;
    try {
        await navigator.clipboard.writeText(daemonCode);
        showToast('Script copiado!', 'success');
    } catch (err) {
        showToast('Erro ao copiar.', 'danger');
    }
}

// ==========================================================================
// PAINEL DE GERENCIAMENTO DO SISTEMA (ACESSO RESTRITO)
// ==========================================================================

function switchAdminTab(tabName) {
    const btnEngines = document.getElementById('btnAdminTabEngines');
    const btnTelemetry = document.getElementById('btnAdminTabTelemetry');
    const contentEngines = document.getElementById('adminTabEnginesContent');
    const contentTelemetry = document.getElementById('adminTabTelemetryContent');

    if (tabName === 'engines') {
        if (btnEngines) btnEngines.classList.add('active');
        if (btnTelemetry) btnTelemetry.classList.remove('active');
        if (contentEngines) contentEngines.style.display = 'block';
        if (contentTelemetry) contentTelemetry.style.display = 'none';
        loadAdminEngineStatus();
    } else {
        if (btnEngines) btnEngines.classList.remove('active');
        if (btnTelemetry) btnTelemetry.classList.add('active');
        if (contentEngines) contentEngines.style.display = 'none';
        if (contentTelemetry) contentTelemetry.style.display = 'block';
        loadAdminTelemetry();
    }
    initIcons();
}

async function loadAdminEngineStatus() {
    try {
        const resp = await fetch('/api/admin/engine_status');
        const data = await resp.json();
        if (data.status !== 'success') return;

        const engines = data.engines || {};

        // 1. Motor TRBOnet One
        const trbo = engines.trbonet || {};
        const bTrbo = document.getElementById('engineBadgeTrbonet');
        const mTrbo = document.getElementById('engineMsgTrbonet');
        const sTrbo = document.getElementById('engineSyncTrbonet');
        const rTrbo = document.getElementById('engineRecordsTrbonet');
        if (bTrbo) {
            bTrbo.className = `engine-status-badge ${trbo.status === 'OPERATIONAL' ? 'badge-operational' : (trbo.status === 'ERROR_CONNECTION' ? 'badge-error-connection' : 'badge-stopped')}`;
            bTrbo.textContent = trbo.status === 'OPERATIONAL' ? 'OPERACIONAL' : (trbo.status === 'ERROR_CONNECTION' ? 'FALHA DE CONEXÃO' : 'MOTOR PARADO');
        }
        if (mTrbo) mTrbo.textContent = trbo.message || '--';
        if (sTrbo) sTrbo.textContent = trbo.last_sync || '--:--:--';
        if (rTrbo) rTrbo.textContent = `${trbo.records || 0} rádios`;

        // 2. Robô CDP Enel SP
        const enel = engines.enel_cdp || {};
        const bEnel = document.getElementById('engineBadgeEnel');
        const mEnel = document.getElementById('engineMsgEnel');
        const sEnel = document.getElementById('engineSyncEnel');
        const rEnel = document.getElementById('engineRecordsEnel');
        if (bEnel) {
            bEnel.className = `engine-status-badge ${enel.status === 'OPERATIONAL' ? 'badge-operational' : (enel.status === 'ERROR_CONNECTION' ? 'badge-error-connection' : 'badge-stopped')}`;
            bEnel.textContent = enel.status === 'OPERATIONAL' ? 'OPERACIONAL' : (enel.status === 'ERROR_CONNECTION' ? 'FALHA DE CONEXÃO' : 'MOTOR PARADO');
        }
        if (mEnel) mEnel.textContent = enel.message || '--';
        if (sEnel) sEnel.textContent = enel.last_sync || '--:--:--';
        if (rEnel) rEnel.textContent = `${enel.records || 0} equipes`;

        // 3. Supabase Cloud
        const cloud = engines.cloud_sync || {};
        const bCloud = document.getElementById('engineBadgeCloud');
        const mCloud = document.getElementById('engineMsgCloud');
        if (bCloud) {
            bCloud.className = `engine-status-badge ${cloud.status === 'OPERATIONAL' ? 'badge-operational' : 'badge-stopped'}`;
            bCloud.textContent = cloud.status === 'OPERATIONAL' ? 'OPERACIONAL' : 'FALHA DE REDE';
        }
        if (mCloud) mCloud.textContent = cloud.message || '--';

    } catch (err) {
        console.error('Erro ao consultar status dos motores:', err);
    }
}

async function triggerRestartEngines() {
    if (!confirm('Deseja enviar comando para reiniciar os motores locais de captura (TRBOnet One e Robô CDP Enel SP)?\nO servidor web continuará funcionando normalmente.')) {
        return;
    }

    const btn = document.getElementById('btnRestartEngines');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> Reiniciando Motores...`;
        initIcons();
    }

    try {
        const resp = await fetch('/api/admin/restart_engines', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            }
        });
        const result = await resp.json();
        if (result.status === 'success') {
            showToast(result.message || 'Motores reiniciados com sucesso!', 'success');
            setTimeout(loadAdminEngineStatus, 1500);
        } else {
            showToast(result.message || 'Erro ao reiniciar motores.', 'danger');
        }
    } catch (err) {
        showToast('Falha na comunicação com o servidor: ' + err.message, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="power" style="width: 16px; height: 16px; margin-right: 6px;"></i> REINICIAR MOTORES LOCAIS`;
            initIcons();
        }
    }
}

let currentTelemetrySessions = [];

async function loadAdminTelemetry() {
    try {
        const resp = await fetch('/api/admin/telemetry_metrics', {
            headers: { 'Authorization': `Bearer ${authState.token || ''}` }
        });
        const data = await resp.json();
        if (data.status !== 'success') return;

        const elAct = document.getElementById('telemetryActiveNow');
        const elTod = document.getElementById('telemetryToday');
        const elWek = document.getElementById('telemetryWeek');
        const elMon = document.getElementById('telemetryMonth');

        if (elAct) elAct.textContent = data.active_now || 0;
        if (elTod) elTod.textContent = data.today_unique || 0;
        if (elWek) elWek.textContent = data.week_unique || 0;
        if (elMon) elMon.textContent = data.month_unique || 0;

        const sessions = data.recent_sessions || [];
        currentTelemetrySessions = sessions;
        const tbody = document.getElementById('telemetrySessionsTableBody');
        if (tbody) {
            if (sessions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; padding: 24px; color: var(--text-secondary);">Nenhuma sessão registrada até o momento.</td></tr>`;
            } else {
                const fiveMinAgo = new Date(Date.now() - 5 * 60 * 1000);
                tbody.innerHTML = sessions.map(s => {
                    const isOnline = s.last_heartbeat ? new Date(s.last_heartbeat) >= fiveMinAgo : false;
                    const badgeClass = isOnline ? 'badge-online-gps' : 'badge-offline-gray';
                    const badgeText = isOnline ? 'ONLINE' : 'DESCONECTADO';
                    const fSeen = s.first_seen ? new Date(s.first_seen).toLocaleString('pt-BR') : '--';
                    const lBeat = s.last_heartbeat ? new Date(s.last_heartbeat).toLocaleTimeString('pt-BR') : '--';
                    const fpShort = s.fingerprint ? `${s.fingerprint.substring(0, 8)}...` : '--';

                    return `
                        <tr>
                            <td><strong style="color: var(--text-primary);">${s.username || 'Colaborador'}</strong></td>
                            <td><code style="color: #00f2fe; font-family: 'JetBrains Mono';">${s.ip_address || '--'}</code></td>
                            <td>${s.geo_city || 'São Paulo'} / <small style="font-weight: 800;">${s.geo_region || 'SP'}</small></td>
                            <td><strong>${s.device_type || 'Desktop'}</strong></td>
                            <td>${s.browser_name || 'Chrome'} <small style="color: var(--text-secondary);">(${s.os_name || 'Windows'})</small></td>
                            <td><span style="font-family: 'JetBrains Mono'; font-size: 0.72rem; color: var(--text-secondary);" title="${s.fingerprint}">${fpShort}</span></td>
                            <td><span class="status-badge ${badgeClass}" style="font-size: 0.72rem; padding: 2px 8px;">${badgeText}</span></td>
                            <td><small style="font-family: 'JetBrains Mono'; color: var(--text-secondary);">${fSeen}</small></td>
                            <td><strong style="font-family: 'JetBrains Mono'; color: ${isOnline ? '#10b981' : 'var(--text-secondary)'};">${lBeat}</strong></td>
                        </tr>
                    `;
                }).join('');
            }
        }
    } catch (err) {
        console.error('Erro ao consultar telemetria:', err);
    }
}

function exportTelemetryExcel() {
    if (!currentTelemetrySessions || currentTelemetrySessions.length === 0) {
        showToast('Nenhuma sessão para exportar.', 'warning');
        return;
    }
    const rows = currentTelemetrySessions.map(s => ({
        "Usuário": s.username || "Colaborador",
        "IP Origem": s.ip_address || "--",
        "Cidade": s.geo_city || "São Paulo",
        "UF": s.geo_region || "SP",
        "Dispositivo": s.device_type || "Desktop",
        "Sistema Operacional": s.os_name || "Windows",
        "Navegador": s.browser_name || "Chrome",
        "Fingerprint": s.fingerprint || "--",
        "Primeiro Acesso": s.first_seen || "--",
        "Último Heartbeat": s.last_heartbeat || "--"
    }));

    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Sessões");
        XLSX.writeFile(wb, `Telemetria_Sessoes_${new Date().toISOString().split('T')[0]}.xlsx`);
        showToast('Relatório de sessões exportado com sucesso!', 'success');
    }
}

function logoutAdminSession() {
    handleLogout();
    navigateToView('hub');
}

// ==============================================================================
// TELEMETRIA SILENCIOSA CLIENT-SIDE (FINGERPRINT, DISPOSITIVO & HEARTBEAT)
// ==============================================================================

function getOrCreateSessionId() {
    let sid = sessionStorage.getItem('cco_client_session_id');
    if (!sid) {
        sid = 'sess_' + Math.random().toString(36).substring(2, 11) + '_' + Date.now();
        sessionStorage.setItem('cco_client_session_id', sid);
    }
    return sid;
}

function generateBrowserFingerprint() {
    let cached = localStorage.getItem('cco_client_fingerprint');
    if (cached) return cached;

    try {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        ctx.textBaseline = 'top';
        ctx.font = "14px 'Arial'";
        ctx.fillStyle = "#f60";
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = "#069";
        ctx.fillText("CCO-ALPITEL-2026", 2, 15);
        ctx.fillStyle = "rgba(102, 204, 0, 0.7)";
        ctx.fillText("CCO-ALPITEL-2026", 4, 17);
        const dataUrl = canvas.toDataURL();
        
        let hash = 0;
        const str = dataUrl + navigator.userAgent + screen.width + 'x' + screen.height + Intl.DateTimeFormat().resolvedOptions().timeZone;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash |= 0;
        }
        const fp = 'fp_' + Math.abs(hash).toString(16);
        localStorage.setItem('cco_client_fingerprint', fp);
        return fp;
    } catch (e) {
        return 'fp_generic_' + Math.abs(Date.now()).toString(16);
    }
}

function detectClientEnvironment() {
    const ua = navigator.userAgent;
    let deviceType = 'Desktop';
    if (/tablet|ipad|playbook|silk/i.test(ua)) deviceType = 'Tablet';
    else if (/Mobile|Android|iP(hone|od)|IEMobile|BlackBerry|Kindle/i.test(ua)) deviceType = 'Mobile';

    let osName = 'Windows';
    if (ua.indexOf('Win') !== -1) osName = 'Windows';
    else if (ua.indexOf('Mac') !== -1) osName = 'macOS';
    else if (ua.indexOf('Android') !== -1) osName = 'Android';
    else if (ua.indexOf('Linux') !== -1) osName = 'Linux';
    else if (/iPhone|iPad|iPod/.test(ua)) osName = 'iOS';

    let browserName = 'Chrome';
    if (ua.indexOf('Edg') !== -1) browserName = 'Edge';
    else if (ua.indexOf('Firefox') !== -1) browserName = 'Firefox';
    else if (ua.indexOf('Safari') !== -1 && ua.indexOf('Chrome') === -1) browserName = 'Safari';

    return { deviceType, osName, browserName };
}

async function sendTelemetryHeartbeat() {
    try {
        const env = detectClientEnvironment();
        const payload = {
            session_id: getOrCreateSessionId(),
            fingerprint: generateBrowserFingerprint(),
            device_type: env.deviceType,
            os_name: env.osName,
            browser_name: env.browserName,
            endpoint: window.location.hash || '/'
        };

        await fetch('/api/telemetry/heartbeat', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: JSON.stringify(payload)
        });
    } catch (e) {
        // Silencioso
    }
}

// Binds Globais
window.navigateToView = navigateToView;
window.switchDeliveryScreen = switchDeliveryScreen;
window.loadDeliveryData = loadDeliveryData;
window.toggleRegionFilter = toggleRegionFilter;
window.toggleBaseFilter = toggleBaseFilter;
window.clearDeliveryBaseFilters = clearDeliveryBaseFilters;
window.setDeliveryShiftFilter = setDeliveryShiftFilter;
window.setDeliveryVehicleFilter = setDeliveryVehicleFilter;
window.debounceDeliverySearch = debounceDeliverySearch;
window.toggleDeliveryTableCollapse = toggleDeliveryTableCollapse;
window.exportDeliveryExcelFiltered = exportDeliveryExcelFiltered;
window.exportDeliveryExcel = exportDeliveryExcel;
window.setHistoryAuditMode = setHistoryAuditMode;
window.refreshCurrentHistoryAudit = refreshCurrentHistoryAudit;
window.loadDailyHistoryAudit = loadDailyHistoryAudit;
window.loadMonthlyHistoryAudit = loadMonthlyHistoryAudit;
window.exportHistoryExcel = exportHistoryExcel;
window.initHistoryDatePicker = initHistoryDatePicker;
window.clearSelectedAuditDates = clearSelectedAuditDates;
window.loadComparisonAudit = loadComparisonAudit;
window.exportComparisonExcel = exportComparisonExcel;
window.openDeliveryCollectModal = openDeliveryCollectModal;
window.copyDaemonScriptToClipboard = copyDaemonScriptToClipboard;
window.triggerEnelCdpCapture = triggerEnelCdpCapture;
window.switchAdminTab = switchAdminTab;
window.loadAdminEngineStatus = loadAdminEngineStatus;
window.triggerRestartEngines = triggerRestartEngines;
window.loadAdminTelemetry = loadAdminTelemetry;
window.exportTelemetryExcel = exportTelemetryExcel;
window.logoutAdminSession = logoutAdminSession;



