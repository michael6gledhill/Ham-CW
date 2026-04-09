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

// Role key -> friendly label lookup
const ROLE_LABELS = {};
AUTO_ROLES.forEach(r => { ROLE_LABELS[r.key] = r.label; });

let cfg = {};
let detectPollTimer = null;
let detectingRole = null;

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
      `<input type="number" class="pin-input pin-manual" id="gpio-manual-${r.key}" min="0" max="27" placeholder="Pin">` +
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
  cancelDetection();
}

async function loadSettings() {
  cfg = await api('GET', '/settings');
  document.getElementById('set-freq').textContent = cfg.frequency + ' Hz';
  document.getElementById('set-wpm').textContent  = cfg.wpm + ' WPM';

  AUTO_ROLES.forEach(r => {
    const el = document.getElementById('gpio-val-' + r.key);
    const manual = document.getElementById('gpio-manual-' + r.key);
    const pin = cfg[r.key];
    el.textContent = pin ? 'GPIO ' + pin : 'None';
    el.classList.remove('awaiting');
    if (manual) manual.value = pin || '';
  });

  document.getElementById('gpio-pin_speaker_1').value = cfg.pin_speaker_1 || 0;
  document.getElementById('gpio-pin_speaker_2').value = cfg.pin_speaker_2 || 0;
}

/* ================================================================
   Adjust buttons
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
   GPIO Detection — full rewrite with active polling
   ================================================================ */

// -- Detection modal helpers --

function showDetectModal(roleName) {
  const modal   = document.getElementById('detect-modal');
  const title   = document.getElementById('detect-title');
  const pinList = document.getElementById('detect-pin-list');
  const msg     = document.getElementById('detect-msg');
  const confirm = document.getElementById('detect-confirm-area');
  const timer   = document.getElementById('detect-timer');

  title.textContent = roleName;
  msg.textContent = 'Flip the switch now...';
  msg.className = 'detect-msg';
  pinList.innerHTML = '';
  confirm.classList.add('hidden');
  timer.textContent = '';
  modal.classList.remove('hidden');
}

function hideDetectModal() {
  document.getElementById('detect-modal').classList.add('hidden');
}

// -- Start detection for a role --

document.addEventListener('click', async e => {
  const btn = e.target.closest('.btn-detect');
  if (!btn) return;

  const role = btn.dataset.role;
  const label = ROLE_LABELS[role] || role;

  // Disable all detect buttons
  document.querySelectorAll('.btn-detect').forEach(b => b.disabled = true);

  // Mark the pin display
  const pinEl = document.getElementById('gpio-val-' + role);
  pinEl.textContent = 'DETECTING';
  pinEl.classList.add('awaiting');

  // Show modal
  showDetectModal(label);
  detectingRole = role;

  // Tell backend to start polling
  await api('POST', '/api/start-detection', { role });

  // Start frontend polling at 200ms
  startDetectPolling(role);
});

function startDetectPolling(role) {
  stopDetectPolling();
  detectPollTimer = setInterval(async () => {
    let data;
    try {
      data = await api('GET', '/api/detection-status');
    } catch (e) {
      return; // network hiccup, keep polling
    }

    const msg     = document.getElementById('detect-msg');
    const pinList = document.getElementById('detect-pin-list');
    const confirm = document.getElementById('detect-confirm-area');
    const timer   = document.getElementById('detect-timer');

    // Show elapsed time
    if (data.detecting) {
      timer.textContent = data.elapsed + 's';
    }

    // Timed out?
    if (data.timed_out) {
      stopDetectPolling();
      msg.textContent = 'No input detected. Try again?';
      msg.className = 'detect-msg detect-timeout';
      confirm.classList.add('hidden');
      pinList.innerHTML = '';
      // Show retry button
      const retryBtn = document.getElementById('detect-retry');
      if (retryBtn) retryBtn.classList.remove('hidden');
      return;
    }

    // Error?
    if (data.error) {
      stopDetectPolling();
      msg.textContent = 'Error: ' + data.error;
      msg.className = 'detect-msg detect-error';
      return;
    }

    // Detected pins?
    if (data.detected_pins && data.detected_pins.length > 0) {
      // Show the live pin list
      pinList.innerHTML = data.detected_pins.map(p => {
        let extra = '';
        if (data.assigned && data.assigned[String(p)]) {
          const assignedRole = data.assigned[String(p)];
          if (assignedRole !== role) {
            extra = ` <span class="detect-warn">(assigned to ${ROLE_LABELS[assignedRole] || assignedRole})</span>`;
          }
        }
        return `<div class="detect-pin-item">GPIO ${p}${extra}</div>`;
      }).join('');

      // Show confirmation for the first detected pin
      const firstPin = data.detected_pins[0];
      const confirmPin = document.getElementById('detect-confirm-pin');
      const confirmRole = document.getElementById('detect-confirm-role');

      // Check for duplicate
      let dupWarn = '';
      if (data.assigned && data.assigned[String(firstPin)]) {
        const ar = data.assigned[String(firstPin)];
        if (ar !== role) {
          dupWarn = ` (currently ${ROLE_LABELS[ar] || ar})`;
        }
      }
      confirmPin.textContent = 'GPIO ' + firstPin + dupWarn;
      confirm.classList.remove('hidden');
      msg.textContent = 'Pin detected!';
      msg.className = 'detect-msg detect-found';

      // Stop polling once we have a detection — wait for user confirm/reject
      stopDetectPolling();
    }

    // Not detecting anymore and no pins?
    if (!data.detecting && data.detected_pins.length === 0 && !data.timed_out) {
      stopDetectPolling();
      finishDetection();
    }
  }, 200);
}

