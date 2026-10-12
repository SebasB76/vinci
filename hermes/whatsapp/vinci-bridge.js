// Hermes' WhatsApp bridge plus Vinci's /send-url-button route. setup.sh copies this file and url_button.js next to
// Hermes' bridge.js and points whatsapp.bridge_script here; each start rebuilds the bridge from the bridge.js on
// disk today, so a Hermes update reaches Vinci at the next restart. Without its anchors (bridge.js changed shape)
// it runs bridge.js untouched and Vinci falls back to plain links.
import { readFileSync, writeFileSync } from 'fs';

const ANCHOR = '\n// Health check\n';
const source = readFileSync(new URL('./bridge.js', import.meta.url), 'utf8');
const firstImport = source.indexOf('\nimport ');

if (source.includes(ANCHOR) && firstImport !== -1) {
  const register = 'registerUrlButton(app, { getSock: () => sock, isConnected: () => !!sock && connectionState === '
    + "'connected', enqueueSend, trackSentMessageId, messageStore, timeoutMs: SEND_TIMEOUT_MS });\n";
  const patched = `${source.slice(0, firstImport)}\nimport { registerUrlButton } from './url_button.js';`
    + source.slice(firstImport).replace(ANCHOR, `\n${register}${ANCHOR}`);
  const generated = new URL('./bridge.vinci.generated.js', import.meta.url);
  writeFileSync(generated, patched);
  await import(generated.href);
} else {
  console.warn('[vinci] bridge.js has no anchor for /send-url-button: running it unchanged');
  await import(new URL('./bridge.js', import.meta.url).href);
}
