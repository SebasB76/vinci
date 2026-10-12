# Feature map

Every feature, where the captain reaches it, the code behind it and how an agent verifies it.
"Model" says whether the feature calls the LLM (costs tokens) or is a fixed script.
User-facing detail lives in `docs/guia/`; the last column names the file and its section.

## Telegram vs WhatsApp

`[channels] telegram = false` (the live setting) turns Telegram off: Vinci talks only on WhatsApp and does the
subject bots' work itself. The Telegram column is what `telegram = true` brings back.

| Feature | Telegram | WhatsApp | Model | Guide (`docs/guia/`) |
|---|---|---|---|---|
| Canvas alerts, reminders, 07:00 summary | Vinci's chat, with buttons | captain's DM, a poll instead of buttons; friends get their own | no | `uso.md` «El resumen de las 7:00» |
| «🎓 Consultar con …» handoff | button under each alert | not needed: reply to the alert, Vinci answers with that subject | yes | `funciones.md` |
| «✅ Ya lo entregué» | button | poll | no | `funciones.md` |
| Dashboard of deliverables | «📋 Entregas» menu button, Mini App | `/entregas` → link button; ticks come back through the relay | no | `uso.md` «El dashboard de entregas» |
| To-do list («anota: …») | card with «✅ Hecho» | poll | yes (parsing), no (reminders) | `funciones.md` |
| Grade calculator | ask Vinci or a subject bot; «✅ Guardar esquema» | ask Vinci; «Guardar esquema» poll | yes, the math is a script | `uso.md` «La calculadora de notas» |
| Team of subject bots | «arma mi equipo» → «➕ Crear» | not needed: one Vinci for every subject | no | `instalacion.md` «7. Arma tu equipo de bots desde el chat» |
| Brief before each class | subject bot, 30 min before | Vinci's DM, 30 min before (a system task Vinci answers) | yes | `whatsapp.md` «El brief antes de cada clase» |
| Subject notebook (notes, photos, voice) | subject bot chat | Vinci's DM; the subject named, replied to, or in class by the schedule | yes | `whatsapp.md` «Tus materias, en un solo chat» |
| Questions on course material, with citations | Vinci or subject bot | Vinci | yes; citations checked by a script | `uso.md` «El material de cada materia» |
| Hand in handwritten work | photos to the subject bot → «📤 Entregar» | photos to Vinci → «📤 Entregar» poll | yes (PDF built by a script) | `uso.md` «Entregar una actividad hecha a mano» |
| `/quiz <tema>` | subject bot (Vinci hands it over), quiz polls | Vinci, polls in the captain's DM | yes (questions), no (scoring) | `funciones.md` «Quiz con `/quiz`» |
| Académico (GPA, history, grades, timetables) | ask Vinci; «🎓 Conectar Académico» Mini App the first time | ask Vinci in the DM; the same button as a link | yes (answers), no (sign-in) | `uso.md` «Tu Académico de ESPOL» |
| Assignment detail (annexes, aula rubric, local dates) | ask Vinci or a subject bot | ask Vinci | yes | `uso.md` «El material de cada materia» |
| DSpace past exams | ask Vinci or a subject bot | ask Vinci | yes | `uso.md` «Exámenes anteriores (DSpace)» |
| Schedule from a screenshot | screenshot to Vinci → «Guardar» | screenshot to Vinci → «✅ Guardar horario» poll | yes (reading), no (saving) | `instalacion.md` «8. Mándale tu horario a Vinci» |
| Class notes folder (`//vinci`) | answers and summaries in the subject bot chat | answers and summaries in Vinci's DM | yes | `uso.md` «Tus apuntes de clase» |
| Slide decks (.pptx) | ask Vinci or a subject bot | ask Vinci | yes | `funciones.md` |
| `/estado` | Vinci | Vinci (DM only) | no | `uso.md` «El estado del sistema» |
| `/token` new Canvas token | Mini App form | guide image + link button, back through the relay | no | `uso.md` «Token nuevo desde Telegram (`/token`)» |
| `/start` | every bot | Vinci | no | `uso.md` «Comandos» |
| Groups («@vinci activa este grupo») | not available | yes; answers whoever mentions it, by name, with no unasked reminders; ignores stickers; starts over after 4 h idle | yes | `whatsapp.md` «Vinci en WhatsApp» |
| A Vinci per friend (`/amigo agregar`) | not available | yes | no (setup), yes (answers) | `whatsapp.md` «Vinci en WhatsApp» |
| Voice notes and audio files | transcribed when Hermes can | DM: voice notes and audio files (.m4a); groups: voice notes that say «Vinci» or reply to Vinci, from the captain or a friend with a Vinci | no (transcription, local Whisper) | `whatsapp.md` «Vinci en WhatsApp» |

