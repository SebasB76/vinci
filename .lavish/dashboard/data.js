// Fictional snapshot: the same subjects as the E2E test. In the real Mini App Vinci would put this JSON,
// compressed, after the # of the menu button's URL on every poll.
window.SNAPSHOT = {
  generated: "lun 5 oct · 08:20",
  passing: 60,
  // term_start comes from the aula; Canvas also has the term's end_at, which Vinci does not store yet.
  semester: { name: "II PAO 2026", start: "2026-09-24T00:00", end: "2027-01-15T23:59", now: "2026-10-05T08:20" },
  status: { ok: true, poll: "hace 12 min", token: "22 min", chain: "sana" },
  nextClass: { code: "CCPG1055", start: "09:00", end: "11:00", room: "LAB 11C", inMin: 40,
               brief: "Repaso de consenso con Raft. Vence el jueves: control de lectura 5." },
  subjects: [
    { code: "ESTG1034", name: "Estadística", avatar: "book.jpg", bot: "vinci_estadistica_bot",
      components: [["Lección 1", 15, 45], ["Taller 1", 10, 60], ["Deberes", 10, 45],
                   ["Examen del segundo parcial", 35, null], ["Taller 2", 10, null], ["Proyecto", 20, null]],
      weak: ["intervalos de confianza", "prueba t"], doubts: ["¿Cuándo uso t y cuándo z?"],
      quiz: { topic: "prueba t", score: 2, of: 5, when: "hace 2 días" } },
    { code: "ADSG1026", name: "Ciencias de la Sostenibilidad", avatar: "sprout.jpg", bot: "vinci_ciencias_bot",
      components: [["Ensayo 1", 25, 64], ["Ensayo 2", 25, null], ["Examen final", 50, null]],
      weak: ["huella hídrica"], doubts: [],
      quiz: { topic: "ODS", score: 4, of: 5, when: "hace 5 días" } },
    { code: "SOFG1007", name: "Ingeniería de Software I", avatar: "robot.jpg", bot: "vinci_ingenieria_software_i_bot",
      components: [["Avance 1 del proyecto", 15, 90], ["Lecciones", 15, 86], ["Avance 2 del proyecto", 15, null],
                   ["Avance final", 25, null], ["Examen", 30, null]],
      weak: ["diagramas de secuencia"], doubts: [],
      quiz: { topic: "patrones de diseño", score: 5, of: 5, when: "ayer" } },
    { code: "CCPG1041", name: "Dirección de Proyectos Informáticos", avatar: "builder.jpg", bot: "vinci_direccion_proyectos_bot",
      components: [["Talleres", 20, 75], ["Lección", 20, 67], ["Examen", 40, null], ["Proyecto", 20, null]],
      weak: ["ruta crítica"], doubts: ["¿La holgura total incluye la libre?"],
      quiz: { topic: "ruta crítica", score: 3, of: 5, when: "hace 3 días" } },
    { code: "CCPG1055", name: "Sistemas Distribuidos", avatar: "server.jpg", bot: "vinci_sistemas_distribuidos_bot",
      components: [], weak: ["teorema CAP"], doubts: ["¿Raft necesita reloj sincronizado?", "¿Qué pasa si se cae el líder?"],
      quiz: { topic: "Raft", score: 2, of: 4, when: "hoy" } },
  ],
  // Already in the 7:00 summary's order: what is due within 24 h first, then what weighs most in the grade.
  deliverables: [
    { id: 1, code: "ESTG1034", title: "Taller 2", due: "hoy 23:59", day: 0, hours: 15, weight: 10, kind: "tarea" },
    { id: 2, code: "ADSG1026", title: "Ensayo 2: huella hídrica", due: "lun 12 oct", day: 7, hours: 183, weight: 25, kind: "tarea" },
    { id: 3, code: "SOFG1007", title: "Avance 2 del proyecto", due: "vie 23:59", day: 4, hours: 111, weight: 15, kind: "tarea" },
    { id: 4, code: "CCPG1041", title: "Acta de constitución", due: "mié 23:59", day: 2, hours: 63, weight: 5, kind: "tarea" },
    { id: 5, code: "CCPG1055", title: "Control de lectura 5", due: "jue 10:00", day: 3, hours: 49, weight: 2, kind: "cuestionario",
      quiz: "10 preguntas · 20 min · 1 intento · abre jue 10:00" },
    { id: 6, code: "ESTG1034", title: "Estudiar el cap. 3", due: "vie", day: 4, hours: 100, weight: null, kind: "pendiente" },
    { id: 7, code: null, title: "Pedir el certificado de matrícula", due: "mié", day: 2, hours: 60, weight: null, kind: "pendiente" },
    { id: 8, code: "ESTG1034", title: "Proyecto final", due: "vie 8 ene", day: 95, hours: 2295, weight: 20, kind: "tarea" },
    { id: 9, code: "SOFG1007", title: "Avance final del proyecto", due: "lun 11 ene", day: 98, hours: 2367, weight: 25, kind: "tarea" },
  ],
  news: [
    { icon: "📢", code: "ESTG1034", kind: "Anuncio", text: "La lección 2 pasa al lunes 12", when: "hace 2 h" },
    { icon: "📄", code: "CCPG1055", kind: "Material", text: "Semana 6 – Raft.pdf", when: "ayer" },
    { icon: "📝", code: "SOFG1007", kind: "Nota", text: "Avance 1 del proyecto: 90/100", when: "ayer" },
    { icon: "🗓️", code: "CCPG1041", kind: "Cambio de fecha", text: "Acta de constitución: del lunes al miércoles", when: "sáb" },
  ],
  days: ["lun 5", "mar 6", "mié 7", "jue 8", "vie 9", "sáb 10", "dom 11"],
  classes: [
    { code: "CCPG1055", day: 0, start: "09:00", end: "11:00", room: "LAB 11C" },
    { code: "CCPG1041", day: 0, start: "14:30", end: "16:30", room: "16C-104" },
    { code: "SOFG1007", day: 1, start: "09:00", end: "11:00", room: "11A-201" },
    { code: "ESTG1034", day: 1, start: "11:30", end: "13:00", room: "A105" },
    { code: "CCPG1055", day: 2, start: "09:00", end: "11:00", room: "LAB 11C" },
    { code: "CCPG1041", day: 2, start: "14:30", end: "16:30", room: "16C-104" },
    { code: "SOFG1007", day: 3, start: "09:00", end: "11:00", room: "11A-201" },
    { code: "ADSG1026", day: 3, start: "16:30", end: "18:00", room: "15A-102" },
    { code: "ESTG1034", day: 4, start: "11:30", end: "13:00", room: "A105" },
  ],
};

