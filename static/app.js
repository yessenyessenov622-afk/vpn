(() => {
  const tg = window.Telegram?.WebApp;
  const initData = typeof tg?.initData === 'string' ? tg.initData : '';
  const preview = !initData;
  const codes = Object.keys(translations);
  const tabs = ['home', 'plans', 'subscription', 'support', 'settings'];
  const icons = {home:'home', plans:'plans', subscription:'user', support:'help', settings:'settings'};
  const returns = {ru:'Вернуться к боту', en:'Return to bot', kk:'Ботқа оралу', tr:'Bota dön', uz:'Botga qaytish', ky:'Ботко кайтуу', de:'Zurück zum Bot', es:'Volver al bot'};
  let language = 'ru', current = 'home', statusKey = '', previousFocus = null;
  let accountState = preview ? 'preview' : 'loading', account = null, receivedAt = 0, busy = false, lastActive = null;
  if (preview) try { const stored = localStorage.getItem('vpn-preview-language'); if (codes.includes(stored)) language = stored; } catch (_) { /* Storage is optional. */ }
  const dialog = document.getElementById('dialog');
  const sourceLabel = document.createElement('p'); sourceLabel.className = 'muted account-source';
  document.querySelector('#home .status-card .status-line').before(sourceLabel);
  const returnButton = document.createElement('button');
  returnButton.className = 'return-button';
  returnButton.type = 'button';
  returnButton.addEventListener('click', () => { if (tg?.initData && typeof tg.close === 'function') tg.close(); });
  dialog.querySelector('.modal').append(returnButton);

  function theme() {
    if (tg?.initData && ['light', 'dark'].includes(tg.colorScheme)) document.documentElement.dataset.theme = tg.colorScheme;
    else delete document.documentElement.dataset.theme;
  }
  if (tg?.initData) { tg.ready(); tg.onEvent('themeChanged', theme); }
  theme();

  function navigate(tab) {
    if (!tabs.includes(tab)) return;
    current = tab;
    document.querySelectorAll('.page').forEach(page => { page.hidden = page.id !== tab; });
    document.querySelectorAll('.nav-item').forEach(button => { if (button.dataset.go === tab) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
    window.scrollTo(0, 0);
  }
  function render() {
    const t = translations[language];
    const a = accountLabels[language];
    document.documentElement.lang = language;
    document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t[el.dataset.i18n]; });
    document.querySelectorAll('[data-i18n-aria]').forEach(el => { el.setAttribute('aria-label', t[el.dataset.i18nAria]); });
    document.querySelectorAll('.desktop-nav, .mobile-nav').forEach(nav => {
      nav.replaceChildren();
      tabs.forEach(tab => {
        const button = document.createElement('button');
      button.type = 'button'; button.className = 'nav-item'; button.dataset.go = tab;
        if (tab === current) button.setAttribute('aria-current', 'page');
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
        use.setAttribute('href', `#i-${icons[tab]}`); svg.append(use);
        const label = document.createElement('span'); label.textContent = t[tab];
        button.append(svg, label); nav.append(button);
      });
    });
    const list = document.getElementById('languages'); list.replaceChildren();
    codes.forEach(code => {
      const button = document.createElement('button'); button.type = 'button'; button.setAttribute('aria-pressed', String(code === language));
      button.disabled = busy || (!preview && accountState !== 'ready');
      button.textContent = translations[code].name + (code === language ? ' ✓' : '');
      button.addEventListener('click', () => { void chooseLanguage(code); });
      list.append(button);
    });
    document.getElementById('status').textContent = statusKey ? (preview ? t[statusKey] : a[statusKey]) : '';
    returnButton.textContent = returns[language];
    const banner = document.querySelector('.preview-banner');
    const title = banner.querySelector('strong'), description = banner.querySelector('span span');
    const reminder = document.querySelector('[data-i18n="demoReminder"]');
    const status = document.querySelectorAll('[data-i18n="demoActive"]');
    const dates = document.querySelectorAll('.status-line strong');
    const vpnTitle = document.querySelector('[data-i18n="unknown"]');
    const vpnText = document.querySelector('[data-i18n="vpnUnknown"]');
    const accountTag = document.querySelector('.date-label');
    if (preview) {
      banner.hidden = false; title.textContent = t.previewTitle; description.textContent = t.previewText;
      dates.forEach(el => { el.textContent = '30.11.2026 UTC'; }); sourceLabel.hidden = true;
    } else {
      accountTag.hidden = true;
      document.querySelector('[data-i18n="languageHelp"]').textContent = a.languageHelp;
      banner.hidden = accountState === 'ready'; title.textContent = accountState === 'loading' ? a.loading : a.error; description.textContent = '';
      const sub = accountState === 'ready' ? account.subscription : null;
      const now = accountState === 'ready' ? account.server_time + (performance.now() - receivedAt) / 1000 : 0;
      lastActive = sub ? sub.expires_at > now : null;
      const stateText = accountState !== 'ready' ? (accountState === 'loading' ? a.loading : a.error) : !sub ? a.none : sub.expires_at > now ? a.active : a.expired;
      status.forEach(el => { el.textContent = stateText; });
      dates.forEach(el => { el.textContent = sub ? new Date(sub.expires_at * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC') : a.endNone; });
      sourceLabel.hidden = !sub; sourceLabel.textContent = sub ? a[account.source] : '';
      reminder.textContent = accountState === 'ready' ? (sub ? a[account.source] : '') : '';
      vpnTitle.textContent = accountState !== 'ready' ? t.unknown : account.vpn === 'none' ? a.vpnNoneTitle : account.vpn === 'allowed' ? a.vpnAllowedTitle : account.vpn === 'revoked' ? a.vpnRevokedTitle : t.unknown;
      vpnText.textContent = accountState !== 'ready' ? '' : account.vpn === 'none' ? a.vpnNone : account.vpn === 'allowed' ? a.vpnAllowed : account.vpn === 'revoked' ? a.vpnRevoked : a.vpnUnknown;
    }
  }
  async function chooseLanguage(code) {
    if (busy || (!preview && accountState !== 'ready')) return;
    if (preview) {
      language = code;
      try { localStorage.setItem('vpn-preview-language', code); statusKey = 'localSaved'; }
      catch (_) { statusKey = 'saveError'; }
    } else {
      busy = true; render();
      try {
        const response = await fetch('/api/settings', {method:'PUT', cache:'no-store', headers:{'Content-Type':'application/json', 'X-Telegram-Init-Data':initData}, body:JSON.stringify({language:code})});
        if (!response.ok || (await response.json()).language !== code) throw new Error('save failed');
        language = code; statusKey = 'saved';
      } catch (_) { statusKey = 'saveError'; }
      finally { busy = false; }
    }
    render();
  }
  async function loadAccount() {
    try {
      const headers = {'X-Telegram-Init-Data':initData};
      const [accountResponse, settingsResponse] = await Promise.all([fetch('/api/account',{headers,cache:'no-store'}),fetch('/api/settings',{headers,cache:'no-store'})]);
      if (!accountResponse.ok || !settingsResponse.ok) throw new Error('unavailable');
      const data = await accountResponse.json(), settings = await settingsResponse.json();
      const sub = data.subscription;
      if (!Number.isSafeInteger(data.server_time) || !['test','paid','mixed','unknown'].includes(data.source) || !['none','unknown','allowed','revoked'].includes(data.vpn) || (sub !== null && (!sub || !Number.isSafeInteger(sub.expires_at) || sub.expires_at < 0 || sub.expires_at > 253402300799)) || !codes.includes(settings.language)) throw new Error('invalid response');
      account = data; receivedAt = performance.now(); language = settings.language; accountState = 'ready';
    } catch (_) { account = null; accountState = 'error'; }
    render();
  }
  function closeDialog() { dialog.hidden = true; previousFocus?.focus(); }
  function showDialog(action) {
    const t = translations[language]; previousFocus = document.activeElement;
    const title = action === 'connect' ? t.connectTitle : action === 'payment' ? t.paymentSoon : t.support;
    const body = action === 'connect' ? (preview ? t.connectText : `${t.stepOneText} ${t.stepTwoText}`) : action === 'payment' ? t.paymentText : t.supportDialog;
    document.getElementById('dialog-title').textContent = title;
    document.getElementById('dialog-text').textContent = body;
    returnButton.hidden = !(action === 'support' && tg?.initData && typeof tg.close === 'function');
    dialog.hidden = false; dialog.querySelector('.modal-close').focus();
  }
  document.addEventListener('click', event => {
    const target = event.target.closest('[data-go], [data-action]');
    if (!target) { if (event.target === dialog) closeDialog(); return; }
    if (target.dataset.go) { event.preventDefault(); navigate(target.dataset.go); }
    else if (target.dataset.action === 'close') closeDialog();
    else if (['connect','payment','support'].includes(target.dataset.action)) showDialog(target.dataset.action);
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !dialog.hidden) closeDialog(); });
  render(); navigate('home');
  if (!preview) { void loadAccount(); setInterval(() => { if (accountState === 'ready' && account.subscription && (account.subscription.expires_at > account.server_time + (performance.now() - receivedAt) / 1000) !== lastActive) render(); }, 1000); }
})();
