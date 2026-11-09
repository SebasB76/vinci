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
const LATER_SHOWN = 3;
const LONG_DAYS = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];
const LONG_MONTHS = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
  "octubre", "noviembre", "diciembre"];

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


const ICONS = {
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


function hue(course) {
  let h = 0;
  for (const c of String(course || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 5;
}

const TICK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path pathLength="1" d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const MINE = "Tus pendientes";
const subject = (item) => (item.todo ? MINE : item.course || "Sin materia");
const tone = (item) => (item.todo ? "mine" : `k${hue(item.course)}`);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// What a row says under its title. `dated`: the row's date is not in a heading or a date column, so it goes here.
function details(item, key, now, { dated, course, ago = false }) {
  const due = item.due ? parseDue(item.due) : null;
  const late = due && Math.round((midnight(now) - midnight(due)) / DAY);
  const when = !due ? "" : key === "overdue" && ago ? (late <= 0 ? "hace un rato" : late === 1 ? "ayer" : `hace ${late} días`)
    : key === "overdue" ? `venció ${WEEKDAYS[due.getDay()]} ${due.getDate()}`
    : dated && key !== "today" ? `${WEEKDAYS[due.getDay()]} ${due.getDate()}${item.allDay ? "" : ` · ${clock(due)}`}`
      : item.allDay ? (dated ? "hoy" : "") : clock(due);
  return [when, item.weight != null ? `vale ${item.weight} %` : "", item.quiz ? "cuestionario" : "",
    item.elsewhere ? "fuera del aula" : "", course ? subject(item) : ""].filter(Boolean).map(esc).join(" · ");
}

function tick(item, done) {
  return `<button type="button" class="v-tick" data-check="${esc(item.id)}" aria-pressed="${done}"
    aria-label="${done ? "Desmarcar" : "Marcar"}: ${esc(item.title)}">${TICK}</button>`;
}

function dayRow(item, key, now, done) {
  return `<div class="it ${tone(item)}${done ? " done" : ""}" id="it-${esc(item.id)}"><div class="body">
    <div class="t">${esc(item.title)}</div>
    <div class="s"><span class="dot"></span><span class="mono ellipsis">${details(item, key, now,
      { dated: key === "later" || key === "undated", course: true })}</span></div></div>${tick(item, done)}</div>`;
}

function subjectRow(item, key, now, done) {
  const due = item.due ? parseDue(item.due) : null;
  const label = !due ? "sin" : key === "overdue" ? "venció" : key === "today" ? "hoy" : WEEKDAYS[due.getDay()];
  const meta = details(item, key, now, { dated: false, course: false, ago: true });
  return `<div class="it ${tone(item)}${done ? " done" : ""} at-${key}" id="it-${esc(item.id)}">
    <span class="date"><small>${label}</small><b>${due ? due.getDate() : "—"}</b></span><div class="body">
    <div class="t">${esc(item.title)}</div>
    ${meta ? `<div class="s"><span class="mono ellipsis">${meta}</span></div>` : ""}</div>${tick(item, done)}</div>`;
}

function newsView(entry, now, read) {
  const label = NEWS_LABEL[entry.kind] || "Aviso";
  const extra = entry.kind === "due" && entry.due ? ` · ahora vence ${WEEKDAYS[new Date(entry.due).getDay()]} ${shortDate(new Date(entry.due))}`
    : entry.score ? ` · ${esc(entry.score)}` : "";
  return `<div class="nw${read ? " read" : ""}"><span class="ic">${icon(entry.kind)}</span>
    <div class="body"><div class="t">${esc(entry.title)}</div>
      <div class="mono">${label} · ${esc(entry.course)} · ${ago(entry.at, now)}${extra}</div></div>
    <span class="unread" aria-hidden="true"></span></div>`;
}

// The summary sheet: how many are due in the next 7 days, what is late, and one column per day with one capsule per
// deliverable in its subject's color; a ticked capsule fades.
function summary(data, keyed, now, isDone) {
  const today = midnight(now);
  const pending = keyed.filter(([k, i]) => (k === "today" || k === "week") && !isDone(i.id)).length;
  const late = keyed.filter(([k, i]) => k === "overdue" && !isDone(i.id)).length;
  const columns = Array.from({ length: 7 }, (_, n) => {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() + n);
    const due = keyed.filter(([k, i]) => (k === "today" || k === "week") && midnight(parseDue(i.due)).getTime() === day.getTime())
      .map(([, i]) => i);
    // A day heavier than the column draws its first 6 and says how many more.
    const caps = due.length ? due.slice(0, 6).map((i) => `<i class="${tone(i)}${isDone(i.id) ? " off" : ""}" data-cap="${esc(i.id)}"></i>`).join("")
      : "<i></i>";
    const over = due.length > 6 ? `<b class="over">+${due.length - 6}</b>` : "";
    return { day, html: `<div class="col${n ? "" : " today"}"><span class="stack n${Math.min(due.length, 6)}">${caps}${over}</span></div>` };
  });
  let week = "";
  if (data.term) {
    const start = new Date(data.term.start), end = new Date(data.term.end), span = end - start;
    const weeks = Math.ceil(span / DAY / 7), at = Math.min(weeks, Math.floor(Math.max(0, now - start) / DAY / 7) + 1);
    if (now >= start && now <= end) week = `semana ${at} de ${weeks}`;
  }
  return `<section class="v-sheet sum"><div class="v-eyebrow"><span>${LONG_DAYS[now.getDay()].toLowerCase()} ${now.getDate()} de ${
      LONG_MONTHS[now.getMonth()]}</span><span>${week}</span></div>
    <h1 class="ttl">Tu semana</h1>
    <div class="hero"><div class="big${pending > 99 ? " wide" : ""}"><b data-pending>${pending}</b><span>por entregar<br>en 7 días</span></div>
      <span class="lt${late ? "" : " ok"}" data-late><i></i>${late ? plural(late, "atrasada", "atrasadas") : "al día"}</span></div>
    <div class="chart">${columns.map((c) => c.html).join("")}</div>
    <div class="days">${columns.map((c, n) => `<span${n ? "" : ' class="today"'}>${n ? WEEKDAYS[c.day.getDay()] : "hoy"}<b>${c.day.getDate()}</b></span>`).join("")}</div>
  </section>`;
}

function byDay(keyed, now, isDone, state) {
  const today = midnight(now);
  const sections = [];
  const section = (title, cls, items, key, extra = "") => sections.push(`<section class="day${cls}">
    <div class="v-cap"><h2>${title}</h2><span class="mono">${items.length}</span></div>
    <div class="card list">${items.map((i) => dayRow(i, key, now, isDone(i.id))).join("")}${extra}</div></section>`);
  const of = (key) => keyed.filter(([k]) => k === key).map(([, i]) => i)
    .sort((a, b) => (a.due || "").localeCompare(b.due || ""));
  const overdue = of("overdue");
  if (overdue.length) section("Atrasadas", " late", overdue, "overdue");
  if (of("today").length) section("Hoy", " now", of("today"), "today");
  for (let n = 1; n < 7; n += 1) {
    const day = new Date(today.getFullYear(), today.getMonth(), today.getDate() + n);
    const items = of("week").filter((i) => midnight(parseDue(i.due)).getTime() === day.getTime());
    if (items.length) section(n === 1 ? "Mañana" : `${LONG_DAYS[day.getDay()]} ${day.getDate()}`, "", items, "week");
  }
  const later = of("later");
  if (later.length) {
    // What is weeks away folds under a button, so this week's list is not lost in a long scroll.
    const folded = !state.later && later.length > LATER_SHOWN + 1;
    const shown = folded ? later.slice(0, LATER_SHOWN) : later;
    sections.push(`<section class="day"><div class="v-cap"><h2>Más adelante</h2><span class="mono">${later.length}</span></div>
      <div class="card list">${shown.map((i) => dayRow(i, "later", now, isDone(i.id))).join("")}</div>${folded
        ? `<button type="button" class="btn btn-quiet sm unfold" data-later>Ver ${later.length - LATER_SHOWN} más adelante</button>` : ""}</section>`);
  }
  if (of("undated").length) section("Sin fecha", "", of("undated"), "undated");
  return sections.join("") || `<div class="card empty"><b>Nada pendiente.</b>Disfruta mientras dure.</div>`;
}

const RANK = { overdue: 0, today: 1, week: 2, later: 3, undated: 4 };

// One block per subject: the one with something late first, then the one due soonest; your own to-dos last.
function bySubject(keyed, now, isDone) {
  const subjects = new Map();
  for (const [k, i] of keyed) {
    if (!subjects.has(subject(i))) subjects.set(subject(i), []);
    subjects.get(subject(i)).push([k, i]);
  }
  const order = ([, rows]) => {
    const open = rows.filter(([, i]) => !isDone(i.id));
    const first = (open.length ? open : rows).reduce((a, b) => (RANK[a[0]] - RANK[b[0]] || (a[1].due || "~").localeCompare(b[1].due || "~") < 0 ? a : b));
    return [open.length ? 0 : 1, RANK[first[0]], first[1].due || "~"];
  };
  const blocks = [...subjects].sort((a, b) => {
    if ((a[0] === MINE) !== (b[0] === MINE)) return a[0] === MINE ? 1 : -1;
    const [x, y] = [order(a), order(b)];
    return x[0] - y[0] || x[1] - y[1] || x[2].localeCompare(y[2]);
  });
  if (!blocks.length) return `<div class="card empty"><b>Nada pendiente.</b>Disfruta mientras dure.</div>`;
  return blocks.map(([name, rows]) => {
    rows.sort((a, b) => RANK[a[0]] - RANK[b[0]] || (a[1].due || "~").localeCompare(b[1].due || "~"));
    return `<section class="subj ${tone(rows[0][1])}" data-subject="${esc(name)}"><div class="sh">${subjectHead(rows, now, isDone, name)}</div>
      <div class="list">${rows.map(([k, i]) => subjectRow(i, k, now, isDone(i.id))).join("")}</div></section>`;
  }).join("");
}

function subjectHead(rows, now, isDone, name) {
  const open = rows.filter(([, i]) => !isDone(i.id));
  const late = open.filter(([k]) => k === "overdue").length;
  const next = open.find(([k]) => k !== "overdue");
  const due = next && next[1].due ? parseDue(next[1].due) : null;
  const line = !open.length ? "todo listo" : late ? plural(late, "atrasada", "atrasadas")
    : !due ? "sin fecha" : `próxima: ${next[0] === "today" ? "hoy" : `${WEEKDAYS[due.getDay()]} ${due.getDate()}`}${
      next[1].allDay ? "" : `, ${clock(due)}`}`;
  const share = rows.length ? 1 - open.length / rows.length : 0;
  return `<div class="top"><h3>${esc(name)}</h3><span class="cnt"><b>${open.length}</b>${open.length === 1 ? "queda" : "quedan"}</span></div>
    <div class="prog"><i data-share="${share.toFixed(3)}"></i></div><span class="mono next">${line}</span>`;
}

const TABS = [["day", "Por día"], ["subject", "Por materia"], ["news", "Novedades"]];

// The whole page as HTML. `state` is what the phone remembers: {marks: {id: {done, at}}, read: [news ids], tab, later}.
export function view(data, now, state = {}, { inline = false } = {}) {
  const snapshotAt = Date.parse(data.at || 0);
  const marks = state.marks || {}, read = new Set(state.read || []);
  const isDone = (id) => Boolean(marks[id] && marks[id].at > snapshotAt && marks[id].done);
  const items = data.items || [], news = data.news || [];
  const keyed = items.map((i) => [group(i, now), i]);
  const unread = news.filter((n) => !read.has(n.id)).length;
  const tabs = news.length ? TABS : TABS.slice(0, 2);
  const tab = tabs.some(([k]) => k === state.tab) ? state.tab : "day";
  const at = tabs.findIndex(([k]) => k === tab);
  const updated = data.at ? new Date(data.at) : null;

  const seg = `<div class="v-seg" role="tablist" data-n="${tabs.length}" data-at="${at}"${inline
    ? ` style="--seg-n:${tabs.length};--seg-at:${at}"` : ""}><span class="ind" aria-hidden="true"></span>${tabs.map(([k, label]) =>
    `<button type="button" role="tab" data-tab="${k}" aria-selected="${k === tab}">${label}${
      k === "news" && unread ? ` <span class="badge">${unread}</span>` : ""}</button>`).join("")}</div>`;
  let body;
  if (tab === "news") {
    body = `<section class="card list">${news.map((n) => newsView(n, now, read.has(n.id))).join("")}</section>
      ${unread ? `<button type="button" class="btn btn-quiet sm read-all" data-read-all>Marcar todo como leído</button>` : ""}`;
  } else {
    body = tab === "subject" ? bySubject(keyed, now, isDone) : byDay(keyed, now, isDone, state);
    if (data.more) body += `<p class="mono more">Y ${data.more} más en el aula virtual.</p>`;
  }
  const foot = updated ? `<p class="mono foot">actualizado ${WEEKDAYS[updated.getDay()]} ${shortDate(updated)}, ${clock(updated)}</p>` : "";
  const html = `${summary(data, keyed, now, isDone)}${seg}<div class="view" data-view="${tab}">${body}</div>${foot}`;
  return inline ? html.replace(/<i data-share="([\d.]+)"><\/i>/g, '<i style="transform:scaleX($1)"></i>') : html;
}

// The page's CSP takes no style attribute: what view() leaves in data-* becomes inline style here.
export function applyLayout(root) {
  for (const el of root.querySelectorAll("[data-share]")) el.style.transform = `scaleX(${el.dataset.share})`;
  for (const el of root.querySelectorAll(".v-seg")) {
    el.style.setProperty("--seg-n", el.dataset.n);
    el.style.setProperty("--seg-at", el.dataset.at);
  }
}

// https://core.telegram.org/api/web-events: the native apps inject TelegramWebviewProxy; Telegram Web
// hosts the page in an iframe and listens for postMessage.
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

// After a tick only the counts, the capsule and the subject's header change: the row stays so its tick can animate.
function sync(app, data, state) {
  const next = document.createElement("main");
  next.innerHTML = view(data, new Date(), state);
  applyLayout(next);
  for (const sel of ["[data-pending]", "[data-late]"]) {
    const old = app.querySelector(sel), fresh = next.querySelector(sel);
    if (old && fresh) { old.className = fresh.className; old.innerHTML = fresh.innerHTML; }
  }
  for (const cap of app.querySelectorAll("[data-cap]")) {
    cap.classList.toggle("off", Boolean(next.querySelector(`[data-cap="${CSS.escape(cap.dataset.cap)}"]`)?.classList.contains("off")));
  }
  for (const block of app.querySelectorAll("[data-subject]")) {
    const fresh = next.querySelector(`[data-subject="${CSS.escape(block.dataset.subject)}"] .sh`);
    if (!fresh) continue;
    block.querySelector(".cnt").innerHTML = fresh.querySelector(".cnt").innerHTML;
    block.querySelector(".next").textContent = fresh.querySelector(".next").textContent;
    block.querySelector("[data-share]").style.transform = fresh.querySelector("[data-share]").style.transform;
  }
  for (const row of app.querySelectorAll(".it[id]")) {
    const fresh = next.querySelector(`#${CSS.escape(row.id)}`);
    if (!fresh) continue;
    row.classList.toggle("done", fresh.classList.contains("done"));
    const button = row.querySelector(".v-tick"), model = fresh.querySelector(".v-tick");
    for (const name of ["aria-pressed", "aria-label"]) button.setAttribute(name, model.getAttribute(name));
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
  // A tab switch swaps only the list: the summary stays and the segment's pill slides; the new list comes in from the
  // side of the tab that was tapped.
  const switchTab = (key) => {
    const seg = app.querySelector(".v-seg"), from = Number(seg.dataset.at);
    state.tab = key;
    save(state);
    const next = document.createElement("main");
    next.innerHTML = view(data, new Date(), state);
    applyLayout(next);
    const fresh = next.querySelector(".view"), at = Number(next.querySelector(".v-seg").dataset.at);
    seg.dataset.at = at;
    seg.style.setProperty("--seg-at", at);
    seg.querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === key)));
    fresh.style.setProperty("--dx", `${Math.sign(at - from) * 14}px`);
    fresh.classList.add("enter");
    app.querySelector(".view").replaceWith(fresh);
  };
  render();
  app.classList.add("first");
  setTimeout(() => app.classList.remove("first"), 800);
  requestAnimationFrame(() => requestAnimationFrame(() => app.querySelector(".v-seg")?.setAttribute("data-ready", "")));
  app.addEventListener("click", (event) => {
    const check = event.target.closest("[data-check]"), tab = event.target.closest("[data-tab]");
    if (check) {
      const id = check.dataset.check, done = check.getAttribute("aria-pressed") !== "true";
      state.marks = { ...state.marks, [id]: { done, at: Date.now() } };
      save(state);
      sync(app, data, state);
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
    } else if (tab && tab.getAttribute("aria-selected") !== "true") {
      switchTab(tab.dataset.tab);
    } else if (event.target.closest("[data-later]")) {
      state.later = true;
      render();
      app.querySelector(".v-seg")?.setAttribute("data-ready", "");
    } else if (event.target.closest("[data-read-all]")) {
      state.read = [...new Set([...(state.read || []), ...(data.news || []).map((n) => n.id)])].slice(-200);
      save(state);
      render();
      app.querySelector(".v-seg")?.setAttribute("data-ready", "");
    }
  });
}

if (typeof document !== "undefined") init();
