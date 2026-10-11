// The messages the webview experiment sends: one per variant, each with the extra stanza nodes it relays with.
// Each recipe is copied from the public source named next to it; see ../README.md for versions and hashes.
import { randomBytes, randomUUID } from 'crypto';

export const VARIANTS = ['plain_url', 'cta_url', 'cta_url_webview', 'cta_url_webview_fork', 'open_webview'];

const BUTTON_TEXT = 'Abrir formulario';

// digows/baileys N03 (commit 1441cf3): the only URL button with a reported click on iOS and Web.
const minimalBizNode = () => ({
  tag: 'biz',
  attrs: {},
  content: [{
    tag: 'interactive',
    attrs: { type: 'native_flow', v: '1' },
    content: [{ tag: 'native_flow', attrs: { v: '9', name: 'mixed' } }],
  }],
});

// @hassanfuad/baileys-ios-webview 7.3.7 and @rexxhayanasi/elaina-baileys 1.4.4 relay native flows with this one.
const forkBizNode = () => ({
  tag: 'biz',
  attrs: { actual_actors: '2', host_storage: '2', privacy_mode_ts: String(Math.floor(Date.now() / 1000)) },
  content: [
    {
      tag: 'interactive',
      attrs: { type: 'native_flow', v: '1' },
      content: [{ tag: 'native_flow', attrs: { v: '9', name: 'mixed' } }],
    },
    {
      tag: 'quality_control',
      attrs: { decision_id: randomBytes(20).toString('hex'), source_type: 'third_party' },
      content: [{ tag: 'decision_source', attrs: { value: 'df' } }],
    },
  ],
});

const tapTarget = (url) => ({ canonical_url: url, url_type: 'STATIC', button_index: 0, tap_target_format: 1 });

// fukubailyes lib/Utils/ios-webview-helper.js: tap targets so the client treats the button as a webview.
const webviewParams = (url) => JSON.stringify({
  bottom_sheet: { in_thread_buttons_limit: 3, divider_indices: [] },
  tap_target_configuration: tapTarget(url),
  tap_target_list: [tapTarget(url)],
});

const interactive = (text, button, messageParamsJson, extra = {}) => ({
  interactiveMessage: {
    body: { text },
    footer: { text: 'Experimento · datos ficticios' },
    nativeFlowMessage: { buttons: [button], messageParamsJson },
    ...extra,
  },
});

export function buildVariant(variant, { url, text }) {
  if (!/^https:\/\//.test(url || '')) throw new Error('url must be https');
  switch (variant) {
    case 'plain_url':
      return { message: { extendedTextMessage: { text: `${text}\n\n${url}` } }, additionalNodes: [] };
    case 'cta_url':
      return {
        message: interactive(text, {
          name: 'cta_url',
          buttonParamsJson: JSON.stringify({ display_text: BUTTON_TEXT, url, merchant_url: url }),
        }, JSON.stringify({ from: 'api', templateId: randomUUID() })),
        additionalNodes: [minimalBizNode()],
      };
    case 'cta_url_webview':
      // Same relay node as cta_url, so only the button's webview fields differ between the two.
      return {
        message: interactive(text, {
          name: 'cta_url',
          buttonParamsJson: JSON.stringify({
            display_text: BUTTON_TEXT, url, landing_page_url: url,
            webview_interaction: true, webview_presentation: null, payment_link_preview: false,
          }),
        }, webviewParams(url), { contextInfo: { dataSharingContext: { showMmDisclosure: false } } }),
        additionalNodes: [minimalBizNode()],
      };
    case 'cta_url_webview_fork':
      // What hassanfuad's sendMessage really relays for an `open_webview` input: a cta_url, never open_webview.
      return {
        message: interactive(text, {
          name: 'cta_url',
          buttonParamsJson: JSON.stringify({
            display_text: BUTTON_TEXT, url, landing_page_url: url, webview_presentation: null,
            webview_interaction: true, payment_link_preview: false, merchant_url: url, in_app_webview: true,
          }),
        }, webviewParams(url)),
        additionalNodes: [forkBizNode()],
      };
    case 'open_webview':
      // The button name as is; elaina maps it to the message_with_link flow and warns only Android renders it.
      return {
        message: interactive(text, {
          name: 'open_webview',
          buttonParamsJson: JSON.stringify({ title: BUTTON_TEXT, link: { url, in_app_webview: true } }),
        }, '{}'),
        additionalNodes: [forkBizNode()],
      };
    default:
      throw new Error(`unknown variant ${variant}`);
  }
}
