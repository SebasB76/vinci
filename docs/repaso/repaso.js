// A study page as Vinci sends it on WhatsApp (espol_bot/study_page.py, which checked every field). The content rides
// in the URL's fragment (#d=<base64url of raw DEFLATE JSON>) and the page asks no server for anything; what the
// student answers stays here. Model-written text only ever reaches the DOM as text nodes.

const SVG = "http://www.w3.org/2000/svg";
const INK = "#000000", INK3 = "#70685C", LINE = "#CDC6BC", SOFT = "#ECE8E2", ACCENT = "#7AF3C2", LATE = "#B5432E";
const CURVES = ["#000000", "#1E9E6E", "#7C5CD6"];

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

// The grammar study_page.py checks: + - * / ^ (or **), parentheses, numbers, pi, e, x, the sliders' names and FUNCS.
const FUNCS = { sin: Math.sin, cos: Math.cos, tan: Math.tan, asin: Math.asin, acos: Math.acos, atan: Math.atan,
  sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh, exp: Math.exp, ln: Math.log, log: Math.log10, sqrt: Math.sqrt,
  abs: Math.abs, floor: Math.floor, ceil: Math.ceil };
const CONSTS = { pi: Math.PI, e: Math.E };

export function compile(src) {
  const tokens = String(src).replace(/\*\*/g, "^").match(/\d*\.?\d+(?:e[+-]?\d+)?|[a-zA-Z_]\w*|[-+*/^()]|\S/g) || [];
  let at = 0;
  const peek = () => tokens[at];
  const take = (t) => (tokens[at] === t ? (at += 1, true) : false);
  const fail = () => { throw new Error(`no entiendo «${src}»`); };
  function primary() {
    const t = tokens[at++];
    if (t === undefined) fail();
    if (t === "(") { const inner = sum(); if (!take(")")) fail(); return inner; }
    if (/^[\d.]/.test(t)) { const v = Number(t); return () => v; }
    if (/^[a-zA-Z_]/.test(t)) {
      if (FUNCS[t]) { if (!take("(")) fail(); const arg = sum(); if (!take(")")) fail(); const f = FUNCS[t]; return (env) => f(arg(env)); }
      if (t in CONSTS) { const v = CONSTS[t]; return () => v; }
      return (env) => (t in env ? env[t] : NaN);
    }
    return fail();
  }
  function power() { const base = primary(); if (take("^")) { const exp = unary(); return (env) => base(env) ** exp(env); } return base; }
  function unary() { if (take("-")) { const v = unary(); return (env) => -v(env); } take("+"); return power(); }
  function product() {
    let left = unary();
    for (let op = peek(); op === "*" || op === "/"; op = peek()) {
      at += 1;
      const a = left, b = unary();
      left = op === "*" ? (env) => a(env) * b(env) : (env) => a(env) / b(env);
    }
    return left;
  }
  function sum() {
    let left = product();
    for (let op = peek(); op === "+" || op === "-"; op = peek()) {
      at += 1;
      const a = left, b = product();
      left = op === "+" ? (env) => a(env) + b(env) : (env) => a(env) - b(env);
    }
    return left;
  }
  const fn = sum();
  if (at !== tokens.length) fail();
  return fn;
}

// -- small helpers ------------------------------------------------------------------------------------------------

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}
function svgEl(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}
function button(cls, text, onClick) {
  const b = el("button", cls, text);
  b.type = "button";
  b.addEventListener("click", onClick);
  return b;
}
const fmtCache = {};
export function fmt(value, digits) {
  if (!Number.isFinite(value)) return "—";
  const d = digits ?? (Math.abs(value) >= 100 ? 1 : Math.abs(value) >= 1 ? 2 : 3);
  fmtCache[d] ??= new Intl.NumberFormat("es", { maximumFractionDigits: d });
  return fmtCache[d].format(Math.abs(value) < 1e-12 ? 0 : value).replace("-", "−");
}
const pct = (p) => `${fmt(p * 100, p * 100 >= 99.95 || p * 100 < 0.05 ? 2 : 1)} %`;
function shuffled(list, keepOff = true) {
  const order = list.map((_, i) => i);
  for (let tries = 0; tries < 8; tries += 1) {
    for (let k = order.length - 1; k > 0; k -= 1) {
      const j = Math.floor(Math.random() * (k + 1));
      [order[k], order[j]] = [order[j], order[k]];
    }
    if (!keepOff || order.length < 2 || order.some((v, i) => v !== i)) break;
  }
  return order;
}
function niceStep(range, target = 5) {
  const raw = range / target, mag = 10 ** Math.floor(Math.log10(raw)), f = raw / mag;
  return (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * mag;
}
let uid = 0;

const ICONS = {
  book: '<path d="M4 19.5V5a2 2 0 0 1 2-2h13v15H6a2 2 0 0 0-2 2Zm0 0A2 2 0 0 0 6 22h13"/><path d="M9 8h6M9 11h4"/>',
  tip: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.5.4.8 1 .8 1.6V16h5.4v-.5c0-.6.3-1.2.8-1.6A6 6 0 0 0 12 3Z"/>',
  warning: '<path d="M12 4l9 16H3zM12 10v4M12 17h.01"/>',
  key: '<path d="M12 3l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.3 6.8 19l1-5.8L3.6 9.1l5.8-.8z"/>',
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/>',
};
function icon(name) {
  const s = svgEl("svg", { class: "i", viewBox: "0 0 24 24", "aria-hidden": "true" });
  s.innerHTML = ICONS[name]; // our own constant markup, never model text
  return s;
}

// -- math: KaTeX loads only when a page has formulas; until then (or if it fails) the TeX shows as written ---------

const pendingMath = [];
let katexLoad = null;
function loadKatex() {
  katexLoad ??= new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = "katex/katex.min.css?v=1";
    document.head.append(css);
    const js = document.createElement("script");
    js.src = "katex/katex.min.js?v=1";
    js.onload = () => resolve(window.katex);
    js.onerror = reject;
    document.head.append(js);
  });
  return katexLoad;
}
function typeset(span) {
  try {
    window.katex.render(span.dataset.tex, span, { displayMode: span.dataset.display === "1", throwOnError: false });
    span.classList.remove("raw");
  } catch { /* keeps the raw TeX */ }
}
function tex(source, display = false) {
  const span = el("span", "tex raw", source);
  span.dataset.tex = source;
  span.dataset.display = display ? "1" : "0";
  if (window.katex) typeset(span);
  else {
    pendingMath.push(span);
    loadKatex().then(() => pendingMath.splice(0).forEach(typeset), () => {});
  }
  return span;
}

