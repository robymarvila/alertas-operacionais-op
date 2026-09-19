/**
 * PAINEL OPERACIONAL CCO - POWERON VS TRBONET (ULTRA PREMIUM)
 * Motor Reativo, Multi-Seleção Regional e de Bases, Sincronização PowerON e Auditoria
 */

// Configuração das 2 Regiões Oficiais Alpitel (7 Bases Oficiais)
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
    }
};

// Funções Utilitárias Globais de Normalização e Sanitização
function cleanNodeLabel(lbl, fallback = '') {
    if (!lbl) return fallback;
    let s = String(lbl)
        .replace(/MÃ¡quina/g, 'Máquina')
        .replace(/M\uFFFDquina/g, 'Máquina')
        .replace(/Mquina/g, 'Máquina')
        .replace(/SÃ£o Paulo/g, 'São Paulo')
        .replace(/S\uFFFD\s*Paulo/g, 'São Paulo');
    if (s.includes('MAQUINA_1') || (s.includes('Principal') && !s.includes('Máquina'))) {
        return 'Servidor CCO Principal (Máquina 1)';
    }
    if (s.includes('MAQUINA_2') || (s.includes('Redundante') && !s.includes('Máquina'))) {
        return 'Servidor CCO Redundante (Máquina 2)';
    }
    return s;
}

function normalizeBidStatus(rawSt) {
    if (!rawSt || rawSt === '--' || rawSt === 'None' || rawSt === 'null') {
        return 'Não Encontrada';
    }
    const up = String(rawSt).toUpperCase();
    if (up.includes('OPERA')) return 'Em Operação';
    if (up.includes('CHECKLIST')) return 'Em Checklist';
    if (up.includes('PLANEJAD')) return 'Planejada';
    if (up.includes('RETORNAD')) return 'Retornada';
    if (up.includes('BLOQUEAD')) return 'Bloqueada';
    if (up.includes('NÃO') || up.includes('NAO') || up.includes('ENCONTRADA')) return 'Não Encontrada';
    return String(rawSt).trim();
}

function getOperationalDate() {
    // Horário oficial Enel/CCO (Brasília UTC-3)
    // O dia operacional vira pontualmente às 04:31 da manhã.
    // Das 00:00 às 04:30 pertence ao dia operacional anterior.
    const now = new Date();
    const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
    const br = new Date(utc - (3 * 3600000));
    const h = br.getHours();
    const m = br.getMinutes();
    if (h < 4 || (h === 4 && m <= 30)) {
        br.setDate(br.getDate() - 1);
    }
    const y = br.getFullYear();
    const mm = String(br.getMonth() + 1).padStart(2, '0');
    const dd = String(br.getDate()).padStart(2, '0');
    return `${y}-${mm}-${dd}`;
}

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
    selectedStatuses: new Set(['ALL']), // Set contendo 'ALL' ou status selecionados
    selectedShifts: new Set(['ALL']), // Set contendo 'ALL' ou turnos selecionados
    selectedFrotas: new Set(['ALL']), // Set contendo 'ALL' ou tipos de frota selecionados
    filteredTeams: [],
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

    // Atualiza classes no elemento raiz HTML e BODY para consistência absoluta de CSS
    document.documentElement.classList.remove('route-hub', 'route-module', 'route-delivery', 'route-admin');
    document.body.classList.remove('route-hub', 'route-module', 'route-delivery', 'route-admin');
    if (viewName === 'delivery') {
        document.documentElement.classList.add('route-delivery');
        document.body.classList.add('route-delivery');
    } else if (viewName === 'module' || viewName === 'trbonet') {
        document.documentElement.classList.add('route-module');
        document.body.classList.add('route-module');
    } else if (viewName === 'admin') {
        document.documentElement.classList.add('route-admin');
        document.body.classList.add('route-admin');
    } else {
        document.documentElement.classList.add('route-hub');
        document.body.classList.add('route-hub');
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

    if (typeof syncMobileBottomNav === 'function') {
        syncMobileBottomNav(viewName);
    }

    if (typeof updateMobileSubnav === 'function') {
        updateMobileSubnav(viewName);
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
    if (typeof updateMobileSubnav === 'function') {
        updateMobileSubnav('module', tabName);
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
        const url = isManual ? `/api/data?_=${Date.now()}` : '/api/data';
        const response = await fetch(url);
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
            syncStatusUI();
            syncTurnoUI();
            syncFrotaUI();
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
// ==========================================================================
// ATUALIZAR DADOS / SINCRONIZAÇÃO UNIFICADA (TRBONET + EQUIPES BRASIL)
// ==========================================================================
async function syncUnifiedLive() {
    if (!authState.isAuthenticated) {
        showToast('Ação Restrita: Efetue o login no Cadeado para atualizar os dados.', 'warning');
        openAuthModal();
        return;
    }

    const btn = document.getElementById('btnLiveCapture');
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Atualizando...</span>`;
    }
    initIcons();

    try {
        const response = await fetch('/api/sync/unified', {
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
            showToast(result.message || 'Dados atualizados com sucesso!', 'success');
            fetchDashboardData(false);
            if (typeof fetchDeliveryState === 'function') fetchDeliveryState(false);
        } else if (response.status === 202 || result?.status === 'queued') {
            const cmdId = result.command_id;
            showToast('Ordem enviada ao Robô Local Windows via Nuvem! Aguardando execução...', 'info');
            
            let completed = false;
            if (cmdId) {
                for (let attempt = 1; attempt <= 15; attempt++) {
                    if (btn) btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> <span>Robô Local executando (${attempt * 2}s)...</span>`;
                    initIcons();
                    await new Promise(r => setTimeout(r, 2000));
                    try {
                        const checkResp = await fetch(`/api/commands/${cmdId}`);
                        if (checkResp.ok) {
                            const cmdStatus = await checkResp.json();
                            if (cmdStatus.status === 'COMPLETED') {
                                showToast('Sincronização unificada concluída pelo Robô Local Windows com sucesso!', 'success');
                                fetchDashboardData(false);
                                if (typeof fetchDeliveryState === 'function') fetchDeliveryState(false);
                                completed = true;
                                break;
                            } else if (cmdStatus.status === 'ERROR') {
                                showToast('O robô local reportou erro: ' + (cmdStatus.message || 'Falha na sincronização.'), 'danger');
                                completed = true;
                                break;
                            }
                        }
                    } catch (pollErr) {
                        console.warn('[POLL WARN]', pollErr);
                    }
                }
            }

            if (!completed) {
                showToast('Comando em processamento pelo robô local. Os dados serão atualizados em instantes via Realtime!', 'info');
                fetchDashboardData(false);
                if (typeof fetchDeliveryState === 'function') fetchDeliveryState(false);
            }
        } else if (result.status === 'warning') {
            showToast(result.message, 'danger');
        } else {
            showToast(`Erro na sincronização: ${result.message}`, 'danger');
        }
    } catch (err) {
        showToast(`Falha ao conectar com o robô de atualização: ${err.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="refresh-cw" id="liveCaptureIcon"></i> <span>Atualizar / Sincronizar</span>`;
        }
        initIcons();
    }
}

async function captureTRBOnetLive() {
    return syncUnifiedLive();
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
        if (supabaseClient && realtimeSyncChannel) {
            try {
                supabaseClient.removeChannel(realtimeSyncChannel);
            } catch (ignore) {}
            realtimeSyncChannel = null;
        }

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
                { event: 'INSERT', schema: 'public', table: 'operational_snapshots' },
                (payload) => {
                    console.log('[REALTIME WS] Novo operational_snapshot gravado no Supabase!', payload);
                    fetchDashboardData(false);
                    updateHubCard();
                    showRealtimeIndicator('Snapshot Operacional Atualizado ao Vivo');
                }
            )
            .on(
                'postgres_changes',
                { event: 'INSERT', schema: 'public', table: 'team_delivery_sessions' },
                (payload) => {
                    console.log('[REALTIME WS] Nova coleta Enel SP gravada no Supabase!', payload);
                    loadDeliveryData(false);
                    updateDeliveryHubCard();
                    const scrOnlineBid = document.getElementById('deliveryScreenOnlineBid');
                    if (scrOnlineBid && scrOnlineBid.style.display !== 'none') {
                        loadOnlineXBidData();
                    }
                    showRealtimeIndicator('Entrega de Equipes Atualizada ao Vivo');
                }
            )
            .on(
                'postgres_changes',
                { event: '*', schema: 'public', table: 'bid_visao_operacional_records' },
                (payload) => {
                    console.log('[REALTIME WS] Atualização na Visão Operacional BidTech (Checklist)!', payload);
                    // Atualiza em tempo real a tela de Reconciliação ONLINE x BID
                    const scrOnlineBid = document.getElementById('deliveryScreenOnlineBid');
                    if (scrOnlineBid && scrOnlineBid.style.display !== 'none') {
                        loadOnlineXBidData();
                    }
                    // Atualiza também os badges do checklist dentro da Entrega de Equipes ao vivo
                    if (appState.currentView === 'delivery') {
                        loadDeliveryData(false);
                    }
                    showRealtimeIndicator('Checklist BidTech Atualizado ao Vivo');
                }
            )
            .on(
                'postgres_changes',
                { event: '*', schema: 'public', table: 'system_engine_health' },
                (payload) => {
                    console.log('[REALTIME WS] Estado do motor operacional atualizado:', payload);
                    const engineName = payload?.new?.engine_name || '';
                    if (engineName === 'bid_cdp_collector') {
                        const scrOnlineBid = document.getElementById('deliveryScreenOnlineBid');
                        if (scrOnlineBid && scrOnlineBid.style.display !== 'none') {
                            loadOnlineXBidData();
                        }
                        if (appState.currentView === 'delivery') {
                            loadDeliveryData(false);
                        }
                        showRealtimeIndicator('Robô BidTech Sincronizado');
                    } else if (engineName === 'enel_cdp_collector') {
                        loadDeliveryData(false);
                        showRealtimeIndicator('Robô Enel SP Sincronizado');
                    }
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

// Re-conexão automática ao restaurar do Back-Forward Cache (bfcache) do navegador
window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
        console.log('[REALTIME WS] Página restaurada do bfcache. Reconectando WebSocket...');
        setTimeout(() => {
            if (typeof initSupabaseRealtime === 'function') initSupabaseRealtime();
            if (typeof fetchDashboardData === 'function') fetchDashboardData(false);
            if (typeof loadDeliveryData === 'function') loadDeliveryData(false);
        }, 500);
    }
});

// Verificação de visibilidade da aba
document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
        if (!realtimeSyncChannel || realtimeSyncChannel.state === 'closed' || realtimeSyncChannel.state === 'errored') {
            console.log('[REALTIME WS] Aba reativada. Reconectando WebSocket...');
            if (typeof initSupabaseRealtime === 'function') initSupabaseRealtime();
        }
    }
});

// Intercepta e silencia erros externos do observador de performance/vitals do navegador no bfcache
window.addEventListener('error', (event) => {
    const msg = event?.message || '';
    if (msg.includes('startTime') || msg.includes('reportAllChanges') || msg.includes('Back-Forward Cache')) {
        console.warn('[BROWSER BFCACHE/VITALS HANDLER] Erro de telemetria externa do navegador interceptado:', msg);
        if (event.preventDefault) event.preventDefault();
        return true;
    }
});

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

    // Filtrar também por Turno se selecionado
    if (appState.selectedShifts && !appState.selectedShifts.has('ALL') && appState.selectedShifts.size > 0) {
        targetTeams = targetTeams.filter(t => matchTurno(t, appState.selectedShifts));
    }

    // Filtrar também por Frota se selecionada
    if (appState.selectedFrotas && !appState.selectedFrotas.has('ALL') && appState.selectedFrotas.size > 0) {
        targetTeams = targetTeams.filter(t => matchFrota(t, appState.selectedFrotas));
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
            scopeText.textContent = `Todas as 7 Bases Alpitel (Visão Global • ${targetTeams.length} equipes monitoradas)`;
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
// RENDERIZAÇÃO DAS 7 BASES OPERACIONAIS ALPITEL POR REGIÃO
// ==========================================================================
function renderRegionalBases() {
    const northAlpitelGrid = document.getElementById('northAlpitelBasesGrid');
    const eastAlpitelGrid = document.getElementById('eastAlpitelBasesGrid');

    const regions = appState.regions || {};
    const northAlpitelBases = regions.NORTE_ALPITEL ? regions.NORTE_ALPITEL.bases : [];
    const eastAlpitelBases = regions.LESTE_ALPITEL ? regions.LESTE_ALPITEL.bases : [];

    if (northAlpitelGrid) northAlpitelGrid.innerHTML = northAlpitelBases.map(b => createBaseCardHTML(b)).join('');
    if (eastAlpitelGrid) eastAlpitelGrid.innerHTML = eastAlpitelBases.map(b => createBaseCardHTML(b)).join('');

    initIcons();
}

function createBaseCardHTML(b) {
    const isAll = appState.selectedBases.has('ALL') || appState.selectedBases.size === 0;
    const isSelected = !isAll && appState.selectedBases.has(b.prefix);
    return `
        <div class="base-card-premium ${isSelected ? 'active-filter' : ''}" data-base-code="${b.prefix}" onclick="toggleBaseFilter('${b.prefix}')" title="Clique para filtrar/desfiltrar a base ${b.name} (${b.prefix})">
            <div class="base-card-top">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span class="base-code-pill">${b.prefix}</span>
                    <h5 class="base-name-title">${b.name}</h5>
                </div>
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span class="base-compliance-badge ${getComplianceBadgeClass(b.compliance_rate)}">
                        ${b.compliance_rate}%
                    </span>
                    <span class="base-filter-check" title="Base selecionada no filtro">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    </span>
                </div>
            </div>

            <div class="base-metrics-grid">
                <div class="base-metric-col">
                    <span class="metric-col-label">LOGADO</span>
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
            // Se todas as bases da região já estavam marcadas, desmarca essa região
            regionBases.forEach(b => appState.selectedBases.delete(b));
            if (appState.selectedBases.size === 0) {
                appState.selectedBases.add('ALL');
            }
        } else {
            // Adiciona todas as bases da região, mantendo outras seleções (multi-filtro)
            appState.selectedBases.delete('ALL');
            regionBases.forEach(b => appState.selectedBases.add(b));
        }
    }

    syncBaseUI();
    updateKPIs();
    updateFilterBadges();
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
    updateFilterBadges();
    renderResults();
}

function setBaseFilter(baseCode, element) {
    toggleBaseFilter(baseCode);
}

function syncBaseUI() {
    const isAll = appState.selectedBases.has('ALL') || appState.selectedBases.size === 0;

    const northBases = REGION_CONFIG.NORTE_ALPITEL ? REGION_CONFIG.NORTE_ALPITEL.bases : ['ENL', 'ECL', 'EEL'];
    const eastBases = REGION_CONFIG.LESTE_ALPITEL ? REGION_CONFIG.LESTE_ALPITEL.bases : ['EML', 'EQL', 'EVL', 'ESL'];

    const northAll = northBases.every(b => appState.selectedBases.has(b));
    const northSome = northBases.some(b => appState.selectedBases.has(b));
    const eastAll = eastBases.every(b => appState.selectedBases.has(b));
    const eastSome = eastBases.some(b => appState.selectedBases.has(b));

    // 1. Sincronizar Chips de Região (Barra de Filtros)
    const regionChips = document.querySelectorAll('#regionFiltersContainer .chip-filter');
    regionChips.forEach(chip => {
        const reg = chip.getAttribute('data-region');
        if (reg === 'ALL') chip.classList.toggle('active', isAll);
        if (reg === 'NORTE_ALPITEL') chip.classList.toggle('active', !isAll && northAll);
        if (reg === 'LESTE_ALPITEL') chip.classList.toggle('active', !isAll && eastAll);
    });

    // 2. Sincronizar Botões Rápidos de Região (Barra de KPIs)
    const quickRegBtns = document.querySelectorAll('.kpi-quick-regions .btn-quick-region');
    quickRegBtns.forEach(btn => {
        const reg = btn.getAttribute('data-region');
        if (reg === 'ALL') btn.classList.toggle('active', isAll);
        if (reg === 'NORTE_ALPITEL') btn.classList.toggle('active', !isAll && northAll);
        if (reg === 'LESTE_ALPITEL') btn.classList.toggle('active', !isAll && eastAll);
    });

    // 3. Atualizar Texto do Escopo dos KPIs
    const scopeText = document.getElementById('kpiScopeText');
    if (scopeText) {
        if (isAll) {
            scopeText.textContent = 'Todas as 7 Bases Alpitel (Visão Global Consolidada)';
        } else {
            const activeRegs = [];
            if (northAll) activeRegs.push('Norte Alpitel');
            else if (northSome) {
                const sel = northBases.filter(b => appState.selectedBases.has(b));
                activeRegs.push(`Norte (${sel.join(', ')})`);
            }

            if (eastAll) activeRegs.push('Leste Alpitel');
            else if (eastSome) {
                const sel = eastBases.filter(b => appState.selectedBases.has(b));
                activeRegs.push(`Leste (${sel.join(', ')})`);
            }

            if (activeRegs.length > 0) {
                scopeText.textContent = `Escopo: ${activeRegs.join(' + ')}`;
            } else {
                scopeText.textContent = `Bases Ativas: ${Array.from(appState.selectedBases).join(', ')}`;
            }
        }
    }

    // 4. Sincronizar Chips de Base
    const baseChips = document.querySelectorAll('#baseFiltersContainer .chip-filter');
    baseChips.forEach(chip => {
        const code = chip.getAttribute('data-base');
        if (code === 'ALL') {
            chip.classList.toggle('active', isAll);
        } else {
            chip.classList.toggle('active', !isAll && appState.selectedBases.has(code));
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

    if (blockNorthAlpitel) {
        blockNorthAlpitel.classList.toggle('active-region', !isAll && northAll);
        blockNorthAlpitel.classList.toggle('has-active-bases', !isAll && northSome && !northAll);
    }
    if (blockEastAlpitel) {
        blockEastAlpitel.classList.toggle('active-region', !isAll && eastAll);
        blockEastAlpitel.classList.toggle('has-active-bases', !isAll && eastSome && !eastAll);
    }

    // Badges de contagem dos blocos
    const northBadge = document.getElementById('northAlpitelBasesCountBadge');
    if (northBadge) {
        if (!isAll && northAll) {
            northBadge.textContent = '✓ 3 Bases Ativas';
            northBadge.style.color = '#10b981';
            northBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        } else if (!isAll && northSome) {
            const count = northBases.filter(b => appState.selectedBases.has(b)).length;
            northBadge.textContent = `${count}/3 Bases`;
            northBadge.style.color = '#38bdf8';
            northBadge.style.borderColor = 'rgba(56, 189, 248, 0.4)';
        } else {
            northBadge.textContent = '3 Bases';
            northBadge.style.color = '';
            northBadge.style.borderColor = '';
        }
    }

    const eastBadge = document.getElementById('eastAlpitelBasesCountBadge');
    if (eastBadge) {
        if (!isAll && eastAll) {
            eastBadge.textContent = '✓ 4 Bases Ativas';
            eastBadge.style.color = '#3b82f6';
            eastBadge.style.borderColor = 'rgba(59, 130, 246, 0.4)';
        } else if (!isAll && eastSome) {
            const count = eastBases.filter(b => appState.selectedBases.has(b)).length;
            eastBadge.textContent = `${count}/4 Bases`;
            eastBadge.style.color = '#38bdf8';
            eastBadge.style.borderColor = 'rgba(56, 189, 248, 0.4)';
        } else {
            eastBadge.textContent = '4 Bases';
            eastBadge.style.color = '';
            eastBadge.style.borderColor = '';
        }
    }
}

function toggleStatusFilter(statusCode, element) {
    if (!appState.selectedStatuses) {
        appState.selectedStatuses = new Set(['ALL']);
    }

    if (statusCode === 'ALL') {
        appState.selectedStatuses.clear();
        appState.selectedStatuses.add('ALL');
    } else {
        appState.selectedStatuses.delete('ALL');
        if (appState.selectedStatuses.has(statusCode)) {
            appState.selectedStatuses.delete(statusCode);
            if (appState.selectedStatuses.size === 0) {
                appState.selectedStatuses.add('ALL');
            }
        } else {
            appState.selectedStatuses.add(statusCode);
        }
    }

    if (appState.selectedStatuses.has('ALL') || appState.selectedStatuses.size === 0) {
        appState.currentStatusFilter = 'ALL';
    } else if (appState.selectedStatuses.size === 1) {
        appState.currentStatusFilter = Array.from(appState.selectedStatuses)[0];
    } else {
        appState.currentStatusFilter = 'MULTI';
    }

    syncStatusUI();
    renderResults();
}

function setStatusFilter(statusCode, element) {
    toggleStatusFilter(statusCode, element);
}

function syncStatusUI() {
    const isAll = !appState.selectedStatuses || appState.selectedStatuses.has('ALL') || appState.selectedStatuses.size === 0;

    const chips = document.querySelectorAll('#statusFiltersContainer .chip-filter, .filter-cluster .chip-filter[data-status]');
    chips.forEach(chip => {
        const st = chip.getAttribute('data-status');
        if (st === 'ALL') {
            chip.classList.toggle('active', isAll);
        } else {
            chip.classList.toggle('active', !isAll && appState.selectedStatuses.has(st));
        }
    });

    const kpiPowerOn = document.getElementById('kpiCardPowerOn');
    const kpiOnline = document.getElementById('kpiCardOnline');
    const kpiOffline = document.getElementById('cardOfflineAlert');
    const kpiTrboOnly = document.getElementById('kpiCardTrboOnly');

    if (kpiPowerOn) kpiPowerOn.classList.toggle('kpi-selected-filter', isAll);
    if (kpiOnline) kpiOnline.classList.toggle('kpi-selected-filter', !isAll && appState.selectedStatuses && appState.selectedStatuses.has('ONLINE'));
    if (kpiOffline) kpiOffline.classList.toggle('kpi-selected-filter', !isAll && appState.selectedStatuses && appState.selectedStatuses.has('OFFLINE'));
    if (kpiTrboOnly) kpiTrboOnly.classList.toggle('kpi-selected-filter', !isAll && appState.selectedStatuses && appState.selectedStatuses.has('TRBO_ONLY'));
}

// ==========================================================================
// FILTROS MULTI-SELECT DE TURNO E FROTA
// ==========================================================================
function matchTurno(team, selectedShifts) {
    if (!selectedShifts || selectedShifts.has('ALL') || selectedShifts.size === 0) return true;
    const sRaw = `${team.shift_slot || ''} ${team.shift_code || ''} ${team.turno || ''}`.toUpperCase();

    for (const s of selectedShifts) {
        if (s === 'OUTROS') {
            const isKnown = ['06:00', '08:00', '12:00', '14:00', '20:00', '22:00'].some(k => sRaw.includes(k));
            if (!isKnown) return true;
        } else if (sRaw.includes(s)) {
            return true;
        }
    }
    return false;
}

function matchFrota(team, selectedFrotas) {
    if (!selectedFrotas || selectedFrotas.has('ALL') || selectedFrotas.size === 0) return true;
    const vRaw = `${team.vehicle_type || ''} ${team.unified_group || ''} ${team.tipo || ''}`.toLowerCase();

    for (const f of selectedFrotas) {
        if (f === 'CESTO' && vRaw.includes('cesto')) return true;
        if (f === 'LEVE' && (vRaw.includes('leve') || vRaw.includes('veículo leve') || vRaw.includes('veiculo leve'))) return true;
        if (f === 'MOTO' && vRaw.includes('moto')) return true;
        if (f === 'LINHA_VIVA' && vRaw.includes('linha viva')) return true;
        if (f === 'MUNCK' && (vRaw.includes('munck') || vRaw.includes('munk'))) return true;
        if (f === 'OUTROS') {
            const isKnown = vRaw.includes('cesto') || vRaw.includes('leve') || vRaw.includes('moto') || vRaw.includes('linha viva') || vRaw.includes('munck') || vRaw.includes('munk');
            if (!isKnown) return true;
        }
    }
    return false;
}

function toggleTurnoFilter(shiftCode, element) {
    if (!appState.selectedShifts) {
        appState.selectedShifts = new Set(['ALL']);
    }

    if (shiftCode === 'ALL') {
        appState.selectedShifts.clear();
        appState.selectedShifts.add('ALL');
    } else {
        appState.selectedShifts.delete('ALL');
        if (appState.selectedShifts.has(shiftCode)) {
            appState.selectedShifts.delete(shiftCode);
            if (appState.selectedShifts.size === 0) {
                appState.selectedShifts.add('ALL');
            }
        } else {
            appState.selectedShifts.add(shiftCode);
        }
    }

    syncTurnoUI();
    updateKPIs();
    updateFilterBadges();
    renderResults();
}

function toggleFrotaFilter(frotaCode, element) {
    if (!appState.selectedFrotas) {
        appState.selectedFrotas = new Set(['ALL']);
    }

    if (frotaCode === 'ALL') {
        appState.selectedFrotas.clear();
        appState.selectedFrotas.add('ALL');
    } else {
        appState.selectedFrotas.delete('ALL');
        if (appState.selectedFrotas.has(frotaCode)) {
            appState.selectedFrotas.delete(frotaCode);
            if (appState.selectedFrotas.size === 0) {
                appState.selectedFrotas.add('ALL');
            }
        } else {
            appState.selectedFrotas.add(frotaCode);
        }
    }

    syncFrotaUI();
    updateKPIs();
    updateFilterBadges();
    renderResults();
}

function syncTurnoUI() {
    const isAll = !appState.selectedShifts || appState.selectedShifts.has('ALL') || appState.selectedShifts.size === 0;
    const chips = document.querySelectorAll('#shiftFiltersContainer .chip-filter');
    chips.forEach(chip => {
        const s = chip.getAttribute('data-shift');
        if (s === 'ALL') {
            chip.classList.toggle('active', isAll);
        } else {
            chip.classList.toggle('active', !isAll && appState.selectedShifts.has(s));
        }
    });
}

function syncFrotaUI() {
    const isAll = !appState.selectedFrotas || appState.selectedFrotas.has('ALL') || appState.selectedFrotas.size === 0;
    const chips = document.querySelectorAll('#frotaFiltersContainer .chip-filter');
    chips.forEach(chip => {
        const f = chip.getAttribute('data-frota');
        if (f === 'ALL') {
            chip.classList.toggle('active', isAll);
        } else {
            chip.classList.toggle('active', !isAll && appState.selectedFrotas.has(f));
        }
    });
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
    
    if (!appState.selectedStatuses) {
        appState.selectedStatuses = new Set(['ALL']);
    } else {
        appState.selectedStatuses.clear();
        appState.selectedStatuses.add('ALL');
    }

    if (!appState.selectedShifts) {
        appState.selectedShifts = new Set(['ALL']);
    } else {
        appState.selectedShifts.clear();
        appState.selectedShifts.add('ALL');
    }

    if (!appState.selectedFrotas) {
        appState.selectedFrotas = new Set(['ALL']);
    } else {
        appState.selectedFrotas.clear();
        appState.selectedFrotas.add('ALL');
    }

    appState.currentStatusFilter = 'ALL';
    appState.searchQuery = '';
    
    const input = document.getElementById('searchInput');
    if (input) input.value = '';
    
    const btnClear = document.getElementById('btnClearSearch');
    if (btnClear) btnClear.style.display = 'none';

    syncBaseUI();
    syncStatusUI();
    syncTurnoUI();
    syncFrotaUI();
    updateKPIs();
    updateFilterBadges();
    renderResults();
    showToast('Filtros redefinidos para o estado padrão.', 'info');
}

// ==========================================================================
// RENDERIZAÇÃO DOS RESULTADOS (TABELA & CARDS)
// ==========================================================================
function getFilteredTeams() {
    let filtered = [...appState.teams];

    // Filtro por Multi-seleção de Bases / Regiões
    const isAllBases = appState.selectedBases.has('ALL') || appState.selectedBases.size === 0;
    if (!isAllBases) {
        filtered = filtered.filter(t => {
            if (appState.selectedBases.has(t.prefix)) return true;
            if (appState.selectedBases.has('OUTRAS') && t.is_other_base) return true;
            return false;
        });
    }

    // Filtro por Multi-seleção de Turno
    if (appState.selectedShifts && !appState.selectedShifts.has('ALL') && appState.selectedShifts.size > 0) {
        filtered = filtered.filter(t => matchTurno(t, appState.selectedShifts));
    }

    // Filtro por Multi-seleção de Frota
    if (appState.selectedFrotas && !appState.selectedFrotas.has('ALL') && appState.selectedFrotas.size > 0) {
        filtered = filtered.filter(t => matchFrota(t, appState.selectedFrotas));
    }

    // Filtro por Multi-seleção de Status
    const isAllStatus = !appState.selectedStatuses || appState.selectedStatuses.has('ALL') || appState.selectedStatuses.size === 0;
    if (!isAllStatus) {
        filtered = filtered.filter(t => {
            if (appState.selectedStatuses.has('ONLINE') && t.trbonet) return true;
            if (appState.selectedStatuses.has('OFFLINE') && t.status_code === 'OFFLINE') return true;
            if (appState.selectedStatuses.has('TRBO_ONLY') && t.status_code === 'TRBO_ONLY') return true;
            if (appState.selectedStatuses.has('GPS_ONLY') && t.gps) return true;
            return false;
        });
    }

    // Filtro por Texto de Busca
    if (appState.searchQuery) {
        const q = appState.searchQuery;
        filtered = filtered.filter(t => 
            t.code.toUpperCase().includes(q) ||
            t.base.toUpperCase().includes(q) ||
            (t.vehicle_type && t.vehicle_type.toUpperCase().includes(q)) ||
            (t.shift_slot && t.shift_slot.toUpperCase().includes(q)) ||
            (t.driver && t.driver.toUpperCase().includes(q)) ||
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
    appState.filteredTeams = filteredTeams;

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

        const shiftDisplay = t.shift_slot || t.shift_code || '--';
        const frotaDisplay = t.vehicle_type || '--';

        return `
            <tr>
                <td>
                    <div class="team-code-cell">
                        <strong class="team-code-text">${t.code}</strong>
                        <div style="display: flex; gap: 4px; font-size: 0.72rem; color: var(--text-muted); align-items: center; margin-top: 3px; flex-wrap: wrap;">
                            <span style="background: rgba(255,255,255,0.06); padding: 1px 6px; border-radius: 4px; font-weight: 600; color: #e2e8f0;">${frotaDisplay}</span>
                            <span>•</span>
                            <span style="background: rgba(56, 189, 248, 0.12); color: #38bdf8; padding: 1px 6px; border-radius: 4px; font-weight: 600;">${shiftDisplay}</span>
                        </div>
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
                        <span class="card-row-label"><i data-lucide="truck" class="mini-icon"></i> Frota</span>
                        <span class="card-row-val">${t.vehicle_type || '--'}</span>
                    </div>
                    <div class="team-card-row">
                        <span class="card-row-label"><i data-lucide="clock" class="mini-icon"></i> Turno</span>
                        <span class="card-row-val text-sky">${t.shift_slot || t.shift_code || '--'}</span>
                    </div>
                    <div class="team-card-row">
                        <span class="card-row-label"><i data-lucide="clipboard-check" class="mini-icon"></i> Equipes Brasil</span>
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
    let target = [...appState.teams];
    const isAll = appState.selectedBases.has('ALL') || appState.selectedBases.size === 0;
    if (!isAll) {
        target = target.filter(t => appState.selectedBases.has(t.prefix));
    }
    if (appState.selectedShifts && !appState.selectedShifts.has('ALL') && appState.selectedShifts.size > 0) {
        target = target.filter(t => matchTurno(t, appState.selectedShifts));
    }
    if (appState.selectedFrotas && !appState.selectedFrotas.has('ALL') && appState.selectedFrotas.size > 0) {
        target = target.filter(t => matchFrota(t, appState.selectedFrotas));
    }
    const allEl = document.getElementById('count-all');
    const onlineEl = document.getElementById('count-online');
    const offlineEl = document.getElementById('count-offline');
    const trboEl = document.getElementById('count-trbo-only');
    const gpsEl = document.getElementById('count-gps');

    if (allEl) allEl.textContent = target.length;
    if (onlineEl) onlineEl.textContent = target.filter(t => t.trbonet).length;
    if (offlineEl) offlineEl.textContent = target.filter(t => t.status_code === 'OFFLINE').length;
    if (trboEl) trboEl.textContent = target.filter(t => t.status_code === 'TRBO_ONLY').length;
    if (gpsEl) gpsEl.textContent = target.filter(t => t.gps).length;
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
                        label: 'Escala Equipes Brasil',
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
    if (baseEl) baseEl.textContent = `${team.base} • ${team.region} • ${team.vehicle_type || 'Frota --'} • ${team.shift_slot || 'Turno --'}`;

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
            rec.textContent = 'Verificar se a equipe está prestando serviço extra ou se esqueceu de efetuar o login de início de turno no Equipes Brasil.';
        } else {
            rec.textContent = 'Operação em perfeita conformidade. Nenhuma intervenção necessária.';
        }
    }

    openModal('teamDetailModal');
    initIcons();
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'flex';
        void modal.offsetWidth;
        modal.classList.add('active');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        setTimeout(() => {
            if (!modal.classList.contains('active')) {
                modal.style.display = '';
            }
        }, 250);
    }
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
function toggleExportMenu(e) {
    if (e) {
        if (e.stopPropagation) e.stopPropagation();
        if (e.preventDefault) e.preventDefault();
    }
    const menu = document.getElementById('exportMenu');
    if (menu) {
        menu.classList.toggle('active');
        menu.classList.toggle('show');
    }
}

window.toggleExportMenu = toggleExportMenu;

function exportLiveTeamsExcel() {
    // 1. Obtém estritamente as equipes filtradas no momento
    let teams = [];
    if (typeof getFilteredTeams === 'function') {
        teams = getFilteredTeams();
    } else if (appState && appState.filteredTeams && appState.filteredTeams.length > 0) {
        teams = appState.filteredTeams;
    } else if (appState && appState.teams) {
        teams = appState.teams;
    }
    
    if (!teams || teams.length === 0) {
        showToast('Nenhuma equipe encontrada com os filtros selecionados para exportar.', 'warning');
        const exportMenu = document.getElementById('exportMenu');
        if (exportMenu) {
            exportMenu.classList.remove('active');
            exportMenu.classList.remove('show');
        }
        return;
    }

    const timestamp = new Date().toISOString().replace(/[-:T]/g, '_').slice(0, 15);
    const filename = `Alertas_Operacionais_TRBOnet_Filtrado_${timestamp}.xlsx`;

    // 2. Geração client-side direta via SheetJS (.xlsx)
    if (window.XLSX) {
        try {
            const summary = appState.summary || {};
            const lastPwLogin = summary.last_poweron_login || '--';
            const lastTrboSync = summary.last_trbonet_sync || '--';

            const rows = teams.map(t => ({
                "Código Equipe": t.code || '',
                "Base Operacional": t.base || '',
                "Sigla Base": t.prefix || '',
                "Região": t.region || '',
                "Turno": t.shift_slot || t.shift_code || '--',
                "Frota": t.vehicle_type || '--',
                "Status de Conformidade": t.status_label || t.status_code || '',
                "Escala Equipes Brasil": t.poweron ? 'SIM (ESCALADA)' : 'NÃO (FORA DA ESCALA)',
                "Conexão TRBOnet": t.trbonet ? 'ONLINE (CONECTADO)' : 'DESCONECTADO',
                "Sinal GPS": t.gps ? 'COM SINAL GPS' : 'SEM SINAL GPS',
                "ID do Rádio": t.radio_id || '--',
                "Canal TRBOnet": t.channel || '--',
                "Último Sinal Registrado": t.last_signal || lastTrboSync || '--',
                "Horário Login": t.login_time || lastPwLogin || '--',
                "Motorista": t.driver || '--',
                "Placa": t.plate || '--',
                "Diagnóstico CCO": t.details_text || ''
            }));

            const ws = XLSX.utils.json_to_sheet(rows);
            const wb = XLSX.utils.book_new();
            XLSX.utils.book_append_sheet(wb, ws, "Equipes_Filtradas");
            XLSX.writeFile(wb, filename);

            const exportMenu = document.getElementById('exportMenu');
            if (exportMenu) {
                exportMenu.classList.remove('active');
                exportMenu.classList.remove('show');
            }

            showToast(`Planilha Excel (.xlsx) exportada com sucesso (${teams.length} equipes filtradas)!`, 'success');
            return;
        } catch (err) {
            console.warn('Falha na exportação client-side via SheetJS, tentando fallback backend:', err);
        }
    }

    // 3. Fallback via rota backend
    const exportMenu = document.getElementById('exportMenu');
    if (exportMenu) {
        exportMenu.classList.remove('active');
        exportMenu.classList.remove('show');
    }
    const isAll = appState.teams && teams.length === appState.teams.length;
    const url = isAll ? '/api/export/excel' : `/api/export/excel?teams=${encodeURIComponent(teams.map(t => t.code).join(','))}`;
    window.location.href = url;
    showToast(`Download da Planilha Excel (.xlsx) iniciado (${teams.length} equipes filtradas)!`, 'success');
}

