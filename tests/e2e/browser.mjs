// A real headless Chromium for the E2E test, driven over the DevTools protocol with Node's own WebSocket.
// One JSON command per stdin line, one JSON answer per stdout line:
//   {"op":"open","url":…} → {"id"}   {"op":"eval","id","expr"} → {"value"}   {"op":"close","id"} → {}
import { spawn } from 'child_process';
import { mkdtempSync, readFileSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import path from 'path';
import readline from 'readline';

const profile = mkdtempSync(path.join(tmpdir(), 'e2e-chromium-'));
const chrome = spawn(process.argv[2], ['--headless', '--no-sandbox', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
process.on('exit', () => { chrome.kill(); rmSync(profile, { recursive: true, force: true }); });

let port;
for (let i = 0; i < 100 && !port; i += 1) {
  try { port = readFileSync(path.join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0]; } catch {}
  if (!port) await new Promise((resolve) => setTimeout(resolve, 100));
}
const pages = new Map();

async function connect(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let next = 1;
  const waiting = new Map();
  const listeners = [];
  ws.onmessage = ({ data }) => {
    const msg = JSON.parse(data);
    if (msg.id && waiting.has(msg.id)) {
      waiting.get(msg.id)(msg);
      waiting.delete(msg.id);
    } else if (msg.method) {
      listeners.splice(0).forEach((fn) => fn(msg));
    }
  };
  const send = (method, params = {}) => new Promise((resolve) => {
    const id = next++;
    waiting.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
  return { ws, send, waitEvent: (name) => new Promise((resolve) => {
    const check = (msg) => (msg.method === name ? resolve(msg) : listeners.push(check));
    listeners.push(check);
  }) };
}

async function handle(cmd) {
  if (cmd.op === 'open') {
    const target = await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: 'PUT' })).json();
    const page = await connect(target.webSocketDebuggerUrl);
    await page.send('Page.enable');
    const loaded = page.waitEvent('Page.loadEventFired');
    await page.send('Page.navigate', { url: cmd.url });
    await loaded;
    pages.set(target.id, page);
    return { id: target.id };
  }
  const page = pages.get(cmd.id);
  if (cmd.op === 'eval') {
    const result = await page.send('Runtime.evaluate', { expression: cmd.expr, awaitPromise: true, returnByValue: true });
    if (result.result?.exceptionDetails) return { error: result.result.exceptionDetails.text };
    return { value: result.result?.result?.value };
  }
  if (cmd.op === 'close') {
    page.ws.close();
    // Closing like a person closes the window: the page runs its pagehide handlers.
    await fetch(`http://127.0.0.1:${port}/json/close/${cmd.id}`);
    pages.delete(cmd.id);
    return {};
  }
  return { error: `unknown op ${cmd.op}` };
}

for await (const line of readline.createInterface({ input: process.stdin })) {
  if (!line.trim()) continue;
  try {
    process.stdout.write(`${JSON.stringify(await handle(JSON.parse(line)))}\n`);
  } catch (err) {
    process.stdout.write(`${JSON.stringify({ error: String(err) })}\n`);
  }
}
process.exit(0);
