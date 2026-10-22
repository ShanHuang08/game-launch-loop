let appConfig = null;
let latestLaunchUrls = [];

const $ = (selector) => document.querySelector(selector);

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
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
  return Array.from(new Set(['BRL', 'EUR', 'USD', 'INR', 'PHP', 'THB', 'VND(K)', 'VND', 'IDR(K)', ...selected].filter(Boolean)));
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
  if (selected.length <= 2) return selected.join(', ');
  return `${selected.slice(0, 2).join(', ')} +${selected.length - 2}`;
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

  try {
    const result = await fetchJson('/api/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(buildPayload()),
    });
    $('#logOutput').textContent = `${result.stdout || ''}${result.stderr ? `\n${result.stderr}` : ''}`;
    renderReport(result);
    renderLaunchUrls(result.launchUrls || []);
    const launchOk = result.launchOk ?? (!/\bsuccess=NO\b/.test(result.stdout || '') && result.ok);
    setStatus(launchOk ? 'Completed' : 'Game launch failed', launchOk ? 'ok' : 'error');
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    $('#runButton').disabled = false;
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
    const row = document.createElement('tr');
    row.innerHTML = `
      <td><input type="checkbox" class="launch-check" ${hasUrl ? 'checked' : 'disabled'}></td>
      <td>${escapeHtml(item.env)}</td>
      <td>${escapeHtml(item.agent || agentLabel(item))}</td>
      <td>${escapeHtml(item.gameCode)}</td>
      <td>${escapeHtml(item.currency || '')}</td>
      <td>${escapeHtml(item.success || item.httpStatus || '')}</td>
      <td><button type="button" class="open-one" ${hasUrl ? '' : 'disabled'}>Open Game</button></td>
    `;
    row.querySelector('.open-one').addEventListener('click', () => openLaunchUrls([item.url]));
    row.dataset.url = item.url || '';
    tbody.appendChild(row);
  }
  $('#launchActions').classList.toggle('hidden', items.length === 0);
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
  loadConfig().catch((error) => setStatus(error.message, 'error'));
  $('#reloadConfig').addEventListener('click', () => loadConfig().catch((error) => setStatus(error.message, 'error')));
  document.querySelectorAll('input[name="envMode"]').forEach((input) => {
    input.addEventListener('change', renderEnvControls);
  });
  $('#launchForm').addEventListener('submit', runLaunch);
  $('#runButton').addEventListener('click', runLaunch);
  $('#clearReports').addEventListener('click', clearReports);
  $('#checkReports').addEventListener('click', () => window.open('/reports/', '_blank', 'noopener,noreferrer'));
  $('#gameInput').addEventListener('input', () => $('#gameInput').setCustomValidity(''));
  $('#openSelected').addEventListener('click', () => openLaunchUrls(selectedLaunchUrls()));
  $('#openAll').addEventListener('click', () => openLaunchUrls(latestLaunchUrls.map((item) => item.url)));
  document.addEventListener('click', (event) => {
    if (event.target.closest('.currency-select')) return;
    document.querySelectorAll('.currency-popover').forEach((item) => item.classList.add('hidden'));
    document.querySelectorAll('.currency-trigger').forEach((item) => item.setAttribute('aria-expanded', 'false'));
  });
});
