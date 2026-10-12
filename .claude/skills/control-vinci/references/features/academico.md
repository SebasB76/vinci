# Académico: connecting ESPOL's academic portal

The Académico (academico.espol.edu.ec) has the GPA, degree progress, history, this term's grades
and the class and exam timetables. It has no API: a worker signs in once with the student's user,
password and CAPTCHA, reads every section and saves a copy (`academico.json` in the data folder,
or the friend's folder). Vinci answers from the copy through the `academic_record` tool. The
password never reaches the chat, the model, a log or a file.

| Step | Telegram | WhatsApp |
|---|---|---|
| 1. Trigger | a question about grades, GPA or timetables with no copy, or «actualiza mi Académico» | same, DM only (a group gets «por privado») |
| 2. What arrives | «🎓 Conectar Académico» as a Mini App button | the same button as a URL button |
| 3. The page | `docs/academico/`: user, then password + the CAPTCHA the worker publishes through the relay | same page |
| 4. Back to the laptop | each answer travels sealed to the worker's one-time RSA key, through the relay | same |
| 5. Result | «✅ Listo: guardé tu Académico…», then the plugin puts the original question back in the same Hermes session and Vinci answers it | same |

Who does what: the model's tool opens a relay mailbox (`portal_login.request`);
`espol-bot whatsapp-rele` (every 3 s) starts `espol-bot portal-worker <mailbox>`; the worker sends
the button, drives the portal and saves the copy. Without the relay the flow cannot start.

Limits: one sign-in per person (a new button replaces the last); the button lasts
`portal_login_minutes` (15); 5 tries. The GPA is the portal's figure, never computed from grades.
The page's ID, name, ethnic group and photo are dropped. A WhatsApp chat keyed by its LID needs the
session link that `setup.sh` makes, or the answer to the held question is dropped.

Code: `src/espol_bot/portal_login.py` (button, worker, sealed answers),
`src/espol_bot/academic_portal.py` (sign-in, reading, the copy), `docs/academico/` (the page),
`src/espol_bot/relay.py` + `relay/worker.js`, `academic_record` in `src/espol_bot/herramientas.py`.

Verify without the captain's password:
- `.venv/bin/espol-bot academico` → the copy's date, term and rows per section (read-only).
- `vinci-check chat vinci_espol_bot "¿cuál es mi promedio?"` → answered from the copy, with its date
  (uses the model).
- Never send «actualiza mi Académico» or press «🎓 Conectar Académico» to test: it needs the
  captain's password and CAPTCHA.
The full sign-in, wrong CAPTCHA and LID chat are covered by the E2E against a fake portal.
Phone only: the page inside WhatsApp on the iPhone.
