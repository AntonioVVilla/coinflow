// Chart.js defaults
if (window.Chart) {
    Chart.defaults.color = '#8b8fa0';
    Chart.defaults.borderColor = '#2a2e3e';
    Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif";
}

// Register service worker for PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/static/sw.js').catch(() => {});
    });
}

const COLORS = ['#6366f1', '#22c55e', '#f97316', '#a855f7', '#3b82f6', '#eab308', '#ef4444'];

function app() {
    return {
        // Auth state
        authRequired: false,
        authenticated: true,
        hasPassword: false,
        loginPass: '',
        loginError: '',
        newPassword: '',

        // UI state
        page: 'dashboard',
        currency: localStorage.getItem('currency') || 'USD',
        tradeDetail: null,
        tickResult: null,
        diagnostic: null,
        diagnosticLoading: false,
        showBacktest: false,
        backtestLoading: false,
        backtestResult: null,
        backtestForm: {
            strategy: 'dca',
            symbol: 'BTC/USD',
            timeframe: '1h',
            candles: 500,
            initial_quote: 1000,
            params: { amount_usd: 50, interval_hours: 24 },
        },
        accountData: { accounts: [], total_usd: 0 },
        openOrders: [],
        accountLoading: false,
        syncLoading: false,
        syncReport: null,
        lastSync: localStorage.getItem('lastCoinbaseSync') || null,
        toasts: [],

        // Data state
        dashboard: { total_usd: 0, prices: {}, balances: {}, strategies: {}, stats: {}, recent_trades: [], allocation: [], paper_mode: true, eur_rate: 0.92 },
        strategies: [],
        tradesData: { trades: [], total: 0, page: 1, pages: 0 },
        tradeStats: { totals: {}, by_strategy: [], by_side: [], by_symbol: [], by_day: [] },
        tradeFilters: { page: 1, strategy: '', symbol: '', side: '', since_hours: 168 },
        exchangeStatus: { configured: false },
        notifStatus: { telegram: {}, email: {} },
        riskConfig: { enabled: false, max_daily_loss_usd: 0, max_drawdown_pct: 0, max_btc_allocation_pct: 100, max_eth_allocation_pct: 100, circuit_breaker_pct: 0, paused_until: null },
        wizardKeys: { api_key: '', api_secret: '' },
        wizardLoading: false, wizardValid: false, wizardResult: '',

        // Telegram
        tgConfig: { configured: false, enabled: false, chat_id: '', bot_username: '', token_hint: '' },
        tgWizard: { bot_token: '', chat_id: '', validated: false, bot_username: '',
                    loading: false, error: '', chats: [], detectError: '',
                    testResult: '', testOk: false },
        tgCommands: [],
        showTgCommands: false,
        supportedSymbols: ['BTC/USD', 'ETH/USD'],  // filled from backend

        // Email
        emailConfig: { configured: false, enabled: false, smtp_host: '', smtp_port: 587, smtp_user: '', email_to: '' },
        emailWizard: { smtp_host: '', smtp_port: 587, smtp_user: '', smtp_pass: '', email_to: '',
                       loading: false, result: '', ok: false },
        showEmailWizard: false,

        // Live
        portfolioRange: parseInt(localStorage.getItem('portfolioRange') || '24', 10),
        portfolioScale: localStorage.getItem('portfolioScale') || 'auto',
        priceSymbol: 'BTC/USD',
        priceTimeframe: localStorage.getItem('priceTimeframe') || '1h',
        priceScale: localStorage.getItem('priceScale') || 'auto',
        refreshTimer: null,
        charts: {},
        ws: null,
        wsConnected: false,

        async init() {
            await this.checkAuth();
            if (this.authRequired && !this.authenticated) return;
            await this.loadAll();
            this.connectWS();
            this.refreshTimer = setInterval(() => {
                if (this.page === 'dashboard') this.loadDashboard();
            }, 30000);

            // Re-render charts when window resizes (debounced)
            let resizeTimer;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimer);
                resizeTimer = setTimeout(() => {
                    if (this.page === 'dashboard') this.renderDashboardCharts();
                    if (this.page === 'trades') this.renderTradeCharts();
                }, 300);
            });
        },

        // ============= AUTH =============
        async checkAuth() {
            const status = await this.apiPublic('/api/auth/status');
            if (status) {
                this.authRequired = status.enabled;
                this.authenticated = status.authenticated;
                this.hasPassword = status.enabled;
            }
        },

        async setupPassword() {
            if (this.loginPass.length < 4) { this.loginError = 'Minimo 4 caracteres'; return; }
            const res = await this.apiPublic('/api/auth/setup', { method: 'POST', body: { password: this.loginPass } });
            if (res?.ok) {
                await this.doLogin();
            } else this.loginError = res?.detail || 'Error';
        },

        async doLogin() {
            this.loginError = '';
            const res = await this.apiPublic('/api/auth/login', { method: 'POST', body: { password: this.loginPass } });
            if (res?.ok) {
                this.authenticated = true;
                this.loginPass = '';
                await this.loadAll();
                this.connectWS();
            } else {
                this.loginError = res?.detail || 'Password incorrecto';
            }
        },

        async doLogout() {
            await this.api('/api/auth/logout', { method: 'POST' });
            location.reload();
        },

        async changePassword() {
            if (this.newPassword.length < 4) { alert('Minimo 4 caracteres'); return; }
            const res = await this.api('/api/auth/setup', { method: 'POST', body: { password: this.newPassword } });
            if (res?.ok) {
                this.newPassword = '';
                this.toast('Password actualizado', 'info');
                await this.checkAuth();
            } else alert(res?.detail || 'Error');
        },

        async disableAuth() {
            const pass = prompt('Confirma tu password actual para desactivar la autenticacion:');
            if (!pass) return;
            const res = await this.api('/api/auth/disable', { method: 'POST', body: { password: pass } });
            if (res?.ok) {
                this.toast('Autenticacion desactivada', 'warning');
                location.reload();
            } else alert(res?.detail || 'Error');
        },

        // ============= WEBSOCKET =============
        connectWS() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const url = `${proto}//${location.host}/ws`;
            this.ws = new WebSocket(url);
            this.ws.onopen = () => { this.wsConnected = true; };
            this.ws.onclose = () => {
                this.wsConnected = false;
                setTimeout(() => this.connectWS(), 3000); // reconnect
            };
            this.ws.onerror = () => { this.wsConnected = false; };
            this.ws.onmessage = (e) => {
                try {
                    const msg = JSON.parse(e.data);
                    this.handleWsMessage(msg);
                } catch {}
            };
        },

        handleWsMessage(msg) {
            if (msg.type === 'prices') {
                // Update prices in dashboard object without full reload
                if (msg.data.prices) {
                    Object.assign(this.dashboard.prices, msg.data.prices);
                }
                if (msg.data.strategies) {
                    this.dashboard.strategies = msg.data.strategies;
                }
            } else if (msg.type === 'trade') {
                const d = msg.data;
                const sym = d.side === 'buy' ? '🟢' : '🔴';
                this.toast(`${sym} ${d.side.toUpperCase()} ${d.amount.toFixed(6)} ${d.symbol} @ ${this.money(d.price)}`, 'trade');
                // Refresh dashboard to get new data
                this.loadDashboard();
                if (this.page === 'trades') this.loadTradesAndStats();
            }
        },

        // ============= TOASTS =============
        toast(msg, type = 'info') {
            const id = Date.now() + Math.random();
            this.toasts.push({ id, msg, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 5000);
        },

        setPage(p) {
            // Destroy charts from the page we're leaving to avoid ghost canvases
            if (this.page === 'dashboard') {
                this.destroyChart('portfolio');
                this.destroyChart('allocation');
                this.destroyChart('price');
            }
            if (this.page === 'trades') {
                this.destroyChart('byStrategy');
                this.destroyChart('byDay');
            }
            this.page = p;
            // Multi-stage render: quick try + retries via _ensureCanvas
            requestAnimationFrame(() => {
                setTimeout(() => {
                    if (p === 'dashboard') this.renderDashboardCharts();
                    if (p === 'trades') this.renderTradeCharts();
                    if (p === 'risk') this.loadRisk();
                    if (p === 'account') this.loadAccount();
                }, 50);
            });
        },

        setCurrency(c) {
            this.currency = c;
            localStorage.setItem('currency', c);
            this.$nextTick(() => {
                if (this.page === 'dashboard') this.renderDashboardCharts();
                if (this.page === 'trades') this.renderTradeCharts();
            });
        },

        showTradeDetail(t) { this.tradeDetail = t; },

        // ============= API =============
        async apiPublic(url, opts = {}) {
            try {
                const res = await fetch(url, {
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    ...opts,
                    body: opts.body ? JSON.stringify(opts.body) : undefined,
                });
                return await res.json();
            } catch (e) { console.error('API error:', e); return null; }
        },
        async api(url, opts = {}) {
            try {
                const res = await fetch(url, {
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                    ...opts,
                    body: opts.body ? JSON.stringify(opts.body) : undefined,
                });
                if (res.status === 401) {
                    this.authenticated = false;
                    return null;
                }
                return await res.json();
            } catch (e) { console.error('API error:', e); return null; }
        },

        async loadAll() {
            await Promise.all([
                this.loadDashboard(), this.loadStrategies(),
                this.loadTradesAndStats(), this.loadExchangeStatus(),
                this.loadNotifStatus(), this.loadRisk(),
                this.loadTelegram(), this.loadEmail(),
                this.loadSymbols(),
            ]);
            this.$nextTick(() => this.renderDashboardCharts());
        },

        async loadSymbols() {
            const d = await this.api('/api/settings/symbols');
            if (d?.symbols) this.supportedSymbols = d.symbols;
        },

        // ============= TELEGRAM =============
        async loadTelegram() {
            const [cfg, cmds] = await Promise.all([
                this.api('/api/notifications/telegram'),
                this.api('/api/notifications/telegram/commands'),
            ]);
            if (cfg) this.tgConfig = cfg;
            if (cmds) this.tgCommands = cmds.commands || [];
        },
        async validateTelegramToken() {
            this.tgWizard.loading = true; this.tgWizard.error = ''; this.tgWizard.validated = false;
            const res = await this.api('/api/notifications/telegram/validate', {
                method: 'POST', body: { bot_token: this.tgWizard.bot_token },
            });
            this.tgWizard.loading = false;
            if (res?.valid) {
                this.tgWizard.validated = true;
                this.tgWizard.bot_username = res.bot.username;
            } else {
                this.tgWizard.error = res?.error || 'Token invalido';
            }
        },
        async detectChatId() {
            this.tgWizard.loading = true; this.tgWizard.detectError = ''; this.tgWizard.chats = [];
            const res = await this.api('/api/notifications/telegram/detect-chat', {
                method: 'POST', body: { bot_token: this.tgWizard.bot_token },
            });
            this.tgWizard.loading = false;
            if (res?.ok) {
                this.tgWizard.chat_id = res.chat_id;
                this.tgWizard.chats = res.chats || [];
            } else {
                this.tgWizard.detectError = res?.error || 'No se pudo detectar';
            }
        },
        async testTelegram() {
            this.tgWizard.loading = true; this.tgWizard.testResult = '';
            const res = await this.api('/api/notifications/telegram/test', {
                method: 'POST', body: { bot_token: this.tgWizard.bot_token, chat_id: this.tgWizard.chat_id },
            });
            this.tgWizard.loading = false;
            this.tgWizard.testOk = res?.ok || false;
            this.tgWizard.testResult = res?.ok ? '✓ Mensaje enviado correctamente. Revisa Telegram.' : ('Error: ' + (res?.error || '?'));
        },
        async saveTelegram() {
            this.tgWizard.loading = true;
            const res = await this.api('/api/notifications/telegram/save', {
                method: 'POST', body: { bot_token: this.tgWizard.bot_token, chat_id: this.tgWizard.chat_id },
            });
            this.tgWizard.loading = false;
            if (res?.ok) {
                this.tgWizard = { bot_token: '', chat_id: '', validated: false, bot_username: '',
                                  loading: false, error: '', chats: [], detectError: '',
                                  testResult: '', testOk: false };
                this.toast('Telegram conectado ✓', 'info');
                await this.loadTelegram();
            } else {
                this.tgWizard.testResult = res?.error || 'Error al guardar';
                this.tgWizard.testOk = false;
            }
        },
        async testTelegramSaved() {
            const res = await this.api('/api/notifications/telegram/test-saved', { method: 'POST' });
            if (res?.ok) this.toast('✓ Mensaje enviado, revisa Telegram', 'trade');
            else this.toast('Error: ' + (res?.error || '?'), 'error');
        },
        async sendDailySummary() {
            this.toast('Generando resumen...', 'info');
            const res = await this.api('/api/notifications/daily-summary/send', { method: 'POST' });
            if (res?.ok) this.toast('✓ Resumen enviado a canales activos', 'trade');
            else this.toast('Error: ' + (res?.error || '?'), 'error');
        },
        async toggleTelegram() {
            const res = await this.api('/api/notifications/telegram/toggle', { method: 'POST' });
            if (res?.ok) {
                await this.loadTelegram();
                this.toast(`Telegram ${res.enabled ? 'activado' : 'desactivado'}`, 'info');
            }
        },
        async deleteTelegram() {
            if (!confirm('Eliminar la configuracion de Telegram?')) return;
            await this.api('/api/notifications/telegram', { method: 'DELETE' });
            await this.loadTelegram();
            this.toast('Telegram eliminado', 'warning');
        },

        // ============= EMAIL =============
        async loadEmail() {
            const d = await this.api('/api/notifications/email');
            if (d) {
                this.emailConfig = d;
                // Prefill wizard with existing values
                this.emailWizard.smtp_host = d.smtp_host || '';
                this.emailWizard.smtp_port = d.smtp_port || 587;
                this.emailWizard.smtp_user = d.smtp_user || '';
                this.emailWizard.email_to = d.email_to || '';
            }
        },
        async testEmail() {
            this.emailWizard.loading = true; this.emailWizard.result = '';
            const res = await this.api('/api/notifications/email/test', {
                method: 'POST', body: {
                    smtp_host: this.emailWizard.smtp_host,
                    smtp_port: this.emailWizard.smtp_port || 587,
                    smtp_user: this.emailWizard.smtp_user,
                    smtp_pass: this.emailWizard.smtp_pass,
                    email_to: this.emailWizard.email_to,
                },
            });
            this.emailWizard.loading = false;
            this.emailWizard.ok = res?.ok || false;
            this.emailWizard.result = res?.ok ? '✓ Email enviado. Revisa tu bandeja.' : ('Error: ' + (res?.error || '?'));
        },
        async saveEmail() {
            this.emailWizard.loading = true;
            const res = await this.api('/api/notifications/email/save', {
                method: 'POST', body: {
                    smtp_host: this.emailWizard.smtp_host,
                    smtp_port: this.emailWizard.smtp_port || 587,
                    smtp_user: this.emailWizard.smtp_user,
                    smtp_pass: this.emailWizard.smtp_pass,
                    email_to: this.emailWizard.email_to,
                },
            });
            this.emailWizard.loading = false;
            if (res?.ok) {
                this.showEmailWizard = false;
                this.emailWizard.smtp_pass = '';
                this.emailWizard.result = '';
                this.toast('Email conectado ✓', 'info');
                await this.loadEmail();
            } else {
                this.emailWizard.ok = false;
                this.emailWizard.result = res?.error || 'Error al guardar';
            }
        },
        async toggleEmail() {
            const res = await this.api('/api/notifications/email/toggle', { method: 'POST' });
            if (res?.ok) {
                await this.loadEmail();
                this.toast(`Email ${res.enabled ? 'activado' : 'desactivado'}`, 'info');
            }
        },
        async deleteEmail() {
            if (!confirm('Eliminar la configuracion de Email?')) return;
            await this.api('/api/notifications/email', { method: 'DELETE' });
            await this.loadEmail();
            this.toast('Email eliminado', 'warning');
        },

        async loadDashboard() { const d = await this.api('/api/dashboard'); if (d) this.dashboard = d; },
        async loadStrategies() { const d = await this.api('/api/strategies'); if (d) this.strategies = d.map(s => ({ ...s, params: s.params || {} })); },
        async loadTrades() {
            const params = new URLSearchParams({ page: this.tradeFilters.page, limit: 50 });
            if (this.tradeFilters.strategy) params.set('strategy', this.tradeFilters.strategy);
            if (this.tradeFilters.symbol) params.set('symbol', this.tradeFilters.symbol);
            if (this.tradeFilters.side) params.set('side', this.tradeFilters.side);
            if (this.tradeFilters.since_hours) params.set('since_hours', this.tradeFilters.since_hours);
            const d = await this.api('/api/trades?' + params);
            if (d) this.tradesData = d;
        },
        async loadStats() {
            const d = await this.api('/api/trades/stats?since_hours=' + this.tradeFilters.since_hours);
            if (d) { this.tradeStats = d; if (this.page === 'trades') this.$nextTick(() => this.renderTradeCharts()); }
        },
        async loadTradesAndStats() { await Promise.all([this.loadTrades(), this.loadStats()]); },
        clearFilters() { this.tradeFilters = { page: 1, strategy: '', symbol: '', side: '', since_hours: 168 }; this.loadTradesAndStats(); },
        async exportCsv() {
            const params = new URLSearchParams();
            if (this.tradeFilters.strategy) params.set('strategy', this.tradeFilters.strategy);
            if (this.tradeFilters.symbol) params.set('symbol', this.tradeFilters.symbol);
            if (this.tradeFilters.side) params.set('side', this.tradeFilters.side);
            if (this.tradeFilters.since_hours) params.set('since_hours', this.tradeFilters.since_hours);
            window.location.href = '/api/trades/export.csv?' + params;
        },
        async loadExchangeStatus() { const d = await this.api('/api/settings/exchange'); if (d) this.exchangeStatus = d; },
        async loadNotifStatus() { const d = await this.api('/api/settings/notifications'); if (d) this.notifStatus = d; },
        async loadRisk() { const d = await this.api('/api/risk'); if (d) this.riskConfig = d; },

        async saveRisk() {
            await this.api('/api/risk', {
                method: 'PUT', body: {
                    enabled: this.riskConfig.enabled,
                    max_daily_loss_usd: this.riskConfig.max_daily_loss_usd || 0,
                    max_drawdown_pct: this.riskConfig.max_drawdown_pct || 0,
                    max_btc_allocation_pct: this.riskConfig.max_btc_allocation_pct || 100,
                    max_eth_allocation_pct: this.riskConfig.max_eth_allocation_pct || 100,
                    circuit_breaker_pct: this.riskConfig.circuit_breaker_pct || 0,
                }
            });
            this.toast('Reglas de riesgo actualizadas', 'info');
        },

        async resumeTrading() {
            await this.api('/api/risk/resume', { method: 'POST' });
            await this.loadRisk();
            this.toast('Trading reanudado', 'info');
        },

        async triggerKillSwitch() {
            if (!confirm('⚠ CONFIRMACION: Esto detiene TODAS las estrategias y cancela TODAS las ordenes abiertas.\n\nContinuar?')) return;
            const res = await this.api('/api/risk/kill-switch', { method: 'POST' });
            if (res) {
                this.toast(`Kill switch: ${res.stopped_strategies?.length || 0} estrategias detenidas, ${res.cancelled_orders || 0} ordenes canceladas`, 'warning');
                await this.loadAll();
            }
        },

        async saveStrategy(s) {
            const res = await this.api('/api/strategies/' + s.name, { method: 'PUT', body: { symbol: s.symbol, params: s.params } });
            if (res?.restarted) {
                this.toast(`${s.name.toUpperCase()} reiniciada con ${s.symbol}`, 'info');
                await this.loadStrategies();
                await this.loadDashboard();
            }
        },
        async startStrategy(name) {
            const s = this.strategies.find(x => x.name === name);
            if (s && (!s.params || Object.keys(s.params).length === 0)) { alert('Configura parametros primero'); return; }
            if (s) await this.saveStrategy(s);
            const res = await this.api('/api/strategies/' + name + '/start', { method: 'POST' });
            if (res?.ok) { this.toast(`Estrategia ${name} iniciada`, 'info'); await this.loadStrategies(); await this.loadDashboard(); }
            else alert(res?.detail || 'Error');
        },
        async stopStrategy(name) {
            const res = await this.api('/api/strategies/' + name + '/stop', { method: 'POST' });
            if (res?.ok) { this.toast(`Estrategia ${name} detenida`, 'warning'); await this.loadStrategies(); await this.loadDashboard(); }
        },
        async loadAccount() {
            this.accountLoading = true;
            try {
                const [acc, open] = await Promise.all([
                    this.api('/api/coinbase/accounts'),
                    this.api('/api/coinbase/open-orders'),
                ]);
                if (acc?.ok) this.accountData = acc;
                else if (acc?.error) this.toast('Cuentas: ' + acc.error, 'warning');
                if (open?.ok) this.openOrders = open.orders || [];
            } catch (e) {
                this.toast('Error cargando cuenta', 'error');
            }
            this.accountLoading = false;
        },

        async syncTrades() {
            if (!confirm('Sincronizar trades de los ultimos 30 dias desde Coinbase?\n\nLos que ya esten en la DB se saltan.')) return;
            this.syncLoading = true;
            this.syncReport = null;
            const res = await this.api('/api/coinbase/sync-trades?days=30', { method: 'POST' });
            this.syncLoading = false;
            if (res?.ok) {
                this.syncReport = res;
                this.lastSync = new Date().toISOString();
                localStorage.setItem('lastCoinbaseSync', this.lastSync);
                this.toast(`Importados: ${res.imported}, duplicados: ${res.duplicates_skipped}`, 'info');
                // Refresh trades data
                if (this.page === 'trades') await this.loadTradesAndStats();
            } else {
                this.toast('Error: ' + (res?.error || '?'), 'error');
            }
        },

        async runBacktest() {
            this.backtestLoading = true;
            this.backtestResult = null;
            const res = await this.api('/api/backtest/run', {
                method: 'POST', body: this.backtestForm,
            });
            this.backtestLoading = false;
            this.backtestResult = res;
            if (res?.ok) this.toast('Backtest completado ✓', 'info');
            else this.toast('Backtest fallo: ' + (res?.error || '?'), 'error');
        },

        async runDiagnostic() {
            this.diagnosticLoading = true;
            const res = await this.api('/api/dashboard/diagnostic');
            this.diagnosticLoading = false;
            if (res) {
                this.diagnostic = res;
                this.toast('Diagnostico completado', 'info');
            }
        },

        async tickStrategy(name) {
            const verb = name === 'dca' ? 'realizar compra DCA' : 'ejecutar tick';
            if (!confirm(`Quieres ${verb} ahora mismo?\n\nSe usaran los parametros configurados.`)) return;
            this.toast(`Ejecutando ${name}...`, 'info');
            const res = await this.api('/api/strategies/' + name + '/tick', { method: 'POST' });
            this.tickResult = res;  // Open modal

            // Also show a quick toast summary
            if (res?.error && !res?.results?.length) {
                this.toast('❌ ' + res.error, 'error');
            } else if (res?.filled > 0 && res?.failed === 0) {
                this.toast(`✅ ${res.filled} orden(es) ejecutada(s)`, 'trade');
            } else if (res?.filled > 0 && res?.failed > 0) {
                this.toast(`⚠ ${res.filled} OK, ${res.failed} fallaron`, 'warning');
            } else if (res?.failed > 0) {
                this.toast(`❌ ${res.failed} orden(es) fallaron`, 'error');
            } else if (res?.orders === 0) {
                this.toast('ℹ Sin ordenes generadas', 'info');
            }

            await this.loadStrategies(); await this.loadDashboard();
            if (this.page === 'trades') await this.loadTradesAndStats();
        },
        async validateKeys() {
            this.wizardLoading = true; this.wizardResult = ''; this.wizardValid = false;
            const res = await this.api('/api/settings/exchange/validate', { method: 'POST', body: this.wizardKeys });
            this.wizardLoading = false;
            if (res?.valid) {
                const bals = Object.entries(res.balances || {}).map(([k, v]) => `${k}: ${v}`).join(', ');
                this.wizardResult = 'Conexion exitosa! Balances: ' + bals;
                this.wizardValid = true;
            } else this.wizardResult = res?.error || 'Error';
        },
        async saveKeys() {
            const res = await this.api('/api/settings/exchange/save', { method: 'POST', body: this.wizardKeys });
            if (res?.ok) {
                this.wizardKeys = { api_key: '', api_secret: '' };
                this.wizardResult = ''; this.wizardValid = false;
                await this.loadExchangeStatus(); await this.loadDashboard();
                this.toast('Conectado a Coinbase', 'info');
            }
        },
        async deleteExchangeKeys() {
            if (!confirm('Desconectar de Coinbase?')) return;
            await this.api('/api/settings/exchange', { method: 'DELETE' });
            await this.loadExchangeStatus();
        },
        async toggleMode() {
            const res = await this.api('/api/settings/mode', { method: 'POST' });
            if (res?.error) alert(res.error);
            await this.loadDashboard();
        },

        // ============= CHARTS =============
        // Deep canvas preparation: waits for visibility, destroys ghost charts.
        async _ensureCanvas(id, retries = 8, delayMs = 100) {
            for (let i = 0; i < retries; i++) {
                const ctx = document.getElementById(id);
                if (ctx) {
                    const parent = ctx.parentElement;
                    const w = parent?.offsetWidth || 0;
                    const h = parent?.offsetHeight || 0;
                    if (w > 0 && h > 0) {
                        // Kill any ghost Chart.js instance bound to this canvas
                        try {
                            const existing = (typeof Chart !== 'undefined') && Chart.getChart && Chart.getChart(ctx);
                            if (existing) existing.destroy();
                        } catch {}
                        return ctx;
                    }
                }
                await new Promise(r => setTimeout(r, delayMs));
            }
            return null;
        },

        _canvasReady(id) {
            // Legacy sync check (kept for back-compat, prefer _ensureCanvas)
            const ctx = document.getElementById(id);
            if (!ctx) return null;
            const parent = ctx.parentElement;
            if (!parent) return null;
            if (parent.offsetWidth === 0 || parent.offsetHeight === 0) return null;
            try {
                const existing = (typeof Chart !== 'undefined') && Chart.getChart && Chart.getChart(ctx);
                if (existing) existing.destroy();
            } catch {}
            return ctx;
        },

        async renderDashboardCharts() {
            // Catch each individually so one failure doesn't break the others
            const renders = [
                ['portfolio', () => this.renderPortfolioChart()],
                ['allocation', () => this.renderAllocationChart()],
                ['price', () => this.renderPriceChart()],
            ];
            for (const [name, fn] of renders) {
                try { await fn(); }
                catch (e) { console.error(`Chart ${name} failed:`, e); }
            }
        },

        async renderPortfolioChart() {
            if (this._rendering_portfolio) return;
            this._rendering_portfolio = true;
            try {
            const ctx = await this._ensureCanvas('chartPortfolio');
            if (!ctx) return;
            const data = await this.api('/api/dashboard/portfolio-history?hours=' + this.portfolioRange);
            if (!data) return;

            const rate = this.currency === 'EUR' ? (this.dashboard.eur_rate || 0.92) : 1;
            let raw = (data?.data || []).map(d => ({ x: new Date(d.t).getTime(), y: d.total * rate }));

            // Filter outliers: mode transitions (paper $10k -> live $62) create huge jumps.
            // Strategy: compute median; drop any point >5x median or <1/5x median.
            // Applied to all points (not just leading) to be robust.
            if (raw.length >= 3) {
                const sortedVals = raw.map(p => p.y).filter(v => v > 0).sort((a, b) => a - b);
                if (sortedVals.length > 0) {
                    const median = sortedVals[Math.floor(sortedVals.length / 2)];
                    raw = raw.filter(p => p.y > 0 && p.y <= median * 5 && p.y >= median / 5);
                }
            } else {
                // few points - just drop zeros
                raw = raw.filter(p => p.y > 0);
            }

            this.destroyChart('portfolio');

            // Show empty-state message if no data
            if (raw.length === 0) {
                const parent = ctx.parentElement;
                ctx.style.display = 'none';
                let msg = parent.querySelector('.chart-empty');
                if (!msg) {
                    msg = document.createElement('div');
                    msg.className = 'chart-empty';
                    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:13px;text-align:center;padding:20px';
                    parent.appendChild(msg);
                }
                msg.textContent = 'Sin datos en este rango. Los snapshots se toman cada 5 min.';
                return;
            }
            // Restore canvas visibility
            ctx.style.display = '';
            const emptyMsg = ctx.parentElement.querySelector('.chart-empty');
            if (emptyMsg) emptyMsg.remove();

            const grad = ctx.getContext('2d').createLinearGradient(0, 0, 0, 240);
            grad.addColorStop(0, 'rgba(99, 102, 241, 0.4)');
            grad.addColorStop(1, 'rgba(99, 102, 241, 0)');
            const cur = this.currency, sym = cur === 'EUR' ? '€' : '$';

            const values = raw.map(p => p.y);
            const yOpts = this._computeYScale(values, this.portfolioScale, sym);

            this.charts.portfolio = new Chart(ctx, {
                type: 'line',
                data: { datasets: [{ label: 'Portfolio (' + cur + ')', data: raw, borderColor: '#6366f1', backgroundColor: grad, fill: true, tension: 0.3, pointRadius: raw.length < 10 ? 3 : 0, borderWidth: 2 }]},
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => sym + c.parsed.y.toFixed(2) }}},
                    scales: {
                        x: { type: 'time', time: { tooltipFormat: 'PPp' }, grid: { color: 'rgba(255,255,255,0.04)' }},
                        y: yOpts,
                    }}
            });
            } finally { this._rendering_portfolio = false; }
        },

        _computeYScale(values, mode, sym) {
            const fmt = v => {
                const n = Number(v);
                if (!isFinite(n)) return '';
                // Dynamic decimal places: more decimals for small fluctuations
                const abs = Math.abs(n);
                const decimals = abs < 10 ? 4 : abs < 1000 ? 2 : 0;
                return sym + n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
            };
            const base = {
                ticks: { callback: fmt },
                grid: { color: 'rgba(255,255,255,0.04)' },
            };
            if (!values || values.length === 0) return base;

            // Filter invalid values
            const clean = values.filter(v => typeof v === 'number' && isFinite(v));
            if (clean.length === 0) return base;

            if (mode === 'zero') {
                return { ...base, beginAtZero: true };
            }
            // 'auto' mode: tight fit with padding
            const min = Math.min(...clean);
            const max = Math.max(...clean);
            const range = max - min;
            if (range < 0.0001) {
                // All values equal - add ±2% to show a line in the middle
                const pad = Math.max(Math.abs(max) * 0.02, 0.5);
                return { ...base, min: min - pad, max: max + pad };
            }
            // 10% padding top and bottom for visibility
            const pad = range * 0.1;
            return { ...base, min: min - pad, max: max + pad };
        },

        async renderAllocationChart() {
            if (this._rendering_allocation) return;
            this._rendering_allocation = true;
            try {
            const ctx = await this._ensureCanvas('chartAllocation');
            if (!ctx) return;
            const raw = this.dashboard.allocation || [];
            const rate = this.currency === 'EUR' ? (this.dashboard.eur_rate || 0.92) : 1;
            const sym = this.currency === 'EUR' ? '€' : '$';
            const alloc = raw.map(a => ({ label: a.label, value: a.value * rate }));
            this.destroyChart('allocation');
            this.charts.allocation = new Chart(ctx, {
                type: 'doughnut',
                data: { labels: alloc.map(a => a.label),
                    datasets: [{ data: alloc.map(a => a.value), backgroundColor: COLORS, borderColor: '#161922', borderWidth: 3 }]},
                options: { responsive: true, maintainAspectRatio: false, cutout: '65%',
                    plugins: { legend: { position: 'bottom', labels: { padding: 12 }},
                        tooltip: { callbacks: { label: c => `${c.label}: ${sym}${c.parsed.toFixed(2)} (${(c.parsed / alloc.reduce((s,a)=>s+a.value,0) * 100).toFixed(1)}%)` }}}}
            });
            } finally { this._rendering_allocation = false; }
        },

        async renderPriceChart() {
            if (this._rendering_price) return;
            this._rendering_price = true;
            try {
            const ctx = await this._ensureCanvas('chartPrice');
            if (!ctx) return;
            const [priceData, tradesRes] = await Promise.all([
                this.api(`/api/dashboard/price-history?symbol=${this.priceSymbol}&timeframe=${this.priceTimeframe}&limit=120`),
                this.api(`/api/trades?symbol=${encodeURIComponent(this.priceSymbol)}&limit=100&since_hours=720`),
            ]);
            const rate = this.currency === 'EUR' ? (this.dashboard.eur_rate || 0.92) : 1;
            const sym = this.currency === 'EUR' ? '€' : '$';

            // Candlestick data
            const candles = (priceData?.data || []).map(d => ({
                x: d.t, o: d.o * rate, h: d.h * rate, l: d.l * rate, c: d.c * rate,
            })).filter(c => isFinite(c.o) && isFinite(c.c) && isFinite(c.h) && isFinite(c.l));

            this.destroyChart('price');
            if (candles.length === 0) {
                const parent = ctx.parentElement;
                ctx.style.display = 'none';
                let msg = parent.querySelector('.chart-empty');
                if (!msg) {
                    msg = document.createElement('div');
                    msg.className = 'chart-empty';
                    msg.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:13px;text-align:center;padding:20px';
                    parent.appendChild(msg);
                }
                msg.textContent = 'Sin datos de precio disponibles.';
                return;
            }
            ctx.style.display = '';
            const emptyMsg = ctx.parentElement.querySelector('.chart-empty');
            if (emptyMsg) emptyMsg.remove();

            // Compute Y scale based on candle range
            const allVals = [];
            for (const c of candles) { allVals.push(c.h, c.l); }
            const yOpts = this._computeYScale(allVals, this.priceScale, sym);

            // Trade markers: only those within the visible range
            const tMin = candles[0].x, tMax = candles[candles.length - 1].x;
            const trades = (tradesRes?.trades || []).filter(t => {
                const tt = new Date(t.created_at).getTime();
                return tt >= tMin && tt <= tMax;
            });
            const buyMarkers = trades.filter(t => t.side === 'buy').map(t => ({
                x: new Date(t.created_at).getTime(), y: t.price * rate,
            }));
            const sellMarkers = trades.filter(t => t.side === 'sell').map(t => ({
                x: new Date(t.created_at).getTime(), y: t.price * rate,
            }));

            this.charts.price = new Chart(ctx, {
                type: 'candlestick',
                data: {
                    datasets: [
                        { label: this.priceSymbol.replace('USD', this.currency), data: candles,
                          color: { up: '#22c55e', down: '#ef4444', unchanged: '#8b8fa0' },
                          borderColor: { up: '#22c55e', down: '#ef4444', unchanged: '#8b8fa0' }},
                        { type: 'scatter', label: 'Compras', data: buyMarkers,
                          backgroundColor: '#22c55e', borderColor: '#fff', borderWidth: 2, pointRadius: 6, pointHoverRadius: 9 },
                        { type: 'scatter', label: 'Ventas', data: sellMarkers,
                          backgroundColor: '#ef4444', borderColor: '#fff', borderWidth: 2, pointRadius: 6, pointHoverRadius: 9 },
                    ]
                },
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: true, position: 'top', labels: { boxWidth: 12 }},
                        tooltip: { callbacks: { label: c => {
                            if (c.dataset.type === 'scatter') return `${c.dataset.label}: ${sym}${c.parsed.y.toFixed(2)}`;
                            const d = c.raw;
                            return [`O: ${sym}${d.o.toFixed(2)}`, `H: ${sym}${d.h.toFixed(2)}`, `L: ${sym}${d.l.toFixed(2)}`, `C: ${sym}${d.c.toFixed(2)}`];
                        }}}},
                    scales: {
                        x: { type: 'time', time: { tooltipFormat: 'PPp' }, grid: { color: 'rgba(255,255,255,0.04)' }},
                        y: yOpts,
                    }}
            });
            } finally { this._rendering_price = false; }
        },

        async renderTradeCharts() {
            try { await this.renderByStrategyChart(); } catch (e) { console.error('byStrategy chart failed:', e); }
            try { await this.renderByDayChart(); } catch (e) { console.error('byDay chart failed:', e); }
        },

        async renderByStrategyChart() {
            const ctx = await this._ensureCanvas('chartByStrategy');
            if (!ctx) return;
            const data = this.tradeStats.by_strategy || [];
            const rate = this.currency === 'EUR' ? (this.dashboard.eur_rate || 0.92) : 1;
            const sym = this.currency === 'EUR' ? '€' : '$';
            this.destroyChart('byStrategy');
            this.charts.byStrategy = new Chart(ctx, {
                type: 'bar',
                data: { labels: data.map(d => d.strategy.toUpperCase()),
                    datasets: [{ label: 'Volumen ' + this.currency, data: data.map(d => d.volume * rate), backgroundColor: COLORS, borderRadius: 6 }]},
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => sym + c.parsed.y.toFixed(2) }}},
                    scales: { x: { grid: { display: false }}, y: { ticks: { callback: v => sym + v }, grid: { color: 'rgba(255,255,255,0.04)' }}}}
            });
        },

        async renderByDayChart() {
            const ctx = await this._ensureCanvas('chartByDay');
            if (!ctx) return;
            const data = this.tradeStats.by_day || [];
            const rate = this.currency === 'EUR' ? (this.dashboard.eur_rate || 0.92) : 1;
            const cur = this.currency, sym = cur === 'EUR' ? '€' : '$';
            this.destroyChart('byDay');
            this.charts.byDay = new Chart(ctx, {
                type: 'bar',
                data: { labels: data.map(d => d.date), datasets: [
                    { label: 'Trades', data: data.map(d => d.trades), backgroundColor: '#6366f1', borderRadius: 4, yAxisID: 'y' },
                    { label: 'Volumen (' + cur + ')', data: data.map(d => d.volume * rate), backgroundColor: '#22c55e', borderRadius: 4, yAxisID: 'y1' }]},
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 }}},
                    scales: { x: { grid: { display: false }},
                        y: { position: 'left', ticks: { precision: 0 }, title: { display: true, text: 'Trades' }},
                        y1: { position: 'right', ticks: { callback: v => sym + v }, grid: { display: false }, title: { display: true, text: cur }}}}
            });
        },

        destroyChart(name) { if (this.charts[name]) { this.charts[name].destroy(); delete this.charts[name]; }},
        async changePortfolioRange(h) {
            this.portfolioRange = h;
            localStorage.setItem('portfolioRange', String(h));
            await this.renderPortfolioChart();
        },
        async changePortfolioScale(s) {
            this.portfolioScale = s;
            localStorage.setItem('portfolioScale', s);
            await this.renderPortfolioChart();
        },
        async changePriceSymbol(s) { this.priceSymbol = s; await this.renderPriceChart(); },
        async changePriceTimeframe(t) {
            this.priceTimeframe = t;
            localStorage.setItem('priceTimeframe', t);
            await this.renderPriceChart();
        },
        async changePriceScale(s) {
            this.priceScale = s;
            localStorage.setItem('priceScale', s);
            await this.renderPriceChart();
        },

        // ============= UTILS =============
        numberFmt(n, decimals = 2) {
            if (!n && n !== 0) return '0.00';
            return Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
        },
        money(usdValue, decimals = 2) {
            const v = Number(usdValue || 0);
            if (this.currency === 'EUR') {
                const eur = v * (this.dashboard.eur_rate || 0.92);
                return eur.toLocaleString('de-DE', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + ' €';
            }
            return '$' + v.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
        },
        pnlColor(v) { return (v || 0) >= 0 ? 'var(--green)' : 'var(--red)'; },
        timeAgo(iso) {
            const diff = (new Date() - new Date(iso)) / 1000;
            if (diff < 60) return Math.floor(diff) + 's';
            if (diff < 3600) return Math.floor(diff / 60) + 'm';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h';
            return Math.floor(diff / 86400) + 'd';
        },
    };
}
