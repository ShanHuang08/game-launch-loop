let appConfig = null;
let latestLaunchUrls = [];
let latestReportPath = '';
let isOpenSearchSearching = false;
let activeOpenSearchSignature = '';
let isOpenSearchClearing = false;
let openSearchPointerStartedInside = false;

const $ = (selector) => document.querySelector(selector);
const CURRENCY_LABEL_VISIBLE_LIMIT = 5;

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

async function fetchCommandStream(url, payload, onLog) {
  const response = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorPayload = await response.json();
    throw new Error(errorPayload.error || `HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let finalResult = null;

  while (true) {
    const {value, done} = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), {stream: !done});
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === 'log') {
        onLog(event.text || '');
      } else if (event.type === 'result') {
        finalResult = event;
      }
    }

    if (done) break;
  }

  if (buffer.trim()) {
    const event = JSON.parse(buffer);
    if (event.type === 'result') {
      finalResult = event;
    }
  }
  if (!finalResult) {
    throw new Error('Launch finished without a result.');
  }
  return finalResult;
}

function fetchRunStream(payload, onLog) {
  return fetchCommandStream('/api/run', payload, onLog);
}

function selectedEnvs() {
  return $('input[name="envMode"]:checked').value.split(',');
}

function envLabel(env) {
  return env.toUpperCase();
}

function renderEnvControls() {
  const wrapper = $('#envControls');
  wrapper.innerHTML = '';
  for (const env of selectedEnvs()) {
    const envConfig = appConfig.environments[env];
    const selectedCurrencies = normalizeCurrencies(envConfig.currency);
    const block = document.createElement('section');
    block.className = 'env-block';
    block.dataset.env = env;
    block.innerHTML = `
      <h3>${envLabel(env)}</h3>
      <label class="currency-field">
        Currency
        <div class="currency-select" data-env="${env}">
          <button class="currency-trigger" type="button" aria-expanded="false">
            <span class="currency-label">${escapeHtml(currencyLabel(selectedCurrencies))}</span>
            <span aria-hidden="true">v</span>
          </button>
          <div class="currency-popover hidden">
            ${currencyOptions(selectedCurrencies)}
          </div>
        </div>
      </label>
      <label>
        Agent ID
        <select class="agent" data-env="${env}">
          ${agentOptions(envConfig)}
        </select>
      </label>
    `;
    wrapper.appendChild(block);
  }
  bindCurrencyControls(wrapper);
}

function normalizeCurrencies(value) {
  const values = Array.isArray(value) ? value : [value];
  return values.map((item) => String(item || '').trim()).filter(Boolean);
}

function currencyValues(selected) {
  return Array.from(new Set(['BRL', 'EUR', 'USD', 'INR', 'PHP', 'THB', 'TRY', 'VND(K)', 'VND', 'IDR(K)', 'CNY', ...selected].filter(Boolean)));
}

function currencyOptions(selected) {
  const selectedSet = new Set(selected);
  return currencyValues(selected).map((value) => `
    <label class="currency-option">
      <input type="checkbox" value="${escapeHtml(value)}" ${selectedSet.has(value) ? 'checked' : ''}>
      <span>${escapeHtml(value)}</span>
    </label>
  `).join('');
}

function currencyLabel(selected) {
  if (selected.length === 0) return 'Select currencies';
  if (selected.length <= CURRENCY_LABEL_VISIBLE_LIMIT) return selected.join(', ');
  return `${selected.slice(0, CURRENCY_LABEL_VISIBLE_LIMIT).join(', ')} +${selected.length - CURRENCY_LABEL_VISIBLE_LIMIT}`;
}

function selectedCurrenciesFor(env) {
  return Array.from(document.querySelectorAll(`.currency-select[data-env="${env}"] input:checked`))
    .map((input) => input.value);
}

function updateCurrencyLabel(container) {
  const selected = Array.from(container.querySelectorAll('input:checked')).map((input) => input.value);
  container.querySelector('.currency-label').textContent = currencyLabel(selected);
}

function bindCurrencyControls(wrapper) {
  wrapper.querySelectorAll('.currency-select').forEach((container) => {
    const trigger = container.querySelector('.currency-trigger');
    const popover = container.querySelector('.currency-popover');
    trigger.addEventListener('click', () => {
      const willOpen = popover.classList.contains('hidden');
      document.querySelectorAll('.currency-popover').forEach((item) => item.classList.add('hidden'));
      document.querySelectorAll('.currency-trigger').forEach((item) => item.setAttribute('aria-expanded', 'false'));
      popover.classList.toggle('hidden', !willOpen);
      trigger.setAttribute('aria-expanded', String(willOpen));
    });
    container.querySelectorAll('input').forEach((input) => {
      input.addEventListener('change', () => updateCurrencyLabel(container));
    });
  });
}

function agentOptions(envConfig) {
  const agents = envConfig.agents || (envConfig.agentIds || []).map((id) => ({id, name: ''}));
  return agents.map((agent) => {
    const label = agent.name ? `${agent.id} - ${agent.name}` : agent.id;
    return `<option value="${agent.id}">${escapeHtml(label)}</option>`;
  }).join('');
}

function fillForm(config) {
  appConfig = config;
  const request = config.request || {};
  $('#username').value = request.username || '';
  $('#language').value = request.language || 'en';
  $('#platform').value = request.platform || 'WEB';
  $('#lobbyUrl').value = request.lobbyUrl || 'https://www.google.com/';
  $('#ipAddress').value = request.ipAddress || '192.228.180.86';
  renderEnvControls();
}

async function loadConfig() {
  setStatus('Loading config...', 'idle');
  const config = await fetchJson('/api/config');
  fillForm(config);
  setStatus('Ready', 'idle');
}

function buildPayload() {
  const envs = selectedEnvs();
  const agentIds = {};
  const currencies = {};
  for (const env of envs) {
    agentIds[env] = document.querySelector(`.agent[data-env="${env}"]`).value;
    currencies[env] = selectedCurrenciesFor(env);
  }
  return {
    request: {
      username: $('#username').value.trim(),
      language: $('#language').value.trim(),
      platform: $('#platform').value.trim(),
      lobbyUrl: $('#lobbyUrl').value.trim(),
      ipAddress: $('#ipAddress').value.trim(),
    },
    gameInput: $('#gameInput').value.trim(),
    envs,
    agentIds,
    currencies,
    dryRun: $('#dryRun').checked,
  };
}

function buildOpenSearchPayload() {
  return {
    keyword: $('#opensearchKeyword').value.trim(),
    environment: $('#opensearchEnv').value,
    googleSheets: $('#opensearchGoogleSheets').checked,
  };
}

function openSearchSignature() {
  return JSON.stringify(buildOpenSearchPayload());
}

function loadOpenSearchInputs() {
  $('#opensearchKeyword').value = localStorage.getItem('opensearchKeyword') || '';
  $('#opensearchEnv').value = localStorage.getItem('opensearchEnv') || 'QA';
  $('#opensearchGoogleSheets').checked = localStorage.getItem('opensearchGoogleSheets') === 'true';
}

function saveOpenSearchInputs() {
  localStorage.setItem('opensearchKeyword', $('#opensearchKeyword').value.trim());
  localStorage.setItem('opensearchEnv', $('#opensearchEnv').value);
  localStorage.setItem('opensearchGoogleSheets', String($('#opensearchGoogleSheets').checked));
}

function isOpenSearchPopoverOpen() {
  return !$('#opensearchPopover').classList.contains('hidden');
}

function openOpenSearchPopover() {
  $('#opensearchPopover').classList.remove('hidden');
  requestAnimationFrame(() => $('#opensearchKeyword').focus());
}

function closeOpenSearchPopover() {
  $('#opensearchPopover').classList.add('hidden');
}

function toggleOpenSearchPopover() {
  if (isOpenSearchPopoverOpen()) {
    closeOpenSearchPopover();
  } else {
    openOpenSearchPopover();
  }
}

async function checkOpenSearchLogs() {
  const checkButton = $('#opensearchCheckLogsButton');
  checkButton.disabled = true;

  try {
    const result = await fetchJson('/api/opensearch-check-logs', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    setStatus(result.ok ? 'OpenSearch logs opened' : 'Unable to open OpenSearch logs', result.ok ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    checkButton.disabled = false;
  }
}

async function searchOpenSearchLogs() {
  const keywordInput = $('#opensearchKeyword');
  const keyword = keywordInput.value.trim();
  const signature = openSearchSignature();

  if (!keyword) {
    keywordInput.setCustomValidity('Please enter OpenSearch search text.');
    keywordInput.reportValidity();
    keywordInput.focus();
    return;
  }

  if (isOpenSearchSearching && signature === activeOpenSearchSignature) {
    setStatus('OpenSearch search is already running...', 'running');
    return;
  }

  keywordInput.setCustomValidity('');
  saveOpenSearchInputs();
  isOpenSearchSearching = true;
  activeOpenSearchSignature = signature;
  const searchButton = $('#opensearchSearchButton');
  searchButton.disabled = true;
  searchButton.textContent = 'Searching...';
  setStatus('Searching OpenSearch logs...', 'running');
  $('#logOutput').textContent = '';

  try {
    const result = await fetchJson('/api/opensearch-log-search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(buildOpenSearchPayload()),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    setStatus(result.ok ? 'OpenSearch search completed' : 'OpenSearch search failed', result.ok ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    isOpenSearchSearching = false;
    activeOpenSearchSignature = '';
    searchButton.disabled = false;
    searchButton.textContent = 'Search';
  }
}

async function clearOpenSearchLogs() {
  if (isOpenSearchClearing) return;

  const clearButton = $('#opensearchClearLogButton');
  isOpenSearchClearing = true;
  clearButton.disabled = true;

  try {
    const result = await fetchJson('/api/opensearch-clear-log', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    clearButton.textContent = result.ok ? `Clear ${result.removedCount} files` : 'Clear log';
    setStatus(result.ok ? `Clear ${result.removedCount} files` : 'Clear log failed', result.ok ? 'ok' : 'error');
  } catch (error) {
    clearButton.textContent = 'Clear log';
    setStatus(error.message, 'error');
  } finally {
    isOpenSearchClearing = false;
    clearButton.disabled = false;
  }
}

async function runLaunch(event) {
  event?.preventDefault();
  const gameInput = $('#gameInput');
  if (!gameInput.value.trim()) {
    gameInput.setCustomValidity('Please enter Game Code / Range before launching.');
    gameInput.reportValidity();
    gameInput.focus();
    return;
  }
  gameInput.setCustomValidity('');
  if (!$('#launchForm').reportValidity()) {
    return;
  }

  $('#runButton').disabled = true;
  setStatus('Running...', 'running');
  $('#logOutput').textContent = '';
  $('#reportBox').classList.add('hidden');
  $('#launchActions').classList.add('hidden');
  latestLaunchUrls = [];
  latestReportPath = '';

  try {
    const result = await fetchRunStream(buildPayload(), (text) => {
      $('#logOutput').textContent += text;
      $('#logOutput').scrollTop = $('#logOutput').scrollHeight;
    });
    latestReportPath = result.reportPath || '';
    renderReport(result);
    const launchItems = result.launchUrls || [];
    renderLaunchUrls(launchItems);
    const launchOk = result.launchOk ?? (!/\bsuccess=NO\b/.test(result.stdout || '') && result.ok);
    setStatus(launchOk ? 'Completed' : launchFailureStatus(launchItems), launchOk ? 'ok' : 'error');
    if (launchOk && launchItems.length === 1) {
      lookupBackupLaunchUrlInBackground(launchItems[0]);
    }
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    $('#runButton').disabled = false;
  }
}

async function runTestStgLaunch() {
  const button = $('#testStgLaunchButton');
  button.disabled = true;
  setStatus('Running Test STG launch...', 'running');
  $('#logOutput').textContent = '';
  $('#reportBox').classList.add('hidden');
  $('#launchActions').classList.add('hidden');
  latestLaunchUrls = [];
  latestReportPath = '';

  try {
    const result = await fetchCommandStream('/api/test-stg-launch', {}, (text) => {
      $('#logOutput').textContent += text;
      $('#logOutput').scrollTop = $('#logOutput').scrollHeight;
    });
    latestReportPath = result.reportPath || '';
    renderReport(result);
    renderLaunchUrls(result.launchUrls || []);
    const launchOk = result.launchOk ?? result.ok;
    setStatus(launchOk ? 'Test STG launch completed' : launchFailureStatus(result.launchUrls || []), launchOk ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

async function clearReports() {
  const button = $('#clearReports');
  button.disabled = true;
  setStatus('Clearing reports...', 'running');

  try {
    const result = await fetchJson('/api/clear-reports', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    $('#reportBox').classList.add('hidden');
    $('#launchActions').classList.add('hidden');
    latestLaunchUrls = [];
    latestReportPath = '';
    setStatus(result.ok ? 'Reports cleared' : 'Clear reports failed', result.ok ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    button.disabled = false;
  }
}

function renderReport(result) {
  const box = $('#reportBox');
  if (!result.reportUrl) {
    box.classList.add('hidden');
    return;
  }
  const links = [
    `<a href="${escapeHtml(result.reportUrl)}" target="_blank" rel="noopener noreferrer">Open Markdown Report</a>`,
  ];
  if (result.openSearchUrl) {
    links.push(`<a href="${escapeHtml(result.openSearchUrl)}" target="_blank" rel="noopener noreferrer">OpenSearch Log</a>`);
  }
  box.innerHTML = links.join('');
  box.classList.remove('hidden');
}

function renderLaunchUrls(items) {
  latestLaunchUrls = items.filter((item) => item.url);
  const tbody = $('#launchRows');
  tbody.innerHTML = '';
  for (const item of items) {
    const hasUrl = Boolean(item.url);
    const hasBackupUrl = Boolean(item.backupUrl);
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><input type="checkbox" class="launch-check" ${hasUrl ? 'checked' : 'disabled'}></td>
      <td>${escapeHtml(item.env)}</td>
      <td>${escapeHtml(item.agent || agentLabel(item))}</td>
      <td>${escapeHtml(item.gameCode)}</td>
      <td>${escapeHtml(item.currency || '')}</td>
      <td>${escapeHtml(item.success || item.httpStatus || '')}</td>
      <td class="launch-error">${escapeHtml(item.failureMessage || item.error || '')}</td>
      <td>
        <div class="launch-button-row">
          <button type="button" class="open-one" ${hasUrl ? '' : 'disabled'}>Open Game</button>
          <button type="button" class="open-backup" ${hasBackupUrl ? '' : 'disabled'}>Backup</button>
        </div>
      </td>
    `;
    row.querySelector('.open-one').addEventListener('click', () => openLaunchUrls([item.url]));
    row.querySelector('.open-backup').addEventListener('click', (event) => openBackupLaunchUrl(event.currentTarget, item));
    row.dataset.url = item.url || '';
    row.dataset.backupUrl = item.backupUrl || '';
    row.dataset.index = item.index || '';
    tbody.appendChild(row);
  }
  $('#launchActions').classList.toggle('hidden', items.length === 0);
}