function stopDetectPolling() {
  if (detectPollTimer) {
    clearInterval(detectPollTimer);
    detectPollTimer = null;
  }
}

// -- Confirm detected pin --

document.getElementById('detect-yes').addEventListener('click', async () => {
  const pinText = document.getElementById('detect-confirm-pin').textContent;
  const pinMatch = pinText.match(/GPIO (\d+)/);
  if (!pinMatch || !detectingRole) return;

  const pin = parseInt(pinMatch[1]);
  await api('POST', '/api/confirm-gpio', { pin, role: detectingRole });
  finishDetection();
  loadSettings();
});

// -- Reject — keep waiting for a different pin --

document.getElementById('detect-no').addEventListener('click', async () => {
  // Restart detection for the same role
  const role = detectingRole;
  if (!role) return;

  // Clear the confirm area and restart
  document.getElementById('detect-confirm-area').classList.add('hidden');
  document.getElementById('detect-pin-list').innerHTML = '';
  document.getElementById('detect-msg').textContent = 'Flip the switch now...';
  document.getElementById('detect-msg').className = 'detect-msg';

  await api('POST', '/api/stop-detection');
  await api('POST', '/api/start-detection', { role });
  startDetectPolling(role);
});

// -- Retry after timeout --

document.getElementById('detect-retry').addEventListener('click', async () => {
  const role = detectingRole;
  if (!role) return;

  document.getElementById('detect-retry').classList.add('hidden');
  document.getElementById('detect-msg').textContent = 'Flip the switch now...';
  document.getElementById('detect-msg').className = 'detect-msg';
  document.getElementById('detect-pin-list').innerHTML = '';

  await api('POST', '/api/start-detection', { role });
  startDetectPolling(role);
});

// -- Cancel detection --

async function cancelDetection() {
  stopDetectPolling();
  if (detectingRole) {
    await api('POST', '/api/stop-detection');
  }
  detectingRole = null;
  hideDetectModal();
  document.querySelectorAll('.btn-detect').forEach(b => b.disabled = false);
  loadSettings();
}

document.getElementById('detect-cancel').addEventListener('click', cancelDetection);

// -- Finish and clean up --

function finishDetection() {
  stopDetectPolling();
  detectingRole = null;
  hideDetectModal();
  document.querySelectorAll('.btn-detect').forEach(b => b.disabled = false);
}

/* ================================================================
   Save / Reset
   ================================================================ */

document.getElementById('btn-save').addEventListener('click', async () => {
  const updates = {
    pin_speaker_1: parseInt(document.getElementById('gpio-pin_speaker_1').value) || 0,
    pin_speaker_2: parseInt(document.getElementById('gpio-pin_speaker_2').value) || 0,
  };
  // Include manual pin entries for all auto-detect roles
  AUTO_ROLES.forEach(r => {
    const el = document.getElementById('gpio-manual-' + r.key);
    if (el && el.value !== '') {
      updates[r.key] = parseInt(el.value) || 0;
    }
  });
  await api('POST', '/settings', updates);
  await api('POST', '/save-settings');
  loadSettings();
});

document.getElementById('btn-reset').addEventListener('click', async () => {
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
   Settings toggle
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

    const badge = document.getElementById('mode-badge');
    if (status.mode === 'settings') {
      badge.textContent = 'SETTINGS';
      badge.classList.add('settings-mode');
    } else {
      badge.textContent = 'TRANSMIT';
      badge.classList.remove('settings-mode');
    }

    if (status.mode === 'settings') {
      document.getElementById('settings-overlay').classList.remove('hidden');
    }

    togglePill('ind-dit',     status.dit,      'active');
    togglePill('ind-dah',     status.dah,      'active');
    togglePill('ind-key',     status.key_down, 'key-on');
    togglePill('ind-sending', status.sending,  'sending-on');

    document.getElementById('disp-freq').textContent = config.frequency;
    document.getElementById('disp-wpm').textContent  = config.wpm;

  } catch (e) { /* ignore */ }
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