// **bold**, `code`, $math$ and [label](https://…) inside a line; everything else is plain text.
const INLINE = /(\$[^$\n]+\$|\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\(https:\/\/[^)\s]+\))/g;
function inline(text, into = document.createDocumentFragment()) {
  String(text ?? "").split("\n").forEach((line, i) => {
    if (i) into.append(document.createElement("br"));
    for (const part of line.split(INLINE)) {
      if (!part) continue;
      if (part.length > 2 && part.startsWith("$") && part.endsWith("$")) into.append(tex(part.slice(1, -1)));
      else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) into.append(inline(part.slice(2, -2), el("b")));
      else if (part.startsWith("`") && part.endsWith("`") && part.length > 2) into.append(el("code", null, part.slice(1, -1)));
      else if (part.startsWith("[") && part.includes("](https://")) {
        const [, label, url] = part.match(/^\[([^\]]+)\]\((https:\/\/[^)\s]+)\)$/) || [];
        if (url) {
          const a = el("a", null, label);
          a.href = url;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          into.append(a);
        } else into.append(part);
      } else into.append(part);
    }
  });
  return into;
}
function prose(text, cls = "prose") {
  const box = el("div", cls);
  for (const para of String(text ?? "").split(/\n\s*\n/)) if (para.trim()) box.append(inline(para.trim(), el("p")));
  return box;
}

// -- the page's running score: every quiz question, case to classify and list to order counts once -------------

const score = { right: 0, done: 0, total: 0, card: null };
function counts(n) { score.total += n; }
function answered(right) {
  score.done += 1;
  if (right) score.right += 1;
  if (!score.card) return;
  score.card.hidden = false;
  score.card.querySelector(".big").textContent = `${score.right} de ${score.total}`;
  score.card.querySelector(".meter i").style.width = `${(score.done / score.total) * 100}%`;
  const all = score.done === score.total, share = score.right / score.total;
  score.card.querySelector(".say-end").textContent = !all ? `Te faltan ${score.total - score.done} por responder.`
    : share === 1 ? "Todo bien. Ya lo dominas." : share >= 0.6 ? "Bien. Vuelve a mirar las que fallaste."
    : "Repasa la explicación de arriba y vuelve a intentarlo: recarga la página.";
}

function card(title, kind, extra) {
  const c = el("section", "card");
  c.dataset.block = kind;
  const head = el("div", "lab");
  head.append(el("span", null, title || ""));
  if (extra) head.append(extra);
  if (title || extra) c.append(head);
  return c;
}

// -- blocks ----------------------------------------------------------------------------------------------------------

const LABELS = { tip: "Consejo", warning: "Error común", key: "Clave" };

