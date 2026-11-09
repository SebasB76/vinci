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
const clamp = (value) => Math.max(0, Math.min(100, Number(value) || 0));

// The same color a subject has on «Tu semana» (dashboard.js hue, over the same short name).
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

// The big number answers «what do I need?» by the calculator's verdict; the sentence under it gives the reason.
function hero(s) {
  const aim = s.target === s.passing ? "aprobar" : `llegar a ${num(s.target)}`;
  let big, label, cls = "", badge = "", say;
  if (s.verdict === "reached") {
    big = "Listo";
    cls = " ok word";
    label = `ya tienes ${num(s.target)}<br>asegurados`;
    badge = `<span class="lt ok"><i></i>${s.target === s.passing ? "aprobada" : "meta lograda"}</span>`;
    say = `Pase lo que pase en lo que falta, llegas a ${num(s.target)}.`;
  } else if (s.verdict === "reachable") {
    big = `${num(s.needed)}<small>%</small>`;
    label = "necesitas en<br>lo que falta";
    say = `Para ${aim} necesitas un promedio de ${pct(s.needed)} en los ${num(s.remaining)} puntos que faltan. Como máximo puedes sacar ${num(s.max)}.`;
  } else if (s.verdict === "out_of_reach") {
    big = num(s.max);
    cls = " late";
    label = "lo máximo que<br>puedes sacar";
    badge = `<span class="lt"><i></i>en riesgo</span>`;
    const imp = s.improvement;
    say = `Ni con 100&#8239;% en lo que falta llegas a ${num(s.target)}.`
      + (imp && imp.needed != null ? ` En ${esc(imp.name)} (reemplaza ${esc(imp.replaces)}) necesitas ${pct(imp.needed)}.`
        : imp && imp.possible === false ? ` Ni con ${esc(imp.name)} alcanzas.`
          : imp ? ` ${esc(imp.name)} puede reemplazar tu parcial más bajo.` : "");
  } else {
    big = `${num(s.target)}<small>%</small>`;
    label = "necesitas<br>en todo";
    say = "Todavía no hay notas en lo que cuenta para la nota final.";
  }
  if (s.replaced) say += ` ${esc(s.replaced.improvement)} reemplazó a ${esc(s.replaced.replaced)}.`;
  return { html: `<div class="hero"><div class="big${cls}"><b>${big}</b><span>${label}</span></div>${badge}</div>`, say };
}

// One bar out of 100 points: what is secured, what can still be earned (up to the maximum), what is already lost;
// the line is the target. view() leaves the figures in data-*, applyLayout() turns them into CSS variables.
function meter(s) {
  const got = clamp(s.secured), top = Math.max(got, clamp(s.max ?? got + (s.remaining || 0))), goal = clamp(s.target);
  const label = `${num(s.secured)} de 100 puntos ganados; puedes llegar a ${num(s.max)}; la meta es ${num(s.target)}`;
  return `<div class="meter" role="img" aria-label="${label}" data-got="${got}" data-top="${top}" data-goal="${goal}">
      <span class="bar">${got ? '<i class="got"></i>' : ""}${top > got ? '<i class="can"></i>' : ""}${top < 100 ? '<i class="lost"></i>' : ""}</span>
      <span class="goal"><span class="mono">${num(s.target)}</span></span></div>
    <div class="legend mono"><span><i class="sw got"></i>${num(s.secured)} ganados</span><span><i class="sw can"></i>${
      num(s.remaining)} por evaluar</span><span class="aim"><i class="sw line"></i>meta ${num(s.target)}</span></div>`;
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
  return `<div class="comp"><div class="row"><span class="nm">${esc(c.name)}<span class="mono">${pct(c.weight)}</span></span>
    <b class="sc${c.avg == null ? " none" : ""}">${c.avg == null ? "—" : num(c.avg)}</b></div>${segs}
    ${grades.length ? `<p class="mono gr">${grades.join(" · ")}</p>` : ""}</div>`;
}

// A period is a section of «Componentes»; a subject with only one shows the plain title.
function period(p, several) {
  const title = several || p.imp ? esc(p.name) : "Componentes";
  const meta = p.imp ? `reemplaza ${p.imp.map(esc).join(" o ")} si es mayor`
    : [p.weight != null && several ? `${pct(p.weight)} de la nota` : "", p.so_far != null ? `${pct(p.so_far)} en lo calificado` : ""]
      .filter(Boolean).join(" · ");
  return `<section class="grp"><div class="v-cap"><h2>${title}</h2><span class="mono">${meta}</span></div>
    <div class="card comps">${p.exception ? `<p class="mono exc">↳ ${esc(p.exception)}</p>` : ""}${p.comps.map(component).join("")}</div></section>`;
}