function launchFailureStatus(items) {
  const messageCounts = new Map();
  for (const item of items) {
    if (item.success === 'YES') continue;
    const message = item.failureMessage || item.error || (item.httpStatus ? `HTTP ${item.httpStatus}` : '');
    if (!message) continue;
    messageCounts.set(message, (messageCounts.get(message) || 0) + 1);
  }

  const messages = Array.from(messageCounts, ([message, count]) => `${count} games ${message}`);
  return messages.length ? messages.join(' | ') : 'Game launch failed';
}

async function openBackupLaunchUrl(button, item) {
  if (item.backupUrl) {
    openLaunchUrls([item.backupUrl]);
    return;
  }

  await fetchBackupLaunchUrl(button, item, {openAfterFetch: true, updateStatus: true});
}

async function lookupBackupLaunchUrlInBackground(item) {
  if (item.backupUrl || !(item.env && item.username && item.gameCode)) return;
  const button = document.querySelector(`#launchRows tr[data-index="${CSS.escape(String(item.index || ''))}"] .open-backup`);
  if (!button) return;
  await fetchBackupLaunchUrl(button, item, {openAfterFetch: false, updateStatus: false});
}

async function fetchBackupLaunchUrl(button, item, {openAfterFetch, updateStatus}) {
  button.disabled = true;
  button.textContent = 'Loading';
  if (updateStatus) setStatus('Fetching backup URL...', 'running');

  try {
    const result = await fetchJson('/api/backup-launch-url', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        env: item.env,
        username: item.username,
        gameCode: item.gameCode,
        reportPath: latestReportPath,
        index: item.index,
      }),
    });
    item.backupUrl = result.url || '';
    button.closest('tr').dataset.backupUrl = item.backupUrl;
    if (updateStatus) {
      setStatus(result.reportUpdated ? 'Backup URL opened and report updated' : 'Backup URL opened', 'ok');
    }
    if (openAfterFetch) openLaunchUrls([item.backupUrl]);
  } catch (error) {
    button.title = error.message;
    if (updateStatus) setStatus(error.message, 'error');
  } finally {
    button.textContent = 'Backup';
    button.disabled = !item.backupUrl;
  }
}

