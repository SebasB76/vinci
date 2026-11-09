// «Todo lo que hace Vinci». The link's fragment may carry Vinci's WhatsApp number (#wa=593…), so a tap on an example
// opens the chat with it typed, and the features new in this release (n=id,id), marked «Nuevo».
const TOPICS = [
  { id: "aula", name: "Tu aula", items: [
    { id: "avisos", emo: "🔔", title: "Avisos del aula", text: "Tareas nuevas, cambios de fecha, anuncios y notas, con el comentario del profe y la rúbrica.", ask: "¿Qué hay de nuevo en el aula?" },
    { id: "semana", emo: "📋", title: "Tu semana", text: "Lo que vence, en orden: primero lo urgente y lo que más pesa en tu nota. Con un panel donde marcas lo entregado.", ask: "¿Qué tengo esta semana?" },
    { id: "resumen", emo: "☀️", title: "El resumen de las 7:00", text: "Cada mañana: tus entregas, el calendario de la semana y los feriados de ESPOL.", how: "Te llega solo, cada día." },
    { id: "lista", emo: "📌", title: "Tu lista de pendientes", text: "Lo que el aula no trae: lecturas, trámites, lo que el profe dijo en clase. Te lo recuerda antes.", ask: "Anota: leer el capítulo 3 de Física para el viernes" },
  ] },
  { id: "entregas", name: "Entregar", items: [
    { id: "archivos", emo: "📤", title: "Entrega tus archivos", text: "Mándale tu Word, ZIP o PDF y dile en qué tarea va. Lo sube al aula cuando votas «Entregar».", ask: "Entrégalo en el deber 3", how: "Manda el archivo y escribe esto." },
    { id: "fotos", emo: "📸", title: "Fotos de tu deber a PDF", text: "Las fotos de las hojas se vuelven un PDF, una página por foto, listo para el aula.", ask: "Súbelo al deber 3", how: "Manda las fotos y escribe esto." },
    { id: "grupo-entrega", emo: "👥", title: "Entrega desde el grupo", text: "Responde al archivo que mandó tu compañero. Votas por privado y Vinci avisa en el grupo.", ask: "@vinci sube esto al informe final", how: "Responde al archivo en el grupo." },
  ] },
  { id: "notas", name: "Notas", items: [
    { id: "calculadora", emo: "📊", title: "Cuánto necesitas", text: "Aplica los pesos de cada materia a tus notas y te dice cuánto llevas y qué te falta para pasar.", ask: "¿Cuánto necesito en el final para pasar Cálculo?" },
    { id: "curso", emo: "📈", title: "Tu nota frente al curso", text: "Cuando sale una nota, te dice el promedio del curso, la más alta y la más baja.", how: "Llega con el aviso de la nota." },
  ] },
  { id: "estudiar", name: "Estudiar", items: [
    { id: "repaso", emo: "📚", title: "Repasos interactivos", text: "Una página para el tema: explicación, gráficos que mueves, ejercicios paso a paso y un quiz.", ask: "Ármame un repaso de la distribución normal para la lección" },
    { id: "material", emo: "📄", title: "Pregúntale a tu material", text: "Busca en las diapositivas y PDFs de tu materia y te dice de qué archivo y página sale.", ask: "¿Qué dice el material de Redes sobre TCP?" },
    { id: "quiz", emo: "📝", title: "Quiz de tu material", text: "De 3 a 5 preguntas con encuestas. Al votar te dice si acertaste y por qué.", ask: "Hazme un quiz de derivadas" },
    { id: "examenes", emo: "🗂️", title: "Exámenes anteriores", text: "Busca exámenes de otros años en el repositorio de ESPOL y te ayuda a resolverlos.", ask: "Búscame exámenes anteriores de Física" },
    { id: "sesion", emo: "⏱️", title: "Sesión de estudio", text: "Arma un plan con el tiempo que tienes, con tus dudas y lo que vence.", ask: "Tengo 20 minutos para Cálculo" },
    { id: "pdf", emo: "🖼️", title: "Resúmenes y diapositivas", text: "Un resumen en PDF o una presentación de un tema, con las fuentes de tu material.", ask: "Hazme un resumen en PDF de la unidad 2 de Estadística" },
    { id: "audio", emo: "🔊", title: "Respuestas en audio", text: "Si prefieres escuchar, te contesta con una nota de voz.", ask: "Respóndeme por audio" },
  ] },
  { id: "academico", name: "Académico", items: [
    { id: "promedio", emo: "🎓", title: "Promedio e historial", text: "Tu promedio, tus materias aprobadas, tus horarios de clases y de exámenes, del Académico.", ask: "¿Cuál es mi promedio?" },
    { id: "plan", emo: "🧭", title: "Qué materias tomar", text: "Con tu malla: lo que ya puedes tomar, lo que va junto y lo que te falta.", ask: "¿Qué materias puedo tomar el próximo semestre?" },
    { id: "calendario", emo: "🗓️", title: "El calendario de ESPOL", text: "Feriados, inicio y fin de clases, y cuándo son los exámenes.", ask: "¿Cuándo terminan las clases?" },
  ] },
  { id: "grupos", name: "Grupos", items: [
    { id: "recordatorios", emo: "⏰", title: "Recordatorios para todos", text: "Vinci avisa en el grupo a la hora que digas.", ask: "@vinci recuérdanos el viernes a mediodía que hay que entregar el informe" },
    { id: "reparto", emo: "🤝", title: "Quién hace qué", text: "Guarda el reparto del trabajo y lo recuerda cuando preguntan.", ask: "@vinci quedamos en que yo hago la intro y Ana el análisis" },
    { id: "avisos-grupo", emo: "📣", title: "Avisos de clase en el grupo", text: "Antes de cada clase: el aula, el enlace si es virtual y lo que vence.", ask: "@vinci activa los avisos" },
  ] },
  { id: "album", name: "Álbum", items: [
    { id: "sobres", emo: "🎴", title: "Tu álbum de cartas", text: "Ganas sobres al entregar a tiempo y al sacar 8/10 o más en lecciones y exámenes.", ask: "Muéstrame mi álbum" },
    { id: "cambios", emo: "🔁", title: "Cambios y ranking", text: "Cambia repetidas con tus amigos, canjea 3 por un sobre y mira el ranking.", how: "En tu álbum, en «Cambios» y «Ranking»." },
  ] },
];

