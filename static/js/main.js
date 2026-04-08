/* ================================================================
   ham-cw  --  Frontend logic
   ================================================================ */

// GPIO roles that support auto-detection
const AUTO_ROLES = [
  { key: 'pin_freq_up',    label: 'Frequency Up' },
  { key: 'pin_freq_down',  label: 'Frequency Down' },
  { key: 'pin_speed_up',   label: 'Speed Up' },
  { key: 'pin_speed_down', label: 'Speed Down' },
  { key: 'pin_settings',   label: 'Settings Toggle' },
  { key: 'pin_dot',        label: 'Dot Paddle' },
  { key: 'pin_dash',       label: 'Dash Paddle' },
];

let cfg = {};
let configPolling = null;

/* ================================================================
   API helpers
   ================================================================ */

async function api(method, path, body) {
  const opts = { method };
  if (body !== undefined) {
    opts.headers = { 'Content-Type': 'application/json' };
    opts.body = JSON.stringify(body);
  }
  const r = await fetch(path, opts);
  return r.json();
}

/* ================================================================
   Build GPIO rows
   ================================================================ */

function buildGpioList() {
  const list = document.getElementById('gpio-list');
  AUTO_ROLES.forEach(r => {
    const row = document.createElement('div');
    row.className = 'gpio-row';
    row.innerHTML =
      `<span class="gpio-label">${r.label}</span>` +
      `<span class="gpio-pin" id="gpio-val-${r.key}">--</span>` +
      `<button class="btn-detect" data-role="${r.key}">Detect</button>`;
    list.appendChild(row);
  });
}

/* ================================================================
   Settings panel
   ================================================================ */

function openSettings()  {
  document.getElementById('settings-overlay').classList.remove('hidden');
  loadSettings();
}
function closeSettings() {
  document.getElementById('settings-overlay').classList.add('hidden');
  stopConfigPolling();
}

async function loadSettings() {
  cfg = await api('GET', '/settings');
  document.getElementById('set-freq').textContent = cfg.frequency + ' Hz';
  document.getElementById('set-wpm').textContent  = cfg.wpm + ' WPM';

  // Auto-detect pins
  AUTO_ROLES.forEach(r => {
    const el = document.getElementById('gpio-val-' + r.key);
    const pin = cfg[r.key];
    el.textContent = pin ? 'GPIO ' + pin : 'None';
    el.classList.remove('awaiting');
  });

  // Speaker pins
  document.getElementById('gpio-pin_speaker_1').value = cfg.pin_speaker_1 || 0;
  document.getElementById('gpio-pin_speaker_2').value = cfg.pin_speaker_2 || 0;
}

/* ================================================================
   Adjust buttons (settings panel)
   ================================================================ */

document.addEventListener('click', async e => {
  const btn = e.target.closest('.btn-adj');
  if (!btn) return;
  const param = btn.dataset.p;
  const step  = parseInt(btn.dataset.s);
  const data  = await api('POST', '/api/adjust', { param, step });
  if (data.value !== undefined) {
    if (param === 'frequency') {
      document.getElementById('set-freq').textContent = data.value + ' Hz';
    } else if (param === 'wpm') {
      document.getElementById('set-wpm').textContent = data.value + ' WPM';
    }
  }
});

/* ================================================================
   GPIO auto-detection
   ================================================================ */

document.addEventListener('click', async e => {
  const btn = e.target.closest('.btn-detect');
  if (!btn) return;
  const role = btn.dataset.role;

  // Disable all detect buttons
  document.querySelectorAll('.btn-detect').forEach(b => b.disabled = true);

  // Show config banner
  const banner = document.getElementById('config-status');
  const msg    = document.getElementById('config-msg');
  banner.classList.remove('hidden');
  msg.textContent = 'Flip ' + btn.closest('.gpio-row').querySelector('.gpio-label').textContent + ' now...';

  // Mark pin display
  const pinEl = document.getElementById('gpio-val-' + role);
  pinEl.textContent = 'AWAITING';
  pinEl.classList.add('awaiting');

  await api('POST', '/start-config-mode', { role });

  // Poll for result
  startConfigPolling(role);
});

