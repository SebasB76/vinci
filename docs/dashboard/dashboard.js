// The dashboard behind the menu button of Vinci's chat. Vinci puts the snapshot in the URL's fragment
// (#d=<base64url of raw DEFLATE JSON>, espol_bot/dashboard.py) and the page asks no server for anything: its CSP
// forbids connections. A tick opens Vinci's deep link (/start s_<id>_ok), which the plugin vinci-botones runs as
// the «✅ Ya lo entregué» / «✅ Hecho» button would; from WhatsApp's /entregas (a «wa» number in the snapshot) it
// opens Vinci's WhatsApp chat with «/marca s<id> ok» typed instead. The tick is kept on the phone until a newer
// snapshot comes.

const DAY = 864e5;
const WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const NEWS = {
  assignment: ["📝", "Tarea nueva"], due: ["📅", "Cambio de fecha"], announcement: ["📢", "Anuncio"],
  grade: ["✅", "Nota"], file: ["📚", "Material"], link: ["🔗", "Enlace"], course: ["🎓", "Materia nueva"],
};
const STORE = "vinci-dashboard";

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

function group(item, now) {
  if (!item.due) return "undated";
  const due = new Date(item.due), today = midnight(now);
  const day = item.allDay ? midnight(due) : due;
  if (item.allDay ? day < today : due < now) return "overdue";
  if (midnight(due).getTime() === today.getTime()) return "today";
  return midnight(due) - today < 7 * DAY ? "week" : "later";
}

const GROUPS = [["overdue", "Atrasadas", true], ["today", "Hoy", true], ["week", "Esta semana", false],
  ["later", "Más adelante", false], ["undated", "Sin fecha", false]];

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

function termView(term, items, now, inline) {
  if (!term) return "";
  const start = new Date(term.start), end = new Date(term.end), span = end - start;
  const at = (date) => Math.min(100, Math.max(0, ((date - start) / span) * 100));
  const pct = Math.round(at(now)), gone = Math.max(0, now - start) / DAY;
  const weeks = Math.ceil(span / DAY / 7), week = Math.min(weeks, Math.floor(gone / 7) + 1);
  const left = Math.ceil((end - now) / DAY);
  const months = [];
  for (let m = new Date(start.getFullYear(), start.getMonth() + 1, 1); m < end; m = new Date(m.getFullYear(), m.getMonth() + 1, 1)) {
    months.push(`<span${place(inline, at(m))}>${MONTHS[m.getMonth()]}</span>`);
  }
  const pins = items.filter((i) => i.due && !i.todo && new Date(i.due) >= start && new Date(i.due) <= end).map((i) => {
    const hot = new Date(i.due) - now < DAY;
    return `<button type="button" class="pin${hot ? " hot" : ""}" data-pin="${esc(i.id)}"${place(inline, at(new Date(i.due)))}
      aria-label="${esc(i.title)}" title="${esc(i.title)}"></button>`;
  }).join("");
  return `<section class="term" aria-label="Avance del semestre">
    <div class="head"><h1 class="ellipsis">${esc(term.name || "Semestre")}</h1>
      <span class="pct"><b>${pct}%</b> · semana ${week} de ${weeks}</span></div>
    <div class="line"><div class="rail"></div><div class="gone"${place(inline, 0, pct)}></div>
      <div class="today"${place(inline, pct)}>HOY</div>${pins}</div>
    <div class="months">${months.join("")}</div>
    <div class="legend"><span>${shortDate(start)}</span><span>${left > 0 ? `faltan ${left} días` : "terminó el semestre"}</span>
      <span>${shortDate(end)}</span></div>
  </section>`;
}

function itemView(item, now, done) {
  const icon = item.todo ? "📌 " : item.quiz ? "⏱️ " : "";
  const due = item.due ? new Date(item.due) : null;
  const sub = [due && !item.allDay ? clock(due) : "", item.course || (item.todo ? "Personal" : "")].filter(Boolean).join(" · ");
  const date = due ? `<div class="date"><small>${WEEKDAYS[due.getDay()]}</small><b>${due.getDate()}</b>${
    due.getMonth() !== now.getMonth() ? `<small>${MONTHS[due.getMonth()]}</small>` : ""}</div>` : "";
  return `<div class="it${done ? " done" : ""}" id="it-${esc(item.id)}">
    <button type="button" class="check" data-check="${esc(item.id)}" aria-pressed="${done}"
      aria-label="${done ? "Desmarcar" : "Marcar"}: ${esc(item.title)}">✓</button>
    <div class="body"><div class="t ellipsis">${icon}${esc(item.title)}</div><div class="s ellipsis">${esc(sub)}</div></div>
    ${item.weight != null ? `<span class="wt">${esc(item.weight)}%</span>` : ""}${date}
  </div>`;
}

