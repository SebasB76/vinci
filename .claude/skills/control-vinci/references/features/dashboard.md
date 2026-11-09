# Dashboard of deliverables

A static page (`docs/dashboard/` on GitHub Pages) that reads all its data from its own link, after
the `#`. No server holds the captain's data.

| Step | Telegram | WhatsApp |
|---|---|---|
| 1. How it opens | «📋 Entregas» menu button next to the text field in Vinci's chat | a link button (a friend's Vinci too): `/entregas`, after the 07:00 summary (ticks open 24 h), and Vinci's `show_page` on «¿qué tengo pendiente?» |
| 2. The data | rebuilt after each poll where something changed and put in the button's link | built when the button is sent |
| 3. Ticking a deliverable | opens Vinci's chat with a special `/start`; the plugin handles it, deletes it, confirms, refreshes the button | posted to the relay, confirmed in chat. Without relay: opens the chat with `/marca …` typed |

Parts of the page («Tu semana», on `docs/vinci/vinci.css`): a white summary sheet (how many are due in the next 7
days, how many are late, the week of the semester, and one column per day with one capsule per deliverable in its
subject's color; a ticked capsule fades, a day over 6 shows «+N»), then a three-way segmented control. Por día:
sections Atrasadas, Hoy, Mañana, each day of the week, Más adelante (first 3, the rest under «Ver N más adelante») and
Sin fecha; each row says its time, weight (`vale 25 %`), flags and subject on one line that ends in an ellipsis. Por
materia: one block per subject (something late first, then the soonest; «Tus pendientes» last) with how many are
left, a progress bar and the next date; rows lead with a date column. Novedades: the last 7 days of Canvas news, with
an unread dot. The chosen tab is kept on the phone.

Code: `src/espol_bot/dashboard.py` (`snapshot`, `page_url`, `publish`, `whatsapp_link`),
`docs/dashboard/`, `src/espol_bot/relay.py`, `hermes/plugins/vinci-botones/`.

Verify:
- `vinci-check page dashboard` → builds the link from the live `espol.db` and renders it in headless
  Chrome; the output shows «Tu semana», the tile numbers and the first deliverables.
- `.venv/bin/espol-bot dashboard` → refreshes the Telegram menu button now (real effect, harmless).
Phone only: Telegram caches the menu button for a while; close and reopen the chat.
