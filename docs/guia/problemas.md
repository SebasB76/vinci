# Límites y problemas

## Límites conocidos

- **Crear muchos bots seguidos:** Telegram puede pedirte esperar antes de crear otro. Vinci no se entera: vuelve
  a pulsar «➕ Crear» cuando pase ese tiempo. La tarjeta de «arma mi equipo» muestra hasta 8 botones «Crear» a la
  vez; con más materias, crea esas y pídela otra vez.
- **20 bots por cuenta:** Telegram deja tener como máximo 20 bots por cuenta, contando a Vinci y a los que ya
  tengas. Archivar un bot no lo borra de Telegram; para liberar espacio, bórralo en @BotFather con `/deletebot`.
- **Archivos de más de 20 MB:** un bot de Telegram no puede descargar lo que le mandas si pesa más de 20 MB, así
  que no le llega. Para el libro principal, pon el PDF en `libros/<CÓDIGO>/` de la carpeta de datos. El material
  del aula no tiene ese límite: se baja directo del aula (hasta `material.tamano_maximo_mb`).
- **Qué se puede leer:** el texto de PDF, PPTX, DOCX, XLSX (Excel) y páginas web. Un PDF escaneado se busca por su texto de OCR
  (con `tesseract` instalado), que falla en fórmulas, figuras y letra a mano: eso Vinci (o, con Telegram, el bot
  de su materia) lo mira como imagen, de una en una. Un libro escaneado de 300 páginas tarda unos 10 a 15 minutos de OCR, repartidos en
  los sondeos. Un Google Docs, Drive, SharePoint
  o Dropbox se lee solo si se abre sin iniciar sesión («cualquier persona con el enlace»); si pide tu cuenta de
  ESPOL o de Google, el bot te lo dice y te pide el PDF. Los videos, formularios, carpetas, OneDrive personal y
  Teams solo quedan listados con su enlace, para que los abras tú.
- **Solo se busca en lo ya leído:** del catálogo, solo el sílabo se baja por su cuenta; el resto lo baja Vinci (o,
  con Telegram, el bot de la materia) cuando le hace falta.
- **La materia de una foto o una nota de voz:** sin nombrarla, Vinci la elige por tu horario solo durante la clase
  o hasta una hora después. Fuera de eso te pregunta en un mensaje, sin encuesta.
- **Qué prueba una cita:** que el bot leyó esa página de ese archivo, no que la página diga exactamente lo que el
  bot resume. Ábrela con su enlace si te importa el detalle.
- **Notas de voz:** se transcriben si tu Hermes tiene cómo; si no, el bot guarda el audio sin transcribir.
- **WhatsApp no es oficial:** el puente de Hermes es un cliente no oficial de WhatsApp (Baileys). WhatsApp puede
  bloquear el número de Vinci, por eso va en un chip aparte. En WhatsApp no hay botones: los avisos de un amigo
  llegan como texto.
- **Tu PC tiene que estar encendida:** con la PC apagada o el gateway detenido no hay avisos ni briefs. Lo que le
  escribas a un bot mientras tanto te lo responde al volver, y los cambios del aula llegan en la siguiente revisión;
  el brief de una clase que ya empezó no se manda.
- **Materias sin código ESPOL:** un curso del aula sin un código reconocible (como `MATG1049`) no recibe bot;
  Vinci te lo dice en la tarjeta del equipo.
- **El aula pide calma:** el sondeo espacia sus consultas, baja solo los sílabos (hasta 50 MB por revisión) y
  sigue a lo más 60 enlaces por revisión hacia el material que solo un enlace muestra; lo demás, en las siguientes.
  La primera vez, el catálogo completo puede tomar varias revisiones. Si el aula pide bajar el ritmo, el sondeo no
  la vuelve a leer durante una hora.

- **El Académico, probado contra una imitación:** la prueba E2E entra a un Académico falso que se comporta como
  ASP.NET (VIEWSTATE, EVENTVALIDATION, ingreso en dos pasos, CAPTCHA) y copia la forma de las páginas reales. Si
  ESPOL cambia una página, el lector puede necesitar ajustes. Corre `.venv/bin/espol-bot academico --conectar --html
  …` para ver qué lee con tu cuenta.
- **La malla, todavía no:** Vinci no lee la malla de tu carrera, así que no te dice qué materias te faltan.
- **El Académico sin relé, tampoco:** sin el relé la página no puede mostrarte el CAPTCHA.

## Solución de problemas