function newsView(entry, now, read) {
  const [icon, label] = NEWS[entry.kind] || ["🔔", "Aviso"];
  const extra = entry.kind === "due" && entry.due ? ` · ahora vence ${WEEKDAYS[new Date(entry.due).getDay()]} ${shortDate(new Date(entry.due))}`
    : entry.score ? ` · ${esc(entry.score)}` : "";
  return `<div class="nw${read ? " read" : ""}"><span class="unread" aria-hidden="true"></span>
    <span class="ic" aria-hidden="true">${entry.quiz ? "⏱️" : icon}</span>
    <div class="body"><div class="t">${esc(entry.title)}</div>
      <div class="s">${label} · ${esc(entry.course)} · ${ago(entry.at, now)}${extra}</div></div></div>`;
}

// The whole page as HTML. `state` is what the phone remembers: {marks: {id: {done, at}}, read: [news ids]}.
export function view(data, now, state = {}, { inline = false } = {}) {
  const snapshotAt = Date.parse(data.at || 0);
  const marks = state.marks || {}, read = new Set(state.read || []);
  const isDone = (id) => Boolean(marks[id] && marks[id].at > snapshotAt && marks[id].done);
  const items = data.items || [];
  const groups = GROUPS.map(([key, title, hot]) => {
    const inGroup = items.filter((i) => group(i, now) === key).sort((a, b) => (a.due || "").localeCompare(b.due || ""));
    return inGroup.length ? `<div class="grp${hot ? " hot" : ""}"><h2>${title}</h2><span>${inGroup.length}</span></div>
      <div class="list">${inGroup.map((i) => itemView(i, now, isDone(i.id))).join("")}</div>` : "";
  }).join("");
  const news = data.news || [];
  const updated = data.at ? new Date(data.at) : null;
  return `${termView(data.term, items, now, inline)}
    ${groups || `<div class="empty"><b>🎉</b>No tienes entregas pendientes.</div>`}
    ${data.more ? `<p class="more">Y ${data.more} más en el aula virtual.</p>` : ""}
    ${news.length ? `<div class="feedhead"><h2>Novedades</h2>${news.some((n) => !read.has(n.id))
      ? `<button type="button" data-read-all>Marcar como leídas</button>` : ""}</div>
      <div class="list">${news.map((n) => newsView(n, now, read.has(n.id))).join("")}</div>` : ""}
    ${updated ? `<p class="foot">Actualizado el ${WEEKDAYS[updated.getDay()]} ${shortDate(updated)}, ${clock(updated)}</p>` : ""}`;
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

function applyTheme(theme) {
  const root = document.documentElement.style;
  for (const [name, value] of Object.entries(theme)) {
    if (/^#[0-9a-f]{3,8}$/i.test(value)) root.setProperty(`--tg-${name.replace(/_/g, "-")}`, value);
  }
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
  const { payload, theme } = readFragment(location.hash);
  applyTheme(theme);
  postEvent("web_app_ready");
  postEvent("web_app_expand");
  let data;
  try {
    data = payload ? await decode(payload) : null;
  } catch {
    data = null;
  }
  if (!data || data.v !== 1) {
    app.innerHTML = `<div class="empty"><b>📋</b>Abre este panel con el botón «📋 Entregas» del chat de Vinci, o con /entregas en WhatsApp.</div>`;
    return;
  }
  const state = load();
  const render = () => {
    app.innerHTML = view(data, new Date(), state);
    applyLayout(app);
  };
  render();
  app.addEventListener("click", (event) => {
    const check = event.target.closest("[data-check]"), pin = event.target.closest("[data-pin]");
    if (check) {
      const id = check.dataset.check, done = check.getAttribute("aria-pressed") !== "true";
      state.marks = { ...state.marks, [id]: { done, at: Date.now() } };
      save(state);
      render();
      if (data.wa) {  // opened from /entregas on WhatsApp: back to Vinci's chat with the command typed
        const item = (data.items || []).find((i) => i.id === id);
        const text = `/marca ${id} ${done ? "ok" : "no"}${item ? ` · ${item.title}` : ""}`;
        window.location.href = `https://wa.me/${data.wa}?text=${encodeURIComponent(text)}`;
        return;
      }
      const link = `/${data.bot}?start=${id[0]}_${id.slice(1)}_${done ? "ok" : "no"}`;
      if (!postEvent("web_app_open_tg_link", { path_full: link })) window.open(`https://t.me${link}`, "_blank");
    } else if (pin) {
      const row = document.getElementById(`it-${pin.dataset.pin}`);
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("flash");
      setTimeout(() => row.classList.remove("flash"), 900);
    } else if (event.target.closest("[data-read-all]")) {
      state.read = [...new Set([...(state.read || []), ...(data.news || []).map((n) => n.id)])].slice(-200);
      save(state);
      render();
    }
  });
}

if (typeof document !== "undefined") init();