window.exportLiveTeamsExcel = exportLiveTeamsExcel;

function exportLiveTeamsCSV() {
    const teams = (typeof getFilteredTeams === 'function') ? getFilteredTeams() : (appState.filteredTeams || appState.teams || []);
    if (!teams || teams.length === 0) {
        showToast('Nenhum dado operacional disponível para exportação no momento.', 'warning');
        const exportMenu = document.getElementById('exportMenu');
        if (exportMenu) exportMenu.classList.remove('active');
        return;
    }

    const summary = appState.summary || {};
    const lastPwLogin = summary.last_poweron_login || '--';
    const lastTrboSync = summary.last_trbonet_sync || '--';

    let csv = '\uFEFF'; // UTF-8 BOM para o Microsoft Excel abrir com acentuação perfeita
    csv += 'Equipe;Base;Prefixo;Regiao;Turno;Frota;Status_Operacional;Categoria;Escala_PowerON;Conexao_TRBOnet;Sinal_GPS;Radio_ID;Canal;Ultimo_Sinal_TRBOnet;Ultimo_Login_PowerON;Motorista;Placa;Diagnostico_CCO\n';

    teams.forEach(t => {
        const code = (t.code || '').replace(/"/g, '""');
        const base = (t.base || '').replace(/"/g, '""');
        const prefix = (t.prefix || '').replace(/"/g, '""');
        const region = (t.region || '').replace(/"/g, '""');
        const turno = (t.shift_slot || t.shift_code || '--').replace(/"/g, '""');
        const frota = (t.vehicle_type || '--').replace(/"/g, '""');
        const statusLabel = (t.status_label || t.status_code || '').replace(/"/g, '""');
        const category = (t.status_category || '').replace(/"/g, '""');
        const poweron = t.poweron ? 'SIM (ESCALADA)' : 'NAO (FORA DA ESCALA)';
        const trbonet = t.trbonet ? 'SIM (CONECTADO)' : 'NAO (DESCONECTADO)';
        const gps = t.gps ? 'SIM (COM GPS)' : 'NAO (SEM GPS)';
        const radioId = (t.radio_id || '--').replace(/"/g, '""');
        const channel = (t.channel || '--').replace(/"/g, '""');
        const lastSignal = (t.last_signal || lastTrboSync || '--').replace(/"/g, '""');
        const lastLogin = (t.login_time || lastPwLogin || '--').replace(/"/g, '""');
        const driver = (t.driver || '--').replace(/"/g, '""');
        const plate = (t.plate || '--').replace(/"/g, '""');
        const details = (t.details_text || '').replace(/"/g, '""');

        csv += `"${code}";"${base}";"${prefix}";"${region}";"${turno}";"${frota}";"${statusLabel}";"${category}";"${poweron}";"${trbonet}";"${gps}";"${radioId}";"${channel}";"${lastSignal}";"${lastLogin}";"${driver}";"${plate}";"${details}"\n`;
    });

    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().replace(/[-:T]/g, '_').slice(0, 15);
    link.setAttribute('href', url);
    link.setAttribute('download', `Alertas_Operacionais_TRBOnet_Filtrado_${timestamp}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    const exportMenu = document.getElementById('exportMenu');
    if (exportMenu) exportMenu.classList.remove('active');

    showToast(`Arquivo CSV exportado com sucesso (${teams.length} equipes filtradas)!`, 'success');
}

window.exportLiveTeamsCSV = exportLiveTeamsCSV;

document.addEventListener('click', (e) => {
    const exportBtn = document.getElementById('btnExport');
    const exportToggle = document.getElementById('btnExportMenuToggle');
    const exportMenu = document.getElementById('exportMenu');
    if (exportMenu && (!exportBtn || !exportBtn.contains(e.target)) && (!exportToggle || !exportToggle.contains(e.target)) && !exportMenu.contains(e.target)) {
        exportMenu.classList.remove('active');
        exportMenu.classList.remove('show');
    }
});

function copySummaryToClipboard() {
    const s = appState.summary;
    const text = `=== ALERTAS OPERACIONAIS OP (EQUIPES BRASIL × TRBONET) ===
Data: ${s.last_update}
Total Equipes Brasil: ${s.total_poweron} equipes
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
    selectedDates: [],
    datePickerInstance: null,
    filters: {
        regions: [],
        bases: [],
        statuses: [],
        connected: [],
        poweron: [],
        search: ''
    },
    searchTimer: null
};

// Dicionário oficial de nomes e regiões das bases operacionais
const AUDIT_BASE_NAMES = {
    'ENL': { name: 'Base Fagundes Filho', short: 'Fagundes Filho', region: 'Norte' },
    'ECL': { name: 'Base Cajati', short: 'Cajati', region: 'Norte' },
    'EEL': { name: 'Base Vila Medeiros', short: 'Vila Medeiros', region: 'Norte' },
    'EML': { name: 'Base Monte Santo', short: 'Monte Santo', region: 'Leste' },
    'EQL': { name: 'Base Aricanduva', short: 'Aricanduva', region: 'Leste' },
    'EVL': { name: 'Base Catumbi', short: 'Catumbi', region: 'Leste' },
    'ESL': { name: 'Base Santo André', short: 'Santo André', region: 'Leste' },
    'ENA': { name: 'Base Fagundes Filho', short: 'Fagundes Filho', region: 'Norte' },
    'ECA': { name: 'Base Cajati', short: 'Cajati', region: 'Norte' },
    'EEA': { name: 'Base Vila Medeiros', short: 'Vila Medeiros', region: 'Norte' },
    'EMA': { name: 'Base Monte Santo', short: 'Monte Santo', region: 'Leste' },
    'EQA': { name: 'Base Aricanduva', short: 'Aricanduva', region: 'Leste' },
    'EVA': { name: 'Base Catumbi', short: 'Catumbi', region: 'Leste' },
    'ESA': { name: 'Base Santo André', short: 'Santo André', region: 'Leste' }
};

function getAuditBaseInfo(code) {
    const c = (code || '').toUpperCase().trim();
    if (AUDIT_BASE_NAMES[c]) {
        return { code: c, ...AUDIT_BASE_NAMES[c] };
    }
    return { code: c || '--', name: c ? `Base ${c}` : 'Outras Bases', short: c || '--', region: 'Outras' };
}

/**
 * Inicializa o Flatpickr para seleção de múltiplas datas na Auditoria.
 */
async function initAuditDatePicker() {
    const input = document.getElementById('auditDateInput');
    if (!input || !window.flatpickr) return;
    if (auditState.datePickerInstance) return;

    // Assegura que as datas com dados gravados estejam carregadas
    if (!deliveryState.availableAuditDates || deliveryState.availableAuditDates.length === 0) {
        await reloadAuditAvailableDates();
    }

    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    auditState.selectedDates = [todayStr];

    auditState.datePickerInstance = flatpickr(input, {
        mode: "multiple",
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        conjunction: " | ",
        defaultDate: [todayStr],
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
        onDayCreate: function(dObj, dStr, fp, dayElem) {
            if (!dayElem || !dayElem.dateObj) return;
            const y = dayElem.dateObj.getFullYear();
            const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
            const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
            const ymd = `${y}-${m}-${d}`;
            if (deliveryState.availableAuditDates && deliveryState.availableAuditDates.includes(ymd)) {
                dayElem.classList.add('has-audit-data');
                dayElem.setAttribute('title', 'Dados gravados no banco de auditoria');
            }
        },
        onChange: function(selectedDates, dateStr) {
            if (selectedDates && selectedDates.length > 0) {
                auditState.selectedDates = selectedDates.map(d => {
                    const y = d.getFullYear();
                    const m = String(d.getMonth() + 1).padStart(2, '0');
                    const day = String(d.getDate()).padStart(2, '0');
                    return `${y}-${m}-${day}`;
                });
            } else {
                auditState.selectedDates = [];
            }
            loadAuditData();
        }
    });
}

function updateAuditPillLabel(filterType, totalCount, selectedCount, firstValue) {
    const labelMap = {
        'region': 'auditFilterRegionLabel',
        'base': 'auditFilterBaseLabel',
        'status': 'auditFilterStatusLabel',
        'connected': 'auditFilterConnectedLabel',
        'poweron': 'auditFilterPoweronLabel'
    };
    const el = document.getElementById(labelMap[filterType]);
    if (!el) return;

    if (selectedCount === totalCount || (selectedCount === 0 && totalCount === 0)) {
        el.textContent = 'Todos';
    } else if (selectedCount === 0) {
        el.textContent = 'Nenhum';
    } else if (selectedCount === 1) {
        let clean = (firstValue || '').replace('Região ', '').replace('Base ', '');
        el.textContent = clean || '1 sel.';
    } else {
        el.textContent = `${selectedCount} sel.`;
    }
}

function syncAuditFiltersFromDOM() {
    const getSelected = (filterType) => {
        const cbs = Array.from(document.querySelectorAll(`#tabViewAudit .popover-checkbox[data-audit-filter="${filterType}"]`));
        const checked = cbs.filter(c => c.checked).map(c => c.value);
        updateAuditPillLabel(filterType, cbs.length, checked.length, checked[0] || '');
        return checked;
    };

    auditState.filters.regions = getSelected('region');
    auditState.filters.bases = getSelected('base');
    auditState.filters.statuses = getSelected('status');
    auditState.filters.connected = getSelected('connected');
    auditState.filters.poweron = getSelected('poweron');
    auditState.filters.search = (document.getElementById('auditSearchTeam')?.value || '').trim().toUpperCase();
}

function updateAuditGroupCheckboxesState() {
    document.querySelectorAll('#tabViewAudit .popover-group-checkbox').forEach(gcb => {
        const grp = gcb.getAttribute('data-audit-group');
        const children = Array.from(document.querySelectorAll(`#tabViewAudit .popover-checkbox[data-audit-group="${grp}"]`));
        if (children.length === 0) return;
        const checkedCount = children.filter(c => c.checked).length;
        gcb.checked = (checkedCount === children.length);
        gcb.indeterminate = (checkedCount > 0 && checkedCount < children.length);
    });
}

function setupAuditFilterDropdowns() {
    // 1. Toggle de abertura/fechamento ao clicar no botão da pílula
    document.querySelectorAll('#tabViewAudit .period-filter-pill-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const targetId = btn.getAttribute('data-target');
            const targetMenu = document.getElementById(targetId);
            const isAlreadyActive = targetMenu && targetMenu.classList.contains('active');

            // Fecha outros popovers abertos na tela de auditoria
            document.querySelectorAll('#tabViewAudit .period-filter-popover').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('#tabViewAudit .period-filter-pill-btn').forEach(b => b.classList.remove('active'));

            if (!isAlreadyActive && targetMenu) {
                targetMenu.classList.add('active');
                btn.classList.add('active');
            }
        };
    });

    // 2. Ações de "Todos" e "Limpar" no cabeçalho do popover
    document.querySelectorAll('#tabViewAudit .popover-action-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const action = btn.getAttribute('data-action');
            const filterType = btn.getAttribute('data-audit-filter');
            const cbs = document.querySelectorAll(`#tabViewAudit .popover-checkbox[data-audit-filter="${filterType}"]`);

            cbs.forEach(cb => {
                cb.checked = (action === 'select-all');
            });

            if (filterType === 'base') {
                updateAuditGroupCheckboxesState();
            }

            syncAuditFiltersFromDOM();
            applyAuditFilters();
        };
    });

    // 3. Hierarquia das Bases por Grupo (Norte / Leste)
    document.querySelectorAll('#tabViewAudit .popover-group-checkbox').forEach(gcb => {
        gcb.onchange = (e) => {
            const grp = gcb.getAttribute('data-audit-group');
            const isChecked = gcb.checked;
            document.querySelectorAll(`#tabViewAudit .popover-checkbox[data-audit-group="${grp}"]`).forEach(cb => {
                cb.checked = isChecked;
            });
            syncAuditFiltersFromDOM();
            applyAuditFilters();
        };
    });

    // 4. Checkboxes individuais disparam re-filtro e sincronizam rótulos
    document.querySelectorAll('#tabViewAudit .popover-checkbox').forEach(cb => {
        cb.onchange = () => {
            updateAuditGroupCheckboxesState();
            syncAuditFiltersFromDOM();
            applyAuditFilters();
        };
    });

    // 5. Clique dentro do popover não fecha
    document.querySelectorAll('#tabViewAudit .period-filter-popover').forEach(p => {
        p.onclick = (e) => e.stopPropagation();
    });

    // 6. Clique fora fecha qualquer popover aberto
    if (!window._auditClosePopoverBound) {
        window._auditClosePopoverBound = true;
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#tabViewAudit .dropdown-popover-container')) {
                document.querySelectorAll('#tabViewAudit .period-filter-popover').forEach(p => p.classList.remove('active'));
                document.querySelectorAll('#tabViewAudit .period-filter-pill-btn').forEach(b => b.classList.remove('active'));
            }
        });
    }
}

function initAuditMultiFilters() {
    // 1. REGIÃO (Multi-seleção)
    const regList = document.getElementById('auditFilterRegionList');
    if (regList) {
        regList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="region" value="Norte" checked>
                <span>Região Norte</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="region" value="Leste" checked>
                <span>Região Leste</span>
            </label>
        `;
    }

    // 2. BASE OPERACIONAL (Hierarquia Norte / Leste com nomes amigáveis)
    const baseList = document.getElementById('auditFilterBaseList');
    if (baseList) {
        const norteBases = [
            { code: 'ENL', name: 'Base Fagundes Filho' },
            { code: 'ECL', name: 'Base Cajati' },
            { code: 'EEL', name: 'Base Vila Medeiros' }
        ];
        const lesteBases = [
            { code: 'EML', name: 'Base Monte Santo' },
            { code: 'EQL', name: 'Base Aricanduva' },
            { code: 'EVL', name: 'Base Catumbi' },
            { code: 'ESL', name: 'Base Santo André' }
        ];

        baseList.innerHTML = `
            <div class="popover-group-section">
                <label class="popover-group-header" title="Selecionar/desmarcar todas as bases da Região Norte">
                    <input type="checkbox" class="popover-group-checkbox" data-audit-group="regiao-norte" checked>
                    <span>Região Norte</span>
                </label>
                <div class="popover-group-children">
                    ${norteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-audit-filter="base" data-audit-group="regiao-norte" value="${b.code}" checked>
                            <span>${b.name} (${b.code})</span>
                        </label>
                    `).join('')}
                </div>
            </div>
            <div class="popover-group-section">
                <label class="popover-group-header" title="Selecionar/desmarcar todas as bases da Região Leste">
                    <input type="checkbox" class="popover-group-checkbox" data-audit-group="regiao-leste" checked>
                    <span>Região Leste</span>
                </label>
                <div class="popover-group-children">
                    ${lesteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-audit-filter="base" data-audit-group="regiao-leste" value="${b.code}" checked>
                            <span>${b.name} (${b.code})</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // 3. STATUS DA AUDITORIA
    const statusList = document.getElementById('auditFilterStatusList');
    if (statusList) {
        statusList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="status" value="CONFORME" checked>
                <span>Conforme (Equipes Brasil + TRBOnet)</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="status" value="APENAS_POWERON" checked>
                <span>Apenas no Equipes Brasil</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="status" value="APENAS_TRBONET" checked>
                <span>Apenas no TRBOnet</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="status" value="OFFLINE" checked>
                <span>Offline</span>
            </label>
        `;
    }

    // 4. CONECTOU HOJE?
    const connList = document.getElementById('auditFilterConnectedList');
    if (connList) {
        connList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="connected" value="SIM" checked>
                <span>Sim (Conectou Hoje)</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="connected" value="NAO" checked>
                <span>Não (Nunca Conectou)</span>
            </label>
        `;
    }

    // 5. ESCALA POWERON
    const pwList = document.getElementById('auditFilterPoweronList');
    if (pwList) {
        pwList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="poweron" value="SIM" checked>
                <span>Em Escala</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-audit-filter="poweron" value="NAO" checked>
                <span>Fora de Escala</span>
            </label>
        `;
    }

    setupAuditFilterDropdowns();
    syncAuditFiltersFromDOM();
}

function clearAuditFilters() {
    document.querySelectorAll('#tabViewAudit .popover-checkbox').forEach(cb => cb.checked = true);
    document.querySelectorAll('#tabViewAudit .popover-group-checkbox').forEach(cb => {
        cb.checked = true;
        cb.indeterminate = false;
    });
    const searchInput = document.getElementById('auditSearchTeam');
    if (searchInput) searchInput.value = '';

    syncAuditFiltersFromDOM();
    applyAuditFilters();
    showToast('Filtros de auditoria redefinidos.', 'info');
}

/**
 * Inicializa a aba de Auditoria configurando o datepicker, controles multi-select e disparando a consulta.
 */
function initAuditTab() {
    initAuditDatePicker();
    initAuditMultiFilters();
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
        if (subtitleEl) subtitleEl.textContent = 'Resumo de conexões, horários de login vs rádio e histórico por equipe';
    } else {
        if (btnDaily) btnDaily.classList.remove('active');
        if (btnLogs) btnLogs.classList.add('active');
        if (titleEl) titleEl.textContent = 'Logs Detalhados por Coleta';
        if (subtitleEl) subtitleEl.textContent = 'Histórico individual de cada transmissão de rádio/GPS registrada pelo sistema';
    }

    loadAuditData();
}

/**
 * Consulta a API local (que consulta o Supabase) para carregar os dados de auditoria com suporte a múltiplas datas.
 */
async function loadAuditData(isSilent = false) {
    const refreshIcon = document.getElementById('btnAuditRefreshIcon');
    if (refreshIcon && !isSilent) refreshIcon.classList.add('spin-animation');

    syncAuditFiltersFromDOM();

    const datesParam = (auditState.selectedDates && auditState.selectedDates.length > 0)
        ? auditState.selectedDates.join(',')
        : (new Date().toISOString().split('T')[0]);

    const basesParam = (auditState.filters.bases && auditState.filters.bases.length > 0 && auditState.filters.bases.length < 7)
        ? auditState.filters.bases.join(',')
        : 'ALL';

    const teamVal = auditState.filters.search || '';

    try {
        let endpoint = '';
        if (auditState.mode === 'daily') {
            const params = new URLSearchParams();
            if (datesParam) params.append('date', datesParam);
            if (basesParam && basesParam !== 'ALL') params.append('base', basesParam);
            endpoint = `/api/audit/daily_summary?${params.toString()}`;
        } else {
            const params = new URLSearchParams();
            if (datesParam) params.append('date', datesParam);
            if (basesParam && basesParam !== 'ALL') params.append('base', basesParam);
            if (teamVal) params.append('team', teamVal);
            params.append('limit', '400');
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
 * Aplica os filtros combinados de Região, Base, Status, Conectou Hoje, Escala PowerON e Busca.
 */
function applyAuditFilters() {
    const { regions, bases, statuses, connected, poweron, search } = auditState.filters;

    let filtered = [...auditState.rawData];

    // 1. Filtro por Busca Textual
    if (search) {
        filtered = filtered.filter(item => {
            const team = (item.team_code || '').toUpperCase();
            const bCode = (item.base_code || '').toUpperCase();
            const baseInfo = getAuditBaseInfo(bCode);
            return team.includes(search) || bCode.includes(search) || baseInfo.name.toUpperCase().includes(search);
        });
    }

    // 2. Filtro por Região
    if (regions && regions.length > 0 && regions.length < 2) {
        filtered = filtered.filter(item => {
            const baseInfo = getAuditBaseInfo(item.base_code);
            const regItem = (item.region || '').toLowerCase();
            const regBase = (baseInfo.region || '').toLowerCase();
            return regions.some(r => {
                const rLow = r.toLowerCase();
                return regItem.includes(rLow) || regBase.includes(rLow);
            });
        });
    } else if (regions && regions.length === 0) {
        filtered = [];
    }

    // 3. Filtro por Base Operacional
    if (bases && bases.length >= 0) {
        if (bases.length === 0) {
            filtered = [];
        } else if (bases.length < 7) {
            const selectedSet = new Set(bases.map(b => b.toUpperCase()));
            filtered = filtered.filter(item => {
                const b = (item.base_code || '').toUpperCase();
                return selectedSet.has(b);
            });
        }
    }

    // 4. Filtros exclusivos do modo 'daily'
    if (auditState.mode === 'daily') {
        // Status geral
        if (statuses && statuses.length > 0 && statuses.length < 4) {
            const statusSet = new Set(statuses);
            filtered = filtered.filter(item => {
                const wasPw = !!item.was_in_poweron;
                const wasOn = !!item.was_online_trbonet;

                let st = 'OFFLINE';
                if (wasPw && wasOn) st = 'CONFORME';
                else if (wasPw && !wasOn) st = 'APENAS_POWERON';
                else if (!wasPw && wasOn) st = 'APENAS_TRBONET';

                return statusSet.has(st);
            });
        } else if (statuses && statuses.length === 0) {
            filtered = [];
        }

        // Conectou Hoje?
        if (connected && connected.length === 1) {
            const wantOnline = (connected[0] === 'SIM');
            filtered = filtered.filter(item => wantOnline ? !!item.was_online_trbonet : !item.was_online_trbonet);
        } else if (connected && connected.length === 0) {
            filtered = [];
        }

        // Escala PowerON
        if (poweron && poweron.length === 1) {
            const wantPoweron = (poweron[0] === 'SIM');
            filtered = filtered.filter(item => wantPoweron ? !!item.was_in_poweron : !item.was_in_poweron);
        } else if (poweron && poweron.length === 0) {
            filtered = [];
        }
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
 * Calcula o delta e diagnóstico de confronto entre a Marcação no Equipes Brasil e o 1º Sinal no TRBOnet.
 */
function computeAuditConfront(marcacaoStr, firstSeenStr) {
    if (!marcacaoStr || marcacaoStr === '--') {
        if (firstSeenStr && firstSeenStr !== '--') {
            return {
                badge: '<span class="audit-confront-badge badge-sync-nologin" title="Rádio transmitiu sinal, mas não há registro de login no Equipes Brasil"><i data-lucide="help-circle" style="width:12px;height:12px;"></i> Rádio s/ Login</span>',
                deltaText: 'Rádio s/ Login'
            };
        }
        return {
            badge: '<span class="audit-confront-badge badge-sync-nologin">--</span>',
            deltaText: '--'
        };
    }

    if (!firstSeenStr || firstSeenStr === '--') {
        return {
            badge: '<span class="audit-confront-badge badge-sync-noradio" title="Equipe tem login ativo no aplicativo, porém o rádio não transmitiu sinal no dia"><i data-lucide="alert-octagon" style="width:12px;height:12px;"></i> Sem Sinal Rádio</span>',
            deltaText: 'Sem Sinal Rádio'
        };
    }

    // Ambos os horários existem! Calcular delta em minutos
    try {
        const parseMinutes = (timeStr) => {
            const clean = timeStr.trim();
            const parts = clean.split(':');
            const h = parseInt(parts[0], 10) || 0;
            const m = parseInt(parts[1], 10) || 0;
            return h * 60 + m;
        };

        const mMin = parseMinutes(marcacaoStr);
        const fMin = parseMinutes(firstSeenStr);
        const diff = fMin - mMin; // Positivo: rádio após login; Negativo: rádio antes do login

        if (Math.abs(diff) <= 15) {
            const diffSignal = diff >= 0 ? `+${diff}` : `${diff}`;
            return {
                badge: `<span class="audit-confront-badge badge-sync-ok" title="Diferença de ${diffSignal} min entre login e rádio"><i data-lucide="check-circle-2" style="width:12px;height:12px;"></i> Sincronizado (${diffSignal}m)</span>`,
                deltaText: `${diffSignal}m`
            };
        } else if (diff > 15) {
            return {
                badge: `<span class="audit-confront-badge badge-sync-delay" title="Rádio transmitiu ${diff} min após a marcação"><i data-lucide="clock" style="width:12px;height:12px;"></i> Atraso +${diff}m</span>`,
                deltaText: `+${diff}m`
            };
        } else {
            return {
                badge: `<span class="audit-confront-badge badge-sync-early" title="Rádio transmitiu ${Math.abs(diff)} min antes do login no app"><i data-lucide="zap" style="width:12px;height:12px;"></i> Antecipado ${diff}m</span>`,
                deltaText: `${diff}m`
            };
        }
    } catch {
        return {
            badge: '<span class="audit-confront-badge badge-sync-ok">Registrado</span>',
            deltaText: '--'
        };
    }
}

/**
 * Renderiza o cabeçalho e o corpo da tabela de auditoria com sticky header e colunas enriquecidas.
 */
function renderAuditTable() {
    const thead = document.getElementById('auditTableHeader');
    const tbody = document.getElementById('auditTableBody');
    if (!thead || !tbody) return;

    const formatTime = (ts) => {
        if (!ts) return '--';
        try {
            // Se já vier no formato HH:MM:SS
            if (typeof ts === 'string' && ts.length <= 8 && ts.includes(':')) {
                return ts;
            }
            const d = new Date(ts);
            if (isNaN(d.getTime())) return ts;
            return d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return ts;
        }
    };

    if (auditState.mode === 'daily') {
        thead.innerHTML = `
            <tr>
                <th>Código Equipe</th>
                <th>Base Operacional</th>
                <th>Região</th>
                <th>Escala PowerON</th>
                <th>Conectou no TRBOnet Hoje?</th>
                <th>Horário Marcação (Login)</th>
                <th>1º Sinal Registrado</th>
                <th>Coletas Online / Total</th>
                <th>% Uptime no Dia</th>
                <th>Último Sinal</th>
                <th style="text-align: center;">Auditoria Forense</th>
            </tr>
        `;

        if (auditState.filteredData.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="11" class="empty-table-cell">
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

            const baseInfo = getAuditBaseInfo(item.base_code);
            const basePill = `<span class="audit-base-pill" title="${baseInfo.name}"><span class="base-code-tag">${item.base_code || '--'}</span> ${baseInfo.short}</span>`;

            const marcacaoVal = (item.marcacao && item.marcacao !== '--') ? item.marcacao : '--';
            const firstSeen = formatTime(item.first_seen_online);
            const lastSeen = formatTime(item.last_seen_online);

            return `
                <tr>
                    <td><strong class="team-code-cell">${item.team_code}</strong></td>
                    <td>${basePill}</td>
                    <td><span class="text-secondary">${item.region || (baseInfo.region ? `Região ${baseInfo.region}` : 'Outras Bases')}</span></td>
                    <td>${pwBadge}</td>
                    <td>${statusBadge}</td>
                    <td><span class="time-cell font-bold text-cyan" style="font-family: 'JetBrains Mono', monospace;">${marcacaoVal}</span></td>
                    <td><span class="time-cell">${firstSeen}</span></td>
                    <td><strong>${item.times_seen_online || 0}</strong> / ${item.total_sync_checks || 0} coletas</td>
                    <td>
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <div class="table-progress-bar">
                                <div class="table-progress-fill" style="width: ${Math.min(item.uptime_percentage || 0, 100)}%; background-color: ${getComplianceColor(item.uptime_percentage || 0)}"></div>
                            </div>
                            <span class="font-bold">${item.uptime_percentage || 0}%</span>
                        </div>
                    </td>
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
            const baseInfo = getAuditBaseInfo(item.base_code);
            const basePill = `<span class="audit-base-pill" title="${baseInfo.name}"><span class="base-code-tag">${item.base_code || '--'}</span> ${baseInfo.short}</span>`;
            
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
                    <td>${basePill}</td>
                    <td><span class="text-secondary">${item.region || (baseInfo.region ? `Região ${baseInfo.region}` : 'Outras Bases')}</span></td>
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

    const dateVal = (auditState.selectedDates && auditState.selectedDates.length > 0)
        ? auditState.selectedDates[0]
        : (new Date().toISOString().split('T')[0]);

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
        syncAuditFiltersFromDOM();
        applyAuditFilters();
    }, 200);
}

/**
 * Exporta a tabela filtrada atual para um arquivo XLSX (.xlsx) enriquecido com todas as novas colunas.
 */
function exportAuditTableExcel() {
    const list = auditState.filteredData;
    const dateVal = (auditState.selectedDates && auditState.selectedDates.length > 0)
        ? auditState.selectedDates.join('_')
        : 'hoje';
    const filename = `Auditoria_TRBOnet_PowerON_${dateVal}_${auditState.mode}.xlsx`;

    const formatTime = (ts) => {
        if (!ts) return '--';
        try {
            if (typeof ts === 'string' && ts.length <= 8 && ts.includes(':')) return ts;
            const d = new Date(ts);
            return isNaN(d.getTime()) ? ts : d.toLocaleTimeString('pt-BR');
        } catch { return ts; }
    };

    // 1. Tenta geração client-side instantânea via SheetJS
    if (window.XLSX && list && list.length > 0) {
        try {
            let rows = [];
            if (auditState.mode === 'daily') {
                rows = list.map(i => {
                    const baseInfo = getAuditBaseInfo(i.base_code);
                    const marcVal = (i.marcacao && i.marcacao !== '--') ? i.marcacao : '--';
                    const fSeen = formatTime(i.first_seen_online);
                    const confront = computeAuditConfront(marcVal, fSeen);

                    return {
                        "Data Ref": i.date_ref || dateVal,
                        "Equipe": i.team_code || '',
                        "Código Base": i.base_code || '',
                        "Base Operacional": baseInfo.name,
                        "Região": i.region || (baseInfo.region ? `Região ${baseInfo.region}` : ''),
                        "Escala PowerON": i.was_in_poweron ? 'SIM' : 'NÃO',
                        "Conectou TRBOnet": i.was_online_trbonet ? 'SIM' : 'NÃO',
                        "Horário Marcação (Login)": marcVal,
                        "1º Sinal TRBOnet": fSeen,
                        "Coletas Online": i.times_seen_online || 0,
                        "Total Coletas": i.total_sync_checks || 0,
                        "Uptime (%)": `${i.uptime_percentage || 0}%`,
                        "Último Sinal": formatTime(i.last_seen_online)
                    };
                });
            } else {
                rows = list.map(i => {
                    const baseInfo = getAuditBaseInfo(i.base_code);
                    return {
                        "Data e Hora Coleta": i.captured_at || '',
                        "Data Ref": i.date_ref || '',
                        "Equipe": i.team_code || '',
                        "Código Base": i.base_code || '',
                        "Base Operacional": baseInfo.name,
                        "Região": i.region || '',
                        "Status": i.status || '',
                        "PowerON": i.in_poweron ? 'SIM' : 'NÃO',
                        "TRBOnet": i.in_trbonet ? 'SIM' : 'NÃO',
                        "GPS": i.has_gps ? 'SIM' : 'NÃO',
                        "ID Rádio": i.radio_id || '',
                        "Canal": i.channel || '',
                        "Último Sinal": i.last_signal || ''
                    };
                });
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
    const baseVal = (auditState.filters.bases && auditState.filters.bases.length > 0) ? auditState.filters.bases.join(',') : 'ALL';
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

    const dateVal = (auditState.selectedDates && auditState.selectedDates.length > 0)
        ? auditState.selectedDates.join('_')
        : 'hoje';

    let csvContent = '\uFEFF';

    const formatTime = (ts) => {
        if (!ts) return '--';
        try {
            if (typeof ts === 'string' && ts.length <= 8 && ts.includes(':')) return ts;
            const d = new Date(ts);
            return isNaN(d.getTime()) ? ts : d.toLocaleTimeString('pt-BR');
        } catch { return ts; }
    };

    if (auditState.mode === 'daily') {
        csvContent += 'Data;Equipe;Codigo_Base;Base_Operacional;Regiao;Escala_PowerON;Conectou_TRBOnet;Horario_Marcacao;Primeiro_Sinal;Coletas_Online;Total_Coletas;Uptime_Percentual;Ultimo_Sinal\n';
        list.forEach(i => {
            const baseInfo = getAuditBaseInfo(i.base_code);
            const marcVal = (i.marcacao && i.marcacao !== '--') ? i.marcacao : '--';
            const fSeen = formatTime(i.first_seen_online);

            csvContent += `"${i.date_ref || dateVal}";"${i.team_code}";"${i.base_code || ''}";"${baseInfo.name}";"${i.region || (baseInfo.region ? `Região ${baseInfo.region}` : '')}";"${i.was_in_poweron ? 'SIM' : 'NAO'}";"${i.was_online_trbonet ? 'SIM' : 'NAO'}";"${marcVal}";"${fSeen}";"${i.times_seen_online || 0}";"${i.total_sync_checks || 0}";"${i.uptime_percentage || 0}%";"${formatTime(i.last_seen_online)}"\n`;
        });
    } else {
        csvContent += 'Data_Hora_Coleta;Data_Ref;Equipe;Codigo_Base;Base_Operacional;Regiao;Status;PowerON;TRBOnet;GPS;Radio_ID;Canal;Ultimo_Sinal\n';
        list.forEach(i => {
            const baseInfo = getAuditBaseInfo(i.base_code);
            csvContent += `"${i.captured_at || ''}";"${i.date_ref || ''}";"${i.team_code}";"${i.base_code || ''}";"${baseInfo.name}";"${i.region || ''}";"${i.status || ''}";"${i.in_poweron ? 'SIM' : 'NAO'}";"${i.in_trbonet ? 'SIM' : 'NAO'}";"${i.has_gps ? 'SIM' : 'NAO'}";"${i.radio_id || ''}";"${i.channel || ''}";"${i.last_signal || ''}"\n`;
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
        statusLogin: 'ALL',
        search: ''
    },
    regionalViewMode: 'active', // 'active' (Equipes Ativas) | 'total' (Total do Dia)
    filteredTeams: [],
    isTableCollapsed: false,
    shiftChart: null,
    fleetPieChart: null,
    searchTimer: null,
    historyMode: 'day',
    historyDate: getOperationalDate(),
    historyMonth: getOperationalDate().slice(0, 7),
    historyDayData: null,
    historyMonthData: null,
    historyMonthlyChart: null,
    datePickerInstance: null,
    selectedAuditDates: [getOperationalDate()],
    availableAuditDates: [],
    availableAuditMonths: [],
    comparisonData: [],
    comparisonChart: null,
    auditReconciliationFilter: 'all',
    activeRegion: 'Norte',
    planningTargets: null,
    workforceChart: null
};

// Alternador de Telas (ONLINE vs ONLINE x BID vs AUDITORIA & HISTÓRICO)
async function switchDeliveryScreen(screenName) {
    deliveryState.currentScreen = screenName;
    const btnOnline = document.getElementById('btnSwitchOnline');
    const btnOnlineBid = document.getElementById('btnSwitchOnlineBid');
    const btnHist = document.getElementById('btnSwitchHistory');
    const scrOnline = document.getElementById('deliveryScreenOnline');
    const scrOnlineBid = document.getElementById('deliveryScreenOnlineBid');
    const scrHist = document.getElementById('deliveryScreenHistory');

    if (screenName === 'online') {
        if (btnOnline) btnOnline.classList.add('active');
        if (btnOnlineBid) btnOnlineBid.classList.remove('active');
        if (btnHist) btnHist.classList.remove('active');
        if (scrOnline) scrOnline.style.display = 'block';
        if (scrOnlineBid) scrOnlineBid.style.display = 'none';
        if (scrHist) scrHist.style.display = 'none';
        renderDeliveryCharts();
    } else if (screenName === 'online_bid') {
        if (btnOnline) btnOnline.classList.remove('active');
        if (btnOnlineBid) btnOnlineBid.classList.add('active');
        if (btnHist) btnHist.classList.remove('active');
        if (scrOnline) scrOnline.style.display = 'none';
        if (scrOnlineBid) scrOnlineBid.style.display = 'block';
        if (scrHist) scrHist.style.display = 'none';
        await loadOnlineXBidData();
    } else {
        if (btnOnline) btnOnline.classList.remove('active');
        if (btnOnlineBid) btnOnlineBid.classList.remove('active');
        if (btnHist) btnHist.classList.add('active');
        if (scrOnline) scrOnline.style.display = 'none';
        if (scrOnlineBid) scrOnlineBid.style.display = 'none';
        if (scrHist) scrHist.style.display = 'block';

        // Garante carga das datas e meses disponíveis do Supabase
        await reloadAuditAvailableDates();

        const monthInput = document.getElementById('histMonthInput');
        if (monthInput && !monthInput.value) monthInput.value = deliveryState.historyMonth;
        const wfMonthSel = document.getElementById('wfFilterMonth') || document.getElementById('histWorkforceMonthSelect');
        const wfMonthVal = (wfMonthSel && wfMonthSel.value) ? wfMonthSel.value : (deliveryState.historyMonth || '2026-09');

        initHistoryDatePicker();
        const target = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates[0]) || deliveryState.historyDate;
        loadDailyHistoryAudit(target);
        loadTargetsComparativeAudit(target, deliveryState.activeRegion || 'Norte');
        await loadWorkforceMonthlyChart(wfMonthVal);
    }

    if (typeof syncMobileBottomNav === 'function') {
        syncMobileBottomNav(screenName);
    }
    if (typeof updateMobileSubnav === 'function') {
        updateMobileSubnav('delivery', screenName);
    }
}

// Carregamento de Dados ao Vivo (Módulo 2)
async function loadDeliveryData(forceRefresh = false) {
    const refreshBtn = document.getElementById('btnRefreshDelivery');
    if (refreshBtn) refreshBtn.classList.add('loading-pulse');

    try {
        const url = forceRefresh ? `/api/delivery/data?_=${Date.now()}` : '/api/delivery/data';
        const resp = await fetch(url);
        const result = await resp.json();

        if (result.status === 'success') {
            deliveryState.activeTeams = result.active_teams || [];
            deliveryState.dailyTotalTeams = result.daily_total_teams || [];
            deliveryState.summaryActive = result.summary_active || {};
            deliveryState.summaryTotal = result.summary_total || {};
            deliveryState.intradayCurve = result.intraday_curve || {};
            const rawSync = (result.timestamp && result.timestamp !== '--') ? result.timestamp : (result.last_sync && result.last_sync !== '--' ? result.last_sync : '');
            if (rawSync) {
                deliveryState.lastSync = rawSync;
            } else if (!deliveryState.lastSync || deliveryState.lastSync === '--' || deliveryState.lastSync === '--:--:--') {
                const teams = (result.active_teams && result.active_teams.length > 0) ? result.active_teams : (result.daily_total_teams || []);
                const sample = teams.find(t => t.marcacao || t.captured_at || t.last_seen_time);
                if (sample) {
                    deliveryState.lastSync = sample.marcacao || sample.last_seen_time || '--';
                }
            }

            // Ponto 3: Atualiza a telemetria CCO no cabeçalho (Última Coleta CDP)
            const elCdpTime = document.getElementById('cdpLastSyncTime');
            if (elCdpTime && deliveryState.lastSync) {
                elCdpTime.textContent = deliveryState.lastSync;
            }
            const elCdpBadge = document.getElementById('cdpLastSyncBadge');
            if (elCdpBadge) {
                const src = result.sync_source || 'Robô CDP Operacional';
                elCdpBadge.title = `Última coleta CDP: ${deliveryState.lastSync} (${src}). Clique para forçar conferência.`;
            }

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
    if (elLastSync) {
        const syncVal = (deliveryState.lastSync && deliveryState.lastSync !== '--' && deliveryState.lastSync !== '--:--:--')
            ? deliveryState.lastSync
            : (document.getElementById('cdpLastSyncTime')?.textContent || '--');
        elLastSync.textContent = (syncVal && syncVal !== '--') ? syncVal : '--:--:--';
    }
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

    // Regra Operacional Estrita:
    // No painel ONLINE / TEMPO REAL, caso uma equipe não apareça mais na extração do EB ela não é considerada
    // nem ativa e nem programada. Somente equipes presentes no EB aparecem (seja Logada ou Programada).
    const isOnlineScreen = deliveryState.currentScreen === 'online';
    const sourceList = (isOnlineScreen && isModeActive)
        ? (deliveryState.activeTeams.length > 0 ? deliveryState.activeTeams : deliveryState.dailyTotalTeams.filter(t => t.is_active !== false))
        : (deliveryState.dailyTotalTeams.length > 0 ? deliveryState.dailyTotalTeams : deliveryState.activeTeams);

    // 1. Escopo de Turno, Frota e Busca (usado para alimentar os cards da Região Norte, Região Leste e Bases)
    const scopeFiltered = sourceList.filter(t => {
        if (isModeActive && t.is_active === false) return false;

        // Filtro por Status Login (TODAS / LOGADA / PROGRAMADA)
        const sLoginFilter = deliveryState.filters.statusLogin || 'ALL';
        if (sLoginFilter !== 'ALL') {
            const teamStatusLogin = t.status_login || (t.marcacao && t.marcacao !== '--' ? 'LOGADA' : 'PROGRAMADA');
            if (teamStatusLogin !== sLoginFilter) return false;
        }

        // Filtro por Turnos Múltiplos
        if (shifts.size > 0 && !shifts.has(t.shift_code)) return false;

        // Filtro por Frota / Veículos Múltiplos com normalização fonética/acentos
        if (vehicles.size > 0) {
            const cleanStr = s => String(s || '').normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
            let matchVehicle = false;
            for (const v of vehicles) {
                const vClean = cleanStr(v);
                const tTypeClean = cleanStr(t.vehicle_type);
                const tGroupClean = cleanStr(t.unified_group);
                if (vClean.includes('munk') || vClean.includes('linha viva')) {
                    if (tTypeClean.includes('linha viva') || tTypeClean.includes('munck') || tTypeClean.includes('munk') || tGroupClean.includes('munk') || tGroupClean.includes('linha viva')) {
                        matchVehicle = true;
                        break;
                    }
                } else if (vClean.includes('cesto') && (tTypeClean.includes('cesto') || tGroupClean.includes('cesto'))) {
                    matchVehicle = true;
                    break;
                } else if (vClean.includes('leve') && (tTypeClean.includes('leve') || tGroupClean.includes('leve'))) {
                    matchVehicle = true;
                    break;
                } else if (vClean.includes('moto') && (tTypeClean.includes('moto') || tGroupClean.includes('moto'))) {
                    matchVehicle = true;
                    break;
                } else if (tTypeClean === vClean || tGroupClean === vClean) {
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
        const hasRegions = regions.size > 0;
        const hasBases = bases.size > 0;

        // Filtro por Região Múltipla
        let matchRegion = false;
        if (hasRegions) {
            for (const r of regions) {
                if (t.geo === r || (t.region && t.region.toLowerCase().includes(r.toLowerCase()))) {
                    matchRegion = true;
                    break;
                }
            }
        }

        // Filtro por Base Múltipla com correspondência resiliente
        let matchBase = false;
        if (hasBases) {
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
        }

        // Regra de Composição Geográfica Resiliente:
        // Se tanto regiões quanto bases específicas foram clicadas, a equipe é exibida se corresponder a
        // qualquer uma das regiões selecionadas OU a qualquer uma das bases selecionadas (União Inteligente)
        if (hasRegions && hasBases) {
            if (!matchRegion && !matchBase) return false;
        } else if (hasRegions) {
            if (!matchRegion) return false;
        } else if (hasBases) {
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

// Garante que a tabela esteja expandida ao interagir com filtros
function ensureDeliveryTableExpanded() {
    if (deliveryState.isTableCollapsed) {
        deliveryState.isTableCollapsed = false;
        const bodyEl = document.getElementById('deliveryTableCollapseBody');
        const textEl = document.getElementById('textToggleDeliveryTable');
        const subEl = document.getElementById('deliveryTableStateSubtitle');
        if (bodyEl) bodyEl.classList.remove('table-collapsed');
        if (textEl) textEl.textContent = 'RECOLHER TABELA';
        if (subEl) subEl.textContent = 'Exibindo relação nominal detalhada das equipes filtradas.';
    }
}
window.ensureDeliveryTableExpanded = ensureDeliveryTableExpanded;

// Filtros Interativos Múltiplos por Região (Entrega de Equipes)
function toggleDeliveryRegionFilter(regionName) {
    const cardId = regionName === 'Norte' ? 'filterCardTotalNorte' : 'filterCardTotalLeste';
    const cardEl = document.getElementById(cardId);

    if (deliveryState.filters.regions.has(regionName)) {
        deliveryState.filters.regions.delete(regionName);
        if (cardEl) cardEl.classList.remove('filter-active');
    } else {
        deliveryState.filters.regions.add(regionName);
        if (cardEl) cardEl.classList.add('filter-active');
    }

    ensureDeliveryTableExpanded();
    applyDeliveryFilters();
}

// Filtros Interativos Múltiplos por Base (Entrega de Equipes)
function toggleDeliveryBaseFilter(baseName, el) {
    if (deliveryState.filters.bases.has(baseName)) {
        deliveryState.filters.bases.delete(baseName);
        if (el) el.classList.remove('filter-active');
    } else {
        deliveryState.filters.bases.add(baseName);
        if (el) el.classList.add('filter-active');
    }

    ensureDeliveryTableExpanded();
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

    ensureDeliveryTableExpanded();
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

    ensureDeliveryTableExpanded();
    applyDeliveryFilters();
}

// Filtro por Status Login (TODAS > LOGADA > PROGRAMADA)
function setDeliveryStatusLoginFilter(status, el) {
    const container = document.getElementById('deliveryStatusLoginPills');
    if (container) {
        container.querySelectorAll('.pill-chip').forEach(c => c.classList.remove('active'));
    }
    if (el) {
        el.classList.add('active');
    } else if (container) {
        const btn = container.querySelector(`[data-status-login="${status}"]`);
        if (btn) btn.classList.add('active');
    }

    deliveryState.filters.statusLogin = status || 'ALL';
    ensureDeliveryTableExpanded();
    applyDeliveryFilters();
}
window.setDeliveryStatusLoginFilter = setDeliveryStatusLoginFilter;

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

            // No painel ONLINE: se modo for 'active', exibe equipes em turno ativo; se for 'total', exibe todas do dia
            const isOnlineScreen = deliveryState.currentScreen === 'online';
            const isTotalMode = deliveryState.regionalViewMode === 'total';
            const list = (isOnlineScreen && !isTotalMode)
                ? deliveryState.filteredTeams.filter(t => t.is_active !== false)
                : deliveryState.filteredTeams;

            const shiftSubtitle = document.getElementById('deliveryShiftChartSubtitle');
            if (shiftSubtitle) {
                shiftSubtitle.textContent = isTotalMode 
                    ? 'Total Acumulado de Equipes por Faixa Horária (Ativas + Encerradas)'
                    : 'Entrada de Equipes Ativas por Faixa Horária de Login';
            }

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
            const isTotalMode = deliveryState.regionalViewMode === 'total';
            const list = (isOnlineScreen && !isTotalMode)
                ? deliveryState.filteredTeams.filter(t => t.is_active !== false)
                : deliveryState.filteredTeams;

            const fleetSubtitle = document.getElementById('deliveryFleetChartSubtitle');
            if (fleetSubtitle) {
                fleetSubtitle.textContent = isTotalMode
                    ? 'Total Acumulado do Dia por Tipologia Veicular'
                    : 'Total de Equipes Ativas por Tipologia Veicular';
            }

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
        if (subEl) subEl.textContent = 'Tabela recolhida. Clique em Expandir para visualizar a relação nominal.';
    } else {
        if (bodyEl) bodyEl.classList.remove('table-collapsed');
        if (textEl) textEl.textContent = 'RECOLHER TABELA';
        if (subEl) subEl.textContent = 'Exibindo relação nominal detalhada das equipes filtradas.';
        renderDeliveryTable();
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
        const hasAnyFilter = deliveryState.filters.regions.size > 0 || deliveryState.filters.bases.size > 0 || deliveryState.filters.shifts.size > 0 || deliveryState.filters.vehicles.size > 0 || deliveryState.filters.search;
        tbody.innerHTML = `
            <tr>
                <td colspan="15" style="text-align: center; padding: 36px 20px; color: var(--text-secondary);">
                    <p style="font-weight: 700; font-size: 0.95rem; margin: 0 0 6px 0; color: var(--text-primary);">Nenhuma equipe encontrada para os filtros selecionados.</p>
                    <p style="font-size: 0.8rem; margin: 0; color: var(--text-secondary);">
                        ${hasAnyFilter ? 'Tente desmarcar alguns filtros ou clique em <strong style="color: #38bdf8; cursor: pointer; text-decoration: underline;" onclick="clearDeliveryBaseFilters()">LIMPAR SELEÇÃO</strong>.' : 'Nenhuma equipe registrada no momento.'}
                    </p>
                </td>
            </tr>
        `;
        if (typeof renderMobileDeliveryCards === 'function') {
            renderMobileDeliveryCards([]);
        }
        return;
    }

    tbody.innerHTML = list.map(t => {
        const isAct = t.is_active;
        const statusEB = t.status_equipes_brasil || t.status || (isAct ? 'Logada' : 'Turno Concluído');
        
        let statusBadge = '';
        if (statusEB.toLowerCase().includes('atendimento')) {
            statusBadge = `<span class="badge-status-active" style="background: rgba(14, 165, 233, 0.15); color: #0284c7; border: 1px solid rgba(14, 165, 233, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;"><span class="live-status-dot" style="width:6px;height:6px;background:#0284c7;"></span> Em Atendimento</span>`;
        } else if (statusEB.toLowerCase().includes('descanso')) {
            statusBadge = `<span style="background: rgba(139, 92, 246, 0.15); color: #8b5cf6; border: 1px solid rgba(139, 92, 246, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">☕ Descanso</span>`;
        } else if (statusEB.toLowerCase().includes('livre') || statusEB.toLowerCase().includes('deslocamento')) {
            statusBadge = `<span style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">⚡ ${statusEB}</span>`;
        } else if (isAct) {
            statusBadge = `<span class="badge-status-active" style="background: rgba(16, 185, 129, 0.14); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.35); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;"><span class="live-status-dot" style="width:6px;height:6px;"></span> ${statusEB}</span>`;
        } else {
            statusBadge = `<span style="background: rgba(148, 163, 184, 0.14); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 700;">Turno Concluído</span>`;
        }

        // Badge da Placa & Cruzamento com Frotas
        const plateVal = t.plate && t.plate !== '--' ? t.plate : '';
        let plateHtml = '';
        if (!plateVal) {
            plateHtml = `<span style="color: var(--text-secondary); font-size: 0.75rem;">Sem placa</span>`;
        } else {
            let fleetBadge = '';
            const isCad = t.plate_cadastrada;
            const situacao = (t.situacao_veiculo_cadastrado || '').toUpperCase();
            const statusV = (t.status_veiculo_cadastrado || '').toUpperCase();

            if (!isCad) {
                fleetBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: 800; display: inline-block; margin-top: 2px;">Não Cadastrada</span>`;
            } else if (situacao === 'PARADO' || statusV.includes('MANUTEN') || statusV.includes('ANÁLISE') || statusV.includes('ANALISE')) {
                fleetBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: 800; display: inline-block; margin-top: 2px;" title="Alerta: Veículo cadastrado como ${situacao} (${statusV}) na frota!">⚠️ ${situacao}</span>`;
            } else {
                fleetBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.12); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); padding: 2px 6px; border-radius: 4px; font-size: 0.65rem; font-weight: 800; display: inline-block; margin-top: 2px;">✓ ${situacao}</span>`;
            }

            plateHtml = `
                <div>
                    <strong style="font-family: 'JetBrains Mono', monospace; font-size: 0.82rem; color: var(--text-primary);">${plateVal}</strong>
                </div>
                ${fleetBadge}
            `;
        }

        // Marcação & Desvio
        const marcacaoVal = t.marcacao && t.marcacao !== '--' ? t.marcacao : '--';
        const desvioVal = t.desvio && t.desvio !== '--' ? t.desvio : '--';
        let desvioHtml = `<span style="color: var(--text-secondary); font-size: 0.75rem;">--</span>`;
        if (desvioVal !== '--') {
            const minVal = t.desvio_minutos || 0;
            let dStyle = 'background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);';
            if (Math.abs(minVal) > 30) {
                dStyle = 'background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4);';
            } else if (desvioVal.includes('+')) {
                dStyle = 'background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);';
            }
            desvioHtml = `<span class="badge" style="${dStyle} font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">${desvioVal}</span>`;
        }

        // GPS
        const gpsStr = t.gps_update_str && t.gps_update_str !== '--' ? t.gps_update_str : '--';
        const gpsMin = t.gps_update_minutes;
        const gpsColor = gpsMin !== null && gpsMin !== undefined && gpsMin > 60 ? '#f59e0b' : '#10b981';

        // 11.2 Badge de Status BID (Visão Operacional)
        const rawStBid = t.status_bid || (t.bid_info && t.bid_info.status_bid) || '--';
        const stBid = normalizeBidStatus(rawStBid);
        let bidBadge = '';
        if (stBid === 'Em Operação') {
            bidBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;"><span class="live-status-dot" style="width:6px;height:6px;background:#10b981;"></span> Em Operação</span>`;
        } else if (stBid === 'Em Checklist') {
            bidBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">⏱️ Em Checklist</span>`;
        } else if (stBid === 'Planejada') {
            bidBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">⚠️ Planejada</span>`;
        } else if (stBid === 'Bloqueada' || stBid === 'Retornada') {
            bidBadge = `<span class="badge" style="background: rgba(225, 29, 72, 0.18); color: #e11d48; border: 1px solid rgba(225, 29, 72, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">⛔ ${stBid}</span>`;
        } else if (stBid === 'Não Encontrada') {
            bidBadge = `<span class="badge" style="background: rgba(192, 132, 252, 0.15); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 800;">🟣 Não Cadastrada</span>`;
        } else {
            bidBadge = `<span style="color: var(--text-secondary); font-size: 0.75rem;">--</span>`;
        }

        // Descanso
        const descansoHtml = t.data_inicio_descanso
            ? `<div style="font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; font-weight: 700; color: #8b5cf6;">${t.data_inicio_descanso}</div><div style="font-family: 'JetBrains Mono', monospace; font-size: 0.72rem; color: var(--text-secondary);">${t.hora_inicio_descanso || '--:--'}</div>`
            : `<span style="color: var(--text-secondary); font-size: 0.75rem;">--</span>`;

        // Ordem (com indicador de histórico deduplicado)
        const orderHist = t.order_history || [];
        const orderCount = orderHist.length;
        const ordemHtml = t.ordem_servico
            ? `<div>
                 <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.78rem; color: #0284c7;">${t.ordem_servico}</span>
                 ${orderCount > 1 ? `<div style="font-size: 0.65rem; color: #38bdf8; font-weight: 800; cursor: pointer;" onclick="openDeliveryTeamModal('${t.team_code}')">(${orderCount} OSs hoje)</div>` : ''}
               </div>`
            : `<span style="color: var(--text-secondary); font-size: 0.75rem;">--</span>`;

        return `
            <tr>
                <!-- 1. UT -->
                <td>
                    <div style="font-weight: 700; font-size: 0.76rem; color: var(--text-primary);">${t.ut || '--'}</div>
                </td>
                <!-- 2. BASE -->
                <td>
                    <div style="font-weight: 800; color: var(--text-primary);">${t.base_display || t.base_name || '--'}</div>
                    <small style="color: var(--text-secondary); font-family: 'JetBrains Mono', monospace; font-weight: 700;">${t.base_code || ''}</small>
                </td>
                <!-- 3. FILIAL -->
                <td>
                    <small style="font-weight: 800; color: #0ea5e9;">${t.filial || '--'}</small>
                </td>
                <!-- 4. VEÍCULO -->
                <td>
                    <span style="font-size: 0.75rem; font-weight: 800; color: var(--text-primary);">${t.vehicle_type || t.veiculo_portal || '--'}</span>
                </td>
                <!-- 5. EQUIPE (Clicável para abrir Modal Ultra-Premium) -->
                <td>
                    <button type="button" class="team-badge clickable-team-badge" onclick="event.stopPropagation(); openDeliveryTeamModal('${t.team_code}')" title="Clique para ver Diagnóstico Completo, TRBOnet e Histórico de Ordens" style="cursor: pointer; transition: all 0.2s ease;">
                        ${t.team_code}
                    </button>
                </td>
                <!-- 6. MOTORISTA -->
                <td>
                    <div style="font-weight: 600; font-size: 0.76rem; color: var(--text-primary);">${t.driver || '--'}</div>
                </td>
                <!-- 7. TURNO PROGRAMADO -->
                <td>
                    <span class="shift-pill ${t.shift_pill_class}" style="font-size: 0.74rem;">${t.shift_slot}</span>
                </td>
                <!-- 8. MARCAÇÃO -->
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 800; font-size: 0.8rem; color: #38bdf8;">${marcacaoVal}</span>
                </td>
                <!-- 9. DESVIO -->
                <td>
                    ${desvioHtml}
                </td>
                <!-- 10. GPS (MIN) -->
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700; font-size: 0.76rem; color: ${gpsColor};">
                        ${gpsStr}
                    </span>
                </td>
                <!-- 11. STATUS -->
                <td>${statusBadge}</td>
                <!-- 12. STATUS BID -->
                <td>${bidBadge}</td>
                <!-- 13. PLACA -->
                <td>${plateHtml}</td>
                <!-- 14. INÍCIO DESCANSO -->
                <td>${descansoHtml}</td>
                <!-- 15. ORDEM -->
                <td>${ordemHtml}</td>
            </tr>
        `;
    }).join('');

    if (typeof renderMobileDeliveryCards === 'function') {
        renderMobileDeliveryCards(list);
    }
}

// Exportação Excel (.xlsx) Sensível aos Filtros Ativos (14 Colunas Oficiais)
function exportDeliveryExcelFiltered() {
    const list = deliveryState.filteredTeams;
    if (!list || list.length === 0) {
        showToast('Nenhuma equipe para exportar com os filtros atuais.', 'warning');
        return;
    }

    const rows = list.map(t => ({
        "UT": t.ut || "",
        "Base": t.base_display || t.base_name || "",
        "Filial": t.filial || "",
        "Veículo": t.vehicle_type || t.veiculo_portal || "",
        "Equipe": t.team_code || "",
        "Motorista": t.driver || "",
        "Turno Programado": t.shift_slot || t.raw_shift || "",
        "Marcação": t.marcacao || "",
        "Status Login": t.status_login || (t.marcacao && t.marcacao !== '--' ? "LOGADA" : "PROGRAMADA"),
        "Desvio": t.desvio || "",
        "GPS (min)": t.gps_update_str || "",
        "Status": t.status_equipes_brasil || t.status || (t.is_active ? "Logada" : "Turno Concluído"),
        "Placa": t.plate || "",
        "Início Descanso": t.data_inicio_descanso ? `${t.data_inicio_descanso} ${t.hora_inicio_descanso || ''}`.trim() : "",
        "Ordem": t.ordem_servico || ""
    }));

    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Equipes Entregues");
        const dateStr = new Date().toISOString().split('T')[0];
        XLSX.writeFile(wb, `Entrega_Equipes_Enel_${dateStr}.xlsx`);
        showToast(`Planilha gerada com sucesso (${rows.length} equipes filtradas)!`, 'success');
    } else {
        window.location.href = '/api/delivery/export_excel';
    }
}

// Modal Ultra-Premium de Detalhes da Equipe Entregue (Enel × TRBOnet × Ordens)
async function openDeliveryTeamModal(teamCode) {
    if (!teamCode) return;
    const code = String(teamCode).trim().toUpperCase();

    // 1. Abre o modal imediatamente com backdrop blur
    const modal = document.getElementById('deliveryTeamDetailModal');
    if (modal) {
        modal.style.display = 'flex';
        void modal.offsetWidth;
        modal.classList.add('active');
    } else {
        openModal('deliveryTeamDetailModal');
    }

    // Elementos do Modal
    const codeEl = document.getElementById('delModalTeamCode');
    const baseBadgeEl = document.getElementById('delModalBaseBadge');
    const regionBadgeEl = document.getElementById('delModalRegionBadge');
    const alertsContainer = document.getElementById('delModalAlertsContainer');

    // TRBOnet Card
    const trboBadgeEl = document.getElementById('delModalTrboConnectionBadge');
    const radioIdEl = document.getElementById('delModalRadioId');
    const radioChannelEl = document.getElementById('delModalRadioChannel');
    const radioGpsEl = document.getElementById('delModalRadioGps');
    const radioLastSignalEl = document.getElementById('delModalRadioLastSignal');
    const trboNoteEl = document.getElementById('delModalTrboNote');

    // BID Visão Operacional Card
    const bidBadgeEl = document.getElementById('delModalBidStatusBadge');
    const bidTimerEl = document.getElementById('delModalBidTimer');
    const bidPhoneEl = document.getElementById('delModalBidPhone');
    const bidTipoBaseEl = document.getElementById('delModalBidTipoBase');
    const bidVehicleEl = document.getElementById('delModalBidVehicle');
    const bidMembersListEl = document.getElementById('delModalBidMembersList');

    // Escala e Marcação
    const turnoProgEl = document.getElementById('delModalTurnoProg');
    const marcacaoEl = document.getElementById('delModalMarcacao');
    const desvioBadgeEl = document.getElementById('delModalDesvioBadge');
    const statusOperEl = document.getElementById('delModalStatusOper');
    const gpsEbEl = document.getElementById('delModalGpsEb');
    const descansoEl = document.getElementById('delModalDescanso');

    // Frota e Veículo
    const motoristaEl = document.getElementById('delModalMotorista');
    const veiculoTipoEl = document.getElementById('delModalVeiculoTipo');
    const placaEl = document.getElementById('delModalPlaca');
    const frotaSituacaoEl = document.getElementById('delModalFrotaSituacao');
    const utFilialEl = document.getElementById('delModalUtFilial');

    // Tabela de Ordens
    const ordersTbody = document.getElementById('delModalOrdersTableBody');
    const orderCountBadge = document.getElementById('delModalOrderCountBadge');

    // Estado inicial de carregamento
    if (codeEl) codeEl.textContent = `EQUIPE ${code}`;
    if (baseBadgeEl) baseBadgeEl.textContent = `Carregando...`;
    if (regionBadgeEl) regionBadgeEl.textContent = `...`;
    if (alertsContainer) { alertsContainer.innerHTML = ''; alertsContainer.style.display = 'none'; }
    if (trboBadgeEl) trboBadgeEl.innerHTML = `<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; font-weight: 800;">Consultando TRBOnet...</span>`;
    if (bidBadgeEl) bidBadgeEl.innerHTML = `<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; font-weight: 800;">Consultando BID...</span>`;
    if (bidTimerEl) bidTimerEl.textContent = '--';
    if (bidPhoneEl) bidPhoneEl.textContent = '--';
    if (bidTipoBaseEl) bidTipoBaseEl.textContent = '--';
    if (bidVehicleEl) bidVehicleEl.textContent = '--';
    if (bidMembersListEl) bidMembersListEl.textContent = '--';
    if (ordersTbody) {
        ordersTbody.innerHTML = `<tr><td colspan="5" style="text-align: center; padding: 18px; color: var(--text-secondary);">Buscando histórico de ordens...</td></tr>`;
    }

    // Busca rápida nos dados locais em memória (<1ms) para pré-preencher
    const localTeam = (deliveryState.filteredTeams || []).find(t => t.team_code === code) ||
                      (deliveryState.activeTeams || []).find(t => t.team_code === code) ||
                      (deliveryState.dailyTotalTeams || []).find(t => t.team_code === code);

    if (localTeam) {
        if (baseBadgeEl) baseBadgeEl.textContent = localTeam.base_display || localTeam.base_name || `Base ${localTeam.base_code}`;
        if (regionBadgeEl) regionBadgeEl.textContent = localTeam.region || 'Região';
        if (turnoProgEl) turnoProgEl.textContent = localTeam.shift_slot || localTeam.raw_shift || '--';
        if (marcacaoEl) marcacaoEl.textContent = localTeam.marcacao || '--';
        if (motoristaEl) motoristaEl.textContent = localTeam.driver || '--';
        if (veiculoTipoEl) veiculoTipoEl.textContent = localTeam.vehicle_type || localTeam.veiculo_portal || '--';
        if (placaEl) placaEl.textContent = localTeam.plate || '--';
        if (utFilialEl) utFilialEl.textContent = `${localTeam.ut || '--'} • ${localTeam.filial || '--'}`;
        if (gpsEbEl) gpsEbEl.textContent = localTeam.gps_update_str || '--';
        if (descansoEl) descansoEl.textContent = localTeam.data_inicio_descanso ? `${localTeam.data_inicio_descanso} ${localTeam.hora_inicio_descanso || ''}` : '--';
        
        if (statusOperEl) {
            statusOperEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-weight: 800;">${localTeam.status_equipes_brasil || localTeam.status || 'Ativa'}</span>`;
        }

        if (desvioBadgeEl) {
            const desv = localTeam.desvio || '--';
            let dClass = 'background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3);';
            if (desv !== '--') {
                if (desv.includes('+')) dClass = 'background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);';
                else dClass = 'background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);';
            }
            desvioBadgeEl.innerHTML = `<span class="badge" style="${dClass} font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;">${desv}</span>`;
        }

        const statusLoginBadgeEl = document.getElementById('delModalStatusLoginBadge');
        if (statusLoginBadgeEl) {
            const sLogin = localTeam.status_login || (localTeam.marcacao && localTeam.marcacao !== '--' ? 'LOGADA' : 'PROGRAMADA');
            const isLog = sLogin === 'LOGADA';
            statusLoginBadgeEl.innerHTML = isLog
                ? `<span class="badge" style="background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;"><span class="live-status-dot" style="width:5px;height:5px;background:#10b981;"></span> LOGADA</span>`
                : `<span class="badge" style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;">PROGRAMADA</span>`;
        }
    }

    // 2. Consulta a API Unificada de Detalhes
    try {
        const resp = await fetch(`/api/delivery/team_details/${encodeURIComponent(code)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const result = await resp.json();

        if (result.status === 'success') {
            const d = result.delivery || localTeam || {};
            const trbo = result.trbonet || {};
            const fleet = result.fleet || {};
            const orders = result.order_history || [];
            const alerts = result.alerts || [];

            // Cabeçalho
            if (codeEl) codeEl.textContent = `EQUIPE ${code}`;
            if (baseBadgeEl) baseBadgeEl.textContent = d.base_display || d.base_name || `Base ${d.base_code || ''}`;
            if (regionBadgeEl) regionBadgeEl.textContent = d.region || 'Região';

            // Alertas Críticos
            if (alertsContainer) {
                if (alerts.length > 0) {
                    alertsContainer.style.display = 'block';
                    alertsContainer.innerHTML = alerts.map(a => `
                        <div class="del-modal-alert ${a.type === 'danger' ? 'del-modal-alert-danger' : 'del-modal-alert-warning'}">
                            <i data-lucide="${a.type === 'danger' ? 'alert-triangle' : 'alert-circle'}" style="width: 18px; height: 18px; flex-shrink: 0;"></i>
                            <div><strong>${a.title}:</strong> ${a.message}</div>
                        </div>
                    `).join('');
                } else {
                    alertsContainer.style.display = 'none';
                    alertsContainer.innerHTML = '';
                }
            }

            // TRBOnet One Card
            if (trboBadgeEl) {
                if (trbo.connected) {
                    trboBadgeEl.innerHTML = `
                        <span class="badge badge-trbo-online">
                            <span class="live-status-dot" style="background: #10b981;"></span> ${trbo.status_label}
                        </span>
                    `;
                } else {
                    trboBadgeEl.innerHTML = `
                        <span class="badge badge-trbo-offline">
                            <span class="live-status-dot" style="background: #ef4444;"></span> Desconectado no TRBOnet
                        </span>
                    `;
                }
            }
            if (radioIdEl) radioIdEl.textContent = trbo.radio_id || '--';
            if (radioChannelEl) radioChannelEl.textContent = trbo.channel || '--';
            if (radioGpsEl) {
                radioGpsEl.innerHTML = trbo.has_gps
                    ? `<span class="text-emerald" style="font-weight: 800;">✓ Sinal Ativo</span>`
                    : `<span class="text-amber" style="font-weight: 800;">⚠️ Sem GPS</span>`;
            }
            if (radioLastSignalEl) radioLastSignalEl.textContent = trbo.last_signal || '--:--:--';
            if (trboNoteEl) trboNoteEl.textContent = trbo.details || '';

            // Escala e Marcação
            if (turnoProgEl) turnoProgEl.textContent = d.shift_slot || d.raw_shift || '--';
            if (marcacaoEl) marcacaoEl.textContent = d.marcacao || '--';
            if (gpsEbEl) gpsEbEl.textContent = d.gps_update_str || '--';
            if (descansoEl) descansoEl.textContent = d.data_inicio_descanso ? `${d.data_inicio_descanso} ${d.hora_inicio_descanso || ''}` : '--';
            if (statusOperEl) {
                const s = d.status_equipes_brasil || d.status || 'Ativa';
                statusOperEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-weight: 800; padding: 2px 8px; border-radius: 9999px;">${s}</span>`;
            }
            if (desvioBadgeEl) {
                const desv = d.desvio || '--';
                let dClass = 'background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3);';
                if (desv !== '--') {
                    const minVal = d.desvio_minutos || 0;
                    if (Math.abs(minVal) > 30) {
                        dClass = 'background: rgba(239, 68, 68, 0.18); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.45);';
                    } else if (desv.includes('+')) {
                        dClass = 'background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.45);';
                    } else {
                        dClass = 'background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.45);';
                    }
                }
                desvioBadgeEl.innerHTML = `<span class="badge" style="${dClass} font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;">${desv}</span>`;
            }

            const statusLoginBadgeEl = document.getElementById('delModalStatusLoginBadge');
            if (statusLoginBadgeEl) {
                const sLogin = d.status_login || (d.marcacao && d.marcacao !== '--' ? 'LOGADA' : 'PROGRAMADA');
                const isLog = sLogin === 'LOGADA';
                statusLoginBadgeEl.innerHTML = isLog
                    ? `<span class="badge" style="background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;"><span class="live-status-dot" style="width:5px;height:5px;background:#10b981;"></span> LOGADA</span>`
                    : `<span class="badge" style="background: rgba(56, 189, 248, 0.18); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.4); font-weight: 800; font-size: 0.75rem; padding: 2px 8px; border-radius: 9999px;">PROGRAMADA</span>`;
            }

            // Frota e Veículo
            if (motoristaEl) motoristaEl.textContent = d.driver || '--';
            if (veiculoTipoEl) veiculoTipoEl.textContent = d.vehicle_type || d.veiculo_portal || '--';
            if (placaEl) placaEl.textContent = d.plate || '--';
            if (utFilialEl) utFilialEl.textContent = `${d.ut || '--'} • ${d.filial || '--'}`;

            if (frotaSituacaoEl) {
                const isCad = fleet.plate_cadastrada;
                const sit = (fleet.situacao_veiculo_cadastrado || '').toUpperCase();
                const st = (fleet.status_veiculo_cadastrado || '').toUpperCase();
                if (!isCad) {
                    frotaSituacaoEl.innerHTML = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.35); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 800;">Não Cadastrada</span>`;
                } else if (sit === 'PARADO' || st.includes('MANUTEN') || st.includes('ANÁLISE') || st.includes('ANALISE')) {
                    frotaSituacaoEl.innerHTML = `<span class="badge" style="background: rgba(245, 158, 11, 0.18); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 800;">⚠️ ${sit} (${st || '--'})</span>`;
                } else {
                    frotaSituacaoEl.innerHTML = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.35); padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 800;">✓ ${sit} (${st || 'OPERACIONAL'})</span>`;
                }
            }

            // Histórico de Ordens de Serviço (OS)
            if (orderCountBadge) orderCountBadge.textContent = `${orders.length} ${orders.length === 1 ? 'Ordem' : 'Ordens'}`;
            if (ordersTbody) {
                if (orders.length === 0) {
                    ordersTbody.innerHTML = `
                        <tr>
                            <td colspan="5" style="text-align: center; padding: 20px; color: var(--text-secondary);">
                                Nenhuma ordem de serviço registrada para esta equipe no dia operacional atual.
                            </td>
                        </tr>
                    `;
                } else {
                    const currentOS = d.ordem_servico;
                    ordersTbody.innerHTML = orders.map((o, idx) => {
                        const isCurrent = currentOS && String(o.ordem).trim() === String(currentOS).trim();
                        const isLatest = idx === orders.length - 1;
                        const highlight = isCurrent || isLatest;
                        return `
                            <tr style="${highlight ? 'background: rgba(14, 165, 233, 0.08);' : ''}">
                                <td>
                                    <div style="display: flex; align-items: center; gap: 6px;">
                                        <strong class="del-modal-order-strong ${highlight ? 'order-current' : ''}" style="font-family: 'JetBrains Mono', monospace; font-size: 0.82rem;">${o.ordem}</strong>
                                        ${highlight ? '<span class="badge del-modal-order-badge-current" style="background: rgba(14, 165, 233, 0.2); color: #0284c7; font-size: 0.62rem; font-weight: 800; padding: 1px 5px; border-radius: 4px;">Atual</span>' : ''}
                                    </div>
                                </td>
                                <td>
                                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.76rem; color: var(--text-secondary);">${o.first_seen || '--:--:--'}</span>
                                </td>
                                <td>
                                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.76rem; color: var(--text-secondary);">${o.last_seen || '--:--:--'}</span>
                                </td>
                                <td>
                                    <span style="font-size: 0.74rem; font-weight: 700; color: #10b981;">${o.status || 'Atendida'}</span>
                                </td>
                                <td>
                                    <span class="badge del-modal-cycle-badge">${o.cycles_count || 1}x (${((o.cycles_count || 1) * 2)}min)</span>
                                </td>
                            </tr>
                        `;
                    }).join('');
                }
            }

            // BID Visão Operacional (Checklist)
            const bid = result.bid_info || (localTeam && localTeam.bid_info) || {};
            if (bid && Object.keys(bid).length > 0 && (bid.status_bid || bid.tipo_operacional || bid.plate)) {
                const rawSt = bid.status_bid || 'Não Encontrada';
                const st = normalizeBidStatus(rawSt);
                let bBadge = '';
                if (st === 'Em Operação') {
                    bBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;"><span class="live-status-dot" style="width:6px;height:6px;background:#10b981;"></span> Em Operação</span>`;
                } else if (st === 'Em Checklist') {
                    bBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;">⏱️ Em Checklist</span>`;
                } else if (st === 'Planejada') {
                    bBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.18); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;">⚠️ Planejada (Pendente)</span>`;
                } else if (st === 'Bloqueada' || st === 'Retornada') {
                    bBadge = `<span class="badge" style="background: rgba(225, 29, 72, 0.2); color: #e11d48; border: 1px solid rgba(225, 29, 72, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;">⛔ ${st}</span>`;
                } else {
                    bBadge = `<span class="badge" style="background: rgba(192, 132, 252, 0.18); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;">🟣 Não Cadastrada</span>`;
                }
                if (bidBadgeEl) bidBadgeEl.innerHTML = bBadge;

                const timerVal = bid.timer_value || bid.tempo_operacao || '--';
                const timerLbl = bid.timer_label || (st === 'Em Operação' ? 'Tempo em operação' : 'Tempo');
                if (bidTimerEl) bidTimerEl.textContent = timerVal !== '--' ? `${timerVal} (${timerLbl})` : '--';
                if (bidPhoneEl) bidPhoneEl.textContent = bid.phone || '--';
                if (bidTipoBaseEl) bidTipoBaseEl.textContent = `${bid.tipo_operacional || bid.tipo || '--'} • Base ${bid.base || '--'}`;
                if (bidVehicleEl) bidVehicleEl.textContent = `${bid.plate || '--'} ${bid.vehicle_desc ? '• ' + bid.vehicle_desc : ''}`;

                if (bidMembersListEl) {
                    const members = bid.members || [];
                    if (Array.isArray(members) && members.length > 0) {
                        bidMembersListEl.innerHTML = members.map(m => {
                            const name = typeof m === 'object' ? (m.name || '--') : String(m);
                            const role = typeof m === 'object' ? (m.role || '') : '';
                            const grp = typeof m === 'object' ? (m.group || '') : '';
                            return `<div style="margin-bottom: 3px;"><strong>👤 ${name}</strong> ${role ? `<span style="color: var(--text-secondary);">(${role}${grp ? ' • ' + grp : ''})</span>` : ''}</div>`;
                        }).join('');
                    } else if (typeof members === 'string' && members.trim()) {
                        bidMembersListEl.textContent = members;
                    } else {
                        bidMembersListEl.textContent = 'Nenhum componente especificado no card.';
                    }
                }
            } else {
                if (bidBadgeEl) bidBadgeEl.innerHTML = `<span class="badge" style="background: rgba(192, 132, 252, 0.18); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.4); padding: 3px 8px; border-radius: 9999px; font-weight: 800;">🟣 Não Encontrada no BID</span>`;
                if (bidTimerEl) bidTimerEl.textContent = '--';
                if (bidPhoneEl) bidPhoneEl.textContent = '--';
                if (bidTipoBaseEl) bidTipoBaseEl.textContent = '--';
                if (bidVehicleEl) bidVehicleEl.textContent = '--';
                if (bidMembersListEl) bidMembersListEl.textContent = 'Sem dados de checklist no BID hoje.';
            }

        }
    } catch (err) {
        console.warn('[DELIVERY MODAL ERROR]', err);
    }

    if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
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

// Carregamento e Atualização das Datas e Meses Disponíveis no Banco
async function reloadAuditAvailableDates() {
    try {
        const resp = await fetch('/api/delivery/available-dates');
        const data = await resp.json();
        if (data.status === 'success') {
            deliveryState.availableAuditDates = data.dates || [];
            deliveryState.availableAuditMonths = data.months || [];

            // Garante meses ordenados de forma crescente: Janeiro, Fevereiro, Março, Abril...
            deliveryState.availableAuditMonths.sort((a, b) => {
                const valA = typeof a === 'object' ? a.value : a;
                const valB = typeof b === 'object' ? b.value : b;
                return valA.localeCompare(valB);
            });

            // Popula lista suspensa do FILTROS GERAIS DO PERÍODO
            const wfMonthSel = document.getElementById('wfFilterMonth');
            if (wfMonthSel && deliveryState.availableAuditMonths.length > 0) {
                const monthNames = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"];
                
                const optionsHtml = deliveryState.availableAuditMonths.map(m => {
                    const val = typeof m === 'object' ? m.value : m;
                    let label = typeof m === 'object' ? m.label : null;
                    if (!label && typeof val === 'string' && val.includes('-')) {
                        const parts = val.split('-');
                        const y = parts[0];
                        const monthIdx = parseInt(parts[1], 10) - 1;
                        label = `${monthNames[monthIdx] || parts[1]} de ${y}`;
                    }
                    return `<option value="${val}">${label || val}</option>`;
                }).join('');

                const prevVal = wfMonthSel.value;
                wfMonthSel.innerHTML = optionsHtml;

                // Define o mês de ontem como padrão
                const yesterday = new Date();
                yesterday.setDate(yesterday.getDate() - 1);
                const yMonth = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}`;

                if (prevVal && Array.from(wfMonthSel.options).some(o => o.value === prevVal)) {
                    wfMonthSel.value = prevVal;
                } else if (Array.from(wfMonthSel.options).some(o => o.value === yMonth)) {
                    wfMonthSel.value = yMonth;
                } else if (wfMonthSel.options.length > 0) {
                    wfMonthSel.value = wfMonthSel.options[wfMonthSel.options.length - 1].value;
                }

                if (deliveryState.currentScreen === 'history' && (!deliveryState.monthlyRawData || deliveryState.monthlyRawData.length === 0)) {
                    loadWorkforceMonthlyChart(wfMonthSel.value);
                }
            }

            // Redesenha Flatpickr para renderizar as bolinhas verdes nos dias com dados
            if (deliveryState.datePickerInstance) {
                deliveryState.datePickerInstance.redraw();
            }
            if (typeof auditState !== 'undefined' && auditState && auditState.datePickerInstance) {
                auditState.datePickerInstance.redraw();
            }
        }
    } catch (e) {
        console.warn('Erro ao consultar datas com auditoria disponível:', e);
    }
}

// Inicialização do Flatpickr para Múltiplas Datas de Auditoria (Liquid Glass)
async function initHistoryDatePicker() {
    const input = document.getElementById('histDateInput');
    if (!input || !window.flatpickr) return;
    if (deliveryState.datePickerInstance) return;

    // Busca as datas disponíveis antes de abrir
    await reloadAuditAvailableDates();

    // REGRA DE NEGÓCIO: Fixa como data padrão o ÚLTIMO DIA COM DADOS gravados no banco
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    const yesterdayStr = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;

    let defaultDates = [];
    if (deliveryState.availableAuditDates && deliveryState.availableAuditDates.length > 0) {
        // Seleciona a data mais recente com dados (ex: ontem ou hoje se houver)
        defaultDates = [deliveryState.availableAuditDates[0]];
    } else {
        defaultDates = [yesterdayStr];
    }

    deliveryState.selectedAuditDates = defaultDates;
    deliveryState.historyDate = defaultDates[0];

    deliveryState.datePickerInstance = flatpickr(input, {
        mode: "multiple",
        dateFormat: "Y-m-d",
        altInput: true,
        altFormat: "d/m/Y",
        conjunction: " | ",
        defaultDate: defaultDates,
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
        onDayCreate: function(dObj, dStr, fp, dayElem) {
            if (!dayElem || !dayElem.dateObj) return;
            const y = dayElem.dateObj.getFullYear();
            const m = String(dayElem.dateObj.getMonth() + 1).padStart(2, '0');
            const d = String(dayElem.dateObj.getDate()).padStart(2, '0');
            const ymd = `${y}-${m}-${d}`;
            if (deliveryState.availableAuditDates && deliveryState.availableAuditDates.includes(ymd)) {
                dayElem.classList.add('has-audit-data');
                dayElem.setAttribute('title', 'Dados gravados no banco de auditoria');
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

    // Carrega dados da data padrão inicial
    if (defaultDates && defaultDates[0]) {
        loadDailyHistoryAudit(defaultDates[0]);
        loadTargetsComparativeAudit(defaultDates[0], deliveryState.activeRegion || 'Norte');
    }
}

function handleAuditDatesSelected(dates) {
    if (!dates || dates.length === 0) return;

    const viewDay = document.getElementById('histViewDayContainer');
    const viewComp = document.getElementById('histViewComparisonContainer');
    const viewMonth = document.getElementById('histViewMonthContainer');

    if (viewMonth) viewMonth.style.display = 'none';

    // Dispara o cálculo do comparativo de metas (calculando média diária se > 1 data)
    const datesStr = dates.join(',');
    loadTargetsComparativeAudit(datesStr, deliveryState.activeRegion || 'Norte');

    if (dates.length === 1) {
        if (viewDay) viewDay.style.display = 'block';
        if (viewComp) viewComp.style.display = 'none';
        loadDailyHistoryAudit(dates[0]);
        const m = dates[0].slice(0, 7);
        const selMonth = document.getElementById('wfFilterMonth');
        const wfMonthInput = document.getElementById('histWorkforceMonthInput');
        if (selMonth && selMonth.value !== m) selMonth.value = m;
        if (wfMonthInput) wfMonthInput.value = m;
        loadWorkforceMonthlyChart(m);
    } else {
        if (viewDay) viewDay.style.display = 'none';
        if (viewComp) viewComp.style.display = 'block';
        loadComparisonAudit(dates);
    }
}

function clearSelectedAuditDates() {
    if (deliveryState.datePickerInstance) {
        const todayStr = getOperationalDate();
        deliveryState.datePickerInstance.setDate([todayStr], true);
    }
}

function refreshCurrentHistoryAudit() {
    const datesToPass = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates.length > 0)
        ? deliveryState.selectedAuditDates.join(',')
        : deliveryState.historyDate;
    const target = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates[0]) || deliveryState.historyDate;
    loadDailyHistoryAudit(target);
    loadTargetsComparativeAudit(datesToPass, deliveryState.activeRegion || 'Norte');
    loadWorkforceMonthlyChart();
}

// Filtro de Confronto Spotfire
function setAuditReconciliationFilter(filterKey) {
    deliveryState.auditReconciliationFilter = filterKey;
    const btns = {
        all: document.getElementById('btnFilterReconcileAll'),
        both: document.getElementById('btnFilterReconcileBoth'),
        spotfire_only: document.getElementById('btnFilterReconcileExtra'),
        eb_only: document.getElementById('btnFilterReconcileEbOnly'),
        logoff: document.getElementById('btnFilterReconcileSuccess')
    };
    Object.keys(btns).forEach(k => {
        if (btns[k]) {
            if (k === filterKey) btns[k].classList.add('active');
            else btns[k].classList.remove('active');
        }
    });
    // Se o usuário clicou para filtrar e a tabela estiver recolhida, expande para visualizar
    if (!deliveryState.histTableExpanded) {
        toggleHistTableCollapse(true);
    } else {
        renderDailyAuditTable();
    }
}

// Alterna Recolher / Expandir da Tabela Nominal de Auditoria
function toggleHistTableCollapse(forceExpand = null) {
    const tableBody = document.getElementById('histTableCollapseBody');
    const placeholder = document.getElementById('histTablePlaceholder');
    const textEl = document.getElementById('textToggleHistTable');
    const iconEl = document.getElementById('iconToggleHistTable');

    if (forceExpand !== null) {
        deliveryState.histTableExpanded = forceExpand;
    } else {
        deliveryState.histTableExpanded = !deliveryState.histTableExpanded;
    }

    if (deliveryState.histTableExpanded) {
        if (tableBody) tableBody.style.display = 'block';
        if (placeholder) placeholder.style.display = 'none';
        if (textEl) textEl.textContent = 'RECOLHER TABELA';
        if (iconEl) iconEl.setAttribute('data-lucide', 'chevron-up');
        renderDailyAuditTable();
    } else {
        if (tableBody) tableBody.style.display = 'none';
        if (placeholder) placeholder.style.display = 'block';
        if (textEl) textEl.textContent = 'EXPANDIR TABELA';
        if (iconEl) iconEl.setAttribute('data-lucide', 'chevron-down');
    }
    if (window.lucide) lucide.createIcons();
}

// Disparo Manual de Sincronização do Spotfire via CDP
async function triggerSpotfireManualSync() {
    return handleCarregarBaseClick();
}

// Ação do Botão CARREGAR BASE: Executa o Robô CDP do Scanner 5.0 e atualiza toda a base
async function handleCarregarBaseClick() {
    const btn = document.getElementById('btnCarregarBase');
    const icon = document.getElementById('iconCarregarBase');
    const txt = document.getElementById('txtCarregarBase');
    const origTxt = txt ? txt.textContent : 'Carregar Base';

    if (btn) btn.disabled = true;
    if (icon) icon.classList.add('spin-animation');
    if (txt) txt.textContent = 'Carregando Base...';

    showToast('Iniciando robô CDP do Scanner 5.0 para extrair base completa...', 'info');

    try {
        const resp = await fetch('/api/delivery/spotfire/sync', { method: 'POST' });
        let res = null;
        try {
            res = await resp.json();
        } catch (jsonErr) {
            throw new Error(`Servidor retornou resposta inesperada (${resp.status} ${resp.statusText})`);
        }

        if (resp.ok && res.status === 'success') {
            showToast(`Sucesso! ${res.count || 0} registros do Scanner 5.0 sincronizados com o banco!`, 'success');
            const elUpd = document.getElementById('histReportLastUpdated');
            if (elUpd && res.updated_at) {
                elUpd.textContent = formatDateTimeBR(res.updated_at);
            }
            await reloadAuditAvailableDates();
            refreshCurrentHistoryAudit();
        } else if (res && res.status === 'waiting_login') {
            showToast(res.message, 'warning');
        } else {
            showToast(res ? res.message : 'Aviso durante a atualização do Scanner 5.0.', 'warning');
        }
    } catch (err) {
        showToast('Erro ao comunicar com o robô CDP do Scanner 5.0: ' + err.message, 'danger');
    } finally {
        if (btn) btn.disabled = false;
        if (icon) icon.classList.remove('spin-animation');
        if (txt) txt.textContent = origTxt;
        initIcons();
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

        // Atualiza KPIs do Segmento de Confronto Forense
        const rec = data.reconciliation || {};
        const elAssert = document.getElementById('histReconcileAssertividade');
        const elAmbos = document.getElementById('histReconcileAmbosCount');
        const elOnlySp = document.getElementById('histReconcileOnlySpotfireCount');
        const elOnlyEb = document.getElementById('histReconcileOnlyEbCount');
        const elLogoff = document.getElementById('histReconcileLogoffCount');
        const elTotAudit = document.getElementById('histReconcileTotalAuditCount');
        const elOsProd = document.getElementById('histReconcileOsProdutivas');
        const elOsTot = document.getElementById('histReconcileOsTotal');
        const elPlaceCount = document.getElementById('histTablePlaceholderCount');

        if (elAssert) elAssert.textContent = (rec.assertiveness_rate != null ? rec.assertiveness_rate : 0) + '%';
        if (elAmbos) elAmbos.textContent = rec.total_conciliado_ambos || 0;
        if (elOnlySp) elOnlySp.textContent = rec.total_apenas_spotfire || 0;
        if (elOnlyEb) elOnlyEb.textContent = rec.total_apenas_equipesbrasil || 0;
        if (elLogoff) elLogoff.textContent = rec.total_with_logoff || 0;
        if (elTotAudit) elTotAudit.textContent = rec.total_delivered || 0;
        if (elOsProd) elOsProd.textContent = rec.total_os_produtivas || 0;
        if (elOsTot) elOsTot.textContent = rec.total_os_geral || 0;
        if (elPlaceCount) elPlaceCount.textContent = rec.total_delivered || 0;

        // Renderiza as linhas caso a tabela esteja expandida
        if (deliveryState.histTableExpanded) {
            renderDailyAuditTable();
        }
    } catch (err) {
        console.error('Falha ao carregar histórico diário:', err);
    }
}

// Renderização Reativa da Tabela Nominal de Auditoria
function renderDailyAuditTable() {
    const data = deliveryState.historyDayData;
    const tbody = document.getElementById('histDayTableBody');
    if (!tbody) return;

    if (!data || !data.teams || data.teams.length === 0) {
        tbody.innerHTML = `<tr><td colspan="13" style="text-align: center; padding: 30px; color: var(--text-secondary);">Nenhum registro encontrado para esta data.</td></tr>`;
        return;
    }

    const filterKey = deliveryState.auditReconciliationFilter || 'all';
    let filteredTeams = data.teams;

    if (filterKey === 'both') {
        filteredTeams = data.teams.filter(t => 
            t.status_conciliacao === 'CONCILIADO_TOTAL' || 
            t.status_conciliacao === 'CONCILIADO_AMBOS' || 
            t.status_conciliacao === 'TURNO_EM_ANDAMENTO' ||
            (t.spotfire_reconciled && t.status_conciliacao !== 'APENAS_SPOTFIRE')
        );
    } else if (filterKey === 'spotfire_only') {
        filteredTeams = data.teams.filter(t => t.status_conciliacao === 'APENAS_SPOTFIRE');
    } else if (filterKey === 'eb_only') {
        filteredTeams = data.teams.filter(t => 
            t.status_conciliacao === 'APENAS_EQUIPESBRASIL' || 
            t.status_conciliacao === 'AGUARDANDO_SPOTFIRE'
        );
    } else if (filterKey === 'logoff') {
        filteredTeams = data.teams.filter(t => t.logoff_real && t.logoff_real !== '--' && t.logoff_real !== '--:--');
    }

    if (filteredTeams.length === 0) {
        tbody.innerHTML = `<tr><td colspan="13" style="text-align: center; padding: 30px; color: var(--text-secondary);">Nenhuma equipe encontrada para o filtro de confronto selecionado.</td></tr>`;
        return;
    }

    tbody.innerHTML = filteredTeams.map(t => {
        // Formata Logoff Real
        let logoffHtml = `<span style="color:var(--text-secondary); font-family:'JetBrains Mono', monospace;">--:--</span>`;
        if (t.logoff_real && t.logoff_real !== '--' && t.logoff_real !== '--:--') {
            logoffHtml = `<span class="badge-logoff-closed"><i data-lucide="check"></i> ${t.logoff_real}</span>`;
        }

        // Formata Status de Conciliação
        let statusBadge = '';
        if (t.status_conciliacao === 'CONCILIADO_TOTAL') {
            statusBadge = `<span class="badge-reconcile badge-reconcile-success" title="Turno com LogOff e Produtividade confirmados no Spotfire"><i data-lucide="check-circle-2"></i> 100% CONCILIADO</span>`;
        } else if (t.status_conciliacao === 'CONCILIADO_AMBOS' || t.status_conciliacao === 'TURNO_EM_ANDAMENTO') {
            statusBadge = `<span class="badge-reconcile badge-reconcile-warning" title="Equipe presente no Spotfire e EB, turno em andamento"><i data-lucide="check"></i> CONCILIADO EM AMBOS</span>`;
        } else if (t.status_conciliacao === 'APENAS_SPOTFIRE') {
            statusBadge = `<span class="badge-reconcile badge-reconcile-extra" title="Detectada no Spotfire mas ausente no EquipesBrasil"><i data-lucide="alert-circle"></i> APENAS NO SPOTFIRE</span>`;
        } else {
            statusBadge = `<span class="badge-reconcile badge-reconcile-pending" title="Presente no EquipesBrasil, ausente no Spotfire"><i data-lucide="hourglass"></i> APENAS EQUIPESBRASIL</span>`;
        }

        // Produtividade
        const prod = t.produtivas || 0;
        const totalOs = t.qtd_os || 0;
        const osHtml = `<span title="Produtivas: ${prod} | Total: ${totalOs} | Improdutivas: ${t.improdutiva || 0} | Verificações: ${t.verificacoes || 0}"><strong style="color: #10b981;">${prod}</strong> <small style="color: var(--text-secondary);">/ ${totalOs}</small></span>`;

        // Turno
        const turnoText = t.turno ? `${t.turno} (${t.shift_slot || t.shift_code})` : (t.shift_slot || '--');

        return `
            <tr>
                <td><span class="team-badge" style="font-weight: 800;">${t.team_code}</span></td>
                <td><strong style="color: var(--text-primary);">${t.base_display || t.base_name}</strong></td>
                <td>${t.region} / <small style="font-weight: 800;">${t.company}</small></td>
                <td><strong>${t.vehicle_type}</strong></td>
                <td><span style="color:var(--text-secondary); font-family:'JetBrains Mono', monospace;">${t.login_time || '--:--'}</span></td>
                <td><strong style="color:#38bdf8; font-family:'JetBrains Mono', monospace;">${t.login_real || '--:--'}</strong></td>
                <td>${logoffHtml}</td>
                <td><strong style="color:#a78bfa; font-family:'JetBrains Mono', monospace;">${t.duracao_efetiva || '--'}</strong></td>
                <td>${osHtml}</td>
                <td>${statusBadge}</td>
                <td><span class="shift-pill ${t.shift_pill_class || ''}">${turnoText}</span></td>
                <td>${t.driver || '--'}</td>
                <td><span style="font-family:'JetBrains Mono', monospace;">${t.plate || '--'}</span></td>
            </tr>
        `;
    }).join('');

    if (window.lucide) {
        lucide.createIcons();
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

// ==============================================================================
// METAS OPERACIONAIS E COMPARATIVO (PLAN vs REAL vs GAP) - REGIÕES NORTE & LESTE
// ==============================================================================

function renderTargetsRow(row) {
    let trClass = '';
    if (row.is_grand_total) {
        trClass = 'class="targets-row-total targets-row-grand-total"';
    } else if (row.is_total) {
        trClass = 'class="targets-row-total"';
    }
    const gap = row.gap || 0;
    let gapClass = 'targets-cell-gap';
    let gapText = '0';
    if (gap > 0) {
        gapClass += ' gap-positive';
        gapText = `+${gap}`;
    } else if (gap < 0) {
        gapClass += ' gap-negative';
        gapText = `${gap}`;
    }

    return `
        <tr ${trClass}>
            <td class="targets-cat-name">${row.categoria}</td>
            <td class="targets-num-plan">${row.plan}</td>
            <td class="targets-num-real">${row.real}</td>
            <td class="text-center"><span class="${gapClass}">${gapText}</span></td>
        </tr>
    `;
}

function switchHistoryRegion(region) {
    deliveryState.activeRegion = region;
    const btnNorte = document.getElementById('btnRegionNorte');
    const btnLeste = document.getElementById('btnRegionLeste');
    if (region === 'Norte') {
        if (btnNorte) btnNorte.classList.add('active');
        if (btnLeste) btnLeste.classList.remove('active');
    } else {
        if (btnNorte) btnNorte.classList.remove('active');
        if (btnLeste) btnLeste.classList.add('active');
    }
    const datesToPass = (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates.length > 0)
        ? deliveryState.selectedAuditDates.join(',')
        : deliveryState.historyDate;
    loadTargetsComparativeAudit(datesToPass, region);
}

function formatDateTimeBR(val) {
    if (!val || val === '--' || val === 'None') return '--';
    const str = String(val).trim();
    if (/^\d{2}\/\d{2}\/\d{4}/.test(str)) return str;
    try {
        const cleaned = str.replace('T', ' ').split('.')[0].replace('Z', '');
        if (cleaned.length === 10) {
            const parts = cleaned.split('-');
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        const d = new Date(str);
        if (!isNaN(d.getTime())) {
            const pad = n => String(n).padStart(2, '0');
            return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
        }
    } catch (e) {}
    return str.replace('T', ' ');
}

async function loadTargetsComparativeAudit(targetDate = null, targetRegion = null) {
    let dateVal = targetDate || (deliveryState.selectedAuditDates && deliveryState.selectedAuditDates.length > 0 ? deliveryState.selectedAuditDates.join(',') : deliveryState.historyDate);
    if (dateVal && dateVal.includes('|')) {
        dateVal = dateVal.split('|').map(s => s.trim()).join(',');
    }
    const region = targetRegion || deliveryState.activeRegion || 'Norte';

    try {
        const resp = await fetch(`/api/delivery/targets-audit?date=${encodeURIComponent(dateVal)}&region=${encodeURIComponent(region)}`);
        if (!resp.ok) {
            console.warn(`[TARGETS AUDIT] HTTP ${resp.status} ao consultar metas.`);
            return;
        }
        const data = await resp.json();

        if (data.status === 'success') {
            const tables = data.tables || {};
            const basesBody = document.getElementById('targetBasesTableBody');
            const turnoBody = document.getElementById('targetTurnoTableBody');
            const vehBody = document.getElementById('targetVeiculoTableBody');

            if (basesBody && tables.bases) {
                basesBody.innerHTML = tables.bases.map(renderTargetsRow).join('');
            }
            if (turnoBody && tables.turno) {
                turnoBody.innerHTML = tables.turno.map(renderTargetsRow).join('');
            }
            if (vehBody && tables.veiculo) {
                vehBody.innerHTML = tables.veiculo.map(renderTargetsRow).join('');
            }

            // Atualiza cabeçalhos indicando se é média diária de múltiplas datas
            const isAvg = !!data.is_average;
            const numDays = data.num_days || 1;
            const avgBadge = isAvg ? ` <span style="font-size: 0.72rem; font-weight: 600; color: #38bdf8; text-transform: none; margin-left: 6px;">(MÉDIA ${numDays} DIAS)</span>` : '';
            
            const cards = document.querySelectorAll('.targets-table-card .targets-card-header');
            if (cards && cards.length >= 3) {
                cards[0].innerHTML = `BASES${avgBadge}`;
                cards[1].innerHTML = `TURNO${avgBadge}`;
                cards[2].innerHTML = `TIPO VEÍCULO${avgBadge}`;
            }

            const elUpd = document.getElementById('histReportLastUpdated');
            if (elUpd && data.updated_at) {
                elUpd.textContent = formatDateTimeBR(data.updated_at);
            }

            const fc = data.fleet_cards || {};
            const setNum = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val ?? 0; };
            setNum('fleetValCesto', fc.cesto);
            setNum('fleetValLeve', fc.leve);
            setNum('fleetValMoto', fc.moto);
            setNum('fleetValLv', fc.linhaviva);
            setNum('fleetValMunk', fc.munck);
        }
    } catch (e) {
        console.error('Erro ao carregar comparativo de metas:', e);
    }
}

// ==============================================================================
// FILTROS GERAIS DO PERÍODO & 4 CARDS DE INFORMAÇÕES RÁPIDAS (REATIVOS)
// ==============================================================================

function initPeriodFiltersControls(uniqueDimensions) {
    if (!uniqueDimensions) return;
    
    // Região (Multi-seleção)
    const regList = document.getElementById('wfFilterRegionList');
    if (regList) {
        const regions = uniqueDimensions.regions || ['Região Norte', 'Região Leste'];
        regList.innerHTML = regions.map(r => `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-filter="region" value="${r}" checked>
                <span>${r}</span>
            </label>
        `).join('');
    }

    // Base / UT (Hierarquia Oficial: Região Norte e Região Leste)
    const baseList = document.getElementById('wfFilterBaseList');
    if (baseList) {
        const norteBases = ['Base Fagundes Filho', 'Base Cajati', 'Base Vila Medeiros'];
        const lesteBases = ['Base Monte Santo', 'Base Catumbi', 'Base Aricanduva', 'Base Santo André'];

        baseList.innerHTML = `
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar todas as bases da Região Norte">
                    <input type="checkbox" class="popover-group-checkbox" data-group="regiao-norte" checked>
                    <span>Região Norte</span>
                </label>
                <div class="popover-group-children">
                    ${norteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-filter="base" data-group="regiao-norte" value="${b}" checked>
                            <span>${b}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar todas as bases da Região Leste">
                    <input type="checkbox" class="popover-group-checkbox" data-group="regiao-leste" checked>
                    <span>Região Leste</span>
                </label>
                <div class="popover-group-children">
                    ${lesteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-filter="base" data-group="regiao-leste" value="${b}" checked>
                            <span>${b}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Turno (Multi-seleção)
    const shiftList = document.getElementById('wfFilterShiftList');
    if (shiftList) {
        const shifts = uniqueDimensions.turnos || ['Manhã', 'Tarde', 'Noite'];
        shiftList.innerHTML = shifts.map(s => `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-filter="shift" value="${s}" checked>
                <span>${s}</span>
            </label>
        `).join('');
    }

    // Tipo Veículo (Hierarquia Oficial: TMA e SOT)
    const vehList = document.getElementById('wfFilterVehicleList');
    if (vehList) {
        const tmaVehicles = ['Cesto Aéreo', 'Veículo Leve', 'Moto'];
        const sotVehicles = ['Linha Viva', 'Munck'];

        vehList.innerHTML = `
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar todos os veículos do TMA">
                    <input type="checkbox" class="popover-group-checkbox" data-group="tma" checked>
                    <span>TMA</span>
                </label>
                <div class="popover-group-children">
                    ${tmaVehicles.map(v => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-filter="vehicle" data-group="tma" value="${v}" checked>
                            <span>${v}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar Linha Viva e Munck (SOT)">
                    <input type="checkbox" class="popover-group-checkbox" data-group="sot" checked>
                    <span>SOT</span>
                </label>
                <div class="popover-group-children">
                    ${sotVehicles.map(v => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-filter="vehicle" data-group="sot" value="${v}" checked>
                            <span>${v}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // Gerenciador de Hierarquia: marcar/desmarcar o grupo altera todos os filhos
    document.querySelectorAll('.popover-group-checkbox').forEach(gcb => {
        gcb.addEventListener('change', (e) => {
            const grp = gcb.getAttribute('data-group');
            const isChecked = gcb.checked;
            document.querySelectorAll(`.popover-checkbox[data-group="${grp}"]`).forEach(cb => {
                cb.checked = isChecked;
            });
            syncPeriodFiltersFromDOM();
            applyWorkforcePeriodFilters();
        });
    });

    // Função de sincronização de estado dos grupos pai quando filhos mudam
    function updateGroupCheckboxesState() {
        document.querySelectorAll('.popover-group-checkbox').forEach(gcb => {
            const grp = gcb.getAttribute('data-group');
            const children = Array.from(document.querySelectorAll(`.popover-checkbox[data-group="${grp}"]`));
            if (children.length === 0) return;
            const checkedCount = children.filter(c => c.checked).length;
            gcb.checked = (checkedCount === children.length);
            gcb.indeterminate = (checkedCount > 0 && checkedCount < children.length);
        });
    }

    // Listener de clique para atualizar tudo instantaneamente
    document.querySelectorAll('.popover-checkbox').forEach(cb => {
        cb.addEventListener('change', () => {
            updateGroupCheckboxesState();
            syncPeriodFiltersFromDOM();
            applyWorkforcePeriodFilters();
        });
    });

    syncPeriodFiltersFromDOM();
}

function updateFilterPillLabel(filterType, allCount, selectedCount, firstSelectedValue) {
    const labelId = filterType === 'region' ? 'wfFilterRegionLabel' :
                    filterType === 'base' ? 'wfFilterBaseLabel' :
                    filterType === 'shift' ? 'wfFilterShiftLabel' : 'wfFilterVehicleLabel';
    const el = document.getElementById(labelId);
    if (!el) return;

    if (selectedCount === allCount || (selectedCount > 0 && selectedCount === allCount)) {
        el.textContent = 'Todos';
    } else if (selectedCount === 0) {
        el.textContent = 'Nenhum';
    } else if (selectedCount === 1) {
        el.textContent = firstSelectedValue.replace('Região ', '').replace('Base ', '');
    } else {
        el.textContent = `${selectedCount} sel.`;
    }
}

function syncPeriodFiltersFromDOM() {
    if (!deliveryState.periodFilters) {
        deliveryState.periodFilters = { regions: [], bases: [], shifts: [], vehicles: [] };
    }

    const getSelected = (filterType) => {
        const cbs = Array.from(document.querySelectorAll(`.popover-checkbox[data-filter="${filterType}"]`));
        const checked = cbs.filter(c => c.checked).map(c => c.value);
        updateFilterPillLabel(filterType, cbs.length, checked.length, checked[0] || '');
        return checked;
    };

    deliveryState.periodFilters.regions = getSelected('region');
    deliveryState.periodFilters.bases = getSelected('base');
    deliveryState.periodFilters.shifts = getSelected('shift');
    deliveryState.periodFilters.vehicles = getSelected('vehicle');
}

function setupPeriodFilterDropdowns() {
    if (window._periodFiltersSetupDone) return;
    window._periodFiltersSetupDone = true;

    // Toggle popovers ao clicar nos botões de filtro
    document.querySelectorAll('.period-filter-pill-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const targetId = btn.getAttribute('data-target');
            const targetMenu = document.getElementById(targetId);
            const isAlreadyActive = targetMenu && targetMenu.classList.contains('active');

            // Fecha todos os outros popovers
            document.querySelectorAll('.period-filter-popover').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.period-filter-pill-btn').forEach(b => b.classList.remove('active'));

            if (!isAlreadyActive && targetMenu) {
                targetMenu.classList.add('active');
                btn.classList.add('active');
            }
        });
    });

    // Clique fora fecha popovers
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.dropdown-popover-container')) {
            document.querySelectorAll('.period-filter-popover').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('.period-filter-pill-btn').forEach(b => b.classList.remove('active'));
        }
    });

    // Ações de "Todos" e "Limpar" nos popovers
    document.querySelectorAll('.popover-action-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const action = btn.getAttribute('data-action');
            const filterType = btn.getAttribute('data-filter');
            const listId = filterType === 'region' ? 'wfFilterRegionList' :
                           filterType === 'base' ? 'wfFilterBaseList' :
                           filterType === 'shift' ? 'wfFilterShiftList' : 'wfFilterVehicleList';
            const container = document.getElementById(listId);
            if (!container) return;

            container.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.checked = (action === 'select-all');
                cb.indeterminate = false;
            });

            syncPeriodFiltersFromDOM();
            applyWorkforcePeriodFilters();
        });
    });

    // Listener para o seletor principal de mês
    const wfMonthSel = document.getElementById('wfFilterMonth');
    if (wfMonthSel) {
        wfMonthSel.addEventListener('change', (e) => {
            const val = e.target.value;
            loadWorkforceMonthlyChart(val);
        });
    }
}

function applyWorkforcePeriodFilters() {
    const rawData = deliveryState.monthlyRawData || [];
    const f = deliveryState.periodFilters || { regions: [], bases: [], shifts: [], vehicles: [] };

    const hasFilters = (f.regions && f.regions.length > 0) ||
                       (f.bases && f.bases.length > 0) ||
                       (f.shifts && f.shifts.length > 0) ||
                       (f.vehicles && f.vehicles.length > 0);

    let days = [];
    let filtered = [];
    const dayCounts = {};

    if (!hasFilters && deliveryState.historyMonthlyDays && deliveryState.historyMonthlyDays.length > 0) {
        // Fast-path otimizado (0.01ms): usa os dias pré-agregados do backend
        days = deliveryState.historyMonthlyDays.map(d => ({ ...d }));
        filtered = rawData;
        days.forEach(d => {
            if (d.total_teams > 0) dayCounts[d.date] = d.total_teams;
        });
    } else {
        // Filtra instantaneamente em memória (<1ms)
        filtered = rawData.filter(r => {
            const matchReg = f.regions.length === 0 || f.regions.includes(r.region);
            const matchBase = f.bases.length === 0 || f.bases.includes(r.base);
            const matchShift = f.shifts.length === 0 || f.shifts.includes(r.turno);
            const matchVeh = f.vehicles.length === 0 || f.vehicles.includes(r.vehicle_type);
            return matchReg && matchBase && matchShift && matchVeh;
        });

        // Agrupa contagem por dia (YYYY-MM-DD)
        filtered.forEach(r => {
            const d = r.date;
            if (d) {
                dayCounts[d] = (dayCounts[d] || 0) + 1;
            }
        });

        // Ordena todos os dias disponíveis no mês
        const allDaysInMonth = Array.from(new Set(rawData.map(r => r.date).filter(Boolean))).sort();
        days = allDaysInMonth.map(d => ({
            date: d,
            total_teams: dayCounts[d] || 0
        }));
    }

    // Métricas dos 4 Cards de Informações Rápidas
    const totalDeliveries = filtered.length;
    const activeDaysKeys = Object.keys(dayCounts).filter(k => dayCounts[k] > 0);
    const activeDaysCount = activeDaysKeys.length || (days.length || 1);
    const avgTeamsNum = activeDaysCount > 0 ? (totalDeliveries / activeDaysCount) : 0;
    const avgTeamsStr = avgTeamsNum.toFixed(1);

    // Identifica o dia com maior pico de entrega
    let peakCount = 0;
    let peakDateStr = "--/--";
    days.forEach(d => {
        if (d.total_teams > peakCount) {
            peakCount = d.total_teams;
            const pts = d.date.split('-');
            if (pts.length === 3) {
                peakDateStr = `${pts[2]}/${pts[1]}`;
            }
        }
    });

    // Meta planejada correspondente aos filtros aplicados
    let targetMeta = 226;
    const targets = deliveryState.planningTargets || {};
    const allBases = (deliveryState.uniqueDimensions && deliveryState.uniqueDimensions.bases) || [];
    const allVehs = (deliveryState.uniqueDimensions && deliveryState.uniqueDimensions.vehicles) || [];
    const allShifts = (deliveryState.uniqueDimensions && deliveryState.uniqueDimensions.turnos) || [];
    const hasNorte = f.regions.length === 0 || f.regions.some(r => r.includes('Norte'));
    const hasLeste = f.regions.length === 0 || f.regions.some(r => r.includes('Leste'));

    if (f.vehicles.length > 0 && f.vehicles.length < allVehs.length) {
        let vehSum = 0;
        f.vehicles.forEach(vName => {
            const key = (vName === 'Linha Viva') ? 'LV' : (vName === 'Munck') ? 'Munk' : vName;
            const nV = (hasNorte && targets.Norte && targets.Norte.veiculo) ? (targets.Norte.veiculo[key] || targets.Norte.veiculo[vName] || 0) : 0;
            const lV = (hasLeste && targets.Leste && targets.Leste.veiculo) ? (targets.Leste.veiculo[key] || targets.Leste.veiculo[vName] || 0) : 0;
            vehSum += (nV + lV);
        });
        targetMeta = vehSum > 0 ? vehSum : Math.round(226 * (f.vehicles.length / Math.max(allVehs.length, 1)));
    } else if (f.bases.length > 0 && f.bases.length < allBases.length) {
        let baseSum = 0;
        f.bases.forEach(bName => {
            const cleanB = bName.replace('Base ', '').trim();
            const nMeta = (targets.Norte && targets.Norte.bases) ? (targets.Norte.bases[cleanB] || 0) : 0;
            const lMeta = (targets.Leste && targets.Leste.bases) ? (targets.Leste.bases[cleanB] || 0) : 0;
            baseSum += (nMeta + lMeta);
        });
        targetMeta = baseSum > 0 ? baseSum : Math.round(226 * (f.bases.length / Math.max(allBases.length, 1)));
    } else if (f.shifts.length > 0 && f.shifts.length < allShifts.length) {
        let shiftSum = 0;
        f.shifts.forEach(sName => {
            const nS = (hasNorte && targets.Norte && targets.Norte.turno) ? (targets.Norte.turno[sName] || 0) : 0;
            const lS = (hasLeste && targets.Leste && targets.Leste.turno) ? (targets.Leste.turno[sName] || 0) : 0;
            shiftSum += (nS + lS);
        });
        targetMeta = shiftSum > 0 ? shiftSum : Math.round(226 * (f.shifts.length / Math.max(allShifts.length, 1)));
    } else if (hasNorte && !hasLeste && targets.Norte) {
        targetMeta = Object.values(targets.Norte.bases || {}).reduce((a, b) => a + b, 0);
    } else if (hasLeste && !hasNorte && targets.Leste) {
        targetMeta = Object.values(targets.Leste.bases || {}).reduce((a, b) => a + b, 0);
    } else if (targets.daily_meta) {
        targetMeta = targets.daily_meta;
    }

    const adherencePct = targetMeta > 0 ? Math.round((avgTeamsNum / targetMeta) * 100) : 0;

    // Atualiza os 4 Cards
    const setTxt = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    setTxt('wfKpiAvgTeams', avgTeamsStr);
    setTxt('wfKpiAdherence', `${adherencePct}%`);
    const bar = document.getElementById('wfKpiAdherenceBar');
    if (bar) bar.style.width = `${Math.min(adherencePct, 100)}%`;
    setTxt('wfKpiPlanMeta', targetMeta);
    setTxt('wfKpiPeakTeams', peakCount);
    setTxt('wfKpiPeakDate', peakDateStr);
    setTxt('wfKpiTotalTeams', totalDeliveries);
    setTxt('wfKpiDaysCount', activeDaysCount);

    // Atualiza legendas no cabeçalho do gráfico
    setTxt('legendPlannedNumber', targetMeta);
    setTxt('legendAvgNumber', avgTeamsStr);

    // Calcula acumulados para tooltips ricos
    let runReal = 0;
    let runPlan = 0;
    days.forEach(d => {
        runReal += d.total_teams;
        runPlan += targetMeta;
        d.planned = targetMeta;
        d.cumulative_real = runReal;
        d.cumulative_plan = runPlan;
        d.gap_accumulated = runReal - runPlan;
    });

    // Redesenha o gráfico de evolução diária da força de trabalho
    renderWorkforceMonthlyChart({
        daily_meta: targetMeta,
        avg_total: avgTeamsNum,
        days: days
    });

    if (window.lucide) {
        try { lucide.createIcons(); } catch (e) {}
    }
}

async function loadWorkforceMonthlyChart(targetMonth = null) {
    const sel = document.getElementById('wfFilterMonth') || document.getElementById('histWorkforceMonthSelect');
    let monthVal = targetMonth || (sel && sel.value ? sel.value : deliveryState.historyMonth);
    if (!monthVal) {
        monthVal = new Date().toISOString().slice(0, 7);
    }

    const mSel1 = document.getElementById('wfFilterMonth');
    const mSel2 = document.getElementById('histWorkforceMonthSelect');
    if (mSel1 && mSel1.value !== monthVal) mSel1.value = monthVal;
    if (mSel2 && mSel2.value !== monthVal) mSel2.value = monthVal;
    deliveryState.historyMonth = monthVal;

    try {
        const resp = await fetch(`/api/delivery/monthly?month=${monthVal}`);
        const data = await resp.json();
        
        if (data.status !== 'success') {
            console.warn('[WORKFORCE] Resposta com status não-sucesso:', data.message);
            return;
        }

        deliveryState.monthlyRawData = data.raw_records || [];
        deliveryState.historyMonthlyDays = data.days || [];
        deliveryState.uniqueDimensions = data.unique_dimensions || {};
        deliveryState.planningTargets = data.planning_targets || {};

        setupPeriodFilterDropdowns();
        initPeriodFiltersControls(deliveryState.uniqueDimensions);
        applyWorkforcePeriodFilters();
    } catch (e) {
        console.error('Erro ao carregar evolução diária da força de trabalho:', e);
    }
}

function renderWorkforceMonthlyChart(monthlyData) {
    const canvas = document.getElementById('histWorkforceChart');
    if (!canvas || !window.Chart) return;

    if (deliveryState.workforceChart) {
        deliveryState.workforceChart.destroy();
    }

    const days = monthlyData.days || [];
    if (days.length === 0) return;

    const labels = days.map(d => {
        const p = d.date.split('-');
        return `${p[2]}/${p[1]}`;
    });
    const realData = days.map(d => d.total_teams);
    const dailyMeta = monthlyData.daily_meta || 226;
    const planData = days.map(d => d.planned || dailyMeta);
    const avgVal = monthlyData.avg_total || 0;
    const avgData = days.map(() => avgVal);

    const isLight = document.body.classList.contains('theme-light');
    const textColor = isLight ? '#0f172a' : '#f8fafc';
    const gridColor = isLight ? 'rgba(0, 0, 0, 0.06)' : 'rgba(255, 255, 255, 0.06)';

    const ctx = canvas.getContext('2d');
    const gradient = ctx.createLinearGradient(0, 0, 0, 320);
    gradient.addColorStop(0, 'rgba(37, 99, 235, 0.45)');
    gradient.addColorStop(0.7, 'rgba(37, 99, 235, 0.1)');
    gradient.addColorStop(1, 'rgba(37, 99, 235, 0.0)');

    function createHatchedPattern() {
        const pCanvas = document.createElement('canvas');
        pCanvas.width = 10;
        pCanvas.height = 10;
        const pctx = pCanvas.getContext('2d');
        pctx.fillStyle = 'rgba(245, 158, 11, 0.16)';
        pctx.fillRect(0, 0, 10, 10);
        pctx.strokeStyle = '#f59e0b';
        pctx.lineWidth = 2.2;
        pctx.beginPath();
        pctx.moveTo(0, 10);
        pctx.lineTo(10, 0);
        pctx.stroke();
        return pctx.createPattern(pCanvas, 'repeat');
    }

    const hatchedPattern = createHatchedPattern();

    deliveryState.workforceChart = new Chart(canvas, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    type: 'line',
                    label: 'REAL',
                    data: realData,
                    borderColor: '#2563eb',
                    borderWidth: 3,
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 4,
                    pointHoverRadius: 7,
                    pointBackgroundColor: '#2563eb',
                    pointBorderColor: '#ffffff',
                    pointBorderWidth: 2,
                    order: 1
                },
                {
                    type: 'line',
                    label: `MÉDIA REAL (${avgVal.toFixed(1)})`,
                    data: avgData,
                    borderColor: '#10b981',
                    borderWidth: 2.5,
                    borderDash: [6, 5],
                    pointRadius: 0,
                    fill: false,
                    tension: 0,
                    order: 0
                },
                {
                    type: 'bar',
                    label: `PLANEJADO (${dailyMeta})`,
                    data: planData,
                    backgroundColor: hatchedPattern,
                    borderColor: '#d97706',
                    borderWidth: 1.5,
                    borderRadius: 6,
                    barPercentage: 0.65,
                    categoryPercentage: 0.8,
                    order: 2
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: {
                        color: textColor,
                        font: { family: 'Plus Jakarta Sans', weight: '700', size: 11 }
                    }
                },
                y: {
                    beginAtZero: true,
                    suggestedMax: (() => {
                        const maxReal = Math.max(0, ...(realData.length > 0 ? realData : [0]));
                        const maxVal = Math.max(maxReal, dailyMeta || 0);
                        return maxVal > 0 ? Math.ceil(maxVal * 1.18) + (maxVal < 20 ? 2 : 5) : 50;
                    })(),
                    grid: { color: gridColor },
                    ticks: {
                        color: textColor,
                        font: { family: 'JetBrains Mono', size: 11 },
                        precision: 0
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    enabled: false,
                    external: function(context) {
                        const tooltipEl = document.getElementById('workforceCustomTooltip');
                        if (!tooltipEl) return;
                        const tooltipModel = context.tooltip;
                        if (tooltipModel.opacity === 0) {
                            tooltipEl.style.opacity = '0';
                            return;
                        }
                        const dataIndex = tooltipModel.dataPoints && tooltipModel.dataPoints[0] ? tooltipModel.dataPoints[0].dataIndex : null;
                        if (dataIndex === null) return;
                        const dayObj = days[dataIndex];
                        if (!dayObj) return;

                        const dateParts = dayObj.date.split('-');
                        const formattedDate = `${dateParts[2]}/${dateParts[1]}/${dateParts[0]}`;
                        const realVal = dayObj.total_teams;
                        const planVal = dayObj.planned || dailyMeta;
                        const cumReal = dayObj.cumulative_real;
                        const cumPlan = dayObj.cumulative_plan;
                        const cumGap = dayObj.gap_accumulated;
                        const cumGapSign = cumGap > 0 ? `+${cumGap}` : `${cumGap}`;
                        const cumGapColor = cumGap >= 0 ? '#10b981' : '#ef4444';

                        tooltipEl.innerHTML = `
                            <div class="tooltip-date-header">
                                📅 ${formattedDate}
                            </div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label"><span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#2563eb;"></span> REAL:</span>
                                <span class="tooltip-stat-val text-cyan">${realVal}</span>
                            </div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label"><span style="display:inline-block; width:8px; height:8px; background:#f59e0b; border-radius:2px;"></span> PLANEJADO:</span>
                                <span class="tooltip-stat-val" style="color:#f59e0b;">${planVal}</span>
                            </div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label"><span style="display:inline-block; width:8px; height:2px; background:#10b981;"></span> MÉDIA REAL:</span>
                                <span class="tooltip-stat-val text-emerald">${avgVal.toFixed(1)}</span>
                            </div>
                            <div class="tooltip-divider"></div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label" style="font-size:0.75rem; color:#94a3b8;">Acumulado Planejado:</span>
                                <span class="tooltip-stat-val" style="font-size:0.78rem;">${cumPlan}</span>
                            </div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label" style="font-size:0.75rem; color:#60a5fa;">Acumulado Real:</span>
                                <span class="tooltip-stat-val" style="font-size:0.78rem; color:#60a5fa;">${cumReal}</span>
                            </div>
                            <div class="tooltip-stat-row">
                                <span class="tooltip-stat-label" style="font-size:0.75rem; font-weight:800;">GAP Acumulado:</span>
                                <span class="tooltip-stat-val" style="font-size:0.78rem; color:${cumGapColor}; font-weight:900;">${cumGapSign}</span>
                            </div>
                        `;

                        tooltipEl.style.opacity = '1';
                        tooltipEl.style.left = tooltipModel.caretX + 'px';
                        tooltipEl.style.top = tooltipModel.caretY + 'px';
                    }
                }
            }
        }
    });
}

// ==============================================================================
// MODAL DE GOVERNANÇA E EDIÇÃO DE METAS (ACESSO MASTER)
// ==============================================================================

async function openMasterPlanningModal() {
    openModal('planningMasterModal');
    try {
        const resp = await fetch('/api/delivery/planning/targets');
        const data = await resp.json();
        deliveryState.planningTargets = data;
        populatePlanningForm(data);
    } catch (e) {
        console.error('Erro ao carregar metas:', e);
    }

    if (authState.isAuthenticated && authState.user && authState.user.role === 'admin') {
        unlockPlanningFields();
    } else {
        lockPlanningFields();
    }
}

function verifyAndUnlockPlanning() {
    const passInput = document.getElementById('planningMasterPassword');
    const pass = (passInput ? passInput.value : '').trim();
    if (['Tim@3021', 'admin3021', 'master3021'].includes(pass) || (authState.isAuthenticated && authState.user && authState.user.role === 'admin')) {
        unlockPlanningFields();
        showToast('Acesso Master autenticado! Modo de edição liberado.', 'success');
    } else {
        showToast('Senha Master incorreta! Acesso negado.', 'danger');
    }
}

function unlockPlanningFields() {
    const fieldset = document.getElementById('planningFieldset');
    const btnSave = document.getElementById('btnSavePlanningModal');
    const authInputs = document.getElementById('planningAuthInputs');
    const unlockedBadge = document.getElementById('planningUnlockedBadge');
    if (fieldset) fieldset.disabled = false;
    if (btnSave) btnSave.disabled = false;
    if (authInputs) authInputs.style.display = 'none';
    if (unlockedBadge) unlockedBadge.style.display = 'inline-flex';
}

function lockPlanningFields() {
    const fieldset = document.getElementById('planningFieldset');
    const btnSave = document.getElementById('btnSavePlanningModal');
    const authInputs = document.getElementById('planningAuthInputs');
    const unlockedBadge = document.getElementById('planningUnlockedBadge');
    if (fieldset) fieldset.disabled = true;
    if (btnSave) btnSave.disabled = true;
    if (authInputs) authInputs.style.display = 'flex';
    if (unlockedBadge) unlockedBadge.style.display = 'none';
}

function switchPlanningModalTab(region) {
    const btnNorte = document.getElementById('btnPlanTabNorte');
    const btnLeste = document.getElementById('btnPlanTabLeste');
    const paneNorte = document.getElementById('planPaneNorte');
    const paneLeste = document.getElementById('planPaneLeste');
    if (region === 'Norte') {
        if (btnNorte) btnNorte.classList.add('active');
        if (btnLeste) btnLeste.classList.remove('active');
        if (paneNorte) paneNorte.style.display = 'block';
        if (paneLeste) paneLeste.style.display = 'none';
    } else {
        if (btnNorte) btnNorte.classList.remove('active');
        if (btnLeste) btnLeste.classList.add('active');
        if (paneNorte) paneNorte.style.display = 'none';
        if (paneLeste) paneLeste.style.display = 'block';
    }
}

function populatePlanningForm(data) {
    if (!data) return;
    if (data.daily_meta) {
        const metaInput = document.getElementById('planInputDailyMeta');
        if (metaInput) metaInput.value = data.daily_meta;
    }
    const norte = data.Norte || {};
    const leste = data.Leste || {};

    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

    const nb = norte.bases || {};
    const nt = norte.turno || {};
    const nv = norte.veiculo || {};
    setVal('planNorteBaseFagundes', nb['Fagundes Filho'] ?? 42);
    setVal('planNorteBaseCajati', nb['Cajati'] ?? 24);
    setVal('planNorteBaseVilaMedeiros', nb['Vila Medeiros'] ?? 28);
    setVal('planNorteBaseLv', nb['LV'] ?? 10);
    setVal('planNorteBaseMunk', nb['Munk'] ?? nb['Munck'] ?? 5);

    setVal('planNorteTurnoManha', nt['Manhã'] ?? 54);
    setVal('planNorteTurnoTarde', nt['Tarde'] ?? 42);
    setVal('planNorteTurnoNoite', nt['Noite'] ?? 13);

    setVal('planNorteVehCesto', nv['Cesto Aéreo'] ?? 68);
    setVal('planNorteVehLeve', nv['Veículo Leve'] ?? 13);
    setVal('planNorteVehMoto', nv['Moto'] ?? 13);
    setVal('planNorteVehLv', nv['LV'] ?? 10);
    setVal('planNorteVehMunk', nv['Munk'] ?? nv['Munck'] ?? 5);

    const lb = leste.bases || {};
    const lt = leste.turno || {};
    const lv = leste.veiculo || {};
    setVal('planLesteBaseMonteSanto', lb['Monte Santo'] ?? 33);
    setVal('planLesteBaseCatumbi', lb['Catumbi'] ?? 21);
    setVal('planLesteBaseAricanduva', lb['Aricanduva'] ?? 34);
    setVal('planLesteBaseSantoAndre', lb['Santo André'] ?? 7);
    setVal('planLesteBaseLv', lb['LV'] ?? 0);
    setVal('planLesteBaseMunk', lb['Munk'] ?? lb['Munck'] ?? 0);

    setVal('planLesteTurnoManha', lt['Manhã'] ?? 35);
    setVal('planLesteTurnoTarde', lt['Tarde'] ?? 35);
    setVal('planLesteTurnoNoite', lt['Noite'] ?? 25);

    setVal('planLesteVehCesto', lv['Cesto Aéreo'] ?? 75);
    setVal('planLesteVehLeve', lv['Veículo Leve'] ?? 15);
    setVal('planLesteVehMoto', lv['Moto'] ?? 5);
    setVal('planLesteVehLv', lv['LV'] ?? 0);
    setVal('planLesteVehMunk', lv['Munk'] ?? lv['Munck'] ?? 0);
}

async function savePlanningTargets() {
    const btn = document.getElementById('btnSavePlanningModal');
    const passInput = document.getElementById('planningMasterPassword');
    const pass = (passInput ? passInput.value : '').trim() || 'Tim@3021';
    const email = (authState.user && authState.user.email) || 'admin@alpitelbrasil.com.br';

    const dailyMeta = parseInt(document.getElementById('planInputDailyMeta')?.value || '226', 10);

    const targets = {
        daily_meta: dailyMeta,
        Norte: {
            bases: {
                "Fagundes Filho": parseInt(document.getElementById('planNorteBaseFagundes')?.value || '0', 10),
                "Cajati": parseInt(document.getElementById('planNorteBaseCajati')?.value || '0', 10),
                "Vila Medeiros": parseInt(document.getElementById('planNorteBaseVilaMedeiros')?.value || '0', 10),
                "LV": parseInt(document.getElementById('planNorteBaseLv')?.value || '0', 10),
                "Munk": parseInt(document.getElementById('planNorteBaseMunk')?.value || '0', 10)
            },
            turno: {
                "Manhã": parseInt(document.getElementById('planNorteTurnoManha')?.value || '0', 10),
                "Tarde": parseInt(document.getElementById('planNorteTurnoTarde')?.value || '0', 10),
                "Noite": parseInt(document.getElementById('planNorteTurnoNoite')?.value || '0', 10)
            },
            veiculo: {
                "Cesto Aéreo": parseInt(document.getElementById('planNorteVehCesto')?.value || '0', 10),
                "Veículo Leve": parseInt(document.getElementById('planNorteVehLeve')?.value || '0', 10),
                "Moto": parseInt(document.getElementById('planNorteVehMoto')?.value || '0', 10),
                "LV": parseInt(document.getElementById('planNorteVehLv')?.value || '0', 10),
                "Munk": parseInt(document.getElementById('planNorteVehMunk')?.value || '0', 10)
            }
        },
        Leste: {
            bases: {
                "Monte Santo": parseInt(document.getElementById('planLesteBaseMonteSanto')?.value || '0', 10),
                "Catumbi": parseInt(document.getElementById('planLesteBaseCatumbi')?.value || '0', 10),
                "Aricanduva": parseInt(document.getElementById('planLesteBaseAricanduva')?.value || '0', 10),
                "Santo André": parseInt(document.getElementById('planLesteBaseSantoAndre')?.value || '0', 10),
                "LV": parseInt(document.getElementById('planLesteBaseLv')?.value || '0', 10),
                "Munk": parseInt(document.getElementById('planLesteBaseMunk')?.value || '0', 10)
            },
            turno: {
                "Manhã": parseInt(document.getElementById('planLesteTurnoManha')?.value || '0', 10),
                "Tarde": parseInt(document.getElementById('planLesteTurnoTarde')?.value || '0', 10),
                "Noite": parseInt(document.getElementById('planLesteTurnoNoite')?.value || '0', 10)
            },
            veiculo: {
                "Cesto Aéreo": parseInt(document.getElementById('planLesteVehCesto')?.value || '0', 10),
                "Veículo Leve": parseInt(document.getElementById('planLesteVehLeve')?.value || '0', 10),
                "Moto": parseInt(document.getElementById('planLesteVehMoto')?.value || '0', 10),
                "LV": parseInt(document.getElementById('planLesteVehLv')?.value || '0', 10),
                "Munk": parseInt(document.getElementById('planLesteVehMunk')?.value || '0', 10)
            }
        }
    };

    if (btn) {
        btn.disabled = true;
        btn.innerHTML = `<i data-lucide="loader" class="spin-animation"></i> Salvando...`;
    }

    try {
        const resp = await fetch('/api/delivery/planning/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                master_password: pass,
                user_email: email,
                targets: targets
            })
        });
        const res = await resp.json();
        if (res.status === 'success') {
            showToast('Planejamento operacional atualizado com sucesso!', 'success');
            closeModal('planningMasterModal');
            loadTargetsComparativeAudit();
            loadWorkforceMonthlyChart();
        } else {
            showToast(res.message || 'Erro ao salvar planejamento.', 'danger');
        }
    } catch (e) {
        showToast(`Erro na comunicação: ${e.message}`, 'danger');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i data-lucide="save" style="width: 16px; height: 16px;"></i><span>Salvar Planejamento</span>`;
            if (window.lucide) lucide.createIcons();
        }
    }
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
        "Login Enel": t.login_time || '--:--',
        "Login Real (Spotfire)": t.login_real || '--:--',
        "LogOff Real (Spotfire)": t.logoff_real || '--:--',
        "Duração Efetiva": t.duracao_efetiva || '--',
        "OS Produtivas": t.produtivas || 0,
        "OS Improdutivas": t.improdutiva || 0,
        "Total OS": t.qtd_os || 0,
        "Rejeita": t.rejeita || 'NÃO',
        "Status Conciliação": t.status_conciliacao || 'AGUARDANDO_SPOTFIRE',
        "Turno": t.shift_slot,
        "Motorista": t.driver,
        "Placa": t.plate
    }));
    if (window.XLSX) {
        const ws = XLSX.utils.json_to_sheet(rows);
        const wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, "Auditoria_Confronto");
        XLSX.writeFile(wb, `Auditoria_Confronto_Spotfire_${data.date}.xlsx`);
        showToast(`Auditoria com confronto Spotfire do dia ${data.date} exportada!`, 'success');
    }
}

// Disparo do Robô CDP
async function triggerEnelCdpCapture() {
    const btn = document.getElementById('btnTriggerEnelCdp');
    const btnText = document.getElementById('triggerEnelCdpText');
    const originalText = btnText ? btnText.textContent : 'Disparar Coleta Imediata Agora (Robô CDP)';
    
    if (btnText) btnText.textContent = 'Robô CDP: Lendo equipes na Enel...';
    if (btn) btn.disabled = true;

    try {
        showToast('Robô CDP acionado! Enviando ordem de coleta...', 'info');
        const resp = await fetch('/api/capture/enel', { method: 'POST' });
        let data = null;
        try {
            data = await resp.json();
        } catch (jsonErr) {
            console.error('[CDP CAPTURE ERROR] Resposta não-JSON:', resp.status);
            throw new Error(`Servidor respondeu com status ${resp.status} (${resp.statusText}).`);
        }
        
        if (resp.ok && data.status === 'success') {
            showToast(`Sucesso! ${data.message || 'Dados sincronizados com o Supabase!'}`, 'success');
            await loadDeliveryData(false);
            if (typeof loadOnlineXBidData === 'function') {
                loadOnlineXBidData().catch(() => {});
            }
            closeModal('deliveryCollectModal');
        } else if (resp.status === 202 || data?.status === 'queued') {
            const cmdId = data.command_id;
            showToast('Ordem enviada ao Robô Local via Nuvem! Aguardando extração...', 'info');
            
            // Polling inteligente de até 30 segundos (15 tentativas a cada 2s)
            let completed = false;
            if (cmdId) {
                for (let attempt = 1; attempt <= 15; attempt++) {
                    if (btnText) btnText.textContent = `Robô Local coletando dados (${attempt * 2}s)...`;
                    await new Promise(r => setTimeout(r, 2000));
                    try {
                        const checkResp = await fetch(`/api/commands/${cmdId}`);
                        if (checkResp.ok) {
                            const cmdStatus = await checkResp.json();
                            if (cmdStatus.status === 'COMPLETED') {
                                showToast('Coleta concluída pelo robô local com sucesso!', 'success');
                                await loadDeliveryData(false);
                                if (typeof loadOnlineXBidData === 'function') {
                                    loadOnlineXBidData().catch(() => {});
                                }
                                closeModal('deliveryCollectModal');
                                completed = true;
                                break;
                            } else if (cmdStatus.status === 'ERROR') {
                                showToast('O robô local reportou erro: ' + (cmdStatus.message || 'Falha na captura.'), 'danger');
                                completed = true;
                                break;
                            }
                        }
                    } catch (pollErr) {
                        console.warn('[POLL WARN]', pollErr);
                    }
                }
            }

            if (!completed) {
                showToast('Comando em processamento pelo robô local. Os dados serão atualizados em instantes via Realtime!', 'info');
                await loadDeliveryData(false);
                if (typeof loadOnlineXBidData === 'function') {
                    loadOnlineXBidData().catch(() => {});
                }
                closeModal('deliveryCollectModal');
            }
        } else {
            showToast(data?.message || 'Aviso durante a coleta da Enel.', 'warning');
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
    const serverUrl = `${window.location.origin}/api/delivery/sync`;
    const daemonCode = `// Script autônomo Enel SP
(function iniciarRoboAutonomoEnel() {
    const LOCAL_SERVER_URL = '${serverUrl}';
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

        // 3. Robô CDP Scanner 5.0 (TIBCO Spotfire)
        const spot = engines.spotfire_cdp || {};
        const bSpot = document.getElementById('engineBadgeSpotfire');
        const mSpot = document.getElementById('engineMsgSpotfire');
        const sSpot = document.getElementById('engineSyncSpotfire');
        const rSpot = document.getElementById('engineRecordsSpotfire');
        if (bSpot) {
            bSpot.className = `engine-status-badge ${spot.status === 'OPERATIONAL' ? 'badge-operational' : (spot.status === 'ERROR_CONNECTION' ? 'badge-error-connection' : 'badge-stopped')}`;
            bSpot.textContent = spot.status === 'OPERATIONAL' ? 'OPERACIONAL' : (spot.status === 'ERROR_CONNECTION' ? 'FALHA DE CONEXÃO' : 'MOTOR PARADO');
        }
        if (mSpot) mSpot.textContent = spot.message || '--';
        if (sSpot) sSpot.textContent = spot.last_sync || '--:--:--';
        if (rSpot) rSpot.textContent = `${spot.records || 0} metas`;

        // 4. Robô CDP BidTech (Checklist Operacional)
        const bid = engines.bid_cdp || {};
        const bBid = document.getElementById('engineBadgeBid');
        const mBid = document.getElementById('engineMsgBid');
        const sBid = document.getElementById('engineSyncBid');
        const rBid = document.getElementById('engineRecordsBid');
        if (bBid) {
            bBid.className = `engine-status-badge ${bid.status === 'OPERATIONAL' ? 'badge-operational' : (bid.status === 'ERROR_CONNECTION' ? 'badge-error-connection' : 'badge-stopped')}`;
            bBid.textContent = bid.status === 'OPERATIONAL' ? 'OPERACIONAL' : (bid.status === 'ERROR_CONNECTION' ? 'FALHA DE CONEXÃO' : 'MOTOR PARADO');
        }
        if (mBid) mBid.textContent = bid.message || '--';
        if (sBid) sBid.textContent = bid.last_sync || '--:--:--';
        if (rBid) rBid.textContent = `${bid.records || 0} equipes`;

        // 5. Supabase Cloud
        const cloud = engines.cloud_sync || {};
        const bCloud = document.getElementById('engineBadgeCloud');
        const mCloud = document.getElementById('engineMsgCloud');
        if (bCloud) {
            bCloud.className = `engine-status-badge ${cloud.status === 'OPERATIONAL' ? 'badge-operational' : 'badge-stopped'}`;
            bCloud.textContent = cloud.status === 'OPERATIONAL' ? 'OPERACIONAL' : 'FALHA DE REDE';
        }
        if (mCloud) mCloud.textContent = cloud.message || '--';

        // 6. Cluster de Redundância (Máquina 1 vs Máquina 2)
        if (data.cluster) {
            renderClusterOverview(data.cluster);
        }

    } catch (err) {
        console.error('Erro ao consultar status dos motores:', err);
    }
}

// ==========================================================================
// GESTÃO DO CLUSTER DE REDUNDÂNCIA (MÁQUINA 1 & MÁQUINA 2)
// ==========================================================================

function renderClusterOverview(cluster) {
    if (!cluster) return;
    const nodes = cluster.nodes || [];
    const activeNodeId = cluster.active_node_id || 'MAQUINA_1_PRINCIPAL';

    // Banner no topo indicando qual máquina está alimentando o banco
    const activeBannerName = document.getElementById('clusterActiveFeederName');
    const activeNodeObj = nodes.find(n => n.node_id === activeNodeId) || nodes.find(n => n.is_feeding_db);
    if (activeBannerName) {
        if (activeNodeObj) {
            activeBannerName.textContent = `${cleanNodeLabel(activeNodeObj.node_label || activeNodeObj.node_id)} (⚡ ATIVO)`;
        } else {
            activeBannerName.textContent = `${cleanNodeLabel(activeNodeId)} (⚡ ATIVO)`;
        }
    }

    // Identifica Nó 1 e Nó 2
    const node1 = nodes.find(n => n.node_id === 'MAQUINA_1_PRINCIPAL' || n.role === 'PRIMARY') || nodes[0] || {};
    const node2 = nodes.find(n => n.node_id === 'MAQUINA_2_BACKUP' || n.role === 'STANDBY') || nodes[1] || {};

    updateNodeCardUI(1, node1, activeNodeId);
    updateNodeCardUI(2, node2, activeNodeId);

    initIcons();
}

function updateNodeCardUI(cardIdx, node, activeNodeId) {
    const isFeeding = Boolean(node.is_feeding_db || (node.node_id === activeNodeId));
    const isCommunicating = node.is_communicating !== false;

    const titleEl = document.getElementById(`nodeTitle${cardIdx}`);
    const subEl = document.getElementById(`nodeSub${cardIdx}`);
    const badgeRoleEl = document.getElementById(`nodeBadgeRole${cardIdx}`);
    const badgeFeedingEl = document.getElementById(`nodeBadgeFeeding${cardIdx}`);
    const hbEl = document.getElementById(`nodeHb${cardIdx}`);
    const cdpEl = document.getElementById(`nodeCdp${cardIdx}`);
    const diagEl = document.getElementById(`nodeDiagMsg${cardIdx}`);
    const btnPromote = document.getElementById(`btnPromoteNode${cardIdx}`);
    const cardEl = document.getElementById(`clusterCardNode${cardIdx}`);

    if (titleEl) titleEl.textContent = cleanNodeLabel(node.node_label) || `Máquina ${cardIdx}`;
    if (subEl) subEl.textContent = `${node.hostname || 'Windows'} | IP: ${node.ip_address || '127.0.0.1'}`;

    if (badgeRoleEl) {
        badgeRoleEl.className = `engine-status-badge ${isCommunicating ? (isFeeding ? 'badge-operational' : 'badge-warning') : 'badge-stopped'}`;
        badgeRoleEl.textContent = isCommunicating ? (node.role === 'PRIMARY' ? 'MÁQUINA PRINCIPAL' : 'MÁQUINA REDUNDANTE') : 'DESCONECTADO';
    }

    if (badgeFeedingEl) {
        if (isFeeding) {
            badgeFeedingEl.style.background = 'rgba(16, 185, 129, 0.25)';
            badgeFeedingEl.style.color = '#10b981';
            badgeFeedingEl.style.borderColor = 'rgba(16, 185, 129, 0.5)';
            badgeFeedingEl.textContent = '⚡ ALIMENTANDO BANCO';
        } else {
            badgeFeedingEl.style.background = 'rgba(255, 255, 255, 0.06)';
            badgeFeedingEl.style.color = 'var(--text-secondary)';
            badgeFeedingEl.style.borderColor = 'var(--border-glass)';
            badgeFeedingEl.textContent = '🛡️ STANDBY PRONTO';
        }
    }

    if (hbEl) {
        if (!node.last_heartbeat) {
            hbEl.textContent = 'Aguardando inicialização';
            hbEl.style.color = 'var(--text-secondary)';
        } else {
            const sec = node.seconds_since_heartbeat || 0;
            if (sec < 60) {
                hbEl.textContent = `Há ${sec}s atrás (${node.last_heartbeat_formatted || ''})`;
                hbEl.style.color = '#10b981';
            } else {
                const min = Math.floor(sec / 60);
                hbEl.textContent = `Há ${min} min atrás`;
                hbEl.style.color = min > 4 ? '#ef4444' : '#f59e0b';
            }
        }
    }

    if (cdpEl) {
        const cdpStatus = node.cdp_port_status || 'UNKNOWN';
        if (cdpStatus === 'OPEN') {
            cdpEl.textContent = '🟢 ABERTA (PORTA 9222 PRONTA)';
            cdpEl.style.color = '#10b981';
        } else if (cdpStatus === 'CLOSED') {
            cdpEl.textContent = '🔴 FECHADA (PORTA 9222 INATIVA)';
            cdpEl.style.color = '#ef4444';
        } else {
            cdpEl.textContent = '🟡 AGUARDANDO NÓ';
            cdpEl.style.color = '#f59e0b';
        }
    }

    if (diagEl) {
        if (isFeeding) {
            diagEl.textContent = 'Coletas ativas gravando no banco Supabase';
            diagEl.style.color = '#a7f3d0';
        } else {
            diagEl.textContent = 'Standby atento: monitorando saúde do servidor líder';
            diagEl.style.color = 'var(--text-secondary)';
        }
    }

    if (btnPromote) {
        if (isFeeding) {
            btnPromote.className = 'btn btn-secondary btn-sm';
            btnPromote.innerHTML = '<i data-lucide="check-circle-2" style="width: 12px; height: 12px; margin-right: 4px;"></i> ATIVA';
            btnPromote.disabled = true;
            btnPromote.style.opacity = '0.7';
        } else {
            btnPromote.className = 'btn btn-warning btn-sm';
            btnPromote.innerHTML = '<i data-lucide="arrow-right-left" style="width: 12px; height: 12px; margin-right: 4px;"></i> ASSUMIR COLETA';
            btnPromote.disabled = false;
            btnPromote.style.opacity = '1';
            const targetId = node.node_id || (cardIdx === 1 ? 'MAQUINA_1_PRINCIPAL' : 'MAQUINA_2_BACKUP');
            btnPromote.onclick = () => promoteNodeAction(targetId);
        }
    }

    if (cardEl) {
        if (isFeeding) {
            cardEl.style.borderColor = 'rgba(16, 185, 129, 0.4)';
            cardEl.style.boxShadow = '0 0 20px rgba(16, 185, 129, 0.15)';
        } else {
            cardEl.style.borderColor = 'rgba(255, 255, 255, 0.08)';
            cardEl.style.boxShadow = 'none';
        }
    }
}

async function promoteNodeAction(targetNodeId) {
    if (!confirm(`Deseja definir a máquina [${targetNodeId}] como a ALIMENTADORA do banco de dados?\n\nOs robôs CDP desta máquina passarão a gravar no Supabase imediatamente, e a outra máquina entrará em Standby para evitar duplicidade de coletas.`)) {
        return;
    }
    try {
        const resp = await fetch('/api/admin/cluster/promote', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${authState.token || ''}`
            },
            body: JSON.stringify({ node_id: targetNodeId })
        });

        const text = await resp.text();
        let res = {};
        try {
            res = JSON.parse(text);
        } catch {
            if (resp.status === 401) {
                showToast('Acesso Restrito: Faça login com matrícula e senha para alternar servidores.', 'danger');
                return;
            } else if (resp.status === 404) {
                showToast('O servidor local precisa ser reiniciado para carregar as novas rotas de cluster.', 'warning');
                return;
            } else {
                showToast(`Erro ${resp.status} na resposta do servidor.`, 'danger');
                return;
            }
        }

        if (resp.ok && res.status === 'success') {
            showToast(res.message || 'Servidor promovido com sucesso!', 'success');
            await loadAdminEngineStatus();
        } else {
            showToast(res.message || 'Falha ao alternar servidor.', 'danger');
        }
    } catch (err) {
        showToast('Erro de comunicação com o servidor: ' + (err.message || err), 'danger');
    }
}

// ==========================================================================
// MODAL DE DETALHES, SESSÃO E TELEMETRIA DA MÁQUINA (CLUSTER)
// ==========================================================================

async function openClusterNodeDetailsModal(nodeId) {
    const modal = document.getElementById('modalClusterNodeDetails');
    if (!modal) return;

    modal.classList.add('active');

    const titleEl = document.getElementById('clusterNodeModalTitle');
    const subEl = document.getElementById('clusterNodeModalSubtitle');
    const statusBadge = document.getElementById('clusterNodeModalStatusBadge');
    const feedingBadge = document.getElementById('clusterNodeModalFeedingBadge');
    const bannerBox = document.getElementById('clusterNodeModalRoleBanner');
    const bannerText = document.getElementById('clusterNodeModalBannerText');
    const bannerIcon = document.getElementById('clusterNodeModalBannerIcon');
    const ipEl = document.getElementById('clusterNodeModalIp');
    const osEl = document.getElementById('clusterNodeModalOs');
    const geoEl = document.getElementById('clusterNodeModalGeo');
    const cdpEl = document.getElementById('clusterNodeModalCdp');
    const hbEl = document.getElementById('clusterNodeModalLastHb');
    const roleEl = document.getElementById('clusterNodeModalRole');
    const enginesGrid = document.getElementById('clusterNodeModalEnginesGrid');
    const actionWrapper = document.getElementById('clusterNodeModalActionWrapper');

    if (titleEl) titleEl.textContent = 'Carregando telemetria...';
    if (enginesGrid) {
        enginesGrid.innerHTML = `
            <div style="grid-column: 1 / -1; text-align: center; padding: 24px; color: var(--text-secondary);">
                <i data-lucide="loader" class="spin-animation" style="width: 24px; height: 24px; margin-bottom: 8px; color: #00f2fe;"></i>
                <p style="margin: 0; font-size: 0.85rem;">Consultando dados da máquina no Supabase...</p>
            </div>
        `;
        initIcons();
    }

    try {
        const resp = await fetch('/api/admin/engine_status');
        const data = await resp.json();
        const cluster = data.cluster || {};
        const nodes = cluster.nodes || [];
        const activeNodeId = cluster.active_node_id || 'MAQUINA_1_PRINCIPAL';

        const node = nodes.find(n => n.node_id === nodeId) || {
            node_id: nodeId,
            node_label: nodeId === 'MAQUINA_1_PRINCIPAL' ? 'Servidor CCO Principal (Máquina 1)' : 'Servidor CCO Redundante (Máquina 2)',
            role: nodeId === 'MAQUINA_1_PRINCIPAL' ? 'PRIMARY' : 'STANDBY',
            is_feeding_db: nodeId === activeNodeId,
            status: 'OFFLINE'
        };

        const isFeeding = Boolean(node.is_feeding_db || (node.node_id === activeNodeId));
        const isCommunicating = node.is_communicating !== false && node.status !== 'OFFLINE';

        if (titleEl) titleEl.textContent = cleanNodeLabel(node.node_label) || nodeId;
        if (subEl) subEl.textContent = `Hostname: ${node.hostname || 'Windows'} • IP: ${node.ip_address || '127.0.0.1'} • Python ${node.python_version || '3.13'}`;

        if (statusBadge) {
            statusBadge.className = `engine-status-badge ${isCommunicating ? 'badge-operational' : 'badge-stopped'}`;
            statusBadge.textContent = isCommunicating ? 'ONLINE & CONECTADO' : 'DESCONECTADO / OFFLINE';
        }

        if (feedingBadge) {
            if (isFeeding) {
                feedingBadge.style.background = 'rgba(16, 185, 129, 0.25)';
                feedingBadge.style.color = '#10b981';
                feedingBadge.style.borderColor = 'rgba(16, 185, 129, 0.5)';
                feedingBadge.textContent = '⚡ ALIMENTANDO O BANCO';
            } else {
                feedingBadge.style.background = 'rgba(245, 158, 11, 0.2)';
                feedingBadge.style.color = '#f59e0b';
                feedingBadge.style.borderColor = 'rgba(245, 158, 11, 0.4)';
                feedingBadge.textContent = '🛡️ STANDBY ATENTO';
            }
        }

        if (bannerBox && bannerText) {
            if (isFeeding) {
                bannerBox.style.background = 'rgba(16, 185, 129, 0.12)';
                bannerBox.style.border = '1px solid rgba(16, 185, 129, 0.35)';
                bannerBox.style.color = '#a7f3d0';
                if (bannerIcon) bannerIcon.style.color = '#10b981';
                bannerText.innerHTML = `<strong>⚡ SERVIDOR ATIVO PRINCIPAL:</strong> Esta máquina é a responsável oficial pela coleta e envio dos dados para o Supabase. As rotinas do Enel SP, Spotfire, BidTech e TRBOnet executam e gravam no banco a partir deste computador.`;
            } else {
                bannerBox.style.background = 'rgba(245, 158, 11, 0.12)';
                bannerBox.style.border = '1px solid rgba(245, 158, 11, 0.35)';
                bannerBox.style.color = '#fde68a';
                if (bannerIcon) bannerIcon.style.color = '#f59e0b';
                bannerText.innerHTML = `<strong>🛡️ MODO STANDBY DE VIGILÂNCIA:</strong> Esta máquina está em prontidão operacional. Ela mantém a porta CDP 9222 aberta e monitora a saúde do servidor líder a cada 20 segundos, porém <u>NÃO grava no banco</u> para evitar duplicidade de sessões e conflitos de login corporativo com o servidor líder. Se o servidor principal falhar por mais de 5 minutos, ela assumirá a coleta automaticamente.`;
            }
        }

        if (ipEl) ipEl.textContent = node.ip_address || '127.0.0.1';
        if (osEl) osEl.textContent = node.os_name || 'Windows 11 (64-bit)';
        if (geoEl) {
            const geo = node.geo_location || {};
            geoEl.textContent = `${geo.city || 'São Paulo'}, ${geo.region || 'SP'} (${geo.country || 'Brasil'}) • ${geo.network || 'Rede CCO'}`;
        }
        if (cdpEl) {
            const cdpStatus = node.cdp_port_status || 'UNKNOWN';
            if (cdpStatus === 'OPEN') {
                cdpEl.textContent = '🟢 Aberta & Escutando (Porta 9222)';
                cdpEl.style.color = '#10b981';
            } else {
                cdpEl.textContent = '🔴 Fechada ou Inacessível';
                cdpEl.style.color = '#ef4444';
            }
        }
        if (hbEl) {
            if (!node.last_heartbeat) {
                hbEl.textContent = 'Sem sinal recente';
                hbEl.style.color = 'var(--text-secondary)';
            } else {
                hbEl.textContent = `${node.last_heartbeat_formatted || node.last_heartbeat} (há ${node.seconds_since_heartbeat || 0}s)`;
                hbEl.style.color = (node.seconds_since_heartbeat || 0) < 60 ? '#10b981' : '#f59e0b';
            }
        }
        if (roleEl) {
            roleEl.textContent = node.role === 'PRIMARY' ? 'Nó Primário (Master)' : 'Nó Secundário (Redundante)';
        }

        // Renderiza grid de motores desta máquina
        if (enginesGrid) {
            const engMap = node.engines_status || {};
            const engNames = [
                { id: 'enel_cdp', label: 'Robô CDP Enel SP', icon: 'users', desc: 'Coleta EquipesBrasil a cada 2 min' },
                { id: 'spotfire_cdp', label: 'Robô CDP Spotfire', icon: 'bar-chart-2', desc: 'Extração Scanner 5.0 a cada 30 min' },
                { id: 'bid_cdp', label: 'Robô CDP BidTech', icon: 'check-square', desc: 'Checklists Visão Operacional 2 min' },
                { id: 'trbonet', label: 'Motor TRBOnet One', icon: 'radio', desc: 'Conciliação de rádios e GPS 2 min' }
            ];

            enginesGrid.innerHTML = engNames.map(e => {
                const isOp = isFeeding ? (engMap[e.id] !== false) : true;
                const statusStr = isFeeding ? (isOp ? 'OPERACIONAL' : 'ALERTA') : 'EM PRONTIDÃO (STANDBY)';
                const statusColor = isFeeding ? (isOp ? '#10b981' : '#ef4444') : '#f59e0b';
                const statusBg = isFeeding ? (isOp ? 'rgba(16,185,129,0.15)' : 'rgba(239,68,68,0.15)') : 'rgba(245,158,11,0.15)';

                return `
                    <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 12px; padding: 12px 14px; display: flex; justify-content: space-between; align-items: center;">
                        <div style="display: flex; align-items: center; gap: 10px;">
                            <div style="width: 32px; height: 32px; border-radius: 8px; background: rgba(0,242,254,0.1); border: 1px solid rgba(0,242,254,0.25); display: flex; align-items: center; justify-content: center; color: #00f2fe;">
                                <i data-lucide="${e.icon}" style="width: 16px; height: 16px;"></i>
                            </div>
                            <div>
                                <strong style="font-size: 0.82rem; color: #fff; display: block;">${e.label}</strong>
                                <span style="font-size: 0.7rem; color: var(--text-secondary);">${e.desc}</span>
                            </div>
                        </div>
                        <span style="font-size: 0.68rem; font-weight: 800; padding: 3px 8px; border-radius: 6px; background: ${statusBg}; color: ${statusColor}; font-family: 'JetBrains Mono', monospace;">
                            ${statusStr}
                        </span>
                    </div>
                `;
            }).join('');
        }

        if (actionWrapper) {
            if (isFeeding) {
                actionWrapper.innerHTML = `
                    <span class="badge" style="padding: 10px 18px; font-size: 0.85rem; font-weight: 800; background: rgba(16,185,129,0.2); color: #10b981; border: 1px solid rgba(16,185,129,0.4); border-radius: 10px;">
                        <i data-lucide="check-circle-2" style="width: 16px; height: 16px; margin-right: 6px; vertical-align: text-bottom;"></i>
                        ESTA MÁQUINA JÁ ESTÁ ALIMENTANDO O BANCO
                    </span>
                `;
            } else {
                actionWrapper.innerHTML = `
                    <button class="btn btn-warning" onclick="promoteNodeAction('${node.node_id}'); closeModal('modalClusterNodeDetails');" style="font-weight: 800; padding: 10px 20px; box-shadow: 0 0 15px rgba(245,158,11,0.3);">
                        <i data-lucide="arrow-right-left" style="width: 16px; height: 16px; margin-right: 6px;"></i>
                        PROMOVER: TORNAR ESTA MÁQUINA A ALIMENTADORA DO BANCO
                    </button>
                `;
            }
        }

        // 7. Renderiza Histórico de Comandos de Transição do Cluster
        const cmdListEl = document.getElementById('clusterNodeModalCommandsList');
        if (cmdListEl) {
            try {
                const cmdResp = await fetch('/api/admin/cluster/commands');
                const cmdData = await cmdResp.json();
                const cmds = cmdData.commands || [];
                if (cmds.length === 0) {
                    cmdListEl.innerHTML = '<div style="font-size: 0.75rem; color: var(--text-secondary); text-align: center; padding: 10px;">Nenhum comando de transição registrado recentemente.</div>';
                } else {
                    cmdListEl.innerHTML = cmds.map(c => {
                        const isDone = c.status === 'COMPLETED';
                        const statusColor = isDone ? '#10b981' : (c.status === 'PROCESSING' ? '#00f2fe' : '#f59e0b');
                        const p = c.payload || {};
                        const r = c.result || {};
                        const actNode = p.active_node_id || '--';
                        const byNode = p.promoted_by || 'Admin';
                        return `
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); border-radius: 8px; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; font-size: 0.76rem;">
                                <div>
                                    <strong style="color: #fff; display: block; font-size: 0.8rem;">${c.command} ➔ Definir Líder: <span style="color: #00f2fe;">${actNode}</span></strong>
                                    <span style="color: var(--text-secondary); font-size: 0.7rem;">Solicitado por ${byNode} • ${c.created_at_br || '--'}</span>
                                    ${r.message ? `<div style="color: #a7f3d0; font-size: 0.68rem; margin-top: 2px;">Resultado: ${r.message}</div>` : ''}
                                </div>
                                <span style="font-size: 0.68rem; font-weight: 800; padding: 2px 8px; border-radius: 6px; background: rgba(255,255,255,0.05); color: ${statusColor}; font-family: 'JetBrains Mono', monospace;">
                                    ${c.status}
                                </span>
                            </div>
                        `;
                    }).join('');
                }
            } catch (cmdErr) {
                console.warn('Erro ao carregar comandos de cluster:', cmdErr);
            }
        }

        initIcons();
    } catch (err) {
        console.error('Erro ao abrir detalhes da máquina do cluster:', err);
    }
}

// ==========================================================================
// MONITOR DE ALERTAS EM TELA PARA USUÁRIOS AUTENTICADOS (LOGIN E SENHA)
// ==========================================================================
let _clusterAlertDismissed = false;

function dismissClusterAlert() {
    _clusterAlertDismissed = true;
    const b = document.getElementById('globalClusterAlertBanner');
    if (b) b.style.display = 'none';
}

async function checkClusterHealthAlerts() {
    // Só exibe alerta para usuários logados com login e senha
    if (!authState || !authState.isAuthenticated) {
        const b = document.getElementById('globalClusterAlertBanner');
        if (b) b.style.display = 'none';
        return;
    }

    try {
        const resp = await fetch('/api/admin/engine_status');
        const data = await resp.json();
        if (data.status !== 'success') return;

        const engines = data.engines || {};
        const cluster = data.cluster || {};
        const nodes = cluster.nodes || [];

        // Verifica falhas nos motores
        const failedEngines = [];
        for (const [k, eng] of Object.entries(engines)) {
            if (k === 'cloud_sync') continue;
            if (eng.status && eng.status !== 'OPERATIONAL') {
                failedEngines.push(eng.label || k);
            }
        }

        // Verifica se a máquina ativa está sem comunicação há mais de 4 minutos
        let activeNodeOffline = false;
        const activeNodeObj = nodes.find(n => n.node_id === cluster.active_node_id || n.is_feeding_db);
        if (activeNodeObj && activeNodeObj.seconds_since_heartbeat > 240) {
            activeNodeOffline = true;
        }

        const banner = document.getElementById('globalClusterAlertBanner');
        const titleEl = document.getElementById('globalClusterAlertTitle');
        const msgEl = document.getElementById('globalClusterAlertMsg');
        const badgeEl = document.getElementById('globalClusterAlertBadge');

        if (failedEngines.length > 0 || activeNodeOffline) {
            if (!_clusterAlertDismissed && banner) {
                banner.style.display = 'block';
                if (activeNodeOffline) {
                    if (titleEl) titleEl.textContent = '⚠️ ALERTA CRÍTICO: SERVIDOR ATIVO OFFLINE';
                    if (msgEl) msgEl.textContent = `A máquina [${activeNodeObj.node_label || cluster.active_node_id}] está sem comunicação há mais de 4 minutos. Considere promover o servidor secundário.`;
                    if (badgeEl) badgeEl.textContent = 'MÁQUINA OFFLINE';
                } else {
                    if (titleEl) titleEl.textContent = '⚠️ ALERTA OPERACIONAL: FALHA EM MOTORES CDP';
                    if (msgEl) msgEl.textContent = `Falha de conexão ou motor parado detectado em: ${failedEngines.join(', ')}. Acesse o Painel de Motores para detalhes.`;
                    if (badgeEl) badgeEl.textContent = `${failedEngines.length} MOTOR(ES) COM FALHA`;
                }
                initIcons();
            }
        } else {
            // Tudo restaurado: reseta estado do alerta
            _clusterAlertDismissed = false;
            if (banner) banner.style.display = 'none';
        }
    } catch (e) {
        console.warn('[CLUSTER ALERT MONITOR] Erro na verificação:', e);
    }
}

let currentSelectedEngine = null;

async function openEngineDetailsModal(engineKey) {
    currentSelectedEngine = engineKey;
    const modal = document.getElementById('modalEngineDetails');
    if (!modal) return;
    
    modal.classList.add('active');
    
    // Elementos do Modal
    const titleEl = document.getElementById('engineDetailTitle');
    const subtitleEl = document.getElementById('engineDetailSubtitle');
    const badgeEl = document.getElementById('engineDetailStatusBadge');
    const syncTimeEl = document.getElementById('engineDetailSyncTime');
    const commTagEl = document.getElementById('engineDetailCommTag');
    const kpisEl = document.getElementById('engineDetailKpis');
    const contentEl = document.getElementById('engineDetailContent');
    const actionText = document.getElementById('btnEngineDetailActionText');
    const iconEl = document.getElementById('engineDetailIcon');
    const badgeBox = document.getElementById('engineDetailIconBadge');

    if (kpisEl) kpisEl.innerHTML = '';
    if (contentEl) {
        contentEl.innerHTML = `
            <div style="text-align: center; padding: 40px; color: var(--text-secondary);">
                <i data-lucide="loader" class="spin-animation" style="width: 28px; height: 28px; margin-bottom: 12px; color: #00f2fe;"></i>
                <p style="margin: 0; font-size: 0.9rem;">Consultando telemetria e diagnóstico do motor...</p>
            </div>
        `;
        initIcons();
    }

    try {
        const resp = await fetch(`/api/admin/engine_details/${engineKey}`);
        const data = await resp.json();
        if (data.status !== 'success') {
            if (contentEl) contentEl.innerHTML = `<p style="color: #ef4444; padding: 20px; text-align: center;">Erro ao carregar detalhes: ${data.message || 'Falha desconhecida'}</p>`;
            return;
        }

        const summ = data.summary || {};
        if (titleEl) titleEl.textContent = data.label || data.engine_name || 'Detalhes do Motor';
        if (syncTimeEl) syncTimeEl.textContent = data.last_sync || '--:--:--';
        if (badgeEl) {
            const isOp = data.engine_status === 'OPERATIONAL';
            badgeEl.className = `engine-status-badge ${isOp ? 'badge-operational' : (data.engine_status === 'ERROR_CONNECTION' ? 'badge-error-connection' : 'badge-stopped')}`;
            badgeEl.textContent = isOp ? 'OPERACIONAL' : (data.engine_status === 'ERROR_CONNECTION' ? 'FALHA DE CONEXÃO' : 'MOTOR PARADO');
        }

        // Setup Engine Specifics
        if (engineKey === 'trbonet') {
            if (subtitleEl) subtitleEl.textContent = 'Leitura nativa silenciosa UIAutomation em segundo plano do rádio console';
            if (iconEl) iconEl.setAttribute('data-lucide', 'radio');
            if (badgeBox) { badgeBox.style.background = 'rgba(16, 185, 129, 0.15)'; badgeBox.style.borderColor = 'rgba(16, 185, 129, 0.35)'; }
            if (commTagEl) commTagEl.textContent = 'UIAutomation Local (Windows)';
            if (actionText) actionText.textContent = data.action_label || 'Atualizar / Sincronizar Rádios Agora';
            
            const totalRadios = summ.total_radios ?? data.radios_total ?? 0;
            const withGps = summ.online_with_gps ?? data.radios_with_gps ?? 0;
            const compRate = summ.compliance_rate ?? (data.compliance_summary?.conformes ?? 0);
            const totalPo = summ.total_poweron ?? data.radios_in_poweron ?? 0;

            if (kpisEl) {
                kpisEl.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">TOTAL RÁDIOS</span>
                        <strong style="font-size: 1.35rem; color: #00f2fe; font-family: 'JetBrains Mono';">${totalRadios}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">COM SINAL GPS</span>
                        <strong style="font-size: 1.35rem; color: #10b981; font-family: 'JetBrains Mono';">${withGps}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">CONFORMIDADE</span>
                        <strong style="font-size: 1.35rem; color: #3b82f6; font-family: 'JetBrains Mono';">${typeof compRate === 'number' && compRate <= 100 ? compRate + '%' : compRate}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">POWERON / ESCALA</span>
                        <strong style="font-size: 1.35rem; color: #f59e0b; font-family: 'JetBrains Mono';">${totalPo}</strong>
                    </div>
                `;
            }

            const samples = data.sample_records || data.sample_teams || [];
            if (contentEl) {
                let rowsHtml = samples.map(t => `
                    <tr>
                        <td><strong style="color: var(--text-primary); font-family: 'JetBrains Mono';">${t.code || '--'}</strong></td>
                        <td>${t.base || t.status || '--'}</td>
                        <td><code style="color: #00f2fe;">${t.radio_id || '--'}</code></td>
                        <td><span style="font-size: 0.75rem; color: var(--text-secondary);">${t.channel || t.speed || '--'}</span></td>
                        <td><span class="status-badge ${t.has_gps ? 'badge-online-gps' : 'badge-offline-gray'}">${t.has_gps ? 'GPS OK' : 'SEM GPS'}</span></td>
                        <td><span class="status-badge ${t.poweron !== false ? 'badge-online-gps' : 'badge-offline-gray'}">${t.poweron ? 'ESCALADA' : 'ONLINE'}</span></td>
                    </tr>
                `).join('');

                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <strong style="font-size: 0.88rem; color: var(--text-primary);"><i data-lucide="list" style="width: 15px; height: 15px; margin-right: 6px; vertical-align: middle;"></i> Amostragem de Rádios Monitorados</strong>
                        <small style="color: var(--text-secondary);">Exibindo ${samples.length} de ${totalRadios}</small>
                    </div>
                    <div style="max-height: 240px; overflow-y: auto;">
                        <table class="data-table" style="width: 100%; font-size: 0.8rem;">
                            <thead>
                                <tr>
                                    <th>Equipe</th>
                                    <th>Base / Status</th>
                                    <th>ID Rádio</th>
                                    <th>Canal / Vel</th>
                                    <th>GPS</th>
                                    <th>PowerON</th>
                                </tr>
                            </thead>
                            <tbody>${rowsHtml || '<tr><td colspan="6" style="text-align: center;">Nenhum rádio registrado</td></tr>'}</tbody>
                        </table>
                    </div>
                `;
            }

        } else if (engineKey === 'enel_cdp') {
            if (subtitleEl) subtitleEl.textContent = 'Automação Chrome DevTools Protocol na porta 9222 (500 linhas, F5 e turnos)';
            if (iconEl) iconEl.setAttribute('data-lucide', 'users');
            if (badgeBox) { badgeBox.style.background = 'rgba(0, 242, 254, 0.15)'; badgeBox.style.borderColor = 'rgba(0, 242, 254, 0.35)'; }
            if (commTagEl) commTagEl.textContent = 'Chrome CDP 9222 (Enel)';
            if (actionText) actionText.textContent = data.action_label || 'Disparar Coleta Imediata Enel (CDP)';

            const totalTeams = summ.total_teams ?? data.active_teams_count ?? 0;
            const cesto = summ.cesto_count ?? (data.active_by_type?.CESTO ?? 0);
            const leve = summ.leve_count ?? (data.active_by_type?.LEVE ?? 0);
            const norte = summ.norte_count ?? (data.active_by_region?.Norte ?? 0);

            if (kpisEl) {
                kpisEl.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">ATIVAS NO TURNO</span>
                        <strong style="font-size: 1.35rem; color: #10b981; font-family: 'JetBrains Mono';">${totalTeams}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">CESTO AÉREO</span>
                        <strong style="font-size: 1.35rem; color: #a855f7; font-family: 'JetBrains Mono';">${cesto}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">VEÍCULO LEVE</span>
                        <strong style="font-size: 1.35rem; color: #3b82f6; font-family: 'JetBrains Mono';">${leve}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">REG. NORTE</span>
                        <strong style="font-size: 1.35rem; color: #00f2fe; font-family: 'JetBrains Mono';">${norte}</strong>
                    </div>
                `;
            }

            const samples = data.sample_records || data.sample_teams || [];
            if (contentEl) {
                let rowsHtml = samples.map(t => `
                    <tr>
                        <td><strong style="color: var(--text-primary); font-family: 'JetBrains Mono';">${t.code || '--'}</strong></td>
                        <td>${t.base || '--'}</td>
                        <td><span style="font-size: 0.75rem; color: #00f2fe;">${t.region || t.ut || '--'}</span></td>
                        <td><span class="type-pill pill-${(t.type || t.vehicle_type || 'cesto').toLowerCase()}">${t.type || t.vehicle_type || 'Equipe'}</span></td>
                        <td><code style="color: #f59e0b; font-family: 'JetBrains Mono';">${t.plate || '--'}</code></td>
                        <td><small style="color: var(--text-secondary);">${t.turn || t.status_op || '--'}</small></td>
                    </tr>
                `).join('');

                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <strong style="font-size: 0.88rem; color: var(--text-primary);"><i data-lucide="truck" style="width: 15px; height: 15px; margin-right: 6px; vertical-align: middle;"></i> Amostragem de Equipes Coletadas na Enel</strong>
                        <small style="color: var(--text-secondary);">Exibindo ${samples.length} de ${totalTeams}</small>
                    </div>
                    <div style="max-height: 240px; overflow-y: auto;">
                        <table class="data-table" style="width: 100%; font-size: 0.8rem;">
                            <thead>
                                <tr>
                                    <th>Equipe</th>
                                    <th>Base</th>
                                    <th>Região</th>
                                    <th>Tipologia</th>
                                    <th>Placa</th>
                                    <th>Status / Turno</th>
                                </tr>
                            </thead>
                            <tbody>${rowsHtml || '<tr><td colspan="6" style="text-align: center;">Nenhuma equipe ativa</td></tr>'}</tbody>
                        </table>
                    </div>
                `;
            }

        } else if (engineKey === 'spotfire_cdp') {
            if (subtitleEl) subtitleEl.textContent = 'Leitura automatizada via CDP do TIBCO Spotfire Scanner 5.0 (Metas & Produtividade)';
            if (iconEl) iconEl.setAttribute('data-lucide', 'bar-chart-2');
            if (badgeBox) { badgeBox.style.background = 'rgba(245, 158, 11, 0.15)'; badgeBox.style.borderColor = 'rgba(245, 158, 11, 0.35)'; }
            if (commTagEl) commTagEl.textContent = 'Chrome CDP 9222 (Spotfire)';
            if (actionText) actionText.textContent = data.action_label || 'Forçar Extração do Scanner 5.0 Agora';

            const spotfireRows = summ.total_records ?? data.spotfire_rows ?? 0;

            if (kpisEl) {
                kpisEl.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">METAS SINCRONIZADAS</span>
                        <strong style="font-size: 1.35rem; color: #f59e0b; font-family: 'JetBrains Mono';">${spotfireRows}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">INTERVALO ROBÔ</span>
                        <strong style="font-size: 1.35rem; color: #00f2fe; font-family: 'JetBrains Mono';">${summ.interval || '30 min'}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">FORMATO PERSISTIDO</span>
                        <strong style="font-size: 1.35rem; color: #10b981; font-family: 'JetBrains Mono';">JSON + DB</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">STATUS CONEXÃO</span>
                        <strong style="font-size: 1.35rem; color: #3b82f6; font-family: 'JetBrains Mono';">${data.engine_status || 'OK'}</strong>
                    </div>
                `;
            }

            if (contentEl) {
                contentEl.innerHTML = `
                    <div style="padding: 12px; line-height: 1.6;">
                        <h4 style="margin: 0 0 8px 0; color: #f59e0b; font-size: 0.95rem; display: flex; align-items: center; gap: 6px;">
                            <i data-lucide="check-circle" style="width: 16px; height: 16px;"></i> Integração TIBCO Spotfire Ativa
                        </h4>
                        <p style="font-size: 0.84rem; color: var(--text-secondary); margin: 0 0 12px 0;">
                            O robô local conecta-se silenciosamente ao Chrome corporativo onde o <strong>Scanner 5.0 (TIBCO Spotfire)</strong> está carregado, extraindo a tabela analítica de metas operacionais e persistindo na base de dados e no Supabase.
                        </p>
                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 10px;">
                            <div style="background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border: 1px solid rgba(255,255,255,0.06);">
                                <span style="font-size: 0.72rem; color: var(--text-secondary); display: block;">ARQUIVO LOCAL DE AUDITORIA</span>
                                <strong style="font-size: 0.82rem; color: #00f2fe; font-family: 'JetBrains Mono';">scanner_last_sync.json</strong>
                            </div>
                            <div style="background: rgba(255,255,255,0.03); border-radius: 8px; padding: 10px; border: 1px solid rgba(255,255,255,0.06);">
                                <span style="font-size: 0.72rem; color: var(--text-secondary); display: block;">TABELA SUPABASE</span>
                                <strong style="font-size: 0.82rem; color: #10b981; font-family: 'JetBrains Mono';">spotfire_records</strong>
                            </div>
                        </div>
                    </div>
                `;
            }

        } else if (engineKey === 'bid_cdp') {
            if (subtitleEl) subtitleEl.textContent = 'Automação Chrome DevTools Protocol na porta 9222 (Checklist & Visão Operacional BidTech)';
            if (iconEl) iconEl.setAttribute('data-lucide', 'clipboard-check');
            if (badgeBox) { badgeBox.style.background = 'rgba(236, 72, 153, 0.15)'; badgeBox.style.borderColor = 'rgba(236, 72, 153, 0.35)'; }
            if (commTagEl) commTagEl.textContent = 'Chrome CDP 9222 (BidTech)';
            if (actionText) actionText.textContent = data.action_label || 'Disparar Sincronização BidTech (CDP) Agora';

            const totalTeams = summ.total_teams ?? 0;
            const emOperacao = summ.em_operacao ?? 0;
            const emChecklist = summ.em_checklist ?? 0;
            const bloqueadas = summ.bloqueadas ?? 0;

            if (kpisEl) {
                kpisEl.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">TOTAL CHECKLIST</span>
                        <strong style="font-size: 1.35rem; color: #ec4899; font-family: 'JetBrains Mono';">${totalTeams}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">EM OPERAÇÃO</span>
                        <strong style="font-size: 1.35rem; color: #10b981; font-family: 'JetBrains Mono';">${emOperacao}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">EM CHECKLIST</span>
                        <strong style="font-size: 1.35rem; color: #f59e0b; font-family: 'JetBrains Mono';">${emChecklist}</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">BLOQ. / RETORNADAS</span>
                        <strong style="font-size: 1.35rem; color: #ef4444; font-family: 'JetBrains Mono';">${bloqueadas}</strong>
                    </div>
                `;
            }

            const samples = data.sample_records || [];
            if (contentEl) {
                let rowsHtml = samples.map(t => {
                    const st = t.status_bid || '--';
                    const stUp = st.toUpperCase();
                    let badgeClass = 'badge-neutral';
                    if (stUp.includes('OPERA')) badgeClass = 'badge-conforme';
                    else if (stUp.includes('CHECKLIST')) badgeClass = 'badge-alerta-critico';
                    else if (stUp.includes('PLANEJAD')) badgeClass = 'badge-alerta-grave';
                    else if (stUp.includes('BLOQUEAD') || stUp.includes('RETORNAD')) badgeClass = 'badge-alerta-impeditivo';

                    return `
                    <tr>
                        <td><strong style="color: var(--text-primary); font-family: 'JetBrains Mono';">${t.code || '--'}</strong></td>
                        <td>${t.base || '--'}</td>
                        <td><span class="status-badge ${badgeClass}">${st}</span></td>
                        <td><small style="color: var(--text-primary);">${t.driver || '--'}</small></td>
                        <td><code style="color: #00f2fe; font-family: 'JetBrains Mono';">${t.plate || '--'}</code></td>
                        <td><span style="font-size: 0.75rem; color: var(--text-secondary);">${t.tipo_operacional || '--'}${t.timer_value ? ' (' + t.timer_value + ')' : ''}</span></td>
                    </tr>
                    `;
                }).join('');

                contentEl.innerHTML = `
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                        <strong style="font-size: 0.88rem; color: var(--text-primary);"><i data-lucide="clipboard-check" style="width: 15px; height: 15px; margin-right: 6px; vertical-align: middle; color: #ec4899;"></i> Amostragem de Equipes no Checklist BidTech</strong>
                        <small style="color: var(--text-secondary);">Exibindo ${samples.length} de ${totalTeams}</small>
                    </div>
                    <div style="max-height: 240px; overflow-y: auto;">
                        <table class="data-table" style="width: 100%; font-size: 0.8rem;">
                            <thead>
                                <tr>
                                    <th>Equipe</th>
                                    <th>Base</th>
                                    <th>Status Checklist</th>
                                    <th>Motorista</th>
                                    <th>Placa</th>
                                    <th>Tipologia / Tempo</th>
                                </tr>
                            </thead>
                            <tbody>${rowsHtml || '<tr><td colspan="6" style="text-align: center;">Nenhuma equipe no checklist</td></tr>'}</tbody>
                        </table>
                    </div>
                `;
            }

        } else if (engineKey === 'cloud_sync') {
            if (subtitleEl) subtitleEl.textContent = 'Banco de dados relacional PostgreSQL & WebSocket Realtime na Nuvem';
            if (iconEl) iconEl.setAttribute('data-lucide', 'database');
            if (badgeBox) { badgeBox.style.background = 'rgba(192, 132, 252, 0.15)'; badgeBox.style.borderColor = 'rgba(192, 132, 252, 0.35)'; }
            if (commTagEl) commTagEl.textContent = 'Supabase REST & WSS';
            if (actionText) actionText.textContent = 'Forçar Sincronização com a Nuvem';

            if (kpisEl) {
                kpisEl.innerHTML = `
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">BANCO DE DADOS</span>
                        <strong style="font-size: 1.35rem; color: #c084fc; font-family: 'JetBrains Mono';">PostgreSQL</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">REALTIME WS</span>
                        <strong style="font-size: 1.35rem; color: #10b981; font-family: 'JetBrains Mono';">ATIVO</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">SEGURANÇA</span>
                        <strong style="font-size: 1.35rem; color: #3b82f6; font-family: 'JetBrains Mono';">RLS ON</strong>
                    </div>
                    <div style="background: rgba(255,255,255,0.03); border: 1px solid var(--border-glass); border-radius: 12px; padding: 12px; text-align: center;">
                        <span style="font-size: 0.7rem; color: var(--text-secondary); display: block;">FILA DE COMANDOS</span>
                        <strong style="font-size: 1.35rem; color: #00f2fe; font-family: 'JetBrains Mono';">Bidirecional</strong>
                    </div>
                `;
            }

            if (contentEl) {
                contentEl.innerHTML = `
                    <div style="padding: 12px; line-height: 1.6;">
                        <h4 style="margin: 0 0 8px 0; color: #c084fc; font-size: 0.95rem; display: flex; align-items: center; gap: 6px;">
                            <i data-lucide="cloud" style="width: 16px; height: 16px;"></i> Conectividade Supabase em Alta Disponibilidade
                        </h4>
                        <p style="font-size: 0.84rem; color: var(--text-secondary); margin: 0 0 12px 0;">
                            Garante a comunicação fluida entre o robô local no Windows e os usuários em produção na web (Vercel). Todos os comandos disparados na nuvem são propagados e escutados em milissegundos via Postgres Realtime e HTTP REST.
                        </p>
                    </div>
                `;
            }
        }

        initIcons();

    } catch (err) {
        if (contentEl) contentEl.innerHTML = `<p style="color: #ef4444; padding: 20px; text-align: center;">Falha de comunicação: ${err.message}</p>`;
    }
}

async function triggerCurrentEngineAction() {
    if (!currentSelectedEngine) return;
    closeModal('modalEngineDetails');

    if (currentSelectedEngine === 'trbonet') {
        syncUnifiedLive();
    } else if (currentSelectedEngine === 'enel_cdp') {
        triggerEnelCdpCapture();
    } else if (currentSelectedEngine === 'spotfire_cdp') {
        triggerSpotfireCdpCapture();
    } else if (currentSelectedEngine === 'bid_cdp') {
        triggerBidCdpCapture();
    } else if (currentSelectedEngine === 'cloud_sync') {
        showToast('Sincronizando estado operacional com o Supabase...', 'info');
        if (typeof fetchDashboardData === 'function') fetchDashboardData(true);
        if (typeof loadDeliveryData === 'function') loadDeliveryData(true);
    }
}

async function triggerBidCdpCapture() {
    showToast('Iniciando sincronização da Visão Operacional BidTech...', 'info');
    try {
        const resp = await fetch('/api/capture/bid/direct', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok && (data.status === 'success' || data.total_extracted >= 0)) {
            showToast(data.message || 'Dados do BidTech sincronizados com sucesso!', 'success');
            loadAdminEngineStatus();
            if (typeof loadOnlineXBidData === 'function') loadOnlineXBidData();
            if (currentSelectedEngine === 'bid_cdp') {
                openEngineDetailsModal('bid_cdp');
            }
        } else {
            showToast(data.message || 'Falha ao sincronizar BidTech.', 'danger');
        }
    } catch (err) {
        showToast('Erro de comunicação ao disparar BidTech: ' + err.message, 'danger');
    }
}

async function triggerSpotfireCdpCapture() {
    showToast('Iniciando extração do Scanner 5.0 (TIBCO Spotfire)...', 'info');
    try {
        const resp = await fetch('/api/delivery/spotfire/sync', { method: 'POST' });
        const data = await resp.json();
        if (resp.ok && data.status === 'success') {
            showToast(data.message || 'Dados do Spotfire extraídos com sucesso!', 'success');
            loadAdminEngineStatus();
            if (currentSelectedEngine === 'spotfire_cdp') {
                openEngineDetailsModal('spotfire_cdp');
            }
        } else {
            showToast(data.message || 'Falha ao sincronizar Spotfire.', 'danger');
        }
    } catch (err) {
        showToast('Erro ao comunicar com Robô Spotfire: ' + err.message, 'danger');
    }
}

async function triggerRestartEngines() {
    if (!confirm('Deseja enviar comando para reiniciar os motores locais de captura em segundo plano no Windows (TRBOnet One, Robô CDP Enel SP, Scanner 5.0 e Robô CDP BidTech)?\nO servidor web continuará funcionando normalmente.')) {
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


// ==============================================================================
// ==============================================================================
// MÓDULO: ONLINE (EQUIPES BRASIL) x BIDTECH (CHECKLIST VISÃO OPERACIONAL)
// ==============================================================================
const onlineBidState = {
    allRows: [],
    kpis: {},
    date: '',
    lastBidSync: '',
    isLoading: false,
    activeCardFilter: ''
};

function toggleBidCardFilter(filterType) {
    const selStatus = document.getElementById('filterBidCrossStatus');
    
    // Toggle: se clicar no mesmo card já ativo, desativa o filtro
    if (onlineBidState.activeCardFilter === filterType) {
        onlineBidState.activeCardFilter = '';
        if (selStatus) selStatus.value = '';
    } else {
        onlineBidState.activeCardFilter = filterType;
        if (selStatus) {
            if (filterType === 'TOTAL_EB') {
                selStatus.value = ''; // Limpa filtro de status cruzado para mostrar todas logadas EB
            } else {
                selStatus.value = filterType;
            }
        }
    }
    
    updateActiveKpiCardHighlight(onlineBidState.activeCardFilter);
    filterOnlineBidTable();
}

function onSelectBidCrossStatus(val) {
    onlineBidState.activeCardFilter = val || '';
    updateActiveKpiCardHighlight(onlineBidState.activeCardFilter);
    filterOnlineBidTable();
}

function updateActiveKpiCardHighlight(type) {
    const cardMap = {
        'CONFORME': 'kpiCardBidConforme',
        'ALERTA CRÍTICO': 'kpiCardBidCritico',
        'ALERTA GRAVE': 'kpiCardBidGrave',
        'ALERTA GRAVÍSSIMO': 'kpiCardBidGravissimo',
        'ALERTA IMPEDITIVO': 'kpiCardBidImpeditivo',
        'TOTAL_EB': 'kpiCardBidTotalEb'
    };

    // Remove destaque de todos os cards
    document.querySelectorAll('.online-bid-kpi-grid .fleet-liquid-card').forEach(c => {
        c.classList.remove('active-kpi-card');
    });

    if (type && cardMap[type]) {
        const target = document.getElementById(cardMap[type]);
        if (target) {
            target.classList.add('active-kpi-card');
        }
    }
}

function toggleBidCardFilter(cardType) {
    if (onlineBidState.activeCardFilter === cardType) {
        // Desmarca filtro ativo (toggle off)
        onlineBidState.activeCardFilter = '';
        updateActiveKpiCardHighlight('');
        // Restaura todos os status cruzados e status EB
        document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="cross-status"]').forEach(cb => {
            cb.checked = true;
        });
        document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="eb-status"]').forEach(cb => {
            cb.checked = true;
        });
    } else {
        onlineBidState.activeCardFilter = cardType;
        updateActiveKpiCardHighlight(cardType);

        if (cardType === 'TOTAL_EB') {
            // Seleciona apenas "Logada" no filtro de Status EB
            document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="eb-status"]').forEach(cb => {
                cb.checked = (cb.value === 'Logada');
            });
        } else {
            // Seleciona apenas o status cruzado correspondente
            document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="cross-status"]').forEach(cb => {
                cb.checked = (cb.value === cardType);
            });
        }
    }

    syncOnlineBidFiltersFromDOM();
    filterOnlineBidTable();
}

