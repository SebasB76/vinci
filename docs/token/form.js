// The /token Mini App: encrypts a Canvas token on the phone with the one-time public key in ?k= and hands
// Telegram only the ciphertext, as web_app_data. It makes no network request (the page's CSP forbids them)
// and talks to Telegram through its documented web events, so no third-party script ever sees the token.
// espol_bot/token_form.py holds the private half and decrypts it with the same RSA-OAEP / SHA-256.

export const PREFIX = "v1.";
// ESPOL's aula gives 64 letters and digits; stock Canvas puts "<digits>~" before them. Only the shape of a
// pasted secret is checked here: the aula itself says whether it works.
export const TOKEN_RE = /^(?:\d{1,6}~)?[A-Za-z0-9]{20,}$/;
const MAX_BYTES = 190; // what RSA-OAEP with a 2048-bit key and SHA-256 can seal

function fromBase64Url(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function toBase64Url(bytes) {
  let binary = "";
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function seal(publicKey, token) {
  const plain = new TextEncoder().encode(token);
  if (plain.length > MAX_BYTES) throw new Error("too long");
  const key = await crypto.subtle.importKey("spki", fromBase64Url(publicKey), { name: "RSA-OAEP", hash: "SHA-256" },
    false, ["encrypt"]);
  return PREFIX + toBase64Url(new Uint8Array(await crypto.subtle.encrypt({ name: "RSA-OAEP" }, key, plain)));
}

// https://core.telegram.org/api/web-events: the native apps inject TelegramWebviewProxy; Telegram Web
// hosts the page in an iframe and listens for postMessage.
function postEvent(type, data) {
  if (window.TelegramWebviewProxy) {
    window.TelegramWebviewProxy.postEvent(type, JSON.stringify(data));
    return true;
  }
  if (window.parent !== window) {
    window.parent.postMessage(JSON.stringify({ eventType: type, eventData: data }), "https://web.telegram.org");
    return true;
  }
  return false;
}

function applyTheme(hash) {
  let theme = {};
  try {
    theme = JSON.parse(new URLSearchParams(hash.slice(1)).get("tgWebAppThemeParams") || "{}");
  } catch {
    return;
  }
  const root = document.documentElement.style;
  for (const [name, value] of Object.entries(theme)) {
    if (/^#[0-9a-f]{3,8}$/i.test(value)) root.setProperty(`--tg-${name.replace(/_/g, "-")}`, value);
  }
}

function init() {
  applyTheme(location.hash);
  const $ = (id) => document.getElementById(id);
  const form = $("form"), input = $("token"), send = $("send"), reveal = $("reveal"), status = $("status");
  const publicKey = new URLSearchParams(location.search).get("k") || "";
  const say = (text, kind = "error") => {
    status.textContent = text;
    status.dataset.kind = kind;
  };
  const inTelegram = Boolean(window.TelegramWebviewProxy) || window.parent !== window;
  if (!publicKey || !inTelegram) {
    say("Este formulario se abre desde el botón «🔑 Pegar token» que te manda Vinci cuando le escribes /token.");
    input.disabled = send.disabled = reveal.disabled = true;
    return;
  }
  postEvent("web_app_ready");
  postEvent("web_app_expand");

  reveal.addEventListener("click", () => {
    const hidden = input.type === "password";
    input.type = hidden ? "text" : "password";
    reveal.textContent = hidden ? "Ocultar" : "Mostrar";
    reveal.setAttribute("aria-pressed", String(hidden));
    input.focus();
  });
  input.addEventListener("input", () => say("", "idle"));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const token = input.value.replace(/\s+/g, "");
    if (!TOKEN_RE.test(token)) {
      say("Eso no parece un token del aula: pégalo completo, son unas 64 letras y números sin espacios.");
      input.focus();
      return;
    }
    send.disabled = true;
    try {
      const data = await seal(publicKey, token);
      input.value = "";
      postEvent("web_app_data_send", { data });
      say("🔒 Enviado cifrado. Vinci te confirma en el chat.", "ok");
    } catch {
      send.disabled = false;
      say("No pude cifrarlo. Vuelve a pedir /token y abre el formulario nuevo.");
    }
  });
}

if (typeof document !== "undefined") init();
