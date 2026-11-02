// The dashboard behind the menu button of Vinci's chat. Vinci puts the snapshot in the URL's fragment
// (#d=<base64url of raw DEFLATE JSON>, espol_bot/dashboard.py) and the page asks no server for anything: its CSP
// forbids connections. A tick opens Vinci's deep link (/start s_<id>_ok), which the plugin vinci-botones runs as
// the «✅ Ya lo entregué» / «✅ Hecho» button would; from WhatsApp's /entregas (a «wa» number in the snapshot) it
// opens Vinci's WhatsApp chat with «/marca s<id> ok» typed instead, unless the snapshot names Vinci's relay and a
// mailbox: then the tick is posted there (a workers.dev address, the only host the CSP allows) and Vinci confirms in
// the chat. The tick is kept on the phone until a newer snapshot comes.

const DAY = 864e5;
const WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const STORE = "vinci-dashboard";

const MAILBOX_RE = /^[A-Za-z0-9_-]{22,64}$/;

export async function postMark(data, id, done) {
  // Where it may post is the CSP's to say (connect-src: workers.dev only)
  if (!data.relay || !MAILBOX_RE.test(data.mailbox || "")) return false;
  try {
    const response = await fetch(`${data.relay}/m/${data.mailbox}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "mark", id, done }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

function toast(text) {
  let note = document.getElementById("toast");
  if (!note) {
    note = Object.assign(document.createElement("p"), { id: "toast", role: "status" });
    document.body.append(note);
  }
  note.textContent = text;
  note.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => note.classList.remove("show"), 3500);
}

const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

// Telegram adds its own parameters to the fragment, after an & or a ?; the snapshot is base64url, so it has neither.
export function readFragment(hash) {
  const params = {};
  for (const pair of hash.replace(/^#/, "").split(/[&?]/)) {
    const at = pair.indexOf("=");
    if (at > 0) params[pair.slice(0, at)] = pair.slice(at + 1);
  }
  let theme = {};
  try {
    theme = JSON.parse(decodeURIComponent(params.tgWebAppThemeParams || "%7B%7D"));
  } catch {
    theme = {};
  }
  return { payload: params.d || "", theme };
}

export async function decode(payload) {
  const b64 = payload.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (payload.length % 4)) % 4);
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(stream).text());
}

const midnight = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const shortDate = (date) => `${date.getDate()} ${MONTHS[date.getMonth()]}`;
const clock = (date) => `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;

// A date without a time («2026-11-04») is that day here, not midnight UTC (the evening before in Ecuador).
const parseDue = (due) => /^\d{4}-\d{2}-\d{2}$/.test(due) ? new Date(`${due}T00:00`) : new Date(due);

function group(item, now) {
  if (!item.due) return "undated";
  const due = parseDue(item.due), today = midnight(now);
  const day = item.allDay ? midnight(due) : due;
  if (item.allDay ? day < today : due < now) return "overdue";
  if (midnight(due).getTime() === today.getTime()) return "today";
  return midnight(due) - today < 7 * DAY ? "week" : "later";
}


function ago(at, now) {
  const when = new Date(at), hours = (now - when) / 36e5;
  if (hours < 1) return "hace un rato";
  if (hours < 24 && midnight(when).getTime() === midnight(now).getTime()) return `hace ${Math.floor(hours)} h`;
  if (midnight(now) - midnight(when) === DAY) return "ayer";
  return `${WEEKDAYS[when.getDay()]} ${shortDate(when)}`;
}

// `at` left/width as a style attribute when `inline` (a copy opened from disk), else as data-x for applyLayout:
// the page's CSP takes no style attribute.
const place = (inline, left, width) => inline
  ? ` style="left:${left.toFixed(2)}%${width == null ? "" : `;width:${width.toFixed(2)}%`}"`
  : ` data-left="${left.toFixed(2)}"${width == null ? "" : ` data-width="${width.toFixed(2)}"`}`;


const GROUPS = [["overdue", "Atrasadas"], ["today", "Hoy"], ["week", "Esta semana"], ["later", "Más adelante"],
  ["undated", "Sin fecha"]];

const ICONS = {
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  pin: '<path d="M12 21v-6M8 4h8l-1 6 3 3H6l3-3z"/>',
  assignment: '<path d="M7 3h7l5 5v13H7zM14 3v5h5M10 13h6M10 17h6"/>',
  due: '<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  announcement: '<path d="M4 10v4h3l6 4V6L7 10zM17 9a4 4 0 010 6"/>',
  grade: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/>',
  file: '<path d="M4 5.5A1.5 1.5 0 015.5 4H11v16H5.5A1.5 1.5 0 014 18.5zM20 5.5A1.5 1.5 0 0018.5 4H13v16h5.5a1.5 1.5 0 001.5-1.5z"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  course: '<path d="M2.5 9.5L12 5l9.5 4.5L12 14z"/><path d="M6.5 11.5V16c0 1.5 2.5 3 5.5 3s5.5-1.5 5.5-3v-4.5"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01"/>',
  bell: '<path d="M6 16v-5a6 6 0 0112 0v5l1.5 2h-15zM10 21h4"/>',
};
const icon = (name, cls = "i") => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ICONS.bell}</svg>`;
const NEWS_LABEL = { assignment: "Tarea nueva", due: "Cambio de fecha", announcement: "Anuncio", grade: "Nota",
  file: "Material", link: "Enlace", course: "Materia nueva" };

// A subject keeps one pastel and its initials everywhere: «Sistemas Distribuidos» → SD in the same color each time.
const SMALL = new Set(["de", "del", "la", "las", "los", "el", "y", "e", "en", "a", "para", "i", "ii", "iii", "iv"]);
function initials(course) {
  const words = String(course || "").normalize("NFD").replace(/[̀-ͯ]/g, "").split(/[\s\-–:.,]+/)
    .filter((w) => w && !SMALL.has(w.toLowerCase()));
  if (!words.length) return "·";
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase();
}
function hue(course) {
  let h = 0;
  for (const c of String(course || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 5;
}

function duePill(item, key, now) {
  if (!item.due) return "";
  const due = parseDue(item.due);
  const day = due.getDate() === now.getDate() && key === "today" ? "hoy" : `${WEEKDAYS[due.getDay()]} ${due.getDate()}`;
  const text = item.allDay ? day : `${key === "today" ? "" : `${day} · `}${clock(due)}`.trim();
  const kind = key === "overdue" ? " late" : key === "today" ? " hi" : "";
  return `<span class="pill${kind}">${esc(key === "overdue" ? `venció ${day}` : text)}</span>`;
}

function itemView(item, key, now, done) {
  const avatar = item.todo ? `<span class="av mine">${icon("pin")}</span>`
    : `<span class="av c${hue(item.course)}">${esc(initials(item.course))}</span>`;
  const meta = [item.todo ? "Tuya" : item.course, item.quiz ? "cuestionario" : "", item.elsewhere ? "fuera del aula" : "",
    item.weight != null ? `${item.weight} % de la nota` : ""].filter(Boolean).map(esc).join(" · ");
  return `<div class="it${done ? " done" : ""}" id="it-${esc(item.id)}">${avatar}
    <div class="body"><div class="t ellipsis">${esc(item.title)}</div>
      <div class="s">${duePill(item, key, now)}<span class="ellipsis">${meta}</span></div></div>
    <button type="button" class="check" data-check="${esc(item.id)}" aria-pressed="${done}"
      aria-label="${done ? "Desmarcar" : "Marcar"}: ${esc(item.title)}">${icon("check")}</button>
  </div>`;
}

function newsView(entry, now, read) {
  const label = NEWS_LABEL[entry.kind] || "Aviso";
  const extra = entry.kind === "due" && entry.due ? ` · ahora vence ${WEEKDAYS[new Date(entry.due).getDay()]} ${shortDate(new Date(entry.due))}`
    : entry.score ? ` · ${esc(entry.score)}` : "";
  return `<div class="nw${read ? " read" : ""}"><span class="ic">${icon(entry.kind)}</span>
    <div class="body"><div class="t">${esc(entry.title)}</div>
      <div class="s">${label} · ${esc(entry.course)} · ${ago(entry.at, now)}${extra}</div></div>
    <span class="unread" aria-hidden="true"></span></div>`;
}

function termTile(term, now, inline) {
  if (!term) return "";
  const start = new Date(term.start), end = new Date(term.end), span = end - start;
  const pct = Math.min(100, Math.max(0, ((now - start) / span) * 100));
  const weeks = Math.ceil(span / DAY / 7), week = Math.min(weeks, Math.floor(Math.max(0, now - start) / DAY / 7) + 1);
  return `<div class="tile"><div class="n">${week}/${weeks}</div><div class="l">semanas del semestre</div>
    <div class="term"><i${place(inline, 0, pct)}></i></div></div>`;
}

// The whole page as HTML. `state` is what the phone remembers: {marks: {id: {done, at}}, read: [news ids], tab}.
export function view(data, now, state = {}, { inline = false } = {}) {
  const snapshotAt = Date.parse(data.at || 0);
  const marks = state.marks || {}, read = new Set(state.read || []);
  const isDone = (id) => Boolean(marks[id] && marks[id].at > snapshotAt && marks[id].done);
  const items = data.items || [], news = data.news || [];
  const keyed = items.map((i) => [group(i, now), i]);
  const count = (keys) => keyed.filter(([k, i]) => keys.includes(k) && !isDone(i.id)).length;
  const pending = count(["today", "week"]), late = count(["overdue"]);
  const unread = news.filter((n) => !read.has(n.id)).length;
  const tab = state.tab === "news" && news.length ? "news" : "items";
  const updated = data.at ? new Date(data.at) : null;

  const title = pending ? `${pending} ${pending === 1 ? "entrega" : "entregas"} esta semana`
    : late ? "Ponte al día" : "Semana tranquila";
  const head = `<header class="head"><span class="logo" aria-hidden="true"></span><div>
      <h1>Tu semana</h1><p class="meta">${esc(title)}${updated ? ` · ${WEEKDAYS[now.getDay()]} ${shortDate(now)}` : ""}</p></div></header>`;
  const tiles = `<div class="tiles">
      <div class="tile hi"><div class="n">${pending}</div><div class="l">por entregar esta semana</div></div>
      <div class="tile${late ? " late" : ""}"><div class="n">${late}</div><div class="l">${late === 1 ? "atrasada" : "atrasadas"}</div></div>
      ${termTile(data.term, now, inline) || `<div class="tile"><div class="n">${count(["later", "undated"])}</div><div class="l">más adelante</div></div>`}
    </div>`;
  const tabs = news.length ? `<div class="tabs" role="tablist">
      <button type="button" class="tab" role="tab" data-tab="items" aria-selected="${tab === "items"}">${icon("list")}Entregas</button>
      <button type="button" class="tab" role="tab" data-tab="news" aria-selected="${tab === "news"}">${icon("bell")}Novedades${
        unread ? ` <span class="count">${unread}</span>` : ""}</button></div>` : "";

  let body;
  if (tab === "news") {
    body = `<section class="card list">${news.map((n) => newsView(n, now, read.has(n.id))).join("")}</section>
      ${unread ? `<button type="button" class="btn btn-quiet sm read-all" data-read-all>Marcar todo como leído</button>` : ""}`;
  } else {
    const groups = GROUPS.map(([key, name]) => {
      const inGroup = keyed.filter(([k]) => k === key).map(([, i]) => i).sort((a, b) => (a.due || "").localeCompare(b.due || ""));
      return inGroup.length ? `<p class="gl${key === "overdue" ? " late" : ""}">${name}</p>
        ${inGroup.map((i) => itemView(i, key, now, isDone(i.id))).join("")}` : "";
    }).join("");
    body = groups ? `<section class="card list">${groups}</section>`
      : `<div class="card empty"><b>Nada pendiente.</b>Disfruta mientras dure.</div>`;
    if (data.more) body += `<p class="more">Y ${data.more} más en el aula virtual.</p>`;
  }
  const foot = updated ? `<p class="foot"><span class="live"></span>Actualizado el ${WEEKDAYS[updated.getDay()]} ${shortDate(updated)}, ${clock(updated)}</p>` : "";
  return `${head}${tiles}${tabs}${body}${foot}`;
}

export function applyLayout(root) {
  for (const el of root.querySelectorAll("[data-left]")) {
    el.style.left = `${el.dataset.left}%`;
    if (el.dataset.width) el.style.width = `${el.dataset.width}%`;
  }
}

// https://core.telegram.org/api/web-events: the native apps inject TelegramWebviewProxy; Telegram Web
// hosts the page in an iframe and listens for postMessage.
function postEvent(type, data = {}) {
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

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORE) || "{}");
  } catch {
    return {};
  }
}

function save(state) {
  try {
    localStorage.setItem(STORE, JSON.stringify(state));
  } catch {
    // private mode: the tick still reaches Vinci; it just is not remembered here
  }
}

async function init() {
  const app = document.getElementById("app");
  const { payload } = readFragment(location.hash);
  postEvent("web_app_ready");
  postEvent("web_app_expand");
  let data;
  try {
    data = payload ? await decode(payload) : null;
  } catch {
    data = null;
  }
  if (!data || data.v !== 1) {
    app.innerHTML = `<div class="card empty"><b>Aquí no hay nada todavía.</b>Abre esta página con /entregas en tu chat con Vinci.</div>`;
    return;
  }
  const state = load();
  const render = () => {
    app.innerHTML = view(data, new Date(), state);
    applyLayout(app);
  };
  render();
  app.addEventListener("click", (event) => {
    const check = event.target.closest("[data-check]"), tab = event.target.closest("[data-tab]");
    if (check) {
      const id = check.dataset.check, done = check.getAttribute("aria-pressed") !== "true";
      state.marks = { ...state.marks, [id]: { done, at: Date.now() } };
      save(state);
      render();
      if (data.wa) {  // opened from /entregas on WhatsApp: through the relay, else back to the chat with it typed
        postMark(data, id, done).then((sent) => {
          if (sent) return toast(done ? "Enviado. Vinci te confirma en el chat." : "Desmarcada. Vinci te confirma en el chat.");
          const item = (data.items || []).find((i) => i.id === id);
          const text = `/marca ${id} ${done ? "ok" : "no"}${item ? ` · ${item.title}` : ""}`;
          window.location.href = `https://wa.me/${data.wa}?text=${encodeURIComponent(text)}`;
        });
        return;
      }
      const link = `/${data.bot}?start=${id[0]}_${id.slice(1)}_${done ? "ok" : "no"}`;
      if (!postEvent("web_app_open_tg_link", { path_full: link })) window.open(`https://t.me${link}`, "_blank");
    } else if (tab) {
      state.tab = tab.dataset.tab;
      render();
    } else if (event.target.closest("[data-read-all]")) {
      state.read = [...new Set([...(state.read || []), ...(data.news || []).map((n) => n.id)])].slice(-200);
      save(state);
      render();
    }
  });
}

if (typeof document !== "undefined") init();