function updateOnlineBidPillLabel(filterType, totalCount, selectedCount, firstValue) {
    const labelMap = {
        'region': 'bidFilterRegionLabel',
        'base': 'bidFilterBaseLabel',
        'eb-status': 'bidFilterEbStatusLabel',
        'bid-status': 'bidFilterBidStatusLabel',
        'cross-status': 'bidFilterCrossStatusLabel',
        'turno': 'bidFilterTurnoLabel'
    };
    const el = document.getElementById(labelMap[filterType]);
    if (!el) return;

    if (selectedCount === totalCount || (selectedCount === 0 && totalCount === 0)) {
        el.textContent = 'Todos';
    } else if (selectedCount === 0) {
        el.textContent = 'Nenhum';
    } else if (selectedCount === 1) {
        let clean = (firstValue || '').replace('Região ', '').replace('Base ', '').replace('Turno ', '');
        el.textContent = clean || '1 sel.';
    } else {
        el.textContent = `${selectedCount} sel.`;
    }
}

function syncOnlineBidFiltersFromDOM() {
    if (!onlineBidState.filters) {
        onlineBidState.filters = { regions: [], bases: [], ebStatuses: [], bidStatuses: [], crossStatuses: [], turnos: [] };
    }

    const getSelected = (filterType) => {
        const cbs = Array.from(document.querySelectorAll(`#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="${filterType}"]`));
        const checked = cbs.filter(c => c.checked).map(c => c.value);
        updateOnlineBidPillLabel(filterType, cbs.length, checked.length, checked[0] || '');
        return checked;
    };

    onlineBidState.filters.regions = getSelected('region');
    onlineBidState.filters.bases = getSelected('base');
    onlineBidState.filters.ebStatuses = getSelected('eb-status');
    onlineBidState.filters.bidStatuses = getSelected('bid-status');
    onlineBidState.filters.crossStatuses = getSelected('cross-status');
    onlineBidState.filters.turnos = getSelected('turno');
}