function subjectView(s) {
  const several = s.periods.length > 1;
  const { html, say } = hero(s);
  const notes = [];
  if (s.questions && s.questions.length) {
    notes.push(`<div class="note">${icon("alert")}<span><b>Falta confirmar.</b> ${s.questions.map(esc).join(" ")} Díselo a Vinci en el chat.</span></div>`);
  }
  if (s.loose) {
    notes.push(`<div class="note">${icon("info")}<span>${s.loose === 1 ? "Una nota del aula no va" : `${s.loose} notas del aula no van`} en ninguna parte del esquema. Pregúntale a Vinci a cuál van.</span></div>`);
  }
  const aim = s.target === s.passing ? `apruebas con ${num(s.passing)}` : `meta ${num(s.target)} · apruebas con ${num(s.passing)}`;
  return `<section class="v-sheet sum"><div class="v-eyebrow"><span>${aim}</span><span>${pct(s.graded)} evaluado</span></div>
      <h2 class="ttl">${esc(s.name)}</h2>${html}${meter(s)}<p class="say">${say}</p></section>
    ${s.periods.map((p) => period(p, several)).join("")}${notes.join("")}`;
}

function tabs(subjects, selected) {
  return `<div class="tabs" role="tablist" aria-label="Materias"><div class="track"><span class="ind" aria-hidden="true"></span>${
    subjects.map((s, i) => `<button type="button" role="tab" class="tab k${hue(s.name)}" data-subject="${i}" aria-selected="${i === selected}">
      <i class="dot" aria-hidden="true"></i><span class="nm ellipsis">${esc(s.name)}</span>${s.verdict === "out_of_reach"
        ? '<i class="risk" aria-hidden="true"></i><span class="sr-only">, en riesgo</span>' : ""}</button>`).join("")}</div></div>`;
}

// The whole page as HTML; `selected` is the index in the sorted list.
export function view(data, now, selected = 0) {
  const subjects = sorted(data.subjects || []), without = data.without || [];
  const at = Math.min(selected, Math.max(0, subjects.length - 1));
  const updated = data.at ? new Date(data.at) : null;
  const atRisk = subjects.filter((s) => s.verdict === "out_of_reach").length;
  const meta = subjects.length ? `${subjects.length} ${subjects.length === 1 ? "materia" : "materias"}${atRisk ? ` · ${atRisk} en riesgo` : ""}` : "sin esquemas todavía";
  let html = `<header class="top"><h1>Tus notas</h1><span class="mono">${meta}</span></header>`;
  if (subjects.length > 1) html += tabs(subjects, at);
  html += subjects.length ? `<div class="view k${hue(subjects[at].name)}">${subjectView(subjects[at])}</div>`
    : `<div class="card empty"><b>Ninguna materia tiene su esquema.</b>Pregúntale a Vinci «¿cómo voy en …?» y te propone el de su sílabo.</div>`;
  if (without.length) {
    html += `<div class="note">${icon("info")}<span><b>Sin esquema:</b> ${without.map(esc).join(", ")}. Pregúntale a Vinci «¿cómo voy en ${esc(without[0])}?» y te propone el de su sílabo.</span></div>`;
  }
  if (updated) {
    html += `<p class="mono foot">cuentas de la calculadora de Vinci · ${WEEKDAYS[updated.getDay()]} ${updated.getDate()} ${MONTHS[updated.getMonth()]}, ${
      String(updated.getHours()).padStart(2, "0")}:${String(updated.getMinutes()).padStart(2, "0")}</p>`;
  }
  return html;
}

// The page's CSP takes no style attribute: the bar's figures in data-* become CSS variables here.
export function applyLayout(root) {
  for (const el of root.querySelectorAll(".meter")) {
    for (const key of ["got", "top", "goal"]) el.style.setProperty(`--${key}`, el.dataset[key]);
  }
}

// The white pill sits under the chosen tab; tabs differ in width, so it takes the tab's offset and width.
function placePill(app) {
  const pill = app.querySelector(".tabs .ind"), tab = app.querySelector('.tab[aria-selected="true"]');
  if (!pill || !tab) return;
  pill.style.setProperty("--x", `${tab.offsetLeft}px`);
  pill.style.setProperty("--w", `${tab.offsetWidth}px`);
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
  app.innerHTML = view(data, new Date(), selected);
  applyLayout(app);
  placePill(app);
  app.classList.add("first");
  setTimeout(() => app.classList.remove("first"), 800);
  requestAnimationFrame(() => requestAnimationFrame(() => app.querySelector(".tabs")?.setAttribute("data-ready", "")));
  // The webfont changes the tabs' widths once it arrives, and a rotated phone changes the strip's.
  document.fonts?.ready.then(() => placePill(app));
  addEventListener("resize", () => placePill(app));

  // A tab swaps only the subject below: the strip stays, its pill slides, and the subject comes in from that side.
  app.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-subject]");
    if (!tab || tab.getAttribute("aria-selected") === "true") return;
    const from = selected;
    selected = Number(tab.dataset.subject);
    app.querySelectorAll("[data-subject]").forEach((b) => b.setAttribute("aria-selected", String(b === tab)));
    placePill(app);
    const next = document.createElement("main");
    next.innerHTML = view(data, new Date(), selected);
    applyLayout(next);
    const fresh = next.querySelector(".view");
    fresh.style.setProperty("--dx", `${Math.sign(selected - from) * 14}px`);
    fresh.classList.add("enter");
    app.querySelector(".view").replaceWith(fresh);
    tab.scrollIntoView({ block: "nearest", inline: "center",
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
}

if (typeof document !== "undefined") init();
