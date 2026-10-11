// The experiment's one bridge route: relays a webview variant through the bridge's own socket and send queue.
// It answers only on loopback (the bridge's Host check) and only for the chat in webview_experiment.json.
import { readFileSync } from 'fs';
import { generateWAMessageFromContent, generateMessageIDV2 } from '@whiskeysockets/baileys';
import { buildVariant } from './webview_variants.js';

const CONFIG = new URL('./webview_experiment.json', import.meta.url);

function allowedChat() {
  // Read on every request: deleting the file turns the route off without a restart.
  try {
    return JSON.parse(readFileSync(CONFIG, 'utf8')).allowedChat || '';
  } catch {
    return '';
  }
}

export function registerWebviewExperiment(app, { getSock, isConnected, enqueueSend, trackSentMessageId, messageStore, timeoutMs }) {
  app.post('/experiment/webview/send', async (req, res) => {
    const { chatId, variant, url, text } = req.body || {};
    const allowed = allowedChat();
    if (!allowed || chatId !== allowed) {
      return res.status(403).json({ error: 'chatId is not the experiment recipient' });
    }
    if (!isConnected()) {
      return res.status(503).json({ error: 'Not connected to WhatsApp' });
    }
    let built;
    try {
      built = buildVariant(variant, { url, text: String(text || '') });
    } catch (err) {
      return res.status(400).json({ error: err.message });
    }
    let timer;
    try {
      const sent = await enqueueSend(() => Promise.race([
        (async () => {
          const sock = getSock();
          const full = generateWAMessageFromContent(chatId, built.message, {
            userJid: sock.user.id,
            messageId: generateMessageIDV2(sock.user?.id),
          });
          await sock.relayMessage(chatId, full.message, { messageId: full.key.id, additionalNodes: built.additionalNodes });
          return full;
        })(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('relay timed out')), timeoutMs); }),
      ]).finally(() => clearTimeout(timer)));
      trackSentMessageId(sent);
      messageStore.remember(sent);
      res.json({ success: true, messageId: sent.key.id, variant });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });
}