function updateOnlineBidGroupCheckboxesState() {
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-group-checkbox').forEach(gcb => {
        const grp = gcb.getAttribute('data-bid-group');
        const children = Array.from(document.querySelectorAll(`#deliveryScreenOnlineBid .popover-checkbox[data-bid-group="${grp}"]`));
        if (children.length === 0) return;
        const checkedCount = children.filter(c => c.checked).length;
        gcb.checked = (checkedCount === children.length);
        gcb.indeterminate = (checkedCount > 0 && checkedCount < children.length);
    });
}

function setupOnlineBidFilterDropdowns() {
    // 1. Toggle de popovers ao clicar no botão da pílula
    document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-pill-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const targetId = btn.getAttribute('data-target');
            const targetMenu = document.getElementById(targetId);
            const isAlreadyActive = targetMenu && targetMenu.classList.contains('active');

            // Fecha outros popovers
            document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-popover').forEach(p => p.classList.remove('active'));
            document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-pill-btn').forEach(b => b.classList.remove('active'));

            if (!isAlreadyActive && targetMenu) {
                targetMenu.classList.add('active');
                btn.classList.add('active');
            }
        };
    });

    // 2. Ações de "Todos" e "Limpar" no cabeçalho do popover
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-action-btn').forEach(btn => {
        btn.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            const action = btn.getAttribute('data-action');
            const filterType = btn.getAttribute('data-bid-filter');
            const cbs = document.querySelectorAll(`#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="${filterType}"]`);

            cbs.forEach(cb => {
                cb.checked = (action === 'select-all');
            });

            if (filterType === 'base') {
                updateOnlineBidGroupCheckboxesState();
            }

            syncOnlineBidFiltersFromDOM();
            filterOnlineBidTable();
        };
    });

    // 3. Hierarquia: selecionar grupo pai marca/desmarca todas as filhas
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-group-checkbox').forEach(gcb => {
        gcb.onchange = (e) => {
            const grp = gcb.getAttribute('data-bid-group');
            const isChecked = gcb.checked;
            document.querySelectorAll(`#deliveryScreenOnlineBid .popover-checkbox[data-bid-group="${grp}"]`).forEach(cb => {
                cb.checked = isChecked;
            });
            syncOnlineBidFiltersFromDOM();
            filterOnlineBidTable();
        };
    });

    // 4. Checkboxes individuais disparam re-filtro e sincronizam rótulo
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox').forEach(cb => {
        cb.onchange = () => {
            updateOnlineBidGroupCheckboxesState();
            syncOnlineBidFiltersFromDOM();
            filterOnlineBidTable();
        };
    });

    // 5. Clique interno no popover não propaga (mantém o popover aberto enquanto clica nos itens)
    document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-popover').forEach(p => {
        p.onclick = (e) => {
            e.stopPropagation();
        };
    });

    // 6. Clique FORA fecha qualquer popover que estiver aberto
    if (!window._onlineBidClosePopoverBound) {
        window._onlineBidClosePopoverBound = true;
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#deliveryScreenOnlineBid .dropdown-popover-container')) {
                document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-popover').forEach(p => p.classList.remove('active'));
                document.querySelectorAll('#deliveryScreenOnlineBid .period-filter-pill-btn').forEach(b => b.classList.remove('active'));
            }
        });
    }
}