## Code and verification

| Feature | Code | Verify |
|---|---|---|
| Alerts, reminders, summary | `src/espol_bot/poller.py`, `priority.py`, `messages.py` | `vinci-check status` (poll age); `espol-bot resumen` sends the summary for real |
| Buttons (all) | `src/espol_bot/botones.py`, `hermes/plugins/vinci-botones/` | `vinci-check vote "<option>"` on a harmless poll (`press` with Telegram on) |
| Dashboard | `src/espol_bot/dashboard.py`, `docs/dashboard/` | `vinci-check page dashboard` |
| To-do list | `src/espol_bot/store.py`, `herramientas.py` | `vinci-check say "¿qué tengo esta semana?"` (uses the model) |
| Grade calculator | `src/espol_bot/grades.py` | ask «¿cómo voy en Estadística?» through `chat` (uses the model) |
| Team of subject bots | `src/espol_bot/equipo.py`, `materias.py` | `vinci-check bots`; never press «➕ Crear» to test |
| Class briefs | `src/espol_bot/agenda.py` (`run_vinci` without Telegram), `horario.py`, `relay.queue_turn` | after a class's brief time, `vinci-check whatsapp --chat dm` shows the «[Tarea del sistema …]» turn and the brief |
| Notebook | `src/espol_bot/cuaderno.py`; Vinci's tools in `_subject_work_tools` (`herramientas.py`) | `vinci-check say "¿qué hay en el cuaderno de <materia>?"` (uses the model) |
| Material and citations | `src/aula_core/materials.py`, `search.py`, `src/espol_bot/citations.py`, `libros.py` | a material question through `chat`; check the cited file and page |
| Handwritten hand-in | `src/espol_bot/submission.py` | E2E only: a real hand-in uploads to Canvas |
| Quiz | `src/espol_bot/quiz.py`, `hermes/*/quiz/` | `chat <subject bot> "/quiz <tema>"` (uses the model) |
| Académico | `src/espol_bot/portal_login.py`, `academic_portal.py`, `docs/academico/` | `espol-bot academico` (the copy, read-only); never trigger a new sign-in to test |
| Assignment detail | `ver_tarea` in `herramientas.py`, `src/aula_core/queries.py`, `materials.py` | ask «¿qué pide <tarea>?» through `chat`; check annexes, rubric and dates (uses the model) |
| DSpace | `src/aula_core/dspace.py` | ask for past exams through `chat` (uses the model) |
| Schedule | `src/espol_bot/horario.py` | `chat <subject bot> /start` |
| Class notes | `src/espol_bot/notes.py` | `bot.log` in the data folder (the E2E no longer covers it) |
| Slides | `src/espol_bot/diapositivas.py` | ask for a short deck through `chat` (uses the model) |
| `/estado` | `src/espol_bot/health.py` | `vinci-check smoke` runs it as the captain's WhatsApp would get it |
| `/token` and the token chain | `src/espol_bot/token_form.py`, `token_renewal.py`, `docs/token/` | `vinci-check page token`; `vinci-check status` (chain age) |
| WhatsApp, groups, polls, voice | `src/espol_bot/whatsapp.py`, `hermes/plugins/vinci-whatsapp/`, `hermes/whatsapp/` | `vinci-check whatsapp --chat dm\|group`; voice: the turn starts with «🎙️» and the transcript |
| Friends | `src/espol_bot/amigos.py`, `hermes/amigo/` | `vinci-check whatsapp --profile amigo-<name>` (their private chat) |
| Relay | `src/espol_bot/relay.py`, `relay/worker.js` | `espol-bot whatsapp-rele` shows pending answers |
| Bot personalities | `hermes/vinci/`, `hermes/materia/`, `hermes/amigo/` (`SOUL.md`, `SKILL.md`) | a short `chat`; read the tone |

## Flows with several steps

- [`token.md`](token.md): a new Canvas token from Telegram or WhatsApp.
- [`dashboard.md`](dashboard.md): the dashboard from the menu button or `/entregas`.
- [`academico.md`](academico.md): connecting ESPOL's Académico from «🎓 Conectar Académico».
