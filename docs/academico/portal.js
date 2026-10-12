// The page behind «🎓 Conectar Académico»: the student signs in to ESPOL's Académico here, never in the chat.
// Vinci's PC holds the portal's session (src/espol_bot/portal_login.py) and talks to this page through the relay:
// it publishes what to ask next, with the CAPTCHA (GET /s/<mailbox>), and this page posts each answer sealed to the
// one-time key in ?k= (POST /m/<mailbox>). Sealing: RSA-OAEP / SHA-256 wraps a fresh AES-GCM key, which encrypts the
// answer bound to its mailbox and step, so the relay, the chat and the model only ever see ciphertext.

export const PREFIX = "v2.";
export const MAILBOX_RE = /^[A-Za-z0-9_-]{22,64}$/;
export const USER_RE = /^[A-Za-z0-9._-]{2,60}$/;
const POLL_MS = 1500;
const FINAL = new Set(["done", "failed", "expired", "replaced"]);

function fromBase64Url(text) {
  const b64 = text.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (text.length % 4)) % 4);
  return Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
}

function toBase64Url(bytes) {
  let binary = "";
  for (const b of new Uint8Array(bytes)) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export async function seal(publicKey, data, aad) {
  const rsa = await crypto.subtle.importKey("spki", fromBase64Url(publicKey), { name: "RSA-OAEP", hash: "SHA-256" },
    false, ["encrypt"]);
  const aes = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, true, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const body = await crypto.subtle.encrypt({ name: "AES-GCM", iv, additionalData: new TextEncoder().encode(aad) },
    aes, new TextEncoder().encode(JSON.stringify(data)));
  const wrapped = await crypto.subtle.encrypt({ name: "RSA-OAEP" }, rsa, await crypto.subtle.exportKey("raw", aes));
  return `${PREFIX}${toBase64Url(wrapped)}.${toBase64Url(iv)}.${toBase64Url(body)}`;
}

export async function post(relay, mailbox, message) {
  const response = await fetch(`${relay}/m/${mailbox}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message),
  });
  if (!response.ok) throw new Error(`relay ${response.status}`);
}

export async function readStatus(relay, mailbox) {
  const response = await fetch(`${relay}/s/${mailbox}`, { cache: "no-store" });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`relay ${response.status}`);
  return response.json();
}

// One answer to the step the PC is on: what the UI below sends, and what the E2E test drives on Node.
export async function answer(publicKey, relay, mailbox, step, n, data) {
  const sealed = await seal(publicKey, data, `${mailbox}:${step}`);
  await post(relay, mailbox, { kind: "academico", step, n, sealed });
}

function postEvent(type) {  // Telegram's Mini App events, when Telegram opened the page
  if (window.TelegramWebviewProxy) window.TelegramWebviewProxy.postEvent(type, "{}");
  else if (window.parent !== window) {
    window.parent.postMessage(JSON.stringify({ eventType: type, eventData: {} }), "https://web.telegram.org");
  }
}

function init() {
  const $ = (id) => document.getElementById(id);
  const params = new URLSearchParams(location.search);
  const publicKey = params.get("k") || "";
  const relay = params.get("r") || "";  // the CSP lets the page reach workers.dev only
  const mailbox = new URLSearchParams(location.hash.slice(1)).get("m") || "";
  const status = $("status"), wait = $("wait"), waitText = $("wait-text");
  const userForm = $("user-form"), loginForm = $("login-form");
  const user = $("user"), password = $("password"), code = $("code"), captcha = $("captcha");
  const say = (text, kind = "error") => {
    status.textContent = text || "";
    status.dataset.kind = text ? kind : "idle";
  };
  if (!publicKey || !relay || !MAILBOX_RE.test(mailbox)) {
    waitText.textContent = "Esta página se abre desde el botón «🎓 Conectar Académico» que te manda Vinci.";
    return;
  }
  postEvent("web_app_ready");
  postEvent("web_app_expand");

  let seq = 0, sent = 0, stopped = false, misses = 0;
  const show = (part) => {
    wait.hidden = part !== "wait";
    userForm.hidden = part !== "user";
    loginForm.hidden = part !== "login";
  };
  const busy = (form, on) => form.querySelectorAll("input, button").forEach((el) => { el.disabled = on; });

  function render(state) {
    if (state.seq === seq) return;
    seq = state.seq;
    const answered = (state.handled || 0) >= sent;
    if (state.state === "user") {
      show("user");
      busy(userForm, !answered);
      say(state.error || "");
      if (answered && !state.error) user.focus();
    } else if (state.state === "login") {
      show("login");
      busy(loginForm, !answered);
      if (typeof state.captcha === "string" && state.captcha.startsWith("data:image/")) {
        captcha.src = state.captcha;
        code.value = "";
      }
      say(state.error || "Escribe tu contraseña y el código de la imagen.", state.error ? "error" : "idle");
      if (answered) (password.value ? code : password).focus();
    } else if (state.state === "working") {
      show("wait");
      waitText.textContent = state.message || "Leyendo tu Académico…";
      say("");
    } else if (FINAL.has(state.state)) {
      stopped = true;
      show("wait");
      password.value = code.value = "";
      waitText.textContent = state.message || "";
      say(state.state === "done" ? "🔒 Tu contraseña no se guardó en ningún lado." : "", "ok");
      if (state.state === "done") document.body.dataset.done = "1";
    }
  }

  async function poll() {
    if (stopped) return;
    try {
      const state = await readStatus(relay, mailbox);
      misses = 0;
      if (state) render(state);
    } catch {
      misses += 1;
      if (misses === 5) say("No llego al relé de Vinci; sigo intentando…");
    }
    setTimeout(poll, POLL_MS);
  }

  async function send(form, step, data) {
    busy(form, true);
    sent += 1;
    say(step === "user" ? "Enviando cifrado…" : "Entrando al Académico…", "ok");
    try {
      await answer(publicKey, relay, mailbox, step, sent, data);
    } catch {
      sent -= 1;
      busy(form, false);
      say("No pude enviarlo. Revisa tu conexión e inténtalo otra vez.");
    }
  }

  userForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = user.value.trim().replace(/@espol\.edu\.ec$/i, "");
    if (!USER_RE.test(value)) {
      say("Escribe solo tu usuario de ESPOL, sin @espol.edu.ec.");
      user.focus();
      return;
    }
    send(userForm, "user", { user: value });
  });
  loginForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!password.value || !code.value.trim()) {
      say("Falta la contraseña o el código de la imagen.");
      return;
    }
    send(loginForm, "login", { password: password.value, captcha: code.value.trim() });
  });
  $("reveal").addEventListener("click", () => {
    const hidden = password.type === "password";
    password.type = hidden ? "text" : "password";
    $("reveal").textContent = hidden ? "Ocultar" : "Mostrar";
    $("reveal").setAttribute("aria-pressed", String(hidden));
  });
  show("wait");
  poll();
}

if (typeof document !== "undefined") init();