function initOnlineBidMultiFilters(rows) {
    if (!rows) return;

    // 1. REGIÃO (Multi-seleção)
    const regList = document.getElementById('bidFilterRegionList');
    if (regList) {
        regList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="region" value="Norte" checked>
                <span>Região Norte</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="region" value="Leste" checked>
                <span>Região Leste</span>
            </label>
        `;
    }

    // 2. BASE / UT (Hierarquia com Região Norte e Região Leste)
    const baseList = document.getElementById('bidFilterBaseList');
    if (baseList) {
        // Separação oficial de bases por região
        const allBases = Array.from(new Set(rows.map(r => r.base_display).filter(Boolean))).sort();
        const norteDefault = ['Base Fagundes Filho', 'Base Cajati', 'Base Vila Medeiros'];
        const lesteDefault = ['Base Monte Santo', 'Base Catumbi', 'Base Aricanduva', 'Base Santo André'];

        const norteBases = Array.from(new Set([
            ...norteDefault,
            ...rows.filter(r => (r.geo || '').toLowerCase().includes('norte')).map(r => r.base_display).filter(Boolean)
        ])).sort();

        const lesteBases = Array.from(new Set([
            ...lesteDefault,
            ...rows.filter(r => (r.geo || '').toLowerCase().includes('leste')).map(r => r.base_display).filter(Boolean)
        ])).sort();

        baseList.innerHTML = `
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar todas as bases da Região Norte">
                    <input type="checkbox" class="popover-group-checkbox" data-bid-group="regiao-norte" checked>
                    <span>Região Norte</span>
                </label>
                <div class="popover-group-children">
                    ${norteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-bid-filter="base" data-bid-group="regiao-norte" value="${b}" checked>
                            <span>${b}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
            <div class="popover-group-section">
                <label class="popover-group-header" title="Clique para selecionar/desmarcar todas as bases da Região Leste">
                    <input type="checkbox" class="popover-group-checkbox" data-bid-group="regiao-leste" checked>
                    <span>Região Leste</span>
                </label>
                <div class="popover-group-children">
                    ${lesteBases.map(b => `
                        <label class="popover-item-label child-item">
                            <input type="checkbox" class="popover-checkbox" data-bid-filter="base" data-bid-group="regiao-leste" value="${b}" checked>
                            <span>${b}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `;
    }

    // 3. STATUS EB (NOVO - Logada vs Não Logada)
    const ebList = document.getElementById('bidFilterEbStatusList');
    if (ebList) {
        ebList.innerHTML = `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="eb-status" value="Logada" checked>
                <span>Logada</span>
            </label>
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="eb-status" value="Não Logada" checked>
                <span>Não Logada</span>
            </label>
        `;
    }

    // 4. STATUS BID (NOVO - Status do Checklist BidTech)
    const bidList = document.getElementById('bidFilterBidStatusList');
    if (bidList) {
        const defaultBidStatuses = ['Em Operação', 'Em Checklist', 'Planejada', 'Não Encontrada', 'Bloqueada', 'Retornada'];
        const fromData = Array.from(new Set(rows.map(r => r.status_bid).filter(Boolean)));
        const allBidStatuses = Array.from(new Set([...defaultBidStatuses, ...fromData])).sort();

        bidList.innerHTML = allBidStatuses.map(s => `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="bid-status" value="${s}" checked>
                <span>${s}</span>
            </label>
        `).join('');
    }

    // 5. STATUS CRUZADO (Forense)
    const crossList = document.getElementById('bidFilterCrossStatusList');
    if (crossList) {
        const crossOptions = [
            { val: 'CONFORME', label: '🟢 Conforme (Em Operação)' },
            { val: 'ALERTA CRÍTICO', label: '🟡 Alerta Crítico (Em Checklist)' },
            { val: 'ALERTA GRAVE', label: '🔴 Alerta Grave (Planejada)' },
            { val: 'ALERTA GRAVÍSSIMO', label: '🟣 Alerta Gravíssimo (Não Encontrada)' },
            { val: 'ALERTA IMPEDITIVO', label: '⛔ Alerta Impeditivo (Bloqueada/Retornada)' },
            { val: 'BID SEM LOGIN EB', label: '🟠 Sem Login no Despacho' },
            { val: 'AGUARDANDO APRESENTAÇÃO', label: '🔵 Aguardando Apresentação' }
        ];

        crossList.innerHTML = crossOptions.map(opt => `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="cross-status" value="${opt.val}" checked>
                <span>${opt.label}</span>
            </label>
        `).join('');
    }

    // 6. TURNO (Multi-seleção)
    const turnoList = document.getElementById('bidFilterTurnoList');
    if (turnoList) {
        const fromData = Array.from(new Set(rows.map(r => r.turno).filter(Boolean))).sort();
        const defaultTurnos = ['Turno 06:00', 'Turno 08:00', 'Turno 14:00', 'Turno 15:00', 'Turno 16:00', '--'];
        const allTurnos = Array.from(new Set([...fromData, ...defaultTurnos])).sort();

        turnoList.innerHTML = allTurnos.map(t => `
            <label class="popover-item-label">
                <input type="checkbox" class="popover-checkbox" data-bid-filter="turno" value="${t}" checked>
                <span>${t}</span>
            </label>
        `).join('');
    }

    // Configura todos os dropdowns e listeners
    setupOnlineBidFilterDropdowns();
    syncOnlineBidFiltersFromDOM();
}

function renderOnlineBidKpis(k) {
    if (!k) return;
    const elRate = document.getElementById('onlineBidConformidadeRateBadge');
    const elConforme = document.getElementById('kpiBidConforme');
    const elCritico = document.getElementById('kpiBidCritico');
    const elGrave = document.getElementById('kpiBidGrave');
    const elGravissimo = document.getElementById('kpiBidGravissimo');
    const elImpeditivo = document.getElementById('kpiBidImpeditivo');
    const elTotalEb = document.getElementById('kpiBidTotalEb');
    const elTotalEmOperacaoSub = document.getElementById('kpiBidTotalEmOperacaoSub');

    if (elRate) elRate.textContent = `${k.indice_conformidade || 0.0}%`;
    if (elConforme) elConforme.textContent = k.conforme || 0;
    if (elCritico) elCritico.textContent = k.alerta_critico || 0;
    if (elGrave) elGrave.textContent = k.alerta_grave || 0;
    if (elGravissimo) elGravissimo.textContent = k.alerta_gravissimo || 0;
    if (elImpeditivo) elImpeditivo.textContent = k.alerta_impeditivo || 0;
    if (elTotalEb) elTotalEb.textContent = k.total_logadas_eb || 0;
    if (elTotalEmOperacaoSub) {
        elTotalEmOperacaoSub.textContent = `${k.total_em_operacao_bid || 0} em operação no Checklist`;
    }
}

async function loadOnlineXBidData() {
    const dateInput = document.getElementById('onlineBidDateInput');
    const opDate = getOperationalDate();
    if (dateInput && !dateInput.value) {
        dateInput.value = opDate;
    }
    const targetDate = (dateInput && dateInput.value) ? dateInput.value : opDate;

    try {
        const resp = await fetch(`/api/bid/data?date=${encodeURIComponent(targetDate)}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const result = await resp.json();

        if (result.status === 'success') {
            onlineBidState.allRows = result.rows || [];
            onlineBidState.kpis = result.kpis || {};
            onlineBidState.date = result.date || targetDate;
            onlineBidState.lastBidSync = result.last_bid_sync || '--:--:--';

            // Alinha o input de data com a data operacional retornada pelo backend
            if (dateInput && result.date) {
                dateInput.value = result.date;
            }

            renderOnlineBidKpis(onlineBidState.kpis);
            initOnlineBidMultiFilters(onlineBidState.allRows);
            updateActiveKpiCardHighlight(onlineBidState.activeCardFilter);
            filterOnlineBidTable();
        }
    } catch (err) {
        console.error('[ONLINE x BID ERROR]', err);
        showToast('Falha ao carregar dados da Reconciliação ONLINE x BID', 'danger');
    }
}

function filterOnlineBidTable() {
    const prevScrollY = window.scrollY;
    const tbody = document.getElementById('onlineBidTableBody');
    const countBadge = document.getElementById('onlineBidTableCountBadge');
    if (!tbody) return;

    const f = onlineBidState.filters || {
        regions: [],
        bases: [],
        ebStatuses: [],
        bidStatuses: [],
        crossStatuses: [],
        turnos: []
    };

    const totalReg = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="region"]').length;
    const totalBase = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="base"]').length;
    const totalEb = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="eb-status"]').length;
    const totalBid = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="bid-status"]').length;
    const totalCross = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="cross-status"]').length;
    const totalTurno = document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="turno"]').length;

    const search = (document.getElementById('filterBidSearch')?.value || '').trim().toLowerCase();

    let list = onlineBidState.allRows || [];

    // Filtro ativado via Card "TOTAL LOGADAS (EB)"
    if (onlineBidState.activeCardFilter === 'TOTAL_EB') {
        list = list.filter(r => r.is_eb_active);
    }

    // Interseção com Multi-Filtros
    list = list.filter(r => {
        // 1. Região
        if (totalReg > 0) {
            if (f.regions.length === 0) return false;
            if (f.regions.length < totalReg) {
                const rGeo = (r.geo || '').toLowerCase();
                const matchReg = f.regions.some(reg => rGeo.includes(reg.toLowerCase()));
                if (!matchReg) return false;
            }
        }

        // 2. Base / UT
        if (totalBase > 0) {
            if (f.bases.length === 0) return false;
            if (f.bases.length < totalBase) {
                if (!f.bases.includes(r.base_display)) return false;
            }
        }

        // 3. Status EB (Logada vs Não Logada)
        if (totalEb > 0) {
            if (f.ebStatuses.length === 0) return false;
            if (f.ebStatuses.length < totalEb) {
                const ebVal = r.is_eb_active ? 'Logada' : 'Não Logada';
                if (!f.ebStatuses.includes(ebVal)) return false;
            }
        }

        // 4. Status BID (Checklist BidTech)
        if (totalBid > 0) {
            if (f.bidStatuses.length === 0) return false;
            if (f.bidStatuses.length < totalBid) {
                const bVal = r.status_bid || 'Não Encontrada';
                if (!f.bidStatuses.includes(bVal)) return false;
            }
        }

        // 5. Status Cruzado
        if (totalCross > 0) {
            if (f.crossStatuses.length === 0) return false;
            if (f.crossStatuses.length < totalCross) {
                if (!f.crossStatuses.includes(r.cross_status)) return false;
            }
        }

        // 6. Turno
        if (totalTurno > 0) {
            if (f.turnos.length === 0) return false;
            if (f.turnos.length < totalTurno) {
                const tVal = r.turno || '--';
                if (!f.turnos.includes(tVal)) return false;
            }
        }

        // 7. Busca Textual
        if (search) {
            const team = (r.team_code || '').toLowerCase();
            const plate = (r.plate || '').toLowerCase();
            const plateEb = (r.plate_eb || '').toLowerCase();
            const plateBid = (r.plate_bid || '').toLowerCase();
            const driver = (r.driver || '').toLowerCase();
            const members = Array.isArray(r.bid_members)
                ? r.bid_members.map(m => (typeof m === 'object' ? m.name : String(m))).join(' ').toLowerCase()
                : String(r.bid_members || '').toLowerCase();
            const os = (r.ordem_servico || '').toLowerCase();
            const baseDisp = (r.base_display || '').toLowerCase();
            const matchSearch = team.includes(search) || plate.includes(search) || plateEb.includes(search) ||
                                plateBid.includes(search) || driver.includes(search) || members.includes(search) ||
                                os.includes(search) || baseDisp.includes(search);
            if (!matchSearch) return false;
        }

        return true;
    });

    if (countBadge) {
        countBadge.textContent = `${list.length} equipes listadas`;
    }

    if (list.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="11" style="text-align: center; height: 420px; vertical-align: middle; padding: 40px 20px; color: var(--text-secondary);">
                    <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%;">
                        <i data-lucide="filter-x" style="width: 36px; height: 36px; color: #94a3b8; margin-bottom: 12px; opacity: 0.6;"></i>
                        <p style="font-weight: 700; font-size: 0.95rem; margin: 0 0 6px 0; color: var(--text-primary);">Nenhuma equipe encontrada para os filtros selecionados.</p>
                        <p style="font-size: 0.8rem; margin: 0; color: var(--text-secondary);">
                            Tente ajustar os filtros acima ou clique em <strong style="color: #38bdf8; cursor: pointer; text-decoration: underline;" onclick="clearOnlineBidFilters(event)">LIMPAR FILTROS</strong>.
                        </p>
                    </div>
                </td>
            </tr>
        `;
        if (typeof renderMobileBidCards === 'function') {
            renderMobileBidCards([]);
        }
        if (window.lucide) {
            lucide.createIcons();
        }
        if (Math.abs(window.scrollY - prevScrollY) > 5) {
            window.scrollTo(0, prevScrollY);
        }
        return;
    }

    tbody.innerHTML = list.map(r => {
        // Status Cruzado Badge
        let crossBadgeHtml = '';
        if (r.cross_status === 'CONFORME') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;"><span class="live-status-dot" style="width:6px;height:6px;background:#10b981;"></span> CONFORME</span>`;
        } else if (r.cross_status === 'ALERTA CRÍTICO') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(245, 158, 11, 0.2); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">⏱️ ALERTA CRÍTICO</span>`;
        } else if (r.cross_status === 'ALERTA GRAVE') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">⚠️ ALERTA GRAVE</span>`;
        } else if (r.cross_status === 'ALERTA GRAVÍSSIMO') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(192, 132, 252, 0.2); color: #c084fc; border: 1px solid rgba(192, 132, 252, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">🟣 ALERTA GRAVÍSSIMO</span>`;
        } else if (r.cross_status === 'ALERTA IMPEDITIVO') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(225, 29, 72, 0.2); color: #e11d48; border: 1px solid rgba(225, 29, 72, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">⛔ IMPEDITIVO</span>`;
        } else if (r.cross_status === 'BID SEM LOGIN EB') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(251, 146, 60, 0.2); color: #fb923c; border: 1px solid rgba(251, 146, 60, 0.4); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">🟠 SEM LOGIN</span>`;
        } else if (r.cross_status === 'AGUARDANDO APRESENTAÇÃO') {
            crossBadgeHtml = `<span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 0.75rem;">🔵 AGUARDANDO</span>`;
        } else {
            crossBadgeHtml = `<span class="badge" style="background: rgba(148, 163, 184, 0.15); color: #94a3b8; padding: 4px 10px; border-radius: 9999px; font-weight: 700; font-size: 0.75rem;">${r.cross_status || '--'}</span>`;
        }

        // Status PROG (Equipes Brasil)
        const progStatusText = r.status_prog || r.status_eb || (r.is_eb_active ? 'Logada' : 'Não Logada');
        const isProgActive = r.is_eb_active && progStatusText !== 'Não Logada' && progStatusText !== 'Deslogada';
        const progBadge = isProgActive
            ? `<span class="badge" style="background: rgba(16, 185, 129, 0.12); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;"><span class="live-status-dot" style="width:5px;height:5px;background:#10b981;"></span> ${progStatusText}</span>`
            : `<span style="color: var(--text-secondary); font-size: 0.74rem;">${progStatusText}</span>`;

        // Status LOGIN (LOGADA vs PROGRAMADA)
        const sLogin = r.status_login || (r.marcacao_eb && r.marcacao_eb !== '--' ? 'LOGADA' : 'PROGRAMADA');
        const isLoginLogada = sLogin === 'LOGADA';
        const loginBadge = isLoginLogada
            ? `<span class="badge" style="background: rgba(16, 185, 129, 0.18); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4); font-weight: 800; font-size: 0.72rem; padding: 2px 8px; border-radius: 9999px; letter-spacing: 0.03em;"><span class="live-status-dot" style="width:5px;height:5px;background:#10b981;"></span> LOGADA</span>`
            : `<span class="badge" style="background: rgba(56, 189, 248, 0.15); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.35); font-weight: 800; font-size: 0.72rem; padding: 2px 8px; border-radius: 9999px; letter-spacing: 0.03em;">PROGRAMADA</span>`;

        // Status BID
        let bBadge = '';
        const bStatus = r.status_bid || 'Não Encontrada';
        const bUpper = bStatus.toUpperCase();
        if (bUpper.includes('OPERA')) {
            bBadge = `<span class="badge" style="background: rgba(16, 185, 129, 0.15); color: #10b981; font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">✓ Em Operação</span>`;
        } else if (bUpper.includes('CHECKLIST')) {
            bBadge = `<span class="badge" style="background: rgba(245, 158, 11, 0.18); color: #f59e0b; font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">⏱️ Em Checklist</span>`;
        } else if (bUpper.includes('PLANEJAD')) {
            bBadge = `<span class="badge" style="background: rgba(239, 68, 68, 0.15); color: #ef4444; font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">⚠️ Planejada</span>`;
        } else if (bUpper.includes('BLOQUEAD') || bUpper.includes('RETORNAD')) {
            bBadge = `<span class="badge" style="background: rgba(225, 29, 72, 0.18); color: #e11d48; font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">⛔ ${bStatus}</span>`;
        } else {
            bBadge = `<span class="badge" style="background: rgba(192, 132, 252, 0.15); color: #c084fc; font-weight: 800; font-size: 0.72rem; padding: 2px 7px; border-radius: 9999px;">🟣 Não Cadastrada</span>`;
        }

        // Timer BID
        const timerVal = r.bid_timer_value && r.bid_timer_value !== '--' ? r.bid_timer_value : '--';

        // Turno
        const shiftPillClass = r.shift_pill_class || 'shift-pill-comercial';
        const turnoHtml = (r.turno && r.turno !== '--')
            ? `<span class="badge ${shiftPillClass}" style="font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 6px;">${r.turno}</span>`
            : `<span style="color: var(--text-secondary); font-size: 0.74rem;">--</span>`;

        // Componentes (BID) - desconsiderando tags L e M
        let componentesHtml = '<span style="color: var(--text-secondary); font-size: 0.74rem;">--</span>';
        if (Array.isArray(r.bid_members) && r.bid_members.length > 0) {
            componentesHtml = r.bid_members.map(m => {
                const name = typeof m === 'object' ? (m.name || '') : String(m);
                const role = typeof m === 'object' ? (m.role || '') : '';
                return `
                    <div style="margin-bottom: 4px;">
                        <div style="font-weight: 700; font-size: 0.76rem; color: var(--text-primary); line-height: 1.2;">
                            ${name}
                        </div>
                        ${role ? `<div style="font-size: 0.68rem; color: var(--text-secondary); line-height: 1.15; margin-top: 1px;">${role}</div>` : ''}
                    </div>
                `;
            }).join('');
        }

        // Placa com Validação Forense de Divergência
        let placaHtml = '';
        if (r.plate_divergent) {
            placaHtml = `
                <div class="plate-divergence-pill" title="DIVERGÊNCIA: Placa no Despacho (${r.plate_eb}) difere da Placa no Checklist (${r.plate_bid})">
                    <div style="display: flex; align-items: center; gap: 4px; color: #ef4444; font-weight: 800; font-size: 0.68rem; margin-bottom: 2px;">
                        <i data-lucide="alert-triangle" style="width: 12px; height: 12px;"></i>
                        <span>PLACA DIVERGENTE</span>
                    </div>
                    <div style="font-family: 'JetBrains Mono', monospace; font-size: 0.74rem; line-height: 1.25;">
                        <div><span style="color: var(--text-secondary); font-size: 0.64rem;">DESP:</span> <strong style="color: var(--text-primary);">${r.plate_eb}</strong></div>
                        <div><span style="color: var(--text-secondary); font-size: 0.64rem;">CHECK:</span> <strong style="color: #ef4444;">${r.plate_bid}</strong></div>
                    </div>
                </div>
            `;
        } else if (r.plate_match) {
            placaHtml = `
                <div style="display: inline-flex; align-items: center; gap: 6px;">
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 800; color: var(--text-primary);">${r.plate}</span>
                    <span style="display: inline-flex; align-items: center; justify-content: center; width: 15px; height: 15px; border-radius: 50%; background: rgba(16, 185, 129, 0.18); color: #10b981;" title="Placa validada: Idêntica no Despacho e no Checklist">
                        <i data-lucide="check" style="width: 10px; height: 10px;"></i>
                    </span>
                </div>
            `;
        } else if (r.plate && r.plate !== '--') {
            placaHtml = `<span style="font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 800; color: var(--text-primary);">${r.plate}</span>`;
        } else {
            placaHtml = `<span style="color: var(--text-secondary); font-size: 0.74rem;">--</span>`;
        }

        return `
            <tr>
                <td>
                    ${crossBadgeHtml}
                    <div style="font-size: 0.68rem; color: var(--text-secondary); margin-top: 3px;">${r.cross_desc || ''}</div>
                </td>
                <td>
                    <button type="button" class="team-badge clickable-team-badge" onclick="event.stopPropagation(); openDeliveryTeamModal('${r.team_code}')" title="Clique para abrir Diagnóstico Forense Completo" style="cursor: pointer;">
                        ${r.team_code}
                    </button>
                </td>
                <td>${progBadge}</td>
                <td>${loginBadge}</td>
                <td>${bBadge}</td>
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: #38bdf8; font-weight: 700;">${timerVal}</span>
                </td>
                <td>
                    <strong style="color: var(--text-primary); font-size: 0.78rem;">${r.base_display || '--'}</strong>
                    <div style="font-size: 0.68rem; color: #0ea5e9;">${r.geo || ''}</div>
                </td>
                <td>${turnoHtml}</td>
                <td>${placaHtml}</td>
                <td>${componentesHtml}</td>
                <td>
                    <span style="font-family: 'JetBrains Mono', monospace; font-size: 0.78rem; color: #0284c7; font-weight: 700;">${r.ordem_servico || '--'}</span>
                </td>
            </tr>
        `;
    }).join('');

    if (typeof renderMobileBidCards === 'function') {
        renderMobileBidCards(list);
    }

    if (window.lucide) {
        lucide.createIcons();
    }

    if (Math.abs(window.scrollY - prevScrollY) > 5) {
        window.scrollTo(0, prevScrollY);
    }
}

