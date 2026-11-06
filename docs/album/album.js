// The album, as Vinci sends it on WhatsApp (espol_bot/album.py). The pack and the collection ride in the URL's
// fragment (#d=<base64url of raw DEFLATE JSON>); only the catalog, cards.json, comes from this site. A pack is
// opened the way of the design system's sheets: pull it up, then swipe each card away. Art with real faces is
// stored encrypted (scripts/album_card.py); the fragment's `k` opens it, so it never shows without Vinci's link.
// «Cambios» lists the cards others have repeated (`trade`) and opens WhatsApp with the «/cambio …» that asks for one.

const RL = { com: "Común", rare: "Rara", epic: "Épica", leg: "Legendaria" };
const TAG = { com: "COMUN", rare: "RARA", epic: "EPICA", leg: "★ LEGENDARIA ★" };
// Press Start 2P draws an accented capital as a small letter: the card's pixel text goes without accents, as in old
// games, except the Ñ.
const plain = (text) => String(text ?? "").normalize("NFD").replace(/(?<!N|n)[\u0300-\u036f]/g, "").normalize("NFC");
const OPENED = "album-opened";
const esc = (text) => String(text ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const pad = (n) => String(n).padStart(3, "0");
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const app = document.getElementById("app");
const SPARK = '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>';

export function readFragment(hash, key = "d") {
  for (const pair of hash.replace(/^#/, "").split(/[&?]/)) {
    if (pair.startsWith(`${key}=`)) return pair.slice(key.length + 1);
  }
  return "";
}

const bytesOf = (b64url) => Uint8Array.from(atob(b64url.replace(/-/g, "+").replace(/_/g, "/") +
  "=".repeat((4 - (b64url.length % 4)) % 4)), (c) => c.charCodeAt(0));

export async function decode(payload) {
  const bytes = bytesOf(payload);
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return JSON.parse(await new Response(stream).text());
}

export function initials(name) {
  const words = String(name).replace(/^(The|Los) /, "").split(/\s+/);
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase();
  const w = words[0];
  return w.length <= 5 && w === w.toUpperCase() ? w : w[0];
}

// Only the cards this person owns or is opening: one fetch each, decrypted once per page load.
async function unlock(data, cards) {
  if (!data.k || !crypto.subtle) return;
  const offered = (data.trade?.people || []).flatMap((p) => Object.keys(p.cards || {}));
  const wanted = new Set([...Object.keys(data.have || {}), ...(data.pack?.cards || []).map((e) => e.id), ...offered]);
  try {
    const key = await crypto.subtle.importKey("raw", bytesOf(data.k), "AES-GCM", false, ["decrypt"]);
    await Promise.all([...wanted].map(async (id) => {
      const c = cards.get(id);
      if (!c?.art) return;
      try {
        const sealed = new Uint8Array(await (await fetch(c.art)).arrayBuffer());
        const webp = await crypto.subtle.decrypt({ name: "AES-GCM", iv: sealed.slice(0, 12), additionalData: new TextEncoder().encode(id) },
          key, sealed.slice(12));
        c.src = URL.createObjectURL(new Blob([webp], { type: "image/webp" }));
      } catch { /* a wrong key or a missing file: the card keeps its initials */ }
    }));
  } catch { /* an invalid key */ }
}

function card(c, size = "", flag = "") {
  const src = c.src || c.img;
  const art = src ? `<img src="${esc(src)}" alt="">` : `<span class="ini">${esc(initials(c.name))}</span>`;
  return `<div class="vc t-${c.rarity} ${size}"><div class="art"><span class="no">Nº${pad(c.n)}</span>${flag}${art}</div>
    <div class="bd"><div class="nm">${esc(plain(c.name))}</div><div class="mt">${esc(plain(c.group))}</div></div><div class="rk"><span class="tag">${TAG[c.rarity]}</span></div></div>`;
}

const head = (title, meta) => `<header class="head"><div class="isq">${SPARK}</div><div><h1>${esc(title)}</h1><p class="meta">${esc(meta)}</p></div></header>`;

function opened() {
  try { return new Set(JSON.parse(localStorage.getItem(OPENED) || "[]")); } catch { return new Set(); }
}
function remember(id) {
  try { localStorage.setItem(OPENED, JSON.stringify([...opened(), id].slice(-50))); } catch { /* private mode */ }
}

function note(c, entry, have) {
  if (c.rarity === "leg") return "La carta más difícil del álbum.";
  if (!entry.new) return `Repetida: ya tienes ${have[c.id]}. Guárdala para cambiarla con un amigo.`;
  return "Nueva para tu álbum.";
}

function openPack(data, cards) {
  const pack = data.pack;
  const pulled = pack.cards.map((entry) => ({ entry, c: cards.get(entry.id) })).filter((p) => p.c);
  document.body.classList.add("opening");
  app.innerHTML = head(pack.gold ? "Tu sobre dorado" : pack.daily ? "Tu sobre del día" : pack.gift ? "Un sobre de regalo" : "Tu sobre", pack.reason) + `<section class="stage"><div class="ghost"></div><div class="sheet">
      <div class="stack">${pulled.map((p, i) => `<div class="slot" data-i="${i}">${card(p.c, "", p.entry.new ? '<span class="pill hi flag">Nueva</span>' : `<span class="pill flag">×${data.have[p.c.id] || 2}</span>`)}</div>`).reverse().join("")}</div>
      <div class="pack"><div class="pk"><div class="mark">V</div><span class="n3">${pulled.length} cartas</span>
        <h2>${pack.gold ? "Sobre dorado" : "Tu sobre"}<span class="s">${pack.daily ? "de hoy." : pack.gift ? "de regalo." : "de esta semana."}</span></h2><p class="why">${esc(pack.reason)}</p></div><span class="grab"></span></div>
      <div class="cap"><div class="t">Desliza el sobre hacia arriba</div><div class="h">Tus cartas están debajo.</div></div>
      <div class="foot"><div class="segs">${pulled.map(() => "<i></i>").join("")}</div><button class="btn btn-accent block" type="button">Pegar en mi álbum</button></div>
    </div></section>`;
  const packEl = app.querySelector(".pack"), cap = app.querySelector(".cap"), segs = [...app.querySelectorAll(".segs i")];
  const slots = pulled.map((_, i) => app.querySelector(`.slot[data-i="${i}"]`));
  const button = app.querySelector(".foot .btn");
  let top = 0, done = false;
  const pose = (k) => `translateY(${-k * 12}px) scale(${1 - k * 0.05})`;
  const restack = (anim) => slots.forEach((s, i) => {
    if (i < top) return;
    s.style.transition = anim ? "transform 240ms var(--ease-out)" : "none";
    s.style.zIndex = String(10 - (i - top));
    s.style.transform = pose(i - top);
  });
  restack(false);

  const say = () => {
    const { c, entry } = pulled[top];
    segs.forEach((s, i) => { s.classList.toggle("on", i < top); s.classList.toggle("cur", i === top); });
    const flag = entry.new ? '<span class="pill hi">Nueva</span>' : `<span class="pill">Ya tienes ${data.have[c.id] || 2}</span>`;
    cap.innerHTML = `<div class="t rise">${esc(c.name)}</div><div class="m rise"><span class="rp t-${c.rarity}">${RL[c.rarity]}</span>${flag}</div>
      <div class="h">${top < pulled.length - 1 ? "Desliza la carta para ver la siguiente." : esc(note(c, entry, data.have))}</div>`;
    if (c.rarity === "leg") navigator.vibrate?.([20, 50, 20]);
  };

  // The pack follows the finger up, 1:1; a flick is enough (Emil Kowalski's momentum rule).
  let sy = 0, dy = 0, ly = 0, lt = 0, v = 0, on = false;
  packEl.addEventListener("pointerdown", (e) => {
    if (done) return;
    on = true; packEl.setPointerCapture(e.pointerId);
    sy = ly = e.clientY; lt = e.timeStamp; dy = v = 0; packEl.style.transition = "none";
  });
  packEl.addEventListener("pointermove", (e) => {
    if (!on) return;
    const dt = e.timeStamp - lt; if (dt > 0) v = (e.clientY - ly) / dt;
    ly = e.clientY; lt = e.timeStamp; dy = e.clientY - sy;
    packEl.style.transform = `translateY(${dy < 0 ? dy : dy * 0.2}px)`;
  });
  const release = () => {
    if (!on) return;
    on = false;
    if (Math.abs(dy) < 5) return nudge();
    if (-dy > 110 || v < -0.11) return fly();
    packEl.style.transition = "transform 300ms var(--ease-out)"; packEl.style.transform = "none";
  };
  packEl.addEventListener("pointerup", release);
  packEl.addEventListener("pointercancel", release);
  async function nudge() {
    packEl.style.transition = "transform 200ms var(--ease-out)"; packEl.style.transform = "translateY(-18px)";
    await sleep(210);
    if (!on && !done) packEl.style.transform = "none";
  }
  setTimeout(() => { if (!done) nudge(); }, 900);
  async function fly() {
    done = true;
    navigator.vibrate?.(20);
    packEl.style.transition = "transform 320ms var(--ease-out)";
    packEl.style.transform = "translateY(-130%)";
    await sleep(320);
    packEl.remove();
    say();
  }

  slots.forEach((slot, i) => {
    let sx = 0, dx = 0, lx = 0, lt2 = 0, v2 = 0, held = false;
    slot.addEventListener("pointerdown", (e) => {
      if (!done || i !== top) return;
      held = true; slot.setPointerCapture(e.pointerId);
      sx = lx = e.clientX; lt2 = e.timeStamp; dx = v2 = 0; slot.style.transition = "none";
    });
    slot.addEventListener("pointermove", (e) => {
      if (!held) return;
      const dt = e.timeStamp - lt2; if (dt > 0) v2 = (e.clientX - lx) / dt;
      lx = e.clientX; lt2 = e.timeStamp; dx = e.clientX - sx;
      slot.style.transform = `translateX(${dx}px) rotate(${dx * 0.05}deg)`;
    });
    const up = () => {
      if (!held) return;
      held = false;
      if (Math.abs(dx) < 5) return fling(-1);
      if (Math.abs(dx) > 90 || Math.abs(v2) > 0.11) return fling(Math.sign(dx));
      slot.style.transition = "transform 300ms var(--ease-out)"; slot.style.transform = pose(0);
    };
    slot.addEventListener("pointerup", up);
    slot.addEventListener("pointercancel", up);
    function fling(dir) {
      slot.style.transition = "transform 280ms var(--ease-out), opacity 280ms var(--ease-out)";
      slot.style.transform = `translateX(${dir * 360}px) rotate(${dir * 14}deg)`;
      slot.style.opacity = "0";
      top++;
      if (top < pulled.length) { restack(true); say(); return; }
      segs.forEach((s) => { s.classList.add("on"); s.classList.remove("cur"); });
      const fresh = pulled.filter((p) => p.entry.new).length;
      cap.innerHTML = `<div class="t rise">${pulled.length} cartas, ${fresh === 1 ? "1 nueva" : `${fresh} nuevas`}</div>`;
      button.classList.add("on");
    }
  });
  button.addEventListener("click", () => {
    remember(pack.id);
    showAlbum(data, cards, true);
  });
}

const TRADES = "cambios";
const RANK = ["com", "rare", "epic", "leg"];
const byRarity = (dir) => (a, b) => dir * (RANK.indexOf(a.rarity) - RANK.indexOf(b.rarity)) || a.n - b.n;

// The cards this person lacks that someone else has repeated, each with who has it (data.trade, trades.market).
function wanted(data, cards) {
  const have = data.have || {}, found = new Map();
  for (const person of data.trade?.people || []) {
    for (const id of Object.keys(person.cards || {})) {
      const c = cards.get(id);
      if (!c || have[id]) continue;
      if (!found.has(id)) found.set(id, { c, owners: [] });
      found.get(id).owners.push(person.name);
    }
  }
  return [...found.values()].sort((a, b) => byRarity(-1)(a.c, b.c));
}

function tradeTab(data, cards, mine) {
  const list = wanted(data, cards);
  const repeats = mine.length
    ? `<div class="chips">${mine.map((c) => `<span class="pill">${esc(c.name)} ×${data.have[c.id]}</span>`).join("")}</div>`
    : '<p class="hint">Todavía no tienes repetidas, y solo se cambian las repetidas. Las que te salgan dos veces aparecen aquí.</p>';
  const grid = list.length
    ? `<div class="grid">${list.map(({ c, owners }) => {
        const who = owners.length > 1 ? `${owners.length} personas` : owners[0].split(" ")[0];
        return `<button class="cell own" type="button" data-want="${esc(c.id)}">${card(c, "s", `<span class="pill hi flag">${esc(plain(who))}</span>`)}</button>`;
      }).join("")}</div>`
    : '<p class="empty-state">Nadie tiene repetida una carta que te falte, por ahora.</p>';
  return `<section class="trade"><h2 class="sub">Tus repetidas</h2>${repeats}
    <h2 class="sub">Te faltan y alguien las tiene repetidas</h2>${grid}</section>`;
}

// The sheet for one wanted card: who to ask, which repeat to give, and a WhatsApp chat with «/cambio …» typed.
function offerSheet(data, cards, mine, id) {
  const entry = wanted(data, cards).find((w) => w.c.id === id);
  if (!entry) return;
  let owner = entry.owners[0], give = mine[0];
  const sheet = app.querySelector(".offer"), body = sheet.querySelector(".body");
  const text = () => `/cambio ${owner} ${give.name} por ${entry.c.name}`;
  const draw = () => {
    const chips = (items, on, attr) => `<div class="chips">${items.map((x) =>
      `<button class="chip" type="button" ${attr}="${esc(x.key)}" aria-pressed="${x.key === on}">${esc(x.label)}</button>`).join("")}</div>`;
    body.innerHTML = `<div class="pick"><div class="mini">${card(entry.c, "s")}</div><div><div class="t">${esc(entry.c.name)}</div>
        <div class="m"><span class="rp t-${entry.c.rarity}">${RL[entry.c.rarity]}</span></div>
        <p class="hint">${entry.owners.length > 1 ? "La tienen repetida varias personas: elige a quién pedírsela." : `${esc(owner)} la tiene repetida.`}</p></div></div>
      ${entry.owners.length > 1 ? `<h3 class="sub">Se la pides a</h3>${chips(entry.owners.map((o) => ({ key: o, label: o })), owner, "data-owner")}` : ""}
      ${give ? `<h3 class="sub">Das a cambio</h3>${chips(mine.map((c) => ({ key: c.id, label: `${c.name} ×${data.have[c.id]}` })), give.id, "data-give")}
        ${data.trade.wa ? `<a class="btn btn-accent block" href="https://wa.me/${esc(data.trade.wa)}?text=${encodeURIComponent(text())}">Pedir el cambio en WhatsApp</a>
        <p class="hint c">Se abre tu chat con Vinci con el mensaje listo: solo envíalo.</p>`
        : `<p class="hint c">Escríbele a Vinci: <b>${esc(text())}</b></p>`}`
      : '<p class="hint c">Necesitas una carta repetida para ofrecer a cambio.</p>'}
      <button class="btn btn-quiet block" type="button" data-close>Cerrar</button>`;
    body.querySelectorAll("[data-owner]").forEach((b) => b.addEventListener("click", () => { owner = b.dataset.owner; draw(); }));
    body.querySelectorAll("[data-give]").forEach((b) => b.addEventListener("click", () => { give = cards.get(b.dataset.give); draw(); }));
    body.querySelector("[data-close]").addEventListener("click", () => sheet.classList.remove("on"));
  };
  draw();
  sheet.classList.add("on");
}

function showAlbum(data, cards, fresh, tab) {
  document.body.classList.remove("opening");
  const all = [...cards.values()];
  const collections = [...new Set(all.map((c) => c.collection))];
  const names = Object.fromEntries((data.collections || []).map((c) => [c.id, c.name]));
  if (!(collections.includes(tab) || (tab === TRADES && data.trade))) tab = collections[0];
  const have = data.have || {};
  const owned = all.filter((c) => have[c.id]).length;
  const repeats = all.reduce((sum, c) => sum + Math.max(0, (have[c.id] || 0) - 1), 0);
  const newIds = new Set(fresh && data.pack ? data.pack.cards.filter((e) => e.new).map((e) => e.id) : []);
  const list = all.filter((c) => c.collection === tab).sort((a, b) => a.n - b.n);
  const mine = all.filter((c) => (have[c.id] || 0) > 1).sort(byRarity(1));
  app.innerHTML = head("Tu álbum", `${owned} de ${all.length} cartas`) + `
    <div class="tiles"><div class="tile hi"><div class="n">${owned}</div><div class="l">de ${all.length} cartas</div></div>
      <div class="tile"><div class="n">${newIds.size}</div><div class="l">${newIds.size === 1 ? "nueva hoy" : "nuevas hoy"}</div></div>
      <div class="tile"><div class="n">${repeats}</div><div class="l">${repeats === 1 ? "repetida" : "repetidas"}</div></div></div>
    <div class="tabs" role="tablist">${collections.map((id) => {
      const total = all.filter((c) => c.collection === id), got = total.filter((c) => have[c.id]).length;
      return `<button class="tab" role="tab" type="button" data-t="${esc(id)}" aria-selected="${id === tab}">${esc(names[id] || id)} ${got}/${total.length}</button>`;
    }).join("")}${data.trade ? `<button class="tab" role="tab" type="button" data-t="${TRADES}" aria-selected="${tab === TRADES}">🔁 Cambios ${wanted(data, cards).length}</button>` : ""}</div>
    ${tab === TRADES ? tradeTab(data, cards, mine) : `<div class="grid">${list.map((c) => {
      if (!have[c.id]) return `<div class="cell empty">${pad(c.n)}</div>`;
      const flag = newIds.has(c.id) ? '<span class="pill hi flag">Nueva</span>' : have[c.id] > 1 ? `<span class="pill flag">×${have[c.id]}</span>` : "";
      return `<button class="cell own ${newIds.has(c.id) ? "fresh" : ""}" type="button" data-id="${esc(c.id)}">${card(c, "s", flag)}</button>`;
    }).join("")}</div>`}
    ${data.pack && !fresh ? '<button class="btn btn-quiet block" type="button" data-again>Abrir el sobre otra vez</button>' : ""}
    <div class="zoom" aria-hidden="true"><div class="big"></div></div>
    <div class="offer" role="dialog" aria-label="Pedir un cambio"><div class="body"></div></div>`;
  app.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => showAlbum(data, cards, fresh, b.dataset.t)));
  app.querySelectorAll("[data-want]").forEach((b) => b.addEventListener("click", () => offerSheet(data, cards, mine, b.dataset.want)));
  const offer = app.querySelector(".offer");
  offer.addEventListener("click", (e) => { if (e.target === offer) offer.classList.remove("on"); });
  const zoom = app.querySelector(".zoom");
  app.querySelectorAll(".cell.own[data-id]").forEach((b) => b.addEventListener("click", () => {
    const c = cards.get(b.dataset.id), big = zoom.querySelector(".big");
    big.classList.toggle("wide", Boolean(c.wide && c.src));
    big.innerHTML = card(c);
    zoom.classList.add("on");
  }));
  zoom.addEventListener("click", () => zoom.classList.remove("on"));
  app.querySelector("[data-again]")?.addEventListener("click", () => openPack(data, cards));
}

async function main() {
  let data, catalog;
  try {
    const payload = readFragment(location.hash);
    [data, catalog] = await Promise.all([payload ? decode(payload) : null, fetch("cards.json").then((r) => r.json())]);
  } catch {
    data = null;
  }
  if (!data || !catalog) {
    app.innerHTML = head("Tu álbum", "Vinci") + '<p class="empty-state">Abre tu álbum desde el botón que Vinci te manda en WhatsApp.</p>';
    return;
  }
  data.collections = catalog.collections;
  const cards = new Map(catalog.cards.map((c) => [c.id, c]));
  await unlock(data, cards);
  if (data.pack && !opened().has(data.pack.id)) openPack(data, cards);
  else showAlbum(data, cards, false, readFragment(location.hash, "t"));
}

if (typeof document !== "undefined" && document.getElementById("app")) main();
