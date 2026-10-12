// The form inside WhatsApp. Only «Guardar», answered by the server, completes it; closing the page only leaves
// auxiliary events (hidden, pagehide) that never count as a submission.
const params = new URLSearchParams(location.search);
const runId = params.get('s') || '';
const store = sessionStorage;
const fromFragment = new URLSearchParams(location.hash.slice(1)).get('c');
if (fromFragment) {
  store.setItem(`cap:${runId}`, fromFragment);
  history.replaceState(null, '', `${location.pathname}${location.search}`);
}
const capability = store.getItem(`cap:${runId}`) || '';
const submissionId = store.getItem(`sub:${runId}`) || crypto.randomUUID();
store.setItem(`sub:${runId}`, submissionId);

const $ = (id) => document.getElementById(id);
const api = `/api/demo/sessions/${encodeURIComponent(runId)}`;

function show(text, kind = '') {
  $('status').textContent = text;
  $('status').className = kind;
}

function event(kind) {
  const body = JSON.stringify({ capability, kind, framed: window.top !== window, opener: !!window.opener });
  if (kind === 'load') {
    fetch(`${api}/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body }).catch(() => {});
  } else {
    navigator.sendBeacon(`${api}/events`, new Blob([body], { type: 'application/json' }));
  }
}

async function status() {
  const response = await fetch(`${api}/status`, { headers: { Authorization: `Bearer ${capability}` } });
  return response.ok ? response.json() : { error: response.status };
}

async function followConfirmation() {
  for (let i = 0; i < 60; i += 1) {
    const current = await status().catch(() => null);
    if (current?.confirmation === 'sent') {
      show('Guardado en el servidor ✅. El bot ya te confirmó en el chat; puedes cerrar esta ventana.', 'ok');
      return;
    }
    show('Guardado en el servidor ✅. Confirmación del bot pendiente…', 'ok');
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}

function saved() {
  $('value').disabled = true;
  $('save').disabled = true;
  followConfirmation();
}

const REFUSED = {
  403: 'Este enlace no es válido.',
  409: 'Este formulario ya se guardó antes.',
  410: 'El formulario caducó. Pide uno nuevo en el chat.',
};

async function submit(e) {
  e.preventDefault();
  $('save').disabled = true;
  show('Guardando…');
  try {
    const response = await fetch(`${api}/submit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ capability, submissionId, value: $('value').value }),
    });
    if (response.ok) return saved();
    show(REFUSED[response.status] || `No se guardó (error ${response.status}). Vuelve a pulsar «Guardar».`, 'error');
    $('save').disabled = response.status in REFUSED;
  } catch {
    // The same submissionId on the next press: if the first one did arrive, the server keeps it once.
    show('No se pudo guardar. Revisa la conexión y vuelve a pulsar «Guardar».', 'error');
    $('save').disabled = false;
  }
}

async function start() {
  $('run').textContent = runId || 'desconocida';
  event('load');
  document.addEventListener('visibilitychange', () => event(document.hidden ? 'hidden' : 'visible'));
  addEventListener('pagehide', () => event('pagehide'));
  const current = await status().catch(() => ({ error: 0 }));
  if (current.error) return show(REFUSED[current.error] || 'No se pudo cargar el formulario.', 'error');
  if (current.saved) return saved();
  if (current.expired) return show(REFUSED[410], 'error');
  $('form').hidden = false;
  $('form').addEventListener('submit', submit);
}

start();