function clearOnlineBidFilters(e) {
    if (e && e.preventDefault) e.preventDefault();
    if (e && e.stopPropagation) e.stopPropagation();

    // 1. Marca todos os checkboxes
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox').forEach(cb => {
        cb.checked = true;
    });
    document.querySelectorAll('#deliveryScreenOnlineBid .popover-group-checkbox').forEach(gcb => {
        gcb.checked = true;
        gcb.indeterminate = false;
    });

    // 2. Limpa busca textual
    const search = document.getElementById('filterBidSearch');
    if (search) search.value = '';

    // 3. Reseta card ativo
    onlineBidState.activeCardFilter = '';
    updateActiveKpiCardHighlight('');

    // 4. Sincroniza labels e refiltra
    syncOnlineBidFiltersFromDOM();
    filterOnlineBidTable();
}

function onSelectBidCrossStatus(status) {
    if (!status) {
        document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="cross-status"]').forEach(cb => {
            cb.checked = true;
        });
    } else {
        document.querySelectorAll('#deliveryScreenOnlineBid .popover-checkbox[data-bid-filter="cross-status"]').forEach(cb => {
            cb.checked = (cb.value === status);
        });
    }
    syncOnlineBidFiltersFromDOM();
    filterOnlineBidTable();
}


async function triggerBidCollect() {
    const btn = document.getElementById('btnSyncBidDirect');
    if (btn) {
        btn.classList.add('loading-pulse');
        btn.disabled = true;
    }

    try {
        showToast('Iniciando extração do BID Visão Operacional via CDP...', 'info');
        const resp = await fetch('/api/capture/bid/direct', { method: 'POST' });
        const res = await resp.json();
        if (res.status === 'success') {
            showToast(`Extração concluída com sucesso! ${res.total_collected || 0} equipes sincronizadas.`, 'success');
            await loadOnlineXBidData();
        } else {
            showToast(`Erro na extração BID: ${res.message || 'Falha ao comunicar com CDP'}`, 'danger');
        }
    } catch (err) {
        console.error('[BID SYNC ERROR]', err);
        showToast('Erro de rede ao disparar extração BID.', 'danger');
    } finally {
        if (btn) {
            btn.classList.remove('loading-pulse');
            btn.disabled = false;
        }
    }
}

