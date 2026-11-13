# Feature map

Every feature, where the captain reaches it, the code behind it and how an agent verifies it.
"Model" says whether the feature calls the LLM (costs tokens) or is a fixed script.
User-facing detail lives in `docs/guia/`; the last column names the file and its section.

## Telegram vs WhatsApp

`[channels] telegram = false` (the live setting) turns Telegram off: Vinci talks only on WhatsApp and does the
subject bots' work itself. The Telegram column is what `telegram = true` brings back.

| Feature | Telegram | WhatsApp | Model | Guide (`docs/guia/`) |
|---|---|---|---|---|
| Canvas alerts (a grade carries the professor's comments, late penalty and the course's mean, max and min when Canvas shows them, `score_statistics`; a new comment alone is «💬 Comentario del profe»; also inbox messages from staff, calendar events, new forums and replies to the student's posts, a new group, peer reviews with a reminder), reminders, 07:00 summary (with the week's calendar and pending peer reviews) | Vinci's chat, with buttons | captain's DM, a poll instead of buttons; friends get their own | no | `uso.md` «El resumen de las 7:00» |
| «🎓 Consultar con …» handoff | button under each alert | not needed: reply to the alert, Vinci answers with that subject | yes | `funciones.md` |
| «✅ Ya lo entregué» | button | poll | no | `funciones.md` |
| Work handed in outside the aula (`delivery`: external lab, event in class, unknown) | in every pending list | same; «ya lo hice» / «todavía no» / «se entrega por correo» | no (classification is a script) | `uso.md` «El resumen de las 7:00» |
| Dashboard of deliverables | «📋 Entregas» menu button, Mini App | link button: `/entregas`, after the 07:00 summary, and from Vinci (`show_page`) on «¿qué tengo pendiente?» in private; ticks come back through the relay | no (the button from Vinci: yes) | `uso.md` «El dashboard de entregas» |
| To-do list («anota: …») | card with «✅ Hecho» | poll | yes (parsing), no (reminders) | `funciones.md` |
| Grade calculator | ask Vinci or a subject bot; «✅ Guardar esquema» | ask Vinci; «Guardar esquema» poll; «¿cómo voy en notas?» also brings «📊 Ver mis notas», the «Tus notas» page (`show_page`) | yes, the math is a script | `uso.md` «La calculadora de notas» |
| Card album (a pack per deliverable handed in on time, per lección or exam of 8/10 or more, one a day after the 07:00 summary, a welcome pack with a new friend's token link, and a gift pack for everyone, or one friend with `--para`, from `espol-bot album-regalo`) | a message with a «🎴 Abrir mi sobre» URL button after the poll or the summary | the same as a link button; «¿cómo va mi álbum?» brings «🎴 Ver mi álbum» (`show_page` album) | no (the button from Vinci: yes) | `uso.md` «Tu álbum de cartas» |
| Album ranking (`/ranking`, `/ranking entrar`/`salir`: who has the most distinct cards among those who joined, `ranking.py`; the album's «Ranking» view, where a tap on someone shows their cards) | not available | yes, in private and in a group | no | `uso.md` «El ranking del álbum» |
| Card exchange (`/canje`: 3 repeats, the commonest first and never a last copy, for a pack opened from «🎴 Abrir mi sobre», `album.exchange`; a button in the album's «Cambios») | not available | yes, in private only | no | `uso.md` «Canjear repetidas por un sobre» |
| Card trades (`/cambio`: your repeats and who has the cards you lack; «/cambio Angel Bosque por Lago» sends Angel a poll, and «✅ Acepto» swaps one repeat each in both albums, `trades.py`; the album's «Cambios» button lists the others' repeats and opens WhatsApp with the «/cambio» typed, `trades.market`) | not available | yes, in private and in a group | no | `uso.md` «Cambiar cartas» |
| Team of subject bots | «arma mi equipo» → «➕ Crear» | not needed: one Vinci for every subject | no | `instalacion.md` «7. Arma tu equipo de bots desde el chat» |
| Brief before each class | subject bot, 30 min before | Vinci's DM, 30 min before (a system task Vinci answers) | yes | `whatsapp.md` «El brief antes de cada clase» |
| Subject notebook (notes, photos, voice) | subject bot chat | Vinci's DM; the subject named, replied to, or in class by the schedule | yes | `whatsapp.md` «Tus materias, en un solo chat» |
| Questions on course material, with citations | Vinci or subject bot | Vinci | yes; citations checked by a script | `uso.md` «El material de cada materia» |
| Questions about one assignment: found by its words (`tareas` `buscar`), its annexes searched first (`tarea_id`), official vs suggestion | the same | the same; the DM context also says which PDF waits for the vote and what was handed in | yes | `whatsapp.md` «Lo que pide una tarea» |
| Hand in work (photos of handwritten work as one PDF, or any files as they are: PDF, Word, ZIP, code) | photos to the subject bot → «📤 Entregar» | photos or files to Vinci → «📤 Entregar» poll; the assignment's allowed extensions are checked before the poll; in a group, a reply to anyone's file («@vinci sube esto…») → the poll in the owner's DM, and the group hears it went up | yes (PDF built and upload done by a script) | `uso.md` «Entregar una actividad hecha a mano» |
| Join a course group with open self sign-up («agrégame al grupo 6 de Semana 7») | no | Vinci and friends: `join_group` → «👥 Unirme» poll in the DM; the vote joins (`course_groups.py`, `v1:j:<group>:ok`) | yes (finding the group), no (the join) | `whatsapp.md` «Unirte a un grupo del aula» |
| `/quiz <tema>` | subject bot (Vinci hands it over), quiz polls | Vinci, polls in the captain's DM; asked in a group, polls in that group and one results message once every member answered or 15 min later (`whatsapp-grupo voto` / `cierre`) | yes (questions), no (scoring) | `funciones.md` «Quiz con `/quiz`» |
| Académico (GPA, history, grades, timetables, registration, internships, debts, MOOCs) | ask Vinci; «🎓 Conectar Académico» Mini App the first time | ask Vinci in the DM; the same button as a link | yes (answers), no (sign-in) | `uso.md` «Tu Académico de ESPOL» |
| Degree plan (`plan_carrera`: credits left per category, what to take from the curriculum the Académico sign-in reads from mallacurricular.espol.edu.ec, a GPA estimate; `guardar_malla` from a photo or PDF only when that failed) | ask Vinci | ask Vinci | yes (reading the curriculum), no (the counts) | `uso.md` «Planear tu matrícula» |
| ESPOL's official calendar (holidays, end of classes, terms; `calendario_espol`, «🏛️ En ESPOL esta semana» in the 07:00 summary) | the same | the same | no (read daily by a script), yes (questions) | `uso.md` «El calendario de ESPOL» |
| Assignment detail (annexes, aula rubric, local dates) | ask Vinci or a subject bot | ask Vinci | yes | `uso.md` «El material de cada materia» |
| The aula's Modules as the student sees them (recordings, Perusall, a Zoom ID subheader, each with its aula link; `modulos`), and class videos in the catalog's `videos` | ask Vinci or a subject bot | ask Vinci | yes; the sync stores `module_items` | `whatsapp.md` «Lo que muestran los Módulos», `uso.md` «El material de cada materia» |
| DSpace past exams | ask Vinci or a subject bot | ask Vinci | yes | `uso.md` «Exámenes anteriores (DSpace)» |
| Schedule from a screenshot | screenshot to Vinci → «Guardar» | screenshot to Vinci → «✅ Guardar horario» poll | yes (reading), no (saving) | `instalacion.md` «8. Mándale tu horario a Vinci» |
| Class notes folder (`//vinci`) | answers and summaries in the subject bot chat | answers and summaries in Vinci's DM | yes | `uso.md` «Tus apuntes de clase» |
| Slide decks (.pptx) | ask Vinci or a subject bot | ask Vinci | yes | `funciones.md` |
| Study pages (`send_study_page`: a review or a long explanation as `docs/repaso/`, built from 14 block types: formulas, plots with sliders, a sequence or architecture diagram walked step by step, code, flashcards, classify, order, quiz) | ask Vinci; the link comes as text | «📚 Abrir el repaso» link button, in private or in a group | yes (the content), no (the page) | `uso.md` «Repasos interactivos» |
| PDF summaries | ask Vinci or a subject bot | ask Vinci | yes | `funciones.md` |
| `/estado` | Vinci | Vinci; from a group the answer goes to the sender's DM («Te lo mandé por privado»), as do `/token`, `/entregas` and `show_page` | no | `uso.md` «El estado del sistema» |
| `/token` new Canvas token | Mini App form | guide image + link button, back through the relay; Vinci sends it too (`show_page`) when the token died or he asks | no (from Vinci: yes) | `uso.md` «Token nuevo desde Telegram (`/token`)» |
| `/start` | every bot | Vinci | no | `uso.md` «Comandos» |
| Groups («@vinci activa este grupo») | not available | yes; answers whoever mentions it, by name, with no unasked reminders; someone without a Vinci gets Vinci as a guest (guest tools only, marked in the turn's header); ignores stickers; starts over after 4 h idle | yes | `whatsapp.md` «Vinci en WhatsApp» |
| A Vinci per friend (`/amigo agregar`, or open signup: a stranger's private message gets the token link, `[channels] inscripcion_abierta`) | not available | yes | no (setup), yes (answers) | `whatsapp.md` «Vinci en WhatsApp» |
| News and «Todo lo que hace Vinci» (`whats_new.py`: once per person per `RELEASE`, 08:00–21:00, at a poll; then a button to `docs/funciones/`, whose examples open the chat typed; `show_page` `features` on «¿qué puedes hacer?») | not available | yes | no (news), yes (the button from Vinci) | `whatsapp.md` «Novedades y todo lo que hace Vinci» |
| Admin panel and watchdog (health of every Vinci, a WhatsApp alert to the captain when one breaks and when it recovers) | the same | the same | no | `panel.md` |
| Group notices («@vinci activa los avisos») | not available | yes; a reminder `brief_minutos_antes` before each class (room, virtual, what is due in 7 days), plus new announcements, assignments and due-date changes; no model | yes (`src/espol_bot/avisos.py`) | `whatsapp.md` «Vinci en WhatsApp» |
| Trusted group («@vinci este grupo es de confianza») | not available | yes; the notices tag who has the subject (same paralelo for a class), say who handed in each task, carry a virtual class's meeting link, and pass on the friends' aula news once | yes (`src/espol_bot/avisos.py`) | `whatsapp.md` «Vinci en WhatsApp» |
| Chat context in every turn (clock, chat kind, notes that hold in one chat: `chat_note`) | the same, per chat | the same; a group's note never reaches the DM; a DM or group idle 4 h starts a new conversation | no (a script adds it) | `whatsapp.md` «Vinci en WhatsApp» |
| Reminders at a set time («@vinci recuérdanos el viernes a mediodía…», «avísame cada hora hasta las 7») | no | `chat_reminder`, in a group or the captain's DM; the agenda tick (every 30 s) sends each one to that chat at its time, once and without the model; the ones still to go out are in that chat's turn context; one the bridge refused is retried every tick until it goes out; one late by over 6 h or of a group turned off never goes out; in the captain's DM it carries a poll «⏰ En 1 hora / 🌙 Mañana a esta hora / ✅ Ya está» whose vote snoozes it (botones `v1:p:…`, no model); the captain's Vinci only | yes (`chat_reminder`), no (`avisos.chat_reminders`) | `whatsapp.md` «Recordatorios para el grupo», «Tus avisos» |
| Group agreements (who does which part) | no | a `chat_note` of that group, saved from what the student says was agreed; his Vinci reads only his messages | yes | `whatsapp.md` «Grupos» |
| Subject in focus and open activities (a quiz or study session left and taken up again: `study_activity`) | the same, per Hermes session | the same; «sigamos con el quiz» re-sends only the unanswered polls; a photo or «anota…» without a subject goes to the one named in the last 3 h | no (a script adds it) | `whatsapp.md` «Tus materias, en un solo chat» |
| Study session («tengo 20 minutos») and presentation jury | no (WhatsApp only) | `study_activity` `kind: study` / `jury`: start brings weak topics, doubts, what is due and the rubric; finish with `save_weak` writes weak topics to the notebook | yes | `whatsapp.md` «Tengo 20 minutos», «Jurado de exposición» |
| Voice notes and audio files | transcribed when Hermes can | DM: voice notes and audio files (.m4a); groups: voice notes that say «Vinci» or reply to Vinci, from the captain or a friend with a Vinci; every voice turn's context warns a word may be misheard, and a silent or filler one («Gracias por ver el video») is called unheard (`conversation.voice`) | no (transcription: Groq or OpenAI in the container, local Whisper on a PC) | `whatsapp.md` «Vinci en WhatsApp» |
| Spoken replies («mándame un audio») | the same | text by default, voice notes too; asked for audio, Vinci calls `text_to_speech` and sends a voice note plus the text; Edge TTS, `es-EC-LuisNeural` (`hermes_setup.VOICE`, the `tts` toolset in `VINCI_TOOLSETS`) | no | `whatsapp.md` «Vinci en WhatsApp» |

## Code and verification

| Feature | Code | Verify |
|---|---|---|
| How each assignment is handed in | `src/aula_core/queries.py` (`delivery`, `pending`), `set_assignment_delivery` in `herramientas.py` | `vinci-check say "¿qué tengo pendiente?"` lists an overdue external lab as late (uses the model) |
| Alerts, reminders, summary | `src/espol_bot/poller.py`, `priority.py`, `messages.py`; the loop in the container: `poll_service.py`, `deploy/s6/vinci-sondeo` | `vinci-check status` (poll age); `espol-bot resumen` sends the summary for real; `vinci-check remote logs bot --grep "sondeo --todos"` |
| Buttons (all) | `src/espol_bot/botones.py`, `hermes/plugins/vinci-botones/` | `vinci-check vote "<option>"` on a harmless poll (`press` with Telegram on) |
| Dashboard | `src/espol_bot/dashboard.py` (`whatsapp_link`), `docs/dashboard/`, `show_page` in `herramientas.py`, `Bot._dashboard_button` in `poller.py` | `vinci-check page dashboard`; `vinci-check say "¿qué tengo pendiente?"` brings the button (uses the model) |
| To-do list | `src/espol_bot/store.py`, `herramientas.py` | `vinci-check say "¿qué tengo esta semana?"` (uses the model) |
| Grade calculator | `src/espol_bot/grades.py`; the page: `grades_page.py`, `docs/notas/` | ask «¿cómo voy en Estadística?» through `chat` (uses the model); `vinci-check page notas` renders the page with the live data |
| Card album | `src/espol_bot/album.py` (packs, given in `Bot.poll`; the pack of the day in `Bot.summary`; gift packs from `espol-bot album-regalo`, `cli.py`), the catalog `docs/album/cards.json`, the page `docs/album/`, encrypted art in `docs/album/art/` (made with `scripts/album_card.py`, the `album-card` skill; key `ALBUM_ART_KEY`, in the captain's secrets.env only: a friend's Vinci finds it through `VINCI_CAPTAIN_SECRETS`); assignment groups in `src/aula_core/sync.py` | `vinci-check say "¿cómo va mi álbum?"` brings «🎴 Ver mi álbum» (uses the model); in the container, the `album_packs` table of espol.db |
| Team of subject bots | `src/espol_bot/equipo.py`, `materias.py` | `vinci-check bots`; never press «➕ Crear» to test |
| Class briefs | `src/espol_bot/agenda.py` (`run_vinci` without Telegram), `horario.py`, `relay.queue_turn` | after a class's brief time, `vinci-check whatsapp --chat dm` shows the «[Tarea del sistema …]» turn and the brief |
| Notebook | `src/espol_bot/cuaderno.py`; Vinci's tools in `_subject_work_tools` (`herramientas.py`) | `vinci-check say "¿qué hay en el cuaderno de <materia>?"` (uses the model) |
| Material and citations | `src/aula_core/materials.py`, `search.py`, `src/espol_bot/citations.py`, `libros.py` | a material question through `chat`; check the cited file and page |
| Handwritten hand-in | `src/espol_bot/submission.py` | E2E only: a real hand-in uploads to Canvas |
| Quiz | `src/espol_bot/quiz.py`, `hermes/*/quiz/` | `chat <subject bot> "/quiz <tema>"` (uses the model) |
| Académico | `src/espol_bot/portal_login.py`, `academic_portal.py`, `docs/academico/` | `espol-bot academico` (the copy, read-only); never trigger a new sign-in to test |
| Degree plan | `src/espol_bot/plan.py` (the curriculum: the copy's «malla» section from `academic_portal.read_curriculum`, else `<data>/malla.json`), `plan_carrera` and `guardar_malla` in `herramientas.py` | `vinci-check say "¿qué materias puedo tomar el próximo semestre?"` (uses the model) |
| ESPOL calendar | `src/espol_bot/espol_calendar.py` (the copy in the captain's data folder, `calendario-espol.json`, read by `Bot.maintenance`), `calendario_espol` in `herramientas.py` | `vinci-check remote run espol-bot calendario-espol` (reads the page now and lists the next 60 days) |
| Album ranking | `src/espol_bot/ranking.py` (who joined: `amigos/ranking.json`; each person's cards go to the page as catalog numbers, `c`), the album page's «Ranking» view | `vinci-check say "/ranking"` (no model) |
| Card exchange and pack odds | `album.exchange`, `trades.exchange`; `album.draw` (`OWNED_WEIGHT`: a card already owned keeps 40% of its chance; no card twice in a pack) | `vinci-check say "/canje"` (no model; it spends 3 real repeats) |
| Assignment detail | `ver_tarea` in `herramientas.py`, `src/aula_core/queries.py`, `materials.py` | ask «¿qué pide <tarea>?» through `chat`; check annexes, rubric and dates (uses the model) |
| Finding an assignment and searching its annexes | `queries.find_assignments` (`tareas` with `buscar`), `_search` with `tarea_id`, `search.search(file_ids=…)` | `vinci-check say "en el <tarea por su tema>, qué piden de …?"`, then `vinci-check whatsapp --chat dm`: hits marked `de_la_tarea` first |
| What happened to a submission | `conversation.submissions` (line «Entregas en el aula» of the turn context) | after a `prepare_submission`, the next DM turn says it waits for the vote |
| DSpace | `src/aula_core/dspace.py` | ask for past exams through `chat` (uses the model) |
| Schedule | `src/espol_bot/horario.py` | `chat <subject bot> /start` |
| Chat context | `src/espol_bot/conversation.py`, `espol-bot contexto`, hook `pre_llm_call` in `hermes/plugins/vinci-botones/` | `vinci-check whatsapp --chat dm`: the user turn ends with «[Contexto de este chat…]» and today's clock |
| Focus and activities | `conversation.py` (`note_turn`, `open_activities`), `materias.mentioned`, `study_activity` and `send_quiz` in `herramientas.py`, `quiz.resend` | `vinci-check say "estamos en <materia>"`, then `vinci-check whatsapp --chat dm`: «Materia en foco» in the next turn |
| Class notes | `src/espol_bot/notes.py` | `bot.log` in the data folder (the E2E no longer covers it) |
| Slides | `src/espol_bot/diapositivas.py` | ask for a short deck through `chat` (uses the model) |
| Study pages | `src/espol_bot/study_page.py` (checks each block), `send_study_page` in `herramientas.py`, `docs/repaso/` (draws them; KaTeX in `docs/repaso/katex/`) | `vinci-check say "explícame bien <tema> con un repaso"`; the reply carries «📚 Abrir el repaso» (uses the model); `vinci-check whatsapp --chat dm` shows the URL |
| PDF summaries | `src/espol_bot/resumen.py`, `visuales.py` (diagrams and mockups), `crear_resumen` in `herramientas.py` | `vinci-check say "hazme un resumen en pdf de <tema>"`; the PDF reaches the captain's chat (uses the model) |
| `/estado` | `src/espol_bot/health.py` | `vinci-check smoke` runs it as the captain's WhatsApp would get it |
| `/token` and the token chain | `src/espol_bot/token_form.py`, `token_renewal.py`, `docs/token/`; the renewal loop in the container: `maintenance_service.py`, `deploy/s6/vinci-mantenimiento` | `vinci-check page token`; `vinci-check status` (chain age); `vinci-check remote logs bot --grep "mantenimiento --todos"` |
| WhatsApp, groups, polls, voice | `src/espol_bot/whatsapp.py`, `hermes/plugins/vinci-whatsapp/`, `hermes/whatsapp/` | `vinci-check whatsapp --chat dm\|group`; voice: the turn starts with «🎙️» and the transcript |
| Friends | `src/espol_bot/amigos.py` (`signup` for open signup, called by the `vinci-whatsapp` plugin; `_show_around` sends `docs/images/vinci-video.mp4` and the features button before the first token link), `hermes/amigo/` | `vinci-check whatsapp --profile amigo-<name>` (their private chat) |
| Admin panel, watchdog | `src/espol_bot/panel.py`, `panel.html`, `watch.py` (run by `Bot.maintenance`), `deploy/s6/vinci-panel` | `espol-bot doctor` lists each friend; the panel's «Salud de cada Vinci» |
| Relay | `src/espol_bot/relay.py`, `relay/worker.js` | `espol-bot whatsapp-rele` shows pending answers |
| Bot personalities | `hermes/vinci/`, `hermes/materia/`, `hermes/amigo/` (`SOUL.md`, `SKILL.md`) | a short `chat`; read the tone |

## Flows with several steps

- [`token.md`](token.md): a new Canvas token from Telegram or WhatsApp.
- [`dashboard.md`](dashboard.md): the dashboard from the menu button or `/entregas`.
- [`academico.md`](academico.md): connecting ESPOL's Académico from «🎓 Conectar Académico».