function agentLabel(item) {
  return item.agentName ? `${item.agentId} - ${item.agentName}` : item.agentId;
}

function selectedLaunchUrls() {
  return Array.from(document.querySelectorAll('#launchRows tr'))
    .filter((row) => row.querySelector('.launch-check')?.checked)
    .map((row) => row.dataset.url)
    .filter(Boolean);
}

function openLaunchUrls(urls) {
  const validUrls = urls.filter(Boolean);
  $('#popupWarning').classList.add('hidden');
  if (validUrls.length === 0) return;

  if (validUrls.length === 1) {
    window.open(validUrls[0], '_blank', 'noopener,noreferrer');
    return;
  }

  const blockedUrls = [];
  for (const url of validUrls) {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) blockedUrls.push(url);
  }
  if (blockedUrls.length > 0) {
    const warning = $('#popupWarning');
    warning.textContent = 'Chrome blocked some tabs. Use the per-row Open Game buttons to open them one by one.';
    warning.classList.remove('hidden');
  }
}

function setStatus(text, kind) {
  const status = $('#status');
  status.textContent = text;
  status.className = `status ${kind}`;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  }[char]));
}

document.addEventListener('DOMContentLoaded', () => {
  if (window.location.search) {
    window.history.replaceState(null, '', window.location.pathname);
  }
  loadOpenSearchInputs();
  loadConfig().catch((error) => setStatus(error.message, 'error'));
  $('#reloadConfig').addEventListener('click', () => loadConfig().catch((error) => setStatus(error.message, 'error')));
  document.querySelectorAll('input[name="envMode"]').forEach((input) => {
    input.addEventListener('change', renderEnvControls);
  });
  $('#launchForm').addEventListener('submit', runLaunch);
  $('#runButton').addEventListener('click', runLaunch);
  $('#testStgLaunchButton').addEventListener('click', runTestStgLaunch);
  $('#clearReports').addEventListener('click', clearReports);
  $('#checkReports').addEventListener('click', () => window.open('/reports/', '_blank', 'noopener,noreferrer'));
  $('#opensearchToggle').addEventListener('click', (event) => {
    event.stopPropagation();
    toggleOpenSearchPopover();
  });
  $('#opensearchPopover').addEventListener('click', (event) => {
    event.stopPropagation();
  });
  $('#opensearchKeyword').addEventListener('input', () => {
    $('#opensearchKeyword').setCustomValidity('');
    saveOpenSearchInputs();
  });
  $('#opensearchKeyword').addEventListener('keydown', (event) => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    searchOpenSearchLogs();
  });
  $('#opensearchEnv').addEventListener('change', saveOpenSearchInputs);
  $('#opensearchGoogleSheets').addEventListener('change', saveOpenSearchInputs);
  $('#opensearchCheckLogsButton').addEventListener('click', checkOpenSearchLogs);
  $('#opensearchClearLogButton').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
    }
  });
  $('#opensearchClearLogButton').addEventListener('click', clearOpenSearchLogs);
  $('#opensearchSearchButton').addEventListener('click', searchOpenSearchLogs);
  $('#gameInput').addEventListener('input', () => $('#gameInput').setCustomValidity(''));
  $('#openSelected').addEventListener('click', () => openLaunchUrls(selectedLaunchUrls()));
  $('#openAll').addEventListener('click', () => openLaunchUrls(latestLaunchUrls.map((item) => item.url)));
  document.addEventListener('pointerdown', (event) => {
    openSearchPointerStartedInside = Boolean(event.target.closest('#opensearchPopover'));
  });
  document.addEventListener('click', (event) => {
    if (event.target.closest('#opensearchMenu')) return;
    if (openSearchPointerStartedInside) {
      openSearchPointerStartedInside = false;
      return;
    }
    if (isOpenSearchPopoverOpen()) closeOpenSearchPopover();
    if (event.target.closest('.currency-select')) return;
    document.querySelectorAll('.currency-popover').forEach((item) => item.classList.add('hidden'));
    document.querySelectorAll('.currency-trigger').forEach((item) => item.setAttribute('aria-expanded', 'false'));
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeOpenSearchPopover();
  });
});
