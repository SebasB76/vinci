// Offline check, no WhatsApp connection: each variant survives Baileys' protobuf and binary-node round trip
// with its webview fields intact. Usage: node check_encoding.mjs [bridge dir]
import { pathToFileURL } from 'url';
import path from 'path';
import os from 'os';
import { VARIANTS, buildVariant } from './bridge/webview_variants.js';

const bridgeDir = process.argv[2] || path.join(os.homedir(), '.hermes/hermes-agent/scripts/whatsapp-bridge');
const baileys = await import(pathToFileURL(path.join(bridgeDir, 'node_modules/@whiskeysockets/baileys/lib/index.js')));
const { proto, generateWAMessageFromContent, encodeBinaryNode, decodeBinaryNode } = baileys;

const url = 'https://example.com/demo?s=RUN#c=CAP';
const userJid = '10000000000@s.whatsapp.net';
let failed = 0;

for (const variant of VARIANTS) {
  const { message, additionalNodes } = buildVariant(variant, { url, text: 'Prueba' });
  const full = generateWAMessageFromContent('20000000000@s.whatsapp.net', message, { userJid });
  const bytes = proto.Message.encode(full.message).finish();
  const decoded = proto.Message.toObject(proto.Message.decode(bytes), { defaults: false });
  const flow = decoded.interactiveMessage?.nativeFlowMessage;
  const sentFlow = message.interactiveMessage?.nativeFlowMessage;
  const checks = [];
  if (sentFlow) {
    checks.push(['button name', flow?.buttons?.[0]?.name === sentFlow.buttons[0].name]);
    checks.push(['buttonParamsJson', flow?.buttons?.[0]?.buttonParamsJson === sentFlow.buttons[0].buttonParamsJson]);
    checks.push(['messageParamsJson', flow?.messageParamsJson === sentFlow.messageParamsJson]);
    if (message.interactiveMessage.contextInfo) {
      checks.push(['dataSharingContext', decoded.interactiveMessage.contextInfo?.dataSharingContext?.showMmDisclosure === false]);
    }
  } else {
    checks.push(['text with url', decoded.extendedTextMessage?.text?.endsWith(url)]);
  }
  for (const node of additionalNodes) {
    const back = await decodeBinaryNode(encodeBinaryNode(node));
    checks.push([`<${node.tag}> node`, JSON.stringify(strip(back)) === JSON.stringify(strip(node))]);
  }
  const bad = checks.filter(([, ok]) => !ok).map(([name]) => name);
  failed += bad.length;
  const params = sentFlow ? JSON.parse(sentFlow.buttons[0].buttonParamsJson) : {};
  console.log(`${bad.length ? 'FAIL' : 'ok  '} ${variant.padEnd(22)} ${bytes.length} bytes`
    + `  button=${sentFlow?.buttons[0].name || '-'} params=${Object.keys(params).join(',') || '-'}`
    + `  nodes=${additionalNodes.map(describe).join(' ') || '-'}${bad.length ? `  lost: ${bad.join(', ')}` : ''}`);
}
process.exit(failed ? 1 : 0);

function strip(node) {
  return { tag: node.tag, attrs: node.attrs || {}, content: Array.isArray(node.content) ? node.content.map(strip) : undefined };
}

function describe(node) {
  const kids = Array.isArray(node.content) ? node.content.map(describe).join('') : '';
  return `<${node.tag}${Object.keys(node.attrs || {}).length ? ` ${Object.keys(node.attrs).join(',')}` : ''}>${kids}`;
}
