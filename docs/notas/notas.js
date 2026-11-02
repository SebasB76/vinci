// «Tus notas»: the grade calculator of every subject, as Vinci sends it on WhatsApp (espol_bot/grades_page.py).
// The snapshot rides in the URL's fragment (#d=<base64url of raw DEFLATE JSON>) and the page asks no server for
// anything: its CSP forbids connections. Every figure comes computed; the page only lays it out.

const WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
// Riskiest first: what cannot be reached, then what needs the most on what is left.
const ORDER = { out_of_reach: 0, reachable: 1, no_grades: 2, reached: 3 };

const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

export function readFragment(hash) {
  for (const pair of hash.replace(/^#/, "").split(/[&?]/)) {
    if (pair.startsWith("d=")) return pair.slice(2);
  }
  return "";
}

export async function decode(payload) {
  const b64 = payload.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (payload.length % 4)) % 4);
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(stream).text());
}

// 58.7 → «58,7», 60 → «60», as grades.num writes it in the chat.
export function num(value) {
  if (value == null) return "—";
  return (Math.round(value * 10) / 10).toFixed(1).replace(/\.0$/, "").replace(".", ",");
}
const pct = (value) => `${num(value)}&#8239;%`;

// A subject keeps the same pastel and initials as on «Tu semana» (dashboard.js).
const SMALL = new Set(["de", "del", "la", "las", "los", "el", "y", "e", "en", "a", "para", "i", "ii", "iii", "iv"]);
function initials(name) {
  const words = String(name || "").normalize("NFD").replace(/[̀-ͯ]/g, "").split(/[\s\-–:.,]+/)
    .filter((w) => w && !SMALL.has(w.toLowerCase()));
  if (!words.length) return "·";
  return (words.length > 1 ? words[0][0] + words[1][0] : words[0].slice(0, 2)).toUpperCase();
}
function hue(name) {
  let h = 0;
  for (const c of String(name || "")) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 5;
}

const ICONS = {
  alert: '<path d="M12 4l9 16H3zM12 10v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
};
const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

export function sorted(subjects) {
  return [...subjects].sort((a, b) => (ORDER[a.verdict] ?? 9) - (ORDER[b.verdict] ?? 9)
    || (b.needed ?? 0) - (a.needed ?? 0) || a.name.localeCompare(b.name));
}

// The three tiles of «Para aprobar» and the sentence under them, by the calculator's verdict.
function goal(s) {
  const aim = s.target === s.passing ? "aprobar" : `llegar a ${num(s.target)}`;
  const earned = `<div class="tile"><div class="n">${num(s.secured)}</div><div class="l">Puntos ganados</div></div>`;
  const graded = `<div class="tile"><div class="n">${pct(s.graded)}</div><div class="l">Ya evaluado</div></div>`;
  let first, say;
  if (s.verdict === "reached") {
    first = `<div class="tile done"><div class="n">Listo</div><div class="l">Ya tienes ${num(s.target)} asegurados</div></div>`;
    say = `Pase lo que pase en lo que falta, llegas a ${num(s.target)}.`;
  } else if (s.verdict === "reachable") {
    first = `<div class="tile hi"><div class="n">${pct(s.needed)}</div><div class="l">Necesitas en lo que falta</div></div>`;
    say = `Para ${aim} necesitas un promedio de ${pct(s.needed)} en los ${num(s.remaining)} puntos que faltan. Como máximo puedes sacar ${num(s.max)}.`;
  } else if (s.verdict === "out_of_reach") {
    first = `<div class="tile late"><div class="n">${num(s.max)}</div><div class="l">Lo máximo que puedes sacar</div></div>`;
    const imp = s.improvement;
    say = `Ni con 100&#8239;% en lo que falta llegas a ${num(s.target)}.`
      + (imp && imp.needed != null ? ` En ${esc(imp.name)} (reemplaza ${esc(imp.replaces)}) necesitas ${pct(imp.needed)}.`
        : imp && imp.possible === false ? ` Ni con ${esc(imp.name)} alcanzas.`
          : imp ? ` ${esc(imp.name)} puede reemplazar tu parcial más bajo.` : "");
  } else {
    first = `<div class="tile hi"><div class="n">${pct(s.target)}</div><div class="l">Necesitas en todo</div></div>`;
    say = "Todavía no hay notas en lo que cuenta para la nota final.";
  }
  if (s.replaced) say += ` ${esc(s.replaced.improvement)} reemplazó a ${esc(s.replaced.replaced)}.`;
  return `<div class="tiles">${first}${earned}${graded}</div><p class="say">${say}</p>`;
}

function component(c) {
  const on = c.avg == null ? 0 : Math.max(0, Math.min(10, Math.round(c.avg / 10)));
  const segs = c.avg == null ? `<div class="segs blank"><i></i></div>`
    : `<div class="segs">${Array.from({ length: 10 }, (_, i) => `<i${i < on ? ' class="on"' : ""}></i>`).join("")}</div>`;
  const grades = c.items.map(([name, score, outOf, status, told]) => status === "e" ? `${esc(name)} exonerada`
    : `${esc(name)} ${num(score)}/${num(outOf)}${told ? " (se lo dijiste a Vinci)" : ""}`);
  if (c.cut) grades.push(`${c.cut} más`);
  const waiting = c.pending + (c.missing || 0);
  if (waiting) grades.push(`${waiting} sin nota todavía`);
  return `<div class="ins"><div class="nm">${esc(c.name)} <span>· ${pct(c.weight)}</span></div>
    <span class="sc${c.avg == null ? " none" : ""}">${c.avg == null ? "—" : num(c.avg)}</span>${segs}
    ${grades.length ? `<p class="gr">${grades.join(" · ")}</p>` : ""}</div>`;
}

