const cfg = window.STEUERBOX_CFG || { minRespekt: 900, maxRespekt: 7200 };

const controls = [
  {
    elementId: 'wp-mode',
    action: 'wp_mode',
    type: 'mode',
    states: [
      { label: 'MIN', value: 'min', flavor: 'other', hint: '' },
      { label: 'STD', value: 'std', flavor: 'other', hint: '' },
      { label: 'MAX', value: 'max', flavor: 'other', hint: '' },
    ],
    initial: null,
  },
  {
    elementId: 'battery-mode',
    action: 'battery_mode',
    type: 'mode',
    states: [
      { label: 'KOMFORT', value: 'komfort', flavor: 'other', hint: '25-75%' },
      { label: 'AUTO', value: 'auto', flavor: 'other', hint: '5-100%' },
    ],
    initial: null,
  },
  {
    elementId: 'hp-toggle',
    action: 'hp_toggle',
    type: 'state',
    states: [
      { label: 'AUS', value: 'off', flavor: 'off' },
      { label: 'AN', value: 'on', flavor: 'on' },
    ],
    initial: null,
  },
  {
    elementId: 'klima-toggle',
    action: 'klima_toggle',
    type: 'state',
    states: [
      { label: 'AUS', value: 'off', flavor: 'off' },
      { label: 'AN', value: 'on', flavor: 'on' },
    ],
    initial: null,
  },
  {
    elementId: 'lueftung-toggle',
    action: 'lueftung_toggle',
    type: 'state',
    states: [
      { label: 'AUS', value: 'off', flavor: 'off' },
      { label: 'AN', value: 'on', flavor: 'on' },
    ],
    initial: null,
  },
  {
    elementId: 'wattpilot-mode',
    action: 'wattpilot_mode',
    type: 'mode',
    states: [
      { label: 'ECO', value: 'eco', flavor: 'other' },
      { label: 'DEFAULT', value: 'default', flavor: 'other' },
    ],
    initial: null,
  },
  {
    elementId: 'wattpilot-start-stop',
    action: 'wattpilot_start_stop',
    type: 'command',
    states: [
      { label: 'START', value: 'start', flavor: 'on' },
      { label: 'STOP', value: 'stop', flavor: 'off' },
    ],
    initial: null,
  },
  {
    elementId: 'wattpilot-amp',
    action: 'wattpilot_amp',
    type: 'amp',
    states: [
      { label: '8A', value: 8, flavor: 'other' },
      { label: '24A', value: 24, flavor: 'other' },
    ],
    initial: null,
  },
];

const state = {};
const logEl = document.getElementById('eventLog');
const respektInput = document.getElementById('respektInput');

function logLine(line) {
  const stamp = new Date().toLocaleTimeString('de-DE');
  logEl.textContent = `[${stamp}] ${line}\n` + logEl.textContent;
}

async function fetchControlMeta() {
  const response = await fetch('/api/ops/control-meta', { method: 'GET' });
  let data;
  try {
    data = await response.json();
  } catch (err) {
    throw new Error(`control-meta parse failed: HTTP ${response.status}`);
  }
  if (!response.ok || !data.ok) {
    throw new Error(data.description || data.error || `control-meta HTTP ${response.status}`);
  }
  return data;
}

function applyControlMeta(meta) {
  const controlsMeta = (meta && meta.controls) || {};
  const wpMeta = controlsMeta.wp_mode;
  if (!wpMeta || !wpMeta.states) {
    return;
  }

  const wpControl = controls.find((entry) => entry.action === 'wp_mode');
  if (!wpControl) {
    return;
  }

  wpControl.states = wpControl.states.map((entry) => {
    const perState = wpMeta.states[String(entry.value)];
    if (!perState) {
      return entry;
    }
    return {
      ...entry,
      hint: perState.button_hint || entry.hint || '',
    };
  });
}

function getRespekt() {
  const v = Number.parseInt(respektInput.value, 10);
  if (!Number.isFinite(v)) {
    return cfg.minRespekt;
  }
  return Math.max(cfg.minRespekt, Math.min(cfg.maxRespekt, v));
}

function refreshDurationHint() {
  if (!respektInput) {
    return;
  }
  respektInput.value = String(getRespekt());
}

function toParams(control, selectedValue) {
  if (control.type === 'mode') {
    return { mode: selectedValue };
  }
  if (control.type === 'state') {
    return { state: selectedValue };
  }
  if (control.type === 'command') {
    return { command: selectedValue };
  }
  return { amp: selectedValue };
}

async function sendIntent(control, selectedValue) {
  const headers = {
    'Content-Type': 'application/json',
  };

  const payload = {
    action: control.action,
    params: toParams(control, selectedValue),
    respekt_s: getRespekt(),
  };

  const response = await fetch('/api/ops/intent', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  let data;
  try {
    data = await response.json();
  } catch (err) {
    throw new Error(`HTTP ${response.status}`);
  }
  if (!response.ok || !data.ok) {
    throw new Error(data.description || data.error || `HTTP ${response.status}`);
  }

  if (data.effective_params && control.action === 'wp_mode') {
    const hp = data.effective_params.heiz_temp_c;
    const ww = data.effective_params.ww_temp_c;
    logLine(`${control.action}: ${selectedValue} -> Heiz ${hp}\u00b0C / WW ${ww}\u00b0C (override ${data.override_id})`);
    return;
  }
  logLine(`${control.action}: ${selectedValue} -> override ${data.override_id}`);
}

function updateButtons(container, current) {
  const buttons = container.querySelectorAll('.state-btn');
  buttons.forEach((btn) => {
    const selected = btn.dataset.value === String(current);
    btn.classList.toggle('selected', selected);
    btn.classList.toggle('intent-on', selected && btn.dataset.flavor === 'on');
    btn.classList.toggle('intent-off', selected && btn.dataset.flavor === 'off');
    btn.classList.toggle('intent-other', selected && btn.dataset.flavor === 'other');
  });
}

function buildControl(control) {
  const container = document.getElementById(control.elementId);
  if (!container) {
    return;
  }

  state[control.elementId] = control.initial;

  control.states.forEach((entry) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'state-btn';
    button.dataset.value = String(entry.value);
    button.dataset.flavor = entry.flavor;

    const label = document.createElement('span');
    label.className = 'state-btn-label';
    label.textContent = entry.label;
    button.appendChild(label);

    if (entry.hint) {
      const hint = document.createElement('span');
      hint.className = 'state-btn-hint';
      hint.textContent = entry.hint;
      button.appendChild(hint);
    }

    button.addEventListener('click', async () => {
      const previous = state[control.elementId];
      state[control.elementId] = entry.value;
      updateButtons(container, state[control.elementId]);
      try {
        await sendIntent(control, entry.value);
      } catch (err) {
        state[control.elementId] = previous;
        updateButtons(container, state[control.elementId]);
        logLine(`${control.action}: Fehler ${err.message}`);
      }
    });

    container.appendChild(button);
  });

  updateButtons(container, state[control.elementId]);
}

async function init() {
  try {
    const meta = await fetchControlMeta();
    applyControlMeta(meta);
  } catch (err) {
    logLine(`Parameter-Vorschau nicht geladen: ${err.message}`);
  }

  controls.forEach(buildControl);
  if (respektInput) {
    respektInput.addEventListener('input', refreshDurationHint);
    respektInput.addEventListener('change', refreshDurationHint);
  }
  refreshDurationHint();
  logLine('Schalter initial ohne aktive Auswahl (inkl. Parameter-Vorschau).');
}

init();
