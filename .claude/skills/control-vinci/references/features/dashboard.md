# Dashboard of deliverables

A static page (`docs/dashboard/` on GitHub Pages) that reads all its data from its own link, after
the `#`. No server holds the captain's data.

| Step | Telegram | WhatsApp |
|---|---|---|
| 1. How it opens | «📋 Entregas» menu button next to the text field in Vinci's chat | `/entregas` → link button (a friend's Vinci too) |
| 2. The data | rebuilt after each poll where something changed and put in the button's link | built when `/entregas` is answered |
| 3. Ticking a deliverable | opens Vinci's chat with a special `/start`; the plugin handles it, deletes it, confirms, refreshes the button | posted to the relay, confirmed in chat. Without relay: opens the chat with `/marca …` typed |

Parts of the page: the semester line (today, %, week, days left), pending deliverables grouped
(Atrasadas, Hoy, Esta semana, Más adelante, Sin fecha) with weight in the grade when known, and
the last 7 days of Canvas news.

Code: `src/espol_bot/dashboard.py` (`snapshot`, `page_url`, `publish`, `whatsapp_url`),
`docs/dashboard/`, `src/espol_bot/relay.py`, `hermes/plugins/vinci-botones/`.

Verify:
- `vinci-check page dashboard` → builds the link from the live `espol.db` and renders it in headless
  Chrome; the output shows the semester line and the first deliverables.
- `.venv/bin/espol-bot dashboard` → refreshes the Telegram menu button now (real effect, harmless).
Phone only: Telegram caches the menu button for a while; close and reopen the chat.
