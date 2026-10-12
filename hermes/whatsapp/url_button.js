// POST /send-url-button {chatId, text, buttonText, url, footer?, replyTo?}: a message with one button that opens a page.
// The recipe is the one the webview experiment saw open inside WhatsApp on iPhone (experiments/whatsapp-webview,
// variant cta_url_webview); WhatsApp Web opens it in a new tab, like any link. Baileys' sendMessage drops
// caller stanza nodes, so this relays through the bridge's socket and send queue itself.
import { generateWAMessageFromContent, generateMessageIDV2 } from '@whiskeysockets/baileys';

const tapTarget = (url) => ({ canonical_url: url, url_type: 'STATIC', button_index: 0, tap_target_format: 1 });

export function urlButtonMessage({ text, buttonText, url, footer }) {
  return {
    interactiveMessage: {
      body: { text },
      ...(footer ? { footer: { text: footer } } : {}),
      nativeFlowMessage: {
        buttons: [{
          name: 'cta_url',
          buttonParamsJson: JSON.stringify({
            display_text: buttonText, url, landing_page_url: url,
            webview_interaction: true, webview_presentation: null, payment_link_preview: false,
          }),
        }],
        messageParamsJson: JSON.stringify({
          bottom_sheet: { in_thread_buttons_limit: 3, divider_indices: [] },
          tap_target_configuration: tapTarget(url),
          tap_target_list: [tapTarget(url)],
        }),
      },
      contextInfo: { dataSharingContext: { showMmDisclosure: false } },
    },
  };
}

const BIZ_NODE = {
  tag: 'biz',
  attrs: {},
  content: [{
    tag: 'interactive',
    attrs: { type: 'native_flow', v: '1' },
    content: [{ tag: 'native_flow', attrs: { v: '9', name: 'mixed' } }],
  }],
};

export function registerUrlButton(app, { getSock, isConnected, enqueueSend, trackSentMessageId, messageStore, timeoutMs }) {
  app.post('/send-url-button', async (req, res) => {
    const { chatId, text, buttonText, url, footer, replyTo } = req.body || {};
    if (!chatId || !text || !buttonText || !/^https:\/\//.test(url || '')) {
      return res.status(400).json({ error: 'chatId, text, buttonText and an https url are required' });
    }
    if (!isConnected()) return res.status(503).json({ error: 'Not connected to WhatsApp' });
    let timer;
    try {
      const sent = await enqueueSend(() => Promise.race([
        (async () => {
          const sock = getSock();
          const quoted = messageStore.get(replyTo);
          const full = generateWAMessageFromContent(chatId, urlButtonMessage({ text, buttonText, url, footer }), {
            userJid: sock.user.id,
            messageId: generateMessageIDV2(sock.user?.id),
            ...(quoted?.key && quoted?.message ? { quoted } : {}),
          });
          await sock.relayMessage(chatId, full.message, { messageId: full.key.id, additionalNodes: [BIZ_NODE] });
          return full;
        })(),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('relay timed out')), timeoutMs); }),
      ]).finally(() => clearTimeout(timer)));
      trackSentMessageId(sent);
      messageStore.remember(sent);
      res.json({ success: true, messageId: sent.key.id });
    } catch (err) {
      res.status(500).json({ error: err.message });
    }
  });
}
