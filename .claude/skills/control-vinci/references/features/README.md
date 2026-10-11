# Feature map

Every feature, where the captain reaches it, the code behind it and how an agent verifies it.
"Model" says whether the feature calls the LLM (costs tokens) or is a fixed script.
User-facing detail lives in `README.md`; search it for the section named in the last column.

## Telegram vs WhatsApp

| Feature | Telegram | WhatsApp | Model | README section |
|---|---|---|---|---|
| Canvas alerts, reminders, 07:00 summary | Vinci's chat, with buttons | captain's DM, a poll instead of buttons; friends get their own | no | «El resumen de las 7:00» |
| «🎓 Consultar con …» handoff | button under each alert | not available (subject bots live on Telegram) | yes | «Qué hace» |
| «✅ Ya lo entregué» | button | poll | no | «Qué hace» |
| Dashboard of deliverables | «📋 Entregas» menu button, Mini App | `/entregas` → link button; ticks come back through the relay | no | «El dashboard de entregas» |
| To-do list («anota: …») | card with «✅ Hecho» | poll | yes (parsing), no (reminders) | «Qué hace» |
| Grade calculator | ask Vinci or a subject bot; «✅ Guardar esquema» | ask Vinci; «Guardar esquema» poll | yes, the math is a script | «La calculadora de notas» |
| Team of subject bots | «arma mi equipo» → «➕ Crear» | not available | no | «Arma tu equipo de bots» |
| Brief before each class | subject bot, 30 min before | not available | yes | «Con cada bot de materia» |
| Subject notebook (notes, photos, voice) | subject bot chat | not available | yes | «Qué hace» |
| Questions on course material, with citations | Vinci or subject bot | Vinci | yes; citations checked by a script | «El material de cada materia» |
| Hand in handwritten work | photos to the subject bot → «📤 Entregar» | photos to Vinci → «📤 Entregar» poll | yes (PDF built by a script) | «Entregar una actividad hecha a mano» |
| `/quiz <tema>` | subject bot (Vinci hands it over), quiz polls | Vinci, polls in the captain's DM | yes (questions), no (scoring) | «Quiz con /quiz» |
| DSpace past exams | ask Vinci or a subject bot | ask Vinci | yes | «Exámenes anteriores (DSpace)» |
| Schedule from a screenshot | screenshot to Vinci → «Guardar» | screenshot to Vinci → «✅ Guardar horario» poll | yes (reading), no (saving) | «Mándale tu horario a Vinci» |
| Class notes folder (`//vinci`) | answers and summaries in the subject bot chat | not available | yes | «Tus apuntes de clase» |
| Slide decks (.pptx) | ask Vinci or a subject bot | ask Vinci | yes | «Qué hace» |
| `/estado` | Vinci | Vinci (DM only) | no | «El estado del sistema» |
| `/token` new Canvas token | Mini App form | guide image + link button, back through the relay | no | «Token nuevo desde Telegram» |
| `/start` | every bot | Vinci | no | «Comandos» |
| Groups («@vinci activa este grupo») | not available | yes; answers whoever mentions it | yes | «Vinci en WhatsApp» |
| A Vinci per friend (`/amigo agregar`) | not available | yes | no (setup), yes (answers) | «Vinci en WhatsApp» |
| Voice notes | transcribed when Hermes can | transcribed with faster-whisper | no (transcription) | «Límites conocidos» |

## Code and verification

| Feature | Code | Verify |
|---|---|---|
| Alerts, reminders, summary | `src/espol_bot/poller.py`, `priority.py`, `messages.py` | `vinci-check status` (poll age); `espol-bot resumen` sends the summary for real |
| Buttons (all) | `src/espol_bot/botones.py`, `hermes/plugins/vinci-botones/` | `vinci-check press vinci_espol_bot "<label>"` on a harmless button |
| Dashboard | `src/espol_bot/dashboard.py`, `docs/dashboard/` | `vinci-check page dashboard` |
| To-do list | `src/espol_bot/store.py`, `herramientas.py` | `vinci-check chat vinci_espol_bot "¿qué tengo esta semana?"` (uses the model) |
| Grade calculator | `src/espol_bot/grades.py` | ask «¿cómo voy en Estadística?» through `chat` (uses the model) |
| Team of subject bots | `src/espol_bot/equipo.py`, `materias.py` | `vinci-check bots`; never press «➕ Crear» to test |
| Class briefs | `src/espol_bot/agenda.py`, `horario.py` | `vinci-check chat <subject bot> /start` shows the next class and brief time |
| Notebook | `src/espol_bot/cuaderno.py` | ask Vinci «¿qué hay en el cuaderno de <materia>?» (uses the model) |
| Material and citations | `src/aula_core/materials.py`, `search.py`, `src/espol_bot/citations.py`, `libros.py` | a material question through `chat`; check the cited file and page |
| Handwritten hand-in | `src/espol_bot/submission.py` | E2E only: a real hand-in uploads to Canvas |
| Quiz | `src/espol_bot/quiz.py`, `hermes/*/quiz/` | `chat <subject bot> "/quiz <tema>"` (uses the model) |
| DSpace | `src/aula_core/dspace.py` | ask for past exams through `chat` (uses the model) |
| Schedule | `src/espol_bot/horario.py` | `chat <subject bot> /start` |
| Class notes | `src/espol_bot/notes.py` | `bot.log` in the data folder; E2E covers the flow |
| Slides | `src/espol_bot/diapositivas.py` | ask for a short deck through `chat` (uses the model) |
| `/estado` | `src/espol_bot/health.py` | `vinci-check chat vinci_espol_bot /estado` |
| `/token` and the token chain | `src/espol_bot/token_form.py`, `token_renewal.py`, `docs/token/` | `vinci-check page token`; `vinci-check status` (chain age) |
| WhatsApp, groups, polls | `src/espol_bot/whatsapp.py`, `hermes/plugins/vinci-whatsapp/`, `hermes/whatsapp/` | `vinci-check whatsapp --chat dm\|group` |
| Friends | `src/espol_bot/amigos.py`, `hermes/amigo/` | `vinci-check whatsapp --profile amigo-<name>` (their private chat) |
| Relay | `src/espol_bot/relay.py`, `relay/worker.js` | `espol-bot whatsapp-rele` shows pending answers |
| Bot personalities | `hermes/vinci/`, `hermes/materia/`, `hermes/amigo/` (`SOUL.md`, `SKILL.md`) | a short `chat`; read the tone |

## Flows with several steps

- [`token.md`](token.md): a new Canvas token from Telegram or WhatsApp.
- [`dashboard.md`](dashboard.md): the dashboard from the menu button or `/entregas`.
