# /token: a new Canvas token

ESPOL's Canvas silently invalidates personal tokens after one hour. `token_renewal.py` keeps a
chain alive (successor at 40 min). When the laptop was off for over an hour the chain breaks and
the captain must paste a new token. The model never sees a token.

| Step | Telegram | WhatsApp |
|---|---|---|
| 1. Trigger | the "chain broke" alert with «🔑 Pegar token», or `/token` | `/token` in the DM (in a group it asks for the DM) |
| 2. What arrives | a Mini App button | a guide image with the Canvas steps, then a link button |
| 3. The page | `docs/token/` opens the aula's profile at «+ Nuevo token de acceso» (a fixed ESPOL link), then encrypts with the one-time public key in the link (RSA-OAEP) | same page, WhatsApp mode |
| 4. Back to the laptop | Telegram hands the ciphertext to the plugin | the page posts to the relay; the laptop polls it every 3 s while the link is open. Without relay: ciphertext to paste in the chat |
| 5. Result | Vinci checks it with Canvas, saves it, resumes the chain, confirms in chat | same |

Limits: a form works once; 15 min from `/token`, 24 h when Vinci sent it by itself. A replay, an
older form or an expired one is refused and a new form is sent. A token pasted in any chat is
deleted unused.

Code: `src/espol_bot/token_form.py` (form, one-time keys), `src/espol_bot/token_renewal.py` (chain),
`src/espol_bot/relay.py` + `relay/worker.js` (WhatsApp return path),
`hermes/plugins/vinci-botones/` (catches `/token` and the ciphertext before Hermes).

Verify without a real token:
- `vinci-check status` → token chain age and health.
- `vinci-check page token` → the page loads and shows its form.
- `vinci-check chat vinci_espol_bot /token` → a message with a web_app button. This issues a real
  one-time form; it expires on its own.
The full submit through the relay is covered by the E2E (`test_canvas`, step 6e, and `test_whatsapp_captain`).
Phone only: the page inside WhatsApp on the iPhone.