const BLOCKS = {
  text(b) {
    const c = card(b.title, "text");
    c.append(prose(b.body));
    return c;
  },

  callout(b) {
    const box = el("aside", `callout ${b.kind}`);
    box.dataset.block = "callout";
    box.append(icon(b.kind === "warning" ? "warning" : b.kind === "key" ? "key" : "tip"));
    const body = el("div");
    body.append(el("span", "k", b.title || LABELS[b.kind] || ""), inline(b.body));
    box.append(body);
    return box;
  },

  formula(b) {
    const c = card(b.title, "formula");
    const f = el("div", "formula");
    f.append(tex(b.latex, true));
    c.append(f);
    if (b.legend?.length) {
      const lg = el("div", "legend");
      for (const row of b.legend) {
        const r = el("div");
        r.append(inline(row.symbol, el("span", "sym")), inline(row.meaning, el("span")));
        lg.append(r);
      }
      c.append(lg);
    }
    return c;
  },

  function_plot(b) {
    const c = card(b.title, "function_plot", el("span", "pill", "toca la gráfica"));
    const curves = b.curves.map((cv) => ({ ...cv, fn: (() => { try { return compile(cv.expr); } catch { return () => NaN; } })() }));
    const env = Object.fromEntries(b.params.map((p) => [p.name, p.value]));
    const [x0, x1] = b.x, W = 320, H = 210, PAD = { l: 30, r: 8, t: 8, b: 20 };
    const value = (fn, x) => { try { return fn({ ...env, x }); } catch { return NaN; } };
    let [y0, y1] = b.y || (() => {
      const ys = [];
      for (const cv of curves) for (let k = 0; k <= 200; k += 1) { const y = value(cv.fn, x0 + ((x1 - x0) * k) / 200); if (Number.isFinite(y)) ys.push(y); }
      ys.sort((a, z) => a - z);
      if (!ys.length) return [-1, 1];
      let lo = ys[Math.floor(ys.length * 0.02)], hi = ys[Math.ceil(ys.length * 0.98) - 1];
      if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
      const pad = (hi - lo) * 0.12;
      return [lo - pad, hi + pad];
    })();
    if (b.params.length) { const span = y1 - y0; y0 -= span * 0.25; y1 += span * 0.25; } // room for the sliders' changes
    const sx = (x) => PAD.l + ((x - x0) / (x1 - x0)) * (W - PAD.l - PAD.r);
    const sy = (y) => PAD.t + ((y1 - y) / (y1 - y0)) * (H - PAD.t - PAD.b);
    const svg = svgEl("svg", { class: "plot", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": b.title || "Gráfica" });
    const grid = svgEl("g"), lines = svgEl("g"), cursor = svgEl("g");
    svg.append(svgEl("clipPath", { id: `clip${++uid}` }), grid, lines, cursor);
    svg.firstChild.append(svgEl("rect", { x: PAD.l, y: PAD.t, width: W - PAD.l - PAD.r, height: H - PAD.t - PAD.b }));
    lines.setAttribute("clip-path", `url(#clip${uid})`);
    const xs = niceStep(x1 - x0), ys = niceStep(y1 - y0, 4);
    for (let v = Math.ceil(x0 / xs) * xs; v <= x1 + 1e-9; v += xs) {
      grid.append(svgEl("line", { x1: sx(v), x2: sx(v), y1: PAD.t, y2: H - PAD.b, stroke: Math.abs(v) < xs / 1e6 ? LINE : SOFT }));
      grid.append(svgEl("text", { x: sx(v), y: H - 6, "text-anchor": "middle" }, fmt(v, 2)));
    }
    for (let v = Math.ceil(y0 / ys) * ys; v <= y1 + 1e-9; v += ys) {
      grid.append(svgEl("line", { x1: PAD.l, x2: W - PAD.r, y1: sy(v), y2: sy(v), stroke: Math.abs(v) < ys / 1e6 ? LINE : SOFT }));
      grid.append(svgEl("text", { x: PAD.l - 4, y: sy(v) + 3, "text-anchor": "end" }, fmt(v, 2)));
    }
    const reading = el("p", "reading", "");
    let at = null;
    function draw() {
      lines.replaceChildren();
      curves.forEach((cv, i) => {
        let d = "", prev = null;
        for (let k = 0; k <= 320; k += 1) {
          const x = x0 + ((x1 - x0) * k) / 320, y = value(cv.fn, x);
          const ok = Number.isFinite(y) && Math.abs(sy(y)) < 4 * H && !(prev != null && Math.abs(y - prev) > (y1 - y0) * 3);
          if (ok) d += `${d && prev != null ? "L" : "M"}${sx(x).toFixed(1)},${sy(y).toFixed(1)}`;
          prev = ok ? y : null;
        }
        lines.append(svgEl("path", { d, fill: "none", stroke: CURVES[i], "stroke-width": 2, "stroke-linejoin": "round" }));
      });
      cursor.replaceChildren();
      if (at == null) { reading.textContent = "Arrastra el dedo sobre la gráfica para leer sus valores."; return; }
      cursor.append(svgEl("line", { x1: sx(at), x2: sx(at), y1: PAD.t, y2: H - PAD.b, stroke: INK3, "stroke-dasharray": "3 3" }));
      const parts = [`x = ${fmt(at)}`];
      curves.forEach((cv, i) => {
        const y = value(cv.fn, at);
        if (Number.isFinite(y) && y >= y0 && y <= y1) cursor.append(svgEl("circle", { cx: sx(at), cy: sy(y), r: 4, fill: CURVES[i], stroke: "#fff", "stroke-width": 1.5 }));
        parts.push(`${cv.label || (curves.length > 1 ? `curva ${i + 1}` : "y")} = ${fmt(y)}`);
      });
      reading.textContent = parts.join(" · ");
    }
    const point = (ev) => {
      const box = svg.getBoundingClientRect();
      const x = x0 + (((ev.clientX - box.left) / box.width) * W - PAD.l) / (W - PAD.l - PAD.r) * (x1 - x0);
      at = Math.min(x1, Math.max(x0, x));
      draw();
    };
    svg.addEventListener("pointerdown", (ev) => { svg.setPointerCapture(ev.pointerId); point(ev); });
    svg.addEventListener("pointermove", (ev) => { if (ev.buttons || ev.pointerType === "mouse") point(ev); });
    c.append(svg);
    if (curves.length > 1 || curves[0].label) {
      const keys = el("div", "keys");
      curves.forEach((cv, i) => { const s = el("span"); s.style.color = CURVES[i]; s.append(el("i")); s.append(inline(cv.label || cv.expr, el("span"))); keys.append(s); });
      c.append(keys);
    }
    c.append(reading);
    for (const p of b.params) c.append(slider(p.label || p.name, p.min, p.max, p.step || niceStep(p.max - p.min, 100), p.value, (v) => { env[p.name] = v; draw(); }));
    draw();
    return c;
  },

  distribution(b) { return distribution(b); },

  steps(b) {
    const c = card(b.title, "steps");
    c.append(inline(b.problem, el("p", "problem")));
    const ol = el("ol", "solve");
    c.append(ol);
    let shown = 0;
    const total = b.steps.length + (b.answer ? 1 : 0);
    const next = button("btn btn-accent", "Ver el primer paso", () => {
      const last = b.answer && shown === b.steps.length;
      const li = el("li", last ? "end" : null);
      li.append(el("span", "num", last ? "✓" : String(shown + 1)), inline(last ? b.answer : b.steps[shown], el("div")));
      ol.append(li);
      shown += 1;
      next.disabled = shown >= total;
      next.textContent = shown >= total ? "Listo" : shown === b.steps.length ? "Ver la respuesta" : `Siguiente paso (${shown + 1} de ${b.steps.length})`;
    });
    c.append(next);
    return c;
  },

  flashcards(b) {
    const c = card(b.title || "Tarjetas", "flashcards", el("span", "pill", "toca para voltear"));
    let i = 0, back = false;
    const face = el("button", "flash");
    face.type = "button";
    const dots = el("div", "dots");
    const prev = button("btn btn-quiet sm", "Anterior", () => { i -= 1; back = false; show(); });
    const next = button("btn btn-quiet sm", "Siguiente", () => { i += 1; back = false; show(); });
    face.addEventListener("click", () => { back = !back; show(); });
    function show() {
      face.className = back ? "flash back" : "flash";
      face.replaceChildren(el("span", "k", back ? "Respuesta" : `Tarjeta ${i + 1} de ${b.cards.length}`),
                           inline(back ? b.cards[i].back : b.cards[i].front, el("span", "q")));
      dots.replaceChildren(...b.cards.map((_, k) => el("i", k === i ? "on" : null)));
      prev.disabled = i === 0;
      next.disabled = i === b.cards.length - 1;
    }
    const nav = el("div", "nav");
    nav.append(prev, dots, next);
    c.append(face, nav);
    show();
    return c;
  },

  quiz(b) {
    const tally = el("span", "pill", `0 de ${b.questions.length}`);
    const c = card(b.title || "Ponte a prueba", "quiz", tally);
    let right = 0, done = 0;
    counts(b.questions.length);
    b.questions.forEach((q, qi) => {
      c.append(inline(`${qi + 1}. ${q.question}`, el("p", "qq")));
      const opts = el("div", "opts");
      const buttons = [];
      for (const oi of shuffled(q.options, false)) {
        const opt = button("opt", null, () => {
          const ok = oi === q.answer;
          buttons.forEach(([o, k]) => { o.disabled = true; if (k === q.answer) o.classList.add("ok"); });
          if (!ok) opt.classList.add("bad");
          right += ok ? 1 : 0;
          done += 1;
          const why = el("p", "why appear");
          why.append(el("b", null, ok ? "Bien. " : "Casi. "), inline(q.explanation));
          opts.after(why);
          tally.textContent = `${right} de ${b.questions.length}`;
          if (done === b.questions.length && right === done) tally.className = "pill ok";
          answered(ok);
        });
        opt.append(inline(q.options[oi]));
        buttons.push([opt, oi]);
        opts.append(opt);
      }
      c.append(opts);
    });
    return c;
  },

  sequence(b) { return sequence(b); },

  compare(b) {
    const c = card(b.title, "compare");
    const wrap = el("div", "cmp-wrap"), table = el("table", "cmp"), head = el("tr");
    head.append(el("th"));
    for (const col of b.columns) {
      const th = el("th");
      th.append(inline(col, el("span")));
      head.append(th);
    }
    table.append(head);
    for (const row of b.rows) {
      const tr = el("tr");
      tr.append(inline(row.aspect, el("td")));
      for (const v of row.values) tr.append(inline(v, el("td")));
      table.append(tr);
    }
    wrap.append(table);
    c.append(wrap);
    return c;
  },

  classify(b) {
    const tally = el("span", "pill", `0 de ${b.cases.length}`);
    const c = card(b.title || "Clasifica", "classify", tally);
    counts(b.cases.length);
    const stage = el("div", "card-inner");
    stage.style.display = "grid";
    stage.style.gap = "10px";
    c.append(stage);
    let i = 0, right = 0;
    function show() {
      const cs = b.cases[i];
      const chips = el("div", "chips");
      const all = [];
      b.options.forEach((o, oi) => {
        const chip = button("chip", null, () => {
          const ok = oi === cs.answer;
          all.forEach(([ch, k]) => { ch.disabled = true; if (k === cs.answer) ch.classList.add("ok"); });
          if (!ok) chip.classList.add("bad");
          right += ok ? 1 : 0;
          tally.textContent = `${right} de ${b.cases.length}`;
          const why = el("p", "why appear");
          why.append(el("b", null, ok ? "Bien. " : "Casi. "), inline(cs.explanation));
          stage.append(why);
          if (i < b.cases.length - 1) stage.append(button("btn btn-quiet sm", "Siguiente caso", () => { i += 1; show(); }));
          else if (right === b.cases.length) tally.className = "pill ok";
          answered(ok);
        });
        chip.append(inline(o));
        all.push([chip, oi]);
        chips.append(chip);
      });
      stage.replaceChildren(el("span", "lab", `Caso ${i + 1} de ${b.cases.length}`), inline(cs.text, el("p", "case")), chips);
    }
    show();
    return c;
  },

  order(b) {
    const c = card(b.title || "Ordena", "order", el("span", "pill", "toca en orden"));
    counts(1);
    const slots = el("ol", "slots"), chips = el("div", "chips"), after = el("div");
    after.style.display = "grid";
    after.style.gap = "10px";
    c.append(slots, chips, after);
    let picked = [], pool = [];
    function build() {
      picked = [];
      pool = shuffled(b.items);
      after.replaceChildren();
      draw();
    }
    function draw() {
      const full = picked.length === b.items.length;
      slots.replaceChildren(...b.items.map((_, k) => {
        const v = picked[k];
        const li = el("li");
        const slot = button(`slot${v != null ? " f" : ""}${full ? (v === k ? " ok" : " bad") : ""}`, null, () => {
          pool.push(...picked.splice(k));
          draw();
        });
        slot.disabled = v == null || full;
        slot.append(el("span", "num", String(k + 1)), v != null ? inline(b.items[v], el("span")) : el("span", null, "…"));
        li.append(slot);
        return li;
      }));
      chips.replaceChildren(...pool.map((item, pi) => {
        const chip = button("chip", null, () => { picked.push(item); pool.splice(pi, 1); draw(); });
        chip.append(inline(b.items[item]));
        return chip;
      }));
      if (full && !after.childElementCount) {
        const ok = picked.every((v, k) => v === k);
        const why = el("p", "why appear");
        why.append(el("b", null, ok ? "Exacto. " : "No del todo. "), inline(b.explanation));
        after.append(why);
        if (!c.dataset.scored) { c.dataset.scored = "1"; answered(ok); }
        if (!ok) after.append(button("btn btn-quiet sm", "Intentar de nuevo", build));
      }
    }
    build();
    return c;
  },

  code(b) {
    const c = card(b.title, "code", b.language ? el("span", "pill", b.language) : null);
    const pre = el("pre", "code"), say = el("p", "say");
    const lines = b.code.split("\n");
    c.append(pre, say);
    let i = 0;
    const go = button("btn btn-accent", "Revisar línea por línea", () => { i = i < b.walkthrough.length ? i + 1 : 0; draw(); });
    c.append(go);
    function draw() {
      const marked = i ? b.walkthrough[i - 1].lines : [];
      pre.replaceChildren(...lines.map((line, k) => {
        const span = el("span", marked.includes(k + 1) ? "hl" : i ? "dim" : null, line || " ");
        span.dataset.n = String(k + 1);
        return span;
      }));
      say.replaceChildren(i ? inline(b.walkthrough[i - 1].note) : "Léelo con calma. ¿Qué harías distinto? Después revísalo paso a paso.");
      go.textContent = i === 0 ? "Revisar línea por línea" : i < b.walkthrough.length ? `Siguiente (${i + 1} de ${b.walkthrough.length})` : "Volver a empezar";
      pre.querySelector(".hl")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
    }
    draw();
    return c;
  },

  diagram(b) { return diagram(b); },
};

function slider(label, min, max, step, value, onInput) {
  const row = el("label", "sl");
  const input = el("input");
  Object.assign(input, { type: "range", min, max, step, value });
  const out = el("output", null, fmt(value));
  input.addEventListener("input", () => { out.textContent = fmt(Number(input.value)); onInput(Number(input.value)); });
  row.append(inline(label, el("span")), input, out);
  return row;
}

// -- distributions ------------------------------------------------------------------------------------------------

function erf(x) {
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return x < 0 ? -y : y;
}
const normalCdf = (x, mu, s) => 0.5 * (1 + erf((x - mu) / (s * Math.SQRT2)));

function pmfs(dist, prm, kmax) {
  const out = new Array(kmax + 1).fill(0);
  if (dist === "binomial") {
    const { n, p } = prm;
    if (p <= 0) { out[0] = 1; return out; }
    if (p >= 1) { out[n] = 1; return out; }
    out[0] = (1 - p) ** n;
    for (let k = 0; k < n; k += 1) out[k + 1] = (out[k] * (n - k) / (k + 1)) * (p / (1 - p));
    return out;
  }
  out[0] = Math.exp(-prm.lambda);
  for (let k = 0; k < kmax; k += 1) out[k + 1] = (out[k] * prm.lambda) / (k + 1);
  return out;
}

function distribution(b) {
  const c = card(b.title, "distribution", el("span", "pill", "desliza"));
  const W = 320, H = 170, PAD = { l: 6, r: 6, t: 10, b: 20 };
  const svg = svgEl("svg", { class: "plot", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": b.title || "Distribución" });
  const tiles = el("div", "tiles");
  c.append(svg, tiles);
  const q = { ...b.query };
  const prm = {};
  const between = q.kind === "between";
  let lo, hi, ymax, discrete = b.dist !== "normal";
  if (b.dist === "normal") {
    Object.assign(prm, { mu: b.mu, sigma: b.sigma });
    lo = b.mu - 5 * b.sigma; hi = b.mu + 5 * b.sigma;
    ymax = 1.05 / ((b.sigma / 2) * Math.sqrt(2 * Math.PI));
    const ms = niceStep(6 * b.sigma, 120), ss = niceStep(1.5 * b.sigma, 100);
    c.append(slider("$\\mu$ media", b.mu - 3 * b.sigma, b.mu + 3 * b.sigma, ms, b.mu, (v) => { prm.mu = v; draw(); }));
    c.append(slider("$\\sigma$ desviación", Math.max(ss, b.sigma / 2), 2 * b.sigma, ss, b.sigma, (v) => { prm.sigma = v; draw(); }));
  } else if (b.dist === "binomial") {
    Object.assign(prm, { n: b.n, p: b.p });
    lo = -0.5; hi = Math.min(100, Math.max(2 * b.n, 20)) + 0.5;
    c.append(slider("$n$ intentos", 1, Math.round(hi - 0.5), 1, b.n, (v) => { prm.n = v; draw(); }));
    c.append(slider("$p$ éxito", 0, 1, 0.01, b.p, (v) => { prm.p = v; draw(); }));
  } else {
    Object.assign(prm, { lambda: b.lambda });
    const lmax = Math.max(2 * b.lambda, 10);
    lo = -0.5; hi = Math.ceil(lmax + 4 * Math.sqrt(lmax)) + 0.5;
    c.append(slider("$\\lambda$ promedio", 0.1, lmax, niceStep(lmax, 100), b.lambda, (v) => { prm.lambda = v; draw(); }));
  }
  const xStep = discrete ? 1 : niceStep(hi - lo, 200);
  c.append(slider(between ? "$a$ desde" : "$a$", discrete ? 0 : lo, discrete ? hi - 0.5 : hi, xStep, q.a, (v) => { q.a = v; if (between && q.b < v) q.b = v; draw(); }));
  if (between) c.append(slider("$b$ hasta", discrete ? 0 : lo, discrete ? hi - 0.5 : hi, xStep, q.b, (v) => { q.b = Math.max(v, q.a); draw(); }));
  const sx = (x) => PAD.l + ((x - lo) / (hi - lo)) * (W - PAD.l - PAD.r);
  const inside = (x) => (q.kind === "less" ? x <= q.a : q.kind === "greater" ? x >= q.a : x >= q.a && x <= q.b);
  const label = () => (q.kind === "less" ? `P(X ≤ ${fmt(q.a)})` : q.kind === "greater" ? `P(X ≥ ${fmt(q.a)})` : `P(${fmt(q.a)} ≤ X ≤ ${fmt(q.b)})`);
  function tile(n, l, hi) {
    const t = el("div", hi ? "tile hi" : "tile");
    t.append(el("div", "n", n), inline(l, el("div", "l")));
    return t;
  }
  function draw() {
    svg.replaceChildren();
    const base = H - PAD.b, top = PAD.t;
    let p, mean, sd;
    if (!discrete) {
      const { mu, sigma } = prm;
      const sy = (y) => base - (Math.min(y, ymax) / ymax) * (base - top);
      const pdf = (x) => Math.exp(-((x - mu) ** 2) / (2 * sigma * sigma)) / (sigma * Math.sqrt(2 * Math.PI));
      let curve = "", area = "";
      for (let k = 0; k <= 240; k += 1) {
        const x = lo + ((hi - lo) * k) / 240;
        curve += `${k ? "L" : "M"}${sx(x).toFixed(1)},${sy(pdf(x)).toFixed(1)}`;
      }
      const a = q.kind === "less" ? lo : q.a, z = q.kind === "less" ? q.a : q.kind === "greater" ? hi : q.b;
      if (z > a) {
        area = `M${sx(a)},${base}`;
        for (let k = 0; k <= 120; k += 1) { const x = a + ((z - a) * k) / 120; area += `L${sx(x).toFixed(1)},${sy(pdf(x)).toFixed(1)}`; }
        area += `L${sx(z)},${base}Z`;
        svg.append(svgEl("path", { d: area, fill: ACCENT, opacity: 0.8 }));
      }
      svg.append(svgEl("path", { d: curve, fill: "none", stroke: INK, "stroke-width": 1.8 }));
      svg.append(svgEl("line", { x1: sx(mu), x2: sx(mu), y1: top, y2: base, stroke: INK3, "stroke-dasharray": "3 3" }));
      svg.append(svgEl("text", { x: sx(mu), y: H - 5, "text-anchor": "middle" }, `μ = ${fmt(mu)}`));
      p = q.kind === "less" ? normalCdf(q.a, mu, sigma) : q.kind === "greater" ? 1 - normalCdf(q.a, mu, sigma)
        : normalCdf(q.b, mu, sigma) - normalCdf(q.a, mu, sigma);
      tiles.replaceChildren(tile(pct(p), label(), true), tile(fmt((q.a - mu) / sigma), "$z$ de $a$"),
                            ...(between ? [tile(fmt((q.b - mu) / sigma), "$z$ de $b$")] : []));
    } else {
      const kmax = Math.round(hi - 0.5);
      const probs = pmfs(b.dist, prm, kmax);
      const top2 = Math.max(...probs) * 1.1 || 1;
      const bw = Math.max(1, ((W - PAD.l - PAD.r) / (kmax + 1)) * 0.8);
      p = 0;
      probs.forEach((pk, k) => {
        const on = inside(k);
        if (on) p += pk;
        const h = (pk / top2) * (base - top);
        svg.append(svgEl("rect", { x: sx(k) - bw / 2, y: base - h, width: bw, height: Math.max(h, 0.5), rx: Math.min(2, bw / 3), fill: on ? "#1E9E6E" : LINE }));
      });
      const every = niceStep(kmax, 8);
      for (let k = 0; k <= kmax; k += every) svg.append(svgEl("text", { x: sx(k), y: H - 5, "text-anchor": "middle" }, String(k)));
      if (b.dist === "binomial") { mean = prm.n * prm.p; sd = Math.sqrt(prm.n * prm.p * (1 - prm.p)); }
      else { mean = prm.lambda; sd = Math.sqrt(prm.lambda); }
      tiles.replaceChildren(tile(pct(Math.min(1, p)), label(), true), tile(fmt(mean), "media"), tile(fmt(sd), "desviación"));
    }
    svg.append(svgEl("line", { x1: PAD.l, x2: W - PAD.r, y1: base, y2: base, stroke: LINE }));
  }
  draw();
  return c;
}

// -- sequence diagram ---------------------------------------------------------------------------------------------

function sequence(b) {
  const c = card(b.title, "sequence");
  const n = b.actors.length, W = 320, ROW = 34, TOP = 8;
  const xs = b.actors.map((_, k) => ((k + 0.5) * W) / n);
  const seg = el("div", "seg");
  seg.setAttribute("role", "tablist");
  const actors = el("div", "actors");
  actors.style.gridTemplateColumns = `repeat(${n}, minmax(0, 1fr))`;
  b.actors.forEach((a) => actors.append(el("span", null, a)));
  const box = el("div"), say = el("p", "say");
  const prev = button("btn btn-quiet", "Atrás", () => { i -= 1; draw(); });
  const next = button("btn btn-accent", "Empezar", () => { i += 1; draw(); });
  const nav = el("div", "row2");
  nav.append(prev, next);
  if (b.scenarios.length > 1) c.append(seg);
  c.append(actors, box, say, nav);
  let sc = 0, i = 0;
  function draw() {
    const msgs = b.scenarios[sc].messages, H = TOP + msgs.length * ROW + 8;
    const svg = svgEl("svg", { class: "seq", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Diagrama de secuencia" });
    xs.forEach((x) => svg.append(svgEl("line", { x1: x, x2: x, y1: 0, y2: H, stroke: LINE, "stroke-dasharray": "3 4" })));
    msgs.forEach((m, k) => {
      const y = TOP + k * ROW + 22, color = m.fail ? LATE : INK, on = k < i, current = k === i - 1;
      const g = svgEl("g", { opacity: on ? (current ? 1 : 0.38) : 0.08 });
      if (m.from === m.to) {
        const x = xs[m.from], right = m.from < n - 1 || n === 1;
        g.append(svgEl("circle", { cx: x, cy: y - 4, r: current ? 5 : 4, fill: color }));
        g.append(svgEl("text", { x: right ? x + 9 : x - 9, y: y, "text-anchor": right ? "start" : "end", fill: color }, m.label));
      } else {
        const x1 = xs[m.from], x2 = xs[m.to], dir = x2 > x1 ? 1 : -1;
        g.append(svgEl("line", { x1, x2: x2 - dir * 7, y1: y, y2: y, stroke: color, "stroke-width": current ? 2.2 : 1.5 }));
        g.append(svgEl("path", { d: `M${x2},${y} l${-dir * 9},-5 v10 z`, fill: color }));
        g.append(svgEl("text", { x: (x1 + x2) / 2, y: y - 6, "text-anchor": "middle", fill: color }, m.label));
      }
      svg.append(g);
    });
    box.replaceChildren(svg);
    say.replaceChildren(i ? inline(msgs[i - 1].note) : inline("Toca **Empezar** y avanza mensaje por mensaje."));
    prev.disabled = i === 0;
    next.disabled = i === msgs.length;
    next.textContent = i === 0 ? "Empezar" : i === msgs.length ? "Fin" : `Paso ${i + 1} de ${msgs.length}`;
    seg.replaceChildren(...b.scenarios.map((s, k) => {
      const tab = button("", s.name || `Escenario ${k + 1}`, () => { sc = k; i = 0; draw(); });
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(k === sc));
      return tab;
    }));
  }
  draw();
  return c;
}

// -- architecture diagram: layered top to bottom (a phone is tall), at most 3 boxes a row ---------------------------

export function layout(nodeCount, edges) {
  const forward = edges.filter((e) => e.from !== e.to);
  const out = Array.from({ length: nodeCount }, () => []);
  forward.forEach((e, k) => out[e.from].push(k));
  const state = new Array(nodeCount).fill(0), back = new Set(), order = [];
  const visit = (v) => {
    state[v] = 1;
    for (const k of out[v]) {
      const w = forward[k].to;
      if (state[w] === 1) back.add(k);
      else if (state[w] === 0) visit(w);
    }
    state[v] = 2;
    order.push(v);
  };
  for (let v = 0; v < nodeCount; v += 1) if (!state[v]) visit(v);
  const layer = new Array(nodeCount).fill(0);
  for (const v of order.reverse()) for (const k of out[v]) if (!back.has(k)) layer[forward[k].to] = Math.max(layer[forward[k].to], layer[v] + 1);
  const rows = [];
  const byLayer = [];
  layer.forEach((l, v) => (byLayer[l] ??= []).push(v));
  for (const group of byLayer.filter(Boolean)) for (let s = 0; s < group.length; s += 3) rows.push(group.slice(s, s + 3));
  return rows;
}

function wrap(text, width) {
  const words = String(text).split(/\s+/), lines = [];
  let line = "";
  for (const w of words) {
    if (line && (line + " " + w).length > width) { lines.push(line); line = w; } else line = line ? `${line} ${w}` : w;
  }
  if (line) lines.push(line);
  return lines.flatMap((l) => (l.length > width ? l.match(new RegExp(`.{1,${width}}`, "g")) : [l]));
}

function diagram(b) {
  const c = card(b.title, "diagram");
  const W = 320, GAP = 48, id = ++uid;
  const rows = layout(b.nodes.length, b.edges);
  const pos = [];
  let y = 6;
  for (const row of rows) {
    const cols = row.length, bw = Math.min(140, (W - 12 - (cols - 1) * 12) / cols);
    const per = Math.max(6, Math.floor((bw - 14) / 6.3));
    const sized = row.map((v) => wrap(b.nodes[v].label, per));
    const bh = Math.max(...sized.map((l) => l.length)) * 14 + 16;
    row.forEach((v, k) => { pos[v] = { x: ((k + 0.5) * W) / cols, y, w: bw, h: bh, lines: sized[k] }; });
    y += bh + GAP;
  }
  const H = y - GAP + 6;
  const svg = svgEl("svg", { class: "dia", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": b.title || "Diagrama" });
  const defs = svgEl("defs");
  for (const [name, color] of [["a", INK3], ["h", INK]]) {
    const m = svgEl("marker", { id: `${name}${id}`, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    m.append(svgEl("path", { d: "M0,0 L10,5 L0,10 z", fill: color }));
    defs.append(m);
  }
  svg.append(defs);
  const edgeGs = b.edges.map((e) => {
    const g = svgEl("g", { class: "el" });
    const s = pos[e.from], t = pos[e.to];
    let d, mx, my;
    if (t.y > s.y) {
      const y1 = s.y + s.h, y2 = t.y - 2, k = (y2 - y1) / 2;
      d = `M${s.x},${y1} C${s.x},${y1 + k} ${t.x},${y2 - k} ${t.x},${y2}`;
      mx = (s.x + t.x) / 2; my = (y1 + y2) / 2;
    } else if (t.y < s.y) {
      const side = s.x >= W / 2 ? 1 : -1, x1 = s.x + (side * s.w) / 2, x2 = t.x + (side * t.w) / 2;
      const out = (side > 0 ? Math.max(x1, x2) : Math.min(x1, x2)) + side * 22;
      d = `M${x1},${s.y + s.h / 2} C${out},${s.y + s.h / 2} ${out},${t.y + t.h / 2} ${x2 + side * 2},${t.y + t.h / 2}`;
      mx = out; my = (s.y + t.y + t.h) / 2;
    } else {
      const dir = t.x > s.x ? 1 : -1, x1 = s.x + (dir * s.w) / 2, x2 = t.x - (dir * t.w) / 2 - dir * 2;
      d = `M${x1},${s.y + s.h / 2} L${x2},${t.y + t.h / 2}`;
      mx = (x1 + x2) / 2; my = s.y + s.h / 2 - 6;
    }
    const path = svgEl("path", { d, fill: "none", stroke: INK3, "stroke-width": 1.4, "marker-end": `url(#a${id})` });
    g.append(path);
    if (e.label) {
      const w = e.label.length * 5.6 + 8;
      g.append(svgEl("rect", { x: mx - w / 2, y: my - 8, width: w, height: 14, rx: 7, fill: "#FFFFFF" }));
      g.append(svgEl("text", { x: mx, y: my + 2.5, "text-anchor": "middle" }, e.label));
    }
    svg.append(g);
    return { g, path, e };
  });
  const nodeGs = b.nodes.map((node, v) => {
    const p = pos[v], g = svgEl("g");
    const rect = svgEl("rect", { class: "box", x: p.x - p.w / 2, y: p.y, width: p.w, height: p.h, rx: 12, fill: "#F1EDE7", stroke: LINE });
    g.append(rect);
    p.lines.forEach((line, k) => g.append(svgEl("text", { x: p.x, y: p.y + 8 + 14 * (k + 1) - 3, "text-anchor": "middle" }, line)));
    svg.append(g);
    return { g, rect };
  });
  c.append(svg);
  if (!b.tour?.length) return c;
  const say = el("p", "say"), nav = el("div", "row2");
  let i = 0;
  const prev = button("btn btn-quiet", "Atrás", () => { i -= 1; draw(); });
  const next = button("btn btn-accent", "Recorrerlo", () => { i += 1; draw(); });
  nav.append(prev, next);
  c.append(say, nav);
  function draw() {
    const on = i ? new Set(b.tour[i - 1].nodes) : null;
    nodeGs.forEach(({ g, rect }, v) => {
      g.setAttribute("opacity", !on || on.has(v) ? 1 : 0.35);
      rect.setAttribute("fill", on?.has(v) ? ACCENT : "#F1EDE7");
      rect.setAttribute("stroke", on?.has(v) ? INK : LINE);
    });
    edgeGs.forEach(({ g, path, e }) => {
      const lit = on && on.has(e.from) && on.has(e.to);
      g.setAttribute("opacity", !on || lit ? 1 : 0.25);
      path.setAttribute("stroke", lit ? INK : INK3);
      path.setAttribute("stroke-width", lit ? 2.2 : 1.4);
      path.setAttribute("marker-end", `url(#${lit ? "h" : "a"}${id})`);
    });
    say.replaceChildren(i ? inline(b.tour[i - 1].note) : inline("Toca **Recorrerlo** para seguir el camino paso a paso."));
    prev.disabled = i === 0;
    next.disabled = i === b.tour.length;
    next.textContent = i === 0 ? "Recorrerlo" : i === b.tour.length ? "Fin" : `Paso ${i + 1} de ${b.tour.length}`;
  }
  draw();
  return c;
}

// -- the page -----------------------------------------------------------------------------------------------------

function header(data) {
  const head = el("header", "head");
  const sq = el("div", "isq");
  sq.append(icon("book"));
  const text = el("div");
  text.append(el("h1", null, data.title));
  text.append(el("div", "meta", [data.subject, `repaso de ${data.minutes} min`].filter(Boolean).join(" · ")));
  head.append(sq, text);
  return head;
}

function empty(app, title, line) {
  const box = el("div", "empty");
  box.append(el("b", null, title), el("span", null, line));
  app.replaceChildren(box);
}

export function render(app, data) {
  document.title = data.title || "Repaso";
  const parts = [header(data)];
  for (const block of data.blocks || []) {
    const make = BLOCKS[block.type];
    if (!make) continue;
    try { parts.push(make(block)); } catch (err) { console.error("block", block.type, err); }
  }
  if (score.total) {
    const s = card("Tu resultado", "score");
    s.classList.add("score");
    s.hidden = true;
    const meter = el("div", "meter");
    meter.append(el("i"));
    s.append(el("div", "big", ""), meter, el("p", "say-end prose"));
    score.card = s;
    parts.push(s);
  }
  if (data.sources?.length) {
    const s = card("De dónde sale", "sources");
    const list = el("ul", "sources");
    for (const src of data.sources) {
      const li = el("li");
      li.append(icon("file"));
      if (src.url?.startsWith("https://")) {
        const a = el("a", null, src.label);
        a.href = src.url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        li.append(a);
      } else li.append(el("span", null, src.label));
      list.append(li);
    }
    s.append(list);
    parts.push(s);
  }
  parts.push(el("p", "foot", "Vinci armó este repaso. Lo que respondas se queda en esta página."));
  app.replaceChildren(...parts);
  app.dataset.ready = "1";
}

async function main() {
  const app = document.getElementById("app");
  const payload = readFragment(location.hash);
  if (!payload) return empty(app, "Este enlace está incompleto", "Pídele a Vinci que te lo vuelva a mandar.");
  let data;
  try {
    data = await decode(payload);
  } catch {
    return empty(app, "No pude abrir este repaso", "El enlace se cortó. Pídele a Vinci que te lo vuelva a mandar.");
  }
  render(app, data);
}

if (typeof document !== "undefined") main();