// The grade calculator's numbers for one subject: average over what is graded and what is needed in the rest.
window.grade = function (subject, overrides = {}) {
  const parts = subject.components;
  if (!parts.length) return { state: "none" };
  let earned = 0, graded = 0, simulated = 0;
  for (const [name, weight, score] of parts) {
    if (score != null) { earned += weight * score / 100; graded += weight; }
    else if (overrides[name] != null) simulated += weight * overrides[name] / 100;
  }
  const rest = 100 - graded, pass = window.SNAPSHOT.passing;
  const avg = graded ? earned / graded * 100 : null;
  const need = rest ? Math.max(0, (pass - earned) / rest * 100) : null;
  const state = need > 75 || (avg != null && need > avg + 12) ? "bad" : need >= 55 ? "warn" : "ok";
  return { avg, graded, need, earned, rest, final: earned + simulated, state };
};

window.subjectOf = (code) => window.SNAPSHOT.subjects.find((s) => s.code === code);
window.STATE_LABEL = { ok: "Vas bien", warn: "Atento", bad: "En riesgo", none: "Sin esquema de notas" };

document.documentElement.dataset.theme = new URLSearchParams(location.search).get("theme")
  || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

// Mockup only: what the real button would do (open a chat, send a command to Vinci).
window.toast = function (text) {
  let el = document.querySelector(".toast");
  if (!el) { el = document.createElement("div"); el.className = "toast"; el.setAttribute("role", "status"); document.body.append(el); }
  el.textContent = text; el.classList.add("show");
  clearTimeout(el._t); el._t = setTimeout(() => el.classList.remove("show"), 2200);
};
window.fmt = (n) => (n == null ? "—" : Math.round(n).toString());

// How far into the term the snapshot is: the week number, the share of days gone and the weeks left.
window.semester = function () {
  const m = window.SNAPSHOT.semester, day = 864e5;
  const start = new Date(m.start), end = new Date(m.end), now = new Date(m.now);
  const total = (end - start) / day, gone = (now - start) / day;
  return { name: m.name, start, end, now, pct: Math.round(gone / total * 100), week: Math.floor(gone / 7) + 1,
           weeks: Math.ceil(total / 7), weeksLeft: Math.ceil((total - gone) / 7), daysLeft: Math.ceil(total - gone), total };
};
window.dueDate = (d) => new Date(new Date(window.SNAPSHOT.semester.now).getTime() + d.day * 864e5);