| Síntoma | Qué hacer |
|---|---|
| `No encuentro Hermes Agent en ~/.local/bin/hermes` | Instala Hermes, o indica dónde está: `HERMES_BIN=/ruta/a/hermes ./setup.sh`. |
| `Faltan valores en secrets.env: …` | Completa esas claves (pasos 1 a 4) y vuelve a correr `./setup.sh`. |
| `⚠ Telegram no aceptó el mensaje` | Mándale `/start` a tu bot de Vinci y revisa `TELEGRAM_BOT_TOKEN`. |
| `⚠ No pude leer el aula virtual; revisa CANVAS_TOKEN` | El token inicial no funcionó durante el setup. Crea otro (paso 3) y mándaselo a Vinci con `/token` (o ejecuta `.venv/bin/espol-bot resembrar`). |
| Vinci dice que la cadena del token se cortó | Crea un token nuevo en tu perfil del aula y pégalo con el botón «🔑 Pegar token» de ese mismo aviso: [el formulario](uso.md#token-nuevo-desde-telegram-token) lo cifra en tu celular y la renovación se reanuda. |
| El formulario de `/token` dice que venció o que era de un `/token` anterior | Usa el botón del mensaje más reciente de Vinci, o mándale `/token`: cada formulario sirve una vez, por 15 minutos (o 24 horas si Vinci lo mandó solo). |
| Vinci te dice «Llevo un rato sin poder leer … de …» | Una parte de una materia falló tres veces seguidas. Lo sigue intentando y el resto funciona normal; te avisa de nuevo si vuelve a fallar después de recuperarse. |
| `⚠ Agrega ~/.local/bin a tu PATH` | Agrégalo en tu `~/.bashrc` (o el de tu shell) para usar `aula`. |
| `vinci: command not found` | `vinci` es el alias que Hermes crea para el perfil; sin él, usa `hermes -p vinci …`. |
| `⚠ El gateway de Hermes no cargó el plugin …` | Reinicia el gateway: `hermes gateway stop && hermes gateway start`. |
| Vinci te responde «No sé de qué materia es ese bot» | Pulsa primero «➕ Crear» en la materia que es, y revoca en @BotFather (`/revoke`) el token que mandaste. |
| No te llega el brief | Revisa que guardaste el horario y que la clase está en él, que el bot está activo y que el gateway corre. Mándale `/start` al bot: te dice cuándo es tu próxima clase y a qué hora llega el brief. |
| No ves el botón «📋 Entregas» en el chat de Vinci | Corre `.venv/bin/espol-bot dashboard`, que lo pone al día ya, y después cierra y abre el chat. Si dice que está apagado, revisa `dashboard.url` en `config.toml`. |
| Un bot no contesta o tarda mucho | Abre el [panel](panel.md): la fila de esa conversación dice cuánto tardó o si quedó sin respuesta, y al tocarla ves en qué paso se quedó. «Errores y avisos» muestra qué falló en Hermes. |
| No te llegan avisos del aula | Mándale `/estado` a Vinci o corre `.venv/bin/espol-bot doctor`: te dice si el sondeo dejó de correr, si la cadena del token se cortó o si un feed falla, y qué hacer. |
| Ningún bot responde | `hermes gateway status`; si está apagado, `hermes gateway start`. Si se apaga al cerrar sesión: `sudo loginctl enable-linger "$USER"`. |
| El modelo no responde o falta la credencial | Configura el modelo en Hermes (`hermes model`). Si usas una `ANTHROPIC_API_KEY` y no el login de Anthropic, cada perfil lee su propio `.env`: agrégala al `.env` de `~/.hermes/profiles/vinci/` y de cada `vinci-<código>` (el setup conserva esa línea). |
| `⚠ Sin OCR (opcional)` o `A tesseract le falta el español` | `sudo pacman -S tesseract` y vuelve a correr `./setup.sh` (sin `--skip-deps`): baja los modelos de español e inglés. Hasta entonces los escaneos se miran como imagen. |
| `⚠ No pude ponerle su foto …` o `… el nombre …` | Telegram pidió esperar o no hubo conexión. `./setup.sh` lo reintenta la próxima vez; también puedes hacerlo en @BotFather con `/setuserpic` o `/setname`. |

Para ver qué pasa:

```bash
.venv/bin/espol-bot doctor                             # sondeo, aula y token, de un vistazo
hermes gateway status                                  # ¿está corriendo?
vinci cron list                                        # sondeo, mantenimiento y resumen de Vinci
tail -f ~/.hermes/logs/gateway.log                     # registro del gateway de Hermes
tail -f ~/.local/share/espol-academic-bot/bot.log      # registro del sondeo, la agenda y los botones
```
