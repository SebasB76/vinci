// `espol-bot whatsapp-vincular`: links Vinci's WhatsApp number to Hermes' bridge session with an 8-character
// code typed on the phone (no QR to scan, so whoever holds the phone can be elsewhere), then prints the
// groups the number is in. Baileys comes from Hermes' own bridge (BAILEYS_DIR, its node_modules).
// Usage: node vincular.mjs <session dir> [phone, country code and no «+»]
import { randomBytes } from 'node:crypto';

const modules = process.env.BAILEYS_DIR;
const { makeWASocket, useMultiFileAuthState, DisconnectReason, fetchLatestBaileysVersion, Browsers } =
  await import(`${modules}/@whiskeysockets/baileys/lib/index.js`);
const { default: pino } = await import(`${modules}/pino/pino.js`);

const [session, phone] = process.argv.slice(2);
const ALPHABET = '123456789ABCDEFGHJKLMNPQRSTVWXYZ';
// One code for the whole run: a reconnect registers the same code again, so the one already shared stays valid.
const code = Array.from(randomBytes(8), (b) => ALPHABET[b % 32]).join('');
const { version } = await fetchLatestBaileysVersion();
let shown = false;

async function start() {
  const { state, saveCreds } = await useMultiFileAuthState(session);
  if (!state.creds.registered && !phone) {
    console.error('El número de Vinci no está vinculado: pasa su número (593…, sin «+» ni el 0 inicial).');
    process.exit(2);
  }
  const sock = makeWASocket({ version, auth: state, logger: pino({ level: 'silent' }),
                              browser: Browsers.ubuntu('Chrome'), printQRInTerminal: false });
  let asked = false;
  sock.ev.on('creds.update', saveCreds);
  sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
    if (qr && !asked && !state.creds.registered) {
      asked = true;
      await sock.requestPairingCode(phone, code);
      if (!shown) {
        shown = true;
        console.log(`Código: ${code.slice(0, 4)}-${code.slice(4)}`);
        console.log('En el celular de Vinci: WhatsApp → Dispositivos vinculados → Vincular un dispositivo →');
        console.log('«Vincular con el número de teléfono», y escribe el código. Espero hasta que lo hagas.');
      }
    }
    if (connection === 'open') {
      const groups = Object.values(await sock.groupFetchAllParticipating());
      console.log(groups.length ? 'Grupos del número de Vinci (copia el ID a WHATSAPP_GROUPS):' :
        'El número de Vinci todavía no está en ningún grupo: agrégalo y vuelve a correr esto.');
      for (const g of groups) console.log(`  ${g.id}  ${g.subject} (${g.participants.length} personas)`);
      setTimeout(() => process.exit(0), 2000);  // Baileys flushes the session files
    }
    if (connection === 'close') {
      const reason = lastDisconnect?.error?.output?.statusCode;
      if (reason === DisconnectReason.loggedOut) {
        console.error('WhatsApp cerró la sesión: borra la carpeta de la sesión y vuelve a vincular.');
        process.exit(1);
      }
      setTimeout(start, reason === DisconnectReason.restartRequired ? 1000 : 3000);
    }
  });
}
start();