const params = new URLSearchParams(location.hash.slice(1));
const wa = (params.get("wa") || "").replace(/\D/g, "");
const fresh = new Set((params.get("n") || "").split(",").filter(Boolean));

const ICONS = {
  send: '<path d="M4 12l16-8-6 16-2.5-6.5z"/><path d="M11.5 13.5L20 4"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2.5"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
};
const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
const esc = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function feature(f, inNews = false) {  // in the «Nuevo» section every card is new: no tag there
  const tag = !inNews && fresh.has(f.id) ? ' <span class="pill hi">Nuevo</span>' : "";
  const ask = f.ask
    ? (wa
      ? `<a class="ask" href="https://wa.me/${wa}?text=${encodeURIComponent(f.ask)}">
           <span>«${esc(f.ask)}»</span>${icon("send")}</a>`
      : `<button class="ask" type="button" data-copy="${esc(f.ask)}"><span>«${esc(f.ask)}»</span>${icon("copy")}</button>`)
    : "";
  return `<article class="card feat${tag ? " new" : ""}">
      <div class="row"><div class="emo" aria-hidden="true">${f.emo}</div>
        <div class="x"><h3>${esc(f.title)}${tag}</h3><p>${esc(f.text)}</p></div></div>
      ${ask}${f.how ? `<p class="how">${esc(f.how)}</p>` : ""}
    </article>`;
}

function render() {
  const news = TOPICS.flatMap((t) => t.items).filter((f) => fresh.has(f.id));
  const topics = news.length ? [{ id: "nuevo", name: "Nuevo", items: news }, ...TOPICS] : TOPICS;
  const app = document.getElementById("app");
  app.innerHTML = `
    <header class="head"><div class="isq" aria-hidden="true">✨</div>
      <div><h1>Todo lo que hace Vinci</h1>
        <p class="meta">${wa ? "Toca un ejemplo y se lo mandas a Vinci." : "Toca un ejemplo para copiarlo."}</p></div></header>
    <nav class="chips" aria-label="Temas">
      ${topics.map((t, i) => `<button class="chip" type="button" data-to="${t.id}"${i ? "" : ' aria-current="true"'}>${esc(t.name)}</button>`).join("")}
    </nav>
    ${topics.map((t) => `<section class="topic" id="${t.id}"><h2>${esc(t.name)}</h2>
      ${t.items.map((f) => feature(f, t.id === "nuevo")).join("")}</section>`).join("")}
    <p class="foot">Vinci lee tu aula virtual y tu Académico de ESPOL. Solo entrega o guarda algo cuando tú lo votas.</p>`;

  const chips = [...app.querySelectorAll(".chip")];
  const mark = (id) => chips.forEach((c) => c.setAttribute("aria-current", String(c.dataset.to === id)));
  app.addEventListener("click", async (e) => {
    const chip = e.target.closest(".chip");
    if (chip) {
      mark(chip.dataset.to);
      const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
      document.getElementById(chip.dataset.to).scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
      chip.scrollIntoView({ inline: "nearest", block: "nearest" });
      return;
    }
    const copy = e.target.closest("[data-copy]");
    if (copy) {
      try { await navigator.clipboard.writeText(copy.dataset.copy); } catch { return; }
      copy.dataset.done = "";
      copy.querySelector("svg").outerHTML = icon("check");
      setTimeout(() => { delete copy.dataset.done; copy.querySelector("svg").outerHTML = icon("copy"); }, 1600);
    }
  });
  // The chip of the topic on screen lights up while scrolling.
  const seen = new IntersectionObserver((entries) => {
    const top = entries.filter((x) => x.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (top) mark(top.target.id);
  }, { rootMargin: "-70px 0px -60% 0px" });
  app.querySelectorAll(".topic").forEach((s) => seen.observe(s));
}

render();