function exportOnlineXBidExcel() {
    const dateInput = document.getElementById('onlineBidDateInput');
    const targetDate = (dateInput && dateInput.value) ? dateInput.value : (onlineBidState.date || getOperationalDate());
    window.location.href = `/api/bid/export_excel?date=${encodeURIComponent(targetDate)}`;
    showToast('Download da planilha de reconciliação ONLINE x BID iniciado!', 'success');
}

// Binds Globais - Módulo TRBOnet x Equipes Brasil
window.navigateToView = navigateToView;
window.toggleRegionFilter = toggleRegionFilter;
window.toggleBaseFilter = toggleBaseFilter;
window.setBaseFilter = setBaseFilter;
window.toggleTurnoFilter = toggleTurnoFilter;
window.toggleFrotaFilter = toggleFrotaFilter;
window.syncTurnoUI = syncTurnoUI;
window.syncFrotaUI = syncFrotaUI;
window.toggleStatusFilter = toggleStatusFilter;
window.setStatusFilter = setStatusFilter;
window.clearAllFilters = clearAllFilters;
window.handleSearchChange = handleSearchChange;
window.clearSearch = clearSearch;
window.setViewMode = setViewMode;
window.toggleExportMenu = toggleExportMenu;
window.exportLiveTeamsExcel = exportLiveTeamsExcel;
window.exportLiveTeamsCSV = exportLiveTeamsCSV;
window.copySummaryToClipboard = copySummaryToClipboard;