function startConfigPolling(role) {
  stopConfigPolling();
  configPolling = setInterval(async () => {
    const s = await api('GET', '/config-status');
    if (!s.config_mode) {
      stopConfigPolling();
      const banner = document.getElementById('config-status');
      banner.classList.add('hidden');
      document.querySelectorAll('.btn-detect').forEach(b => b.disabled = false);

      if (s.detected !== null) {
        const pinEl = document.getElementById('gpio-val-' + role);
        pinEl.textContent = 'GPIO ' + s.detected;
        pinEl.classList.remove('awaiting');
      }
      loadSettings();  // refresh all values
    }
  }, 500);
}

function stopConfigPolling() {
  if (configPolling) {
    clearInterval(configPolling);
    configPolling = null;
  }
}

document.getElementById('btn-cancel-config').addEventListener('click', async () => {
  await api('POST', '/stop-config-mode');
  stopConfigPolling();
  document.getElementById('config-status').classList.add('hidden');
  document.querySelectorAll('.btn-detect').forEach(b => b.disabled = false);
  loadSettings();
});

/* ================================================================
   Save / Reset
   ================================================================ */

document.getElementById('btn-save').addEventListener('click', async () => {
  // Include speaker pin manual entries
  const updates = {
    pin_speaker_1: parseInt(document.getElementById('gpio-pin_speaker_1').value) || 0,
    pin_speaker_2: parseInt(document.getElementById('gpio-pin_speaker_2').value) || 0,
  };
  await api('POST', '/settings', updates);
  await api('POST', '/save-settings');
  loadSettings();
});

document.getElementById('btn-reset').addEventListener('click', async () => {
  // Post defaults
  await api('POST', '/settings', {
    frequency: 800, wpm: 20,
    pin_freq_up: 5, pin_freq_down: 6,
    pin_speed_up: 13, pin_speed_down: 19,
    pin_settings: 26, pin_dot: 27, pin_dash: 22,
    pin_speaker_1: 20, pin_speaker_2: 21,
  });
  loadSettings();
});

/* ================================================================
   Transmit controls
   ================================================================ */

document.getElementById('btn-send').addEventListener('click', () => {
  const input = document.getElementById('tx-text');
  const text = input.value.trim();
  if (text) api('POST', '/api/send', { text });
});

document.getElementById('btn-stop').addEventListener('click', () => {
  api('POST', '/api/stop');
});

document.getElementById('btn-test').addEventListener('click', () => {
  api('POST', '/api/test');
});

document.getElementById('tx-text').addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    const text = e.target.value.trim();
    if (text) api('POST', '/api/send', { text });
  }
});

/* ================================================================
   Settings toggle (button + hardware switch via polling)
   ================================================================ */

document.getElementById('btn-open-settings').addEventListener('click', openSettings);
document.getElementById('btn-close-settings').addEventListener('click', closeSettings);

/* ================================================================
   Status polling (5 Hz)
   ================================================================ */

async function pollStatus() {
  try {
    const [status, config] = await Promise.all([
      api('GET', '/gpio-status'),
      api('GET', '/settings'),
    ]);

    // Mode badge
    const badge = document.getElementById('mode-badge');
    if (status.mode === 'settings') {
      badge.textContent = 'SETTINGS';
      badge.classList.add('settings-mode');
    } else {
      badge.textContent = 'TRANSMIT';
      badge.classList.remove('settings-mode');
    }

    // Auto-open settings when hardware switch enters settings mode
    if (status.mode === 'settings') {
      document.getElementById('settings-overlay').classList.remove('hidden');
    }

    // Indicators
    togglePill('ind-dit',     status.dit,      'active');
    togglePill('ind-dah',     status.dah,      'active');
    togglePill('ind-key',     status.key_down, 'key-on');
    togglePill('ind-sending', status.sending,  'sending-on');

    // Main display values
    document.getElementById('disp-freq').textContent = config.frequency;
    document.getElementById('disp-wpm').textContent  = config.wpm;

  } catch (e) { /* ignore fetch errors */ }
}

function togglePill(id, active, cls) {
  const el = document.getElementById(id);
  if (active) el.classList.add(cls);
  else        el.classList.remove(cls);
}

/* ================================================================
   Init
   ================================================================ */

buildGpioList();
pollStatus();
setInterval(pollStatus, 200);