function period(p, several) {
  const head = p.imp ? `<b>${esc(p.name)}</b> · reemplaza ${p.imp.map(esc).join(" o ")} si es mayor`
    : `<b>${esc(p.name)}</b>${p.weight != null ? ` · ${pct(p.weight)} de la nota` : ""}${p.so_far != null ? ` · ${pct(p.so_far)} en lo calificado` : ""}`;
  return `${several || p.imp ? `<p class="gl">${head}</p>` : ""}${p.exception ? `<p class="gl">↳ ${esc(p.exception)}</p>` : ""}
    ${p.comps.map(component).join("")}`;
}

function subjectView(s) {
  const several = s.periods.length > 1;
  const notes = [];
  if (s.questions && s.questions.length) {
    notes.push(`<div class="note">${icon("alert")}<span><b>Falta confirmar.</b> ${s.questions.map(esc).join(" ")} Díselo a Vinci en el chat.</span></div>`);
  }
  if (s.loose) {
    notes.push(`<div class="note">${icon("info")}<span>${s.loose === 1 ? "Una nota del aula no va" : `${s.loose} notas del aula no van`} en ninguna parte del esquema. Pregúntale a Vinci a cuál van.</span></div>`);
  }
  return `<section class="sheet c${hue(s.name)}">
    <header class="head"><span class="av lg">${esc(initials(s.name))}</span><div>
      <h2>${esc(s.name)}</h2><p class="meta">Apruebas con ${num(s.passing)}</p></div></header>
    <div class="card sheet"><p class="lab">Para ${s.target === s.passing ? "aprobar" : `llegar a ${num(s.target)}`}</p>${goal(s)}</div>
    <div class="card"><p class="lab">Componentes</p>${s.periods.map((p) => period(p, several)).join("")}</div>
    ${notes.join("")}
  </section>`;
}

// The whole page as HTML; `selected` is the index in the sorted list.
export function view(data, now, selected = 0) {
  const subjects = sorted(data.subjects || []), without = data.without || [];
  const updated = data.at ? new Date(data.at) : null;
  const atRisk = subjects.filter((s) => s.verdict === "out_of_reach").length;
  const meta = subjects.length ? `${subjects.length} ${subjects.length === 1 ? "materia" : "materias"}${atRisk ? ` · ${atRisk} en riesgo` : ""}` : "Sin esquemas todavía";
  let html = `<header class="head"><span class="logo" aria-hidden="true"></span><div>
    <h1>Tus notas</h1><p class="meta">${meta}</p></div></header>`;
  if (subjects.length > 1) {
    html += `<div class="tabs" role="tablist">${subjects.map((s, i) => `<button type="button" class="tab c${hue(s.name)}" role="tab"
      data-subject="${i}" aria-selected="${i === selected}"><span class="av">${esc(initials(s.name))}</span>${esc(s.name)}${
      s.verdict === "out_of_reach" ? '<span class="dot" aria-label="en riesgo"></span>' : ""}</button>`).join("")}</div>`;
  }
  html += subjects.length ? subjectView(subjects[Math.min(selected, subjects.length - 1)])
    : `<div class="card empty"><b>Ninguna materia tiene su esquema.</b>Pregúntale a Vinci «¿cómo voy en …?» y te propone el de su sílabo.</div>`;
  if (without.length) {
    html += `<div class="note">${icon("info")}<span><b>Sin esquema:</b> ${without.map(esc).join(", ")}. Pregúntale a Vinci «¿cómo voy en ${esc(without[0])}?» y te propone el de su sílabo.</span></div>`;
  }
  if (updated) {
    html += `<p class="foot">Cuentas de la calculadora de Vinci · ${WEEKDAYS[updated.getDay()]} ${updated.getDate()} ${MONTHS[updated.getMonth()]}, ${
      String(updated.getHours()).padStart(2, "0")}:${String(updated.getMinutes()).padStart(2, "0")}</p>`;
  }
  return html;
}

async function init() {
  const app = document.getElementById("app");
  let data;
  try {
    const payload = readFragment(location.hash);
    data = payload ? await decode(payload) : null;
  } catch {
    data = null;
  }
  if (!data || data.v !== 1) {
    app.innerHTML = `<div class="card empty"><b>Aquí no hay nada todavía.</b>Pídele tus notas a Vinci en el chat.</div>`;
    return;
  }
  let selected = 0;
  const render = () => { app.innerHTML = view(data, new Date(), selected); };
  render();
  app.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-subject]");
    if (!tab) return;
    selected = Number(tab.dataset.subject);
    render();
    app.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest", inline: "center" });
  });
}

if (typeof document !== "undefined") init();