// Binds Globais - Módulo Entrega de Equipes
window.switchDeliveryScreen = switchDeliveryScreen;
window.loadDeliveryData = loadDeliveryData;
window.toggleDeliveryRegionFilter = toggleDeliveryRegionFilter;
window.toggleDeliveryBaseFilter = toggleDeliveryBaseFilter;
window.clearDeliveryBaseFilters = clearDeliveryBaseFilters;
window.setDeliveryShiftFilter = setDeliveryShiftFilter;
window.setDeliveryVehicleFilter = setDeliveryVehicleFilter;
window.debounceDeliverySearch = debounceDeliverySearch;
window.toggleDeliveryTableCollapse = toggleDeliveryTableCollapse;
window.exportDeliveryExcelFiltered = exportDeliveryExcelFiltered;
window.exportDeliveryExcel = exportDeliveryExcel;
window.openDeliveryTeamModal = openDeliveryTeamModal;
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

// Binds de Metas e Planejamento Operacional
window.switchHistoryRegion = switchHistoryRegion;
window.loadTargetsComparativeAudit = loadTargetsComparativeAudit;
window.loadWorkforceMonthlyChart = loadWorkforceMonthlyChart;
window.openMasterPlanningModal = openMasterPlanningModal;
window.verifyAndUnlockPlanning = verifyAndUnlockPlanning;
window.switchPlanningModalTab = switchPlanningModalTab;
window.savePlanningTargets = savePlanningTargets;
window.toggleHistTableCollapse = toggleHistTableCollapse;
window.setAuditReconciliationFilter = setAuditReconciliationFilter;
window.handleCarregarBaseClick = handleCarregarBaseClick;
window.reloadAuditAvailableDates = reloadAuditAvailableDates;
window.openEngineDetailsModal = openEngineDetailsModal;
window.triggerCurrentEngineAction = triggerCurrentEngineAction;
window.triggerSpotfireCdpCapture = triggerSpotfireCdpCapture;
window.triggerBidCdpCapture = triggerBidCdpCapture;

// Binds Globais - Módulo ONLINE x BID
window.loadOnlineXBidData = loadOnlineXBidData;
window.filterOnlineBidTable = filterOnlineBidTable;
window.clearOnlineBidFilters = clearOnlineBidFilters;
window.triggerBidCollect = triggerBidCollect;
window.exportOnlineXBidExcel = exportOnlineXBidExcel;
window.toggleBidCardFilter = toggleBidCardFilter;
window.onSelectBidCrossStatus = onSelectBidCrossStatus;

/* ==========================================================================
   SISTEMA ADAPTATIVO MOBILE & TABLET (M3 EXPRESSIVE + APPLE LIQUID GLASS + PWA)
   ========================================================================== */

// 1. Navegação Bottom Nav e Sincronização
window.switchView = navigateToView;
window.navigateToView = navigateToView;

// ==========================================================================
// SUB-NAVEGAÇÃO MÓVEL (Sub-Módulos Entrega e Alertas <= 768px)
// ==========================================================================
function updateMobileSubnav(viewName, subScreen) {
    const subnavBar = document.getElementById('mobileSubnavBar');
    const delSubnav = document.getElementById('mobileDeliverySubnav');
    const alrSubnav = document.getElementById('mobileAlertsSubnav');
    if (!subnavBar) return;

    if (viewName === 'delivery') {
        subnavBar.style.display = 'flex';
        if (delSubnav) delSubnav.style.display = 'flex';
        if (alrSubnav) alrSubnav.style.display = 'none';

        const targetScreen = subScreen || deliveryState.currentScreen || 'online';
        document.querySelectorAll('#mobileDeliverySubnav .mobile-subnav-pill').forEach(btn => btn.classList.remove('active'));
        if (targetScreen === 'online') {
            document.getElementById('mobSubDeliveryOnline')?.classList.add('active');
        } else if (targetScreen === 'online_bid') {
            document.getElementById('mobSubDeliveryBid')?.classList.add('active');
        } else if (targetScreen === 'history') {
            document.getElementById('mobSubDeliveryHistory')?.classList.add('active');
        }
    } else if (viewName === 'module' || viewName === 'trbonet' || viewName === 'alerts') {
        subnavBar.style.display = 'flex';
        if (delSubnav) delSubnav.style.display = 'none';
        if (alrSubnav) alrSubnav.style.display = 'flex';

        const targetTab = subScreen || appState.currentMainTab || 'live';
        document.querySelectorAll('#mobileAlertsSubnav .mobile-subnav-pill').forEach(btn => btn.classList.remove('active'));
        if (targetTab === 'live') {
            document.getElementById('mobSubAlertsLive')?.classList.add('active');
        } else if (targetTab === 'dashboard') {
            document.getElementById('mobSubAlertsDash')?.classList.add('active');
        } else if (targetTab === 'audit') {
            document.getElementById('mobSubAlertsAudit')?.classList.add('active');
        }
    } else {
        subnavBar.style.display = 'none';
        if (delSubnav) delSubnav.style.display = 'none';
        if (alrSubnav) alrSubnav.style.display = 'none';
    }
}
window.updateMobileSubnav = updateMobileSubnav;

function handleMobileDeliverySub(subScreen) {
    if (appState.currentView !== 'delivery') {
        navigateToView('delivery');
    }
    if (typeof switchDeliveryScreen === 'function') {
        switchDeliveryScreen(subScreen);
    }
    updateMobileSubnav('delivery', subScreen);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.handleMobileDeliverySub = handleMobileDeliverySub;

function handleMobileAlertsSub(subTab) {
    if (appState.currentView !== 'module' && appState.currentView !== 'trbonet') {
        navigateToView('module');
    }
    if (typeof switchMainTab === 'function') {
        switchMainTab(subTab);
    }
    updateMobileSubnav('module', subTab);
    window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.handleMobileAlertsSub = handleMobileAlertsSub;

function syncMobileBottomNav(activeIdentifier) {
    const navItems = document.querySelectorAll('#mobileBottomNav .nav-item');
    navItems.forEach(item => item.classList.remove('active'));

    const titleEl = document.getElementById('mobileAppTitle');
    const subtitleEl = document.getElementById('mobileAppSubtitle');

    if (activeIdentifier === 'hub') {
        document.getElementById('navItemHub')?.classList.add('active');
        if (titleEl) titleEl.textContent = 'PORTAL CCO';
        if (subtitleEl) subtitleEl.textContent = 'HUB OPERACIONAL';
        updateMobileSubnav('hub');
    } else if (activeIdentifier === 'module' || activeIdentifier === 'trbonet' || activeIdentifier === 'alerts') {
        const item = document.getElementById('navItemTrbonet') || document.getElementById('navItemAlerts');
        item?.classList.add('active');
        if (titleEl) titleEl.textContent = 'TRBONET';
        if (subtitleEl) subtitleEl.textContent = 'DISCORDÂNCIA REALTIME';
        updateMobileSubnav('module');
    } else if (activeIdentifier === 'delivery' || activeIdentifier === 'online' || activeIdentifier === 'delivery_online' || activeIdentifier === 'online_bid' || activeIdentifier === 'bid' || activeIdentifier === 'delivery_bid' || activeIdentifier === 'history' || activeIdentifier === 'delivery_history') {
        document.getElementById('navItemDelivery')?.classList.add('active');
        if (titleEl) titleEl.textContent = 'ENTREGA DE EQUIPES';
        if (subtitleEl) subtitleEl.textContent = 'EQUIPES BRASIL';
        const sub = (activeIdentifier === 'online_bid' || activeIdentifier === 'bid' || activeIdentifier === 'delivery_bid') ? 'online_bid' : ((activeIdentifier === 'history' || activeIdentifier === 'delivery_history') ? 'history' : (deliveryState.currentScreen || 'online'));
        updateMobileSubnav('delivery', sub);
    } else if (activeIdentifier === 'admin') {
        document.getElementById('navItemMore')?.classList.add('active');
        if (titleEl) titleEl.textContent = 'ADMIN & MOTORES';
        if (subtitleEl) subtitleEl.textContent = 'TELEMETRIA MASTER';
        updateMobileSubnav('admin');
    }
}

function handleMobileNav(target) {
    if (target === 'hub') {
        navigateToView('hub');
        syncMobileBottomNav('hub');
    } else if (target === 'trbonet' || target === 'alerts' || target === 'module') {
        navigateToView('module');
        syncMobileBottomNav('trbonet');
    } else if (target === 'delivery_online' || target === 'delivery') {
        navigateToView('delivery');
        if (typeof switchDeliveryScreen === 'function') switchDeliveryScreen(deliveryState.currentScreen || 'online');
        syncMobileBottomNav('delivery');
    } else if (target === 'delivery_bid') {
        navigateToView('delivery');
        if (typeof switchDeliveryScreen === 'function') switchDeliveryScreen('online_bid');
        syncMobileBottomNav('delivery');
    } else if (target === 'delivery_history') {
        navigateToView('delivery');
        if (typeof switchDeliveryScreen === 'function') switchDeliveryScreen('history');
        syncMobileBottomNav('delivery');
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Alternador de Sub-Abas do Módulo Entrega em Celular (Equipes / Gráficos / Bases)
function switchMobileDeliverySubTab(subtab) {
    document.body.classList.remove('mobile-subtab-feed', 'mobile-subtab-charts', 'mobile-subtab-bases');
    document.body.classList.add(`mobile-subtab-${subtab}`);

    document.querySelectorAll('.mobile-subtab-btn').forEach(btn => {
        if (btn.getAttribute('data-subtab') === subtab) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    if (subtab === 'charts') {
        if (typeof renderDeliveryCharts === 'function') {
            setTimeout(renderDeliveryCharts, 60);
        }
    }
    window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.switchMobileDeliverySubTab = switchMobileDeliverySubTab;

// Sincroniza Bottom Nav em mudanças de URL Hash
window.addEventListener('hashchange', () => {
    const hash = window.location.hash.replace('#', '');
    if (hash === 'delivery') {
        syncMobileBottomNav('delivery');
    } else if (hash === 'module' || hash === 'trbonet' || hash === 'alerts') {
        syncMobileBottomNav('trbonet');
    } else if (hash === 'admin') {
        syncMobileBottomNav('admin');
    } else {
        syncMobileBottomNav('hub');
    }
});

// 2. Sistema de Bottom Sheets (Abertura / Fechamento Suave com Backdrop)
function openBottomSheet(sheetId) {
    closeAllBottomSheets(false);
    const sheet = document.getElementById(sheetId);
    const backdrop = document.getElementById('bottomSheetBackdrop');
    if (!sheet) return;

    sheet.style.display = 'flex';
    // Força reflow antes de adicionar classe de animação
    void sheet.offsetHeight;
    sheet.classList.add('open');

    if (backdrop) {
        backdrop.style.display = 'block';
        void backdrop.offsetHeight;
        backdrop.classList.add('active');
    }
    document.body.style.overflow = 'hidden';
    if (window.lucide) lucide.createIcons();
}

function closeBottomSheet(sheetId) {
    const sheet = document.getElementById(sheetId);
    if (sheet) {
        sheet.classList.remove('open');
        setTimeout(() => {
            if (!sheet.classList.contains('open')) {
                sheet.style.display = 'none';
            }
        }, 360);
    }

    const anyOpen = document.querySelectorAll('.bottom-sheet.open');
    if (anyOpen.length <= 1) {
        const backdrop = document.getElementById('bottomSheetBackdrop');
        if (backdrop) {
            backdrop.classList.remove('active');
            setTimeout(() => {
                if (!backdrop.classList.contains('active')) {
                    backdrop.style.display = 'none';
                }
            }, 300);
        }
        document.body.style.overflow = '';
    }
}

function closeAllBottomSheets(restoreOverflow = true) {
    document.querySelectorAll('.bottom-sheet').forEach(sheet => {
        sheet.classList.remove('open');
        setTimeout(() => {
            if (!sheet.classList.contains('open')) {
                sheet.style.display = 'none';
            }
        }, 360);
    });
    const backdrop = document.getElementById('bottomSheetBackdrop');
    if (backdrop) {
        backdrop.classList.remove('active');
        setTimeout(() => {
            if (!backdrop.classList.contains('active')) {
                backdrop.style.display = 'none';
            }
        }, 300);
    }
    if (restoreOverflow) {
        document.body.style.overflow = '';
    }
}

// 3. Filtros Operacionais Mobile
const mobileFilterState = {
    region: '',
    status: '',
    search: ''
};

function selectMobileRegion(region) {
    mobileFilterState.region = region;
    const chips = document.querySelectorAll('#mobileRegionChips .m3-chip');
    chips.forEach(chip => {
        if (chip.getAttribute('data-region') === region) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });
    updateMobileFilterCountBadge();
}

function selectMobileStatus(status) {
    mobileFilterState.status = status;
    const chips = document.querySelectorAll('#mobileStatusChips .m3-chip');
    chips.forEach(chip => {
        if (chip.getAttribute('data-status') === status) {
            chip.classList.add('active');
        } else {
            chip.classList.remove('active');
        }
    });
    updateMobileFilterCountBadge();
}

function handleMobileSearch(val) {
    mobileFilterState.search = (val || '').trim();
    const clearBtn = document.getElementById('mobileSearchClear');
    if (clearBtn) clearBtn.style.display = mobileFilterState.search ? 'flex' : 'none';
    updateMobileFilterCountBadge();
}

function clearMobileSearch() {
    const input = document.getElementById('mobileSearchInput');
    if (input) input.value = '';
    handleMobileSearch('');
}

function resetMobileFilters() {
    mobileFilterState.region = '';
    mobileFilterState.status = '';
    mobileFilterState.search = '';
    const input = document.getElementById('mobileSearchInput');
    if (input) input.value = '';
    const clearBtn = document.getElementById('mobileSearchClear');
    if (clearBtn) clearBtn.style.display = 'none';

    document.querySelectorAll('#mobileRegionChips .m3-chip').forEach((c, idx) => {
        if (idx === 0) c.classList.add('active'); else c.classList.remove('active');
    });
    document.querySelectorAll('#mobileStatusChips .m3-chip').forEach((c, idx) => {
        if (idx === 0) c.classList.add('active'); else c.classList.remove('active');
    });

    if (typeof clearDeliveryBaseFilters === 'function') {
        clearDeliveryBaseFilters();
    }
    if (typeof clearOnlineBidFilters === 'function') {
        clearOnlineBidFilters();
    }
    updateMobileFilterCountBadge();
    showToast('Filtros limpos', 'info');
}

function updateMobileFilterCountBadge() {
    const badge = document.getElementById('mobileFilteredCount');
    const headerBadge = document.getElementById('mobileFilterBadge');
    let count = 0;
    if (deliveryState && deliveryState.filteredTeams) {
        count = deliveryState.filteredTeams.length;
    }
    if (badge) badge.textContent = `${count} equipes`;

    const hasActiveFilter = mobileFilterState.region || mobileFilterState.status || mobileFilterState.search;
    if (headerBadge) {
        headerBadge.style.display = hasActiveFilter ? 'block' : 'none';
    }
}

function applyMobileFiltersAndClose() {
    if (deliveryState && deliveryState.filters) {
        if (mobileFilterState.region) {
            deliveryState.filters.regions = new Set([mobileFilterState.region]);
        } else {
            deliveryState.filters.regions.clear();
        }
        deliveryState.filters.search = mobileFilterState.search;
        applyDeliveryFilters();
    }

    const searchBidInput = document.getElementById('filterBidSearch');
    if (searchBidInput) {
        searchBidInput.value = mobileFilterState.search;
    }
    if (typeof filterOnlineBidTable === 'function') {
        filterOnlineBidTable();
    }

    closeBottomSheet('sheetFilters');
    showToast('Filtros aplicados com sucesso', 'success');
}

function handleMobileRefresh() {
    const refreshBtn = document.getElementById('btnMobileRefresh');
    if (refreshBtn) refreshBtn.classList.add('loading-pulse');

    if (appState.currentView === 'delivery') {
        if (deliveryState.currentScreen === 'online_bid') {
            if (typeof loadOnlineXBidData === 'function') loadOnlineXBidData();
        } else {
            if (typeof loadDeliveryData === 'function') loadDeliveryData(false);
        }
    } else if (appState.currentView === 'admin') {
        if (typeof loadAdminEngineStatus === 'function') loadAdminEngineStatus();
    } else {
        if (typeof fetchData === 'function') fetchData();
    }

    setTimeout(() => {
        if (refreshBtn) refreshBtn.classList.remove('loading-pulse');
        showToast('Dados sincronizados com sucesso!', 'success');
    }, 800);
}

// 4. Renderizadores de Cards Mobile
function renderMobileDeliveryCards(list) {
    const feed = document.getElementById('deliveryMobileCardsFeed');
    if (!feed) return;

    if (!list || list.length === 0) {
        feed.innerHTML = `
            <div class="mobile-team-card" style="text-align: center; padding: 32px 16px;">
                <i data-lucide="inbox" style="width: 36px; height: 36px; color: #64748b; margin: 0 auto 10px auto;"></i>
                <h4 style="color: var(--text-primary); margin: 0 0 6px 0;">Nenhuma equipe encontrada</h4>
                <p style="color: var(--text-secondary); font-size: 0.8rem; margin: 0;">Ajuste os filtros ou toque em atualizar.</p>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
    }

    feed.innerHTML = list.map(t => {
        const isAct = t.is_active;
        const statusEB = t.status_equipes_brasil || t.status || (isAct ? 'Logada' : 'Turno Concluído');
        
        let borderClass = 'status-border-sem-eb';
        let statusPillStyle = 'background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3);';

        if (statusEB.toLowerCase().includes('atendimento') || statusEB.toLowerCase().includes('livre') || statusEB.toLowerCase().includes('deslocamento') || isAct) {
            borderClass = 'status-border-operacao';
            statusPillStyle = 'background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);';
        } else if (statusEB.toLowerCase().includes('descanso')) {
            borderClass = 'status-border-checklist';
            statusPillStyle = 'background: rgba(139, 92, 246, 0.15); color: #8b5cf6; border: 1px solid rgba(139, 92, 246, 0.4);';
        } else if (statusEB.toLowerCase().includes('bloqueada')) {
            borderClass = 'status-border-bloqueada';
            statusPillStyle = 'background: rgba(244, 63, 94, 0.15); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.4);';
        }

        const teamCode = t.team_code || '--';
        const baseName = t.base_display || t.base_name || t.ut || '--';
        const driverName = t.driver || '--';
        const plateVal = t.plate && t.plate !== '--' ? t.plate : 'Sem placa';
        const shiftSlot = t.shift_slot || t.turno || '--';
        const marcacao = t.marcacao || '--:--';
        const osNum = t.ordem_servico || '--';

        return `
            <div class="mobile-team-card ${borderClass}" onclick="openDeliveryTeamModal('${teamCode}')">
                <div class="card-top-row">
                    <div class="card-team-prefix">
                        <i data-lucide="users" style="width: 18px; height: 18px;"></i>
                        <span>${teamCode}</span>
                    </div>
                    <span class="card-status-pill" style="${statusPillStyle}">${statusEB}</span>
                </div>
                <div class="card-meta-grid">
                    <div class="card-meta-item">
                        <span class="card-meta-label">Base / UT</span>
                        <span class="card-meta-val">${baseName}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Turno</span>
                        <span class="card-meta-val">${shiftSlot}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Motorista</span>
                        <span class="card-meta-val">${driverName}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Placa</span>
                        <span class="card-meta-val">${plateVal}</span>
                    </div>
                </div>
                <div class="card-bottom-row">
                    <div>
                        <span>Login: <strong>${marcacao}</strong></span>
                        ${osNum !== '--' ? ` • OS: <strong style="color: #38bdf8;">${osNum}</strong>` : ''}
                    </div>
                    <div class="card-chevron-hint">
                        <span>Detalhes</span>
                        <i data-lucide="chevron-right" style="width: 14px; height: 14px;"></i>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();
}

function renderMobileBidCards(list) {
    const feed = document.getElementById('onlineBidMobileCardsFeed');
    if (!feed) return;

    if (!list || list.length === 0) {
        feed.innerHTML = `
            <div class="mobile-team-card" style="text-align: center; padding: 32px 16px;">
                <i data-lucide="git-compare" style="width: 36px; height: 36px; color: #64748b; margin: 0 auto 10px auto;"></i>
                <h4 style="color: var(--text-primary); margin: 0 0 6px 0;">Nenhuma equipe no Cruzamento BID</h4>
                <p style="color: var(--text-secondary); font-size: 0.8rem; margin: 0;">Nenhum registro compatível com os filtros atuais.</p>
            </div>
        `;
        if (window.lucide) lucide.createIcons();
        return;
    }

    feed.innerHTML = list.map(r => {
        const teamCode = r.team_code || '--';
        const crossStatus = r.cross_status || 'DESCONHECIDO';
        const isEb = r.is_eb_active;
        const bidStatus = r.status_bid || 'Não Encontrada';
        const timerVal = r.bid_timer_value || '--';
        const baseDisp = r.base_display || r.geo || '--';
        const plateVal = r.plate || r.plate_bid || '--';

        let borderClass = 'status-border-sem-eb';
        let crossPillStyle = 'background: rgba(148, 163, 184, 0.15); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.3);';

        if (crossStatus.includes('CONFORME')) {
            borderClass = 'status-border-operacao';
            crossPillStyle = 'background: rgba(16, 185, 129, 0.15); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.4);';
        } else if (crossStatus.includes('CRÍTICO') || crossStatus.includes('GRAVÍSSIMO') || crossStatus.includes('IMPEDITIVO')) {
            borderClass = 'status-border-bloqueada';
            crossPillStyle = 'background: rgba(244, 63, 94, 0.15); color: #f43f5e; border: 1px solid rgba(244, 63, 94, 0.4);';
        } else if (crossStatus.includes('GRAVE')) {
            borderClass = 'status-border-sem-eb';
            crossPillStyle = 'background: rgba(245, 158, 11, 0.15); color: #f59e0b; border: 1px solid rgba(245, 158, 11, 0.4);';
        }

        return `
            <div class="mobile-team-card ${borderClass}" onclick="openDeliveryTeamModal('${teamCode}')">
                <div class="card-top-row">
                    <div class="card-team-prefix">
                        <i data-lucide="git-merge" style="width: 18px; height: 18px;"></i>
                        <span>${teamCode}</span>
                    </div>
                    <span class="card-status-pill" style="${crossPillStyle}">${crossStatus}</span>
                </div>
                <div class="card-meta-grid">
                    <div class="card-meta-item">
                        <span class="card-meta-label">Status Prog</span>
                        <span class="card-meta-val" style="color: ${isEb ? '#10b981' : '#94a3b8'};">${r.status_prog || (isEb ? 'Logada' : 'Não Logada')}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Status Login</span>
                        <span class="card-meta-val" style="color: ${r.status_login === 'LOGADA' ? '#10b981' : '#38bdf8'}; font-weight: 800;">${r.status_login || 'PROGRAMADA'}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Status BID</span>
                        <span class="card-meta-val" style="color: #38bdf8;">${bidStatus}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Base</span>
                        <span class="card-meta-val">${baseDisp}</span>
                    </div>
                    <div class="card-meta-item">
                        <span class="card-meta-label">Placa</span>
                        <span class="card-meta-val">${plateVal}</span>
                    </div>
                </div>
                <div class="card-bottom-row">
                    <div>
                        <span>Tempo BID: <strong>${timerVal}</strong></span>
                        ${r.turno ? ` • Turno: <strong>${r.turno}</strong>` : ''}
                    </div>
                    <div class="card-chevron-hint">
                        <span>Auditar</span>
                        <i data-lucide="chevron-right" style="width: 14px; height: 14px;"></i>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    if (window.lucide) lucide.createIcons();
}

// 5. Integração PWA e Service Worker
window.deferredPwaPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    window.deferredPwaPrompt = e;
    const btnWrapper = document.getElementById('pwaInstallNativeBtnWrapper');
    if (btnWrapper) btnWrapper.style.display = 'block';
});

function triggerNativePwaInstall() {
    if (window.deferredPwaPrompt) {
        window.deferredPwaPrompt.prompt();
        window.deferredPwaPrompt.userChoice.then((choiceResult) => {
            if (choiceResult.outcome === 'accepted') {
                showToast('Aplicativo instalado com sucesso!', 'success');
            }
            window.deferredPwaPrompt = null;
            const btnWrapper = document.getElementById('pwaInstallNativeBtnWrapper');
            if (btnWrapper) btnWrapper.style.display = 'none';
        });
    } else {
        openBottomSheet('sheetPwaInstallGuide');
    }
}

// Registro do Service Worker ao Carregar a Página
window.addEventListener('load', () => {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/sw.js', { scope: '/' })
            .then(reg => {
                console.log('[PWA] Service Worker registrado com escopo:', reg.scope);
                // Força verificação imediata de nova versão
                reg.update();
            })
            .catch(err => {
                console.warn('[PWA] Falha ao registrar Service Worker:', err);
            });
    }

    // Monitor em tempo real de falha de cluster e motores para usuários autenticados
    setInterval(checkClusterHealthAlerts, 25000);
    setTimeout(checkClusterHealthAlerts, 2500);
});

// Binds Globais para o Window
window.handleMobileNav = handleMobileNav;
window.handleMobileDeliverySub = handleMobileDeliverySub;
window.handleMobileAlertsSub = handleMobileAlertsSub;
window.updateMobileSubnav = updateMobileSubnav;
window.openBottomSheet = openBottomSheet;
window.closeBottomSheet = closeBottomSheet;
window.closeAllBottomSheets = closeAllBottomSheets;
window.selectMobileRegion = selectMobileRegion;
window.selectMobileStatus = selectMobileStatus;
window.handleMobileSearch = handleMobileSearch;
window.clearMobileSearch = clearMobileSearch;
window.resetMobileFilters = resetMobileFilters;
window.applyMobileFiltersAndClose = applyMobileFiltersAndClose;
window.handleMobileRefresh = handleMobileRefresh;
window.renderMobileDeliveryCards = renderMobileDeliveryCards;
window.renderMobileBidCards = renderMobileBidCards;
window.triggerNativePwaInstall = triggerNativePwaInstall;
window.syncMobileBottomNav = syncMobileBottomNav;
window.promoteNodeAction = promoteNodeAction;
window.dismissClusterAlert = dismissClusterAlert;
window.openClusterNodeDetailsModal = openClusterNodeDetailsModal;
