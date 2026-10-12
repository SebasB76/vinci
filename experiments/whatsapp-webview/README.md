# Experimento: formulario propio dentro de WhatsApp, sin Cloud API

Este experimento comprueba si un botón de WhatsApp abre nuestra página dentro de la app.
La página guarda datos en nuestro backend, y después el bot confirma en el mismo chat.
El plan completo está en `docs/research/whatsapp-webviews-handoff.md`.

## Piezas

| Archivo | Qué hace |
|---|---|
| `bridge/webview_variants.js` | Arma el mensaje de cada variante y los nodos `biz` que lo acompañan. |
| `bridge/webview_route.js` | Agrega al puente la ruta `POST /experiment/webview/send`. Usa el socket y la cola de envío del puente. |
| `bridge/install.sh`, `bridge/uninstall.sh` | Instalan y retiran la ruta sin editar `bridge.js`. |
| `check_encoding.mjs` | Comprueba sin conexión que Baileys conserva cada campo al codificar y decodificar. |
| `server.py` | Sirve la página, guarda los envíos y manda la confirmación del bot. |
| `page/` | La página móvil: un campo ficticio y el botón «Guardar». |
| `tests/e2e/test_webview_experiment.py` | Prueba E2E: backend real, Chromium real y un puente falso. |

## Variantes

Todas usan la misma URL HTTPS y el mismo texto. Cada una cambia una sola cosa respecto de la anterior, salvo donde se indica.

| Variante | Mensaje | Nodo `biz` | Fuente |
|---|---|---|---|
| `plain_url` | Texto con la URL | Ninguno | Comportamiento básico. |
| `cta_url` | `interactiveMessage` con un botón `cta_url` (`display_text`, `url`, `merchant_url`) | Mínimo: `interactive > native_flow name=mixed v=9` | digows/baileys, muestra N03, commit `1441cf3`. |
| `cta_url_webview` | `cta_url` con `webview_interaction`, `landing_page_url` y los `tap_target` del helper | El mismo mínimo | `fukubailyes/lib/Utils/ios-webview-helper.js`. |
| `cta_url_webview_fork` | Lo que `@hassanfuad/baileys-ios-webview` 7.3.7 envía de verdad ante un `open_webview`: un `cta_url` con `in_app_webview` y `merchant_url` | El del fork, con `quality_control` | `lib/Utils/messages.js` y `lib/Socket/messages-send.js` del paquete. |
| `open_webview` | Un botón con el nombre `open_webview` y `link.in_app_webview` | El del fork | `@rexxhayanasi/elaina-baileys` 1.4.4 lo asocia al flujo `message_with_link` y advierte que solo Android lo muestra. |

El fork de hassanfuad nunca envía un botón `open_webview`: lo convierte en `cta_url`.
Por eso `cta_url_webview_fork` y `open_webview` son dos mensajes distintos, no dos nombres del mismo.

## Cómo se protege

- La ruta del puente responde solo en loopback (el control de `Host` de `bridge.js`).
  Además, solo envía al chat de `webview_experiment.json`. Si borras ese archivo, la ruta deja de enviar.
- El backend escucha en dos puertos de `127.0.0.1`. El túnel publica únicamente el público (8787).
  El de administración (8788) crea sesiones y pide un token que `serve` guarda en la carpeta de estado.
- El backend escribe solo al destinatario que recibe en `serve --recipient`. La página nunca envía un chat.
- Cada sesión tiene una capacidad de 32 bytes que viaja en el fragmento de la URL (`#c=`).
  El fragmento no llega al túnel ni al log. La página lo quita de la barra de direcciones al leerlo.
  El servidor guarda solo su hash. Quien tenga el enlace puede usarlo hasta que caduque: por eso los datos son ficticios.
- Un envío lleva un `submissionId`. El mismo envío repetido se guarda una vez. Otro envío sobre un formulario guardado recibe 409.
- La confirmación se guarda en la misma transacción que el envío. Un hilo la manda por `/send` del puente y reintenta cada 2 s.
  Si el puente envía pero pierde la respuesta, el reintento duplica el mensaje: la entrega es al menos una vez, no exactamente una vez.
- `hidden`, `visible` y `pagehide` quedan como eventos auxiliares. Nunca cuentan como un envío.

## Comandos

1. Comprueba la codificación sin conexión: `node experiments/whatsapp-webview/check_encoding.mjs`.
2. Instala la ruta del puente: `experiments/whatsapp-webview/bridge/install.sh <tu número con código de país>`.
3. Reinicia el gateway: `systemctl --user restart hermes-gateway`. El puente vuelve con la copia que tiene la ruta.
4. Abre el túnel: `cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787`. Copia la URL `trycloudflare.com`.
5. Arranca el backend: `uv run python experiments/whatsapp-webview/server.py serve --public-url <URL> --recipient <tu número>`.
6. Envía una variante: `uv run python experiments/whatsapp-webview/server.py open --variant cta_url --ttl-seconds 7200`.
7. Mira lo que llegó al servidor: `uv run python experiments/whatsapp-webview/server.py report`.
8. Corre la prueba E2E: `uv run pytest tests/e2e/test_webview_experiment.py`.

Para limpiar:

1. Detén el backend y el túnel (`pkill -f server.py serve`, `pkill -f "cloudflared tunnel"`).
2. Corre `experiments/whatsapp-webview/bridge/uninstall.sh`. Quita la línea de `config.yaml` y los archivos copiados.
3. Reinicia el gateway: `systemctl --user restart hermes-gateway`. Hermes vuelve a su `bridge.js` sin cambios.
4. Si quieres, borra la carpeta de estado `~/.local/state/vinci-webview-experiment/`.

`install.sh` guarda una copia de `config.yaml` en `config.yaml.before-webview-experiment` antes de tocarlo.

## Versiones

| Pieza | Versión |
|---|---|
| Baileys del puente | `@whiskeysockets/baileys` `7.0.0-rc13`, sin cambios |
| Hermes Agent | commit `d0288be5b3` |
| Node del puente | 26.7.0 |
| cloudflared | 2026.10.0, SHA-256 `d33ff2d1…a99db`, igual al publicado en la versión |
| Recetas | digows/baileys `1441cf3` (`selected-profiles.json`, SHA-256 `eab2e25e…f714b8`); hassanfuad 7.3.7; elaina 1.4.4 |

## Resultados

### Sin conexión

`check_encoding.mjs` (2026-10-10): las cinco variantes pasan el viaje de ida y vuelta por protobuf.
Los nodos `biz` pasan por el codificador binario de Baileys sin perder atributos.
`sendMessage` de Baileys descarta los `additionalNodes` del llamador. Por eso la ruta usa `relayMessage`.

### Prueba E2E

`tests/e2e/test_webview_experiment.py` pasa (2026-10-10, 19 s). Comprueba estos puntos:

- La página muestra la ejecución, guarda el texto y el bot confirma en el chat citando el mensaje de apertura.
- El reintento del mismo envío se procesa una vez, y otro envío sobre el formulario guardado recibe 409.
- Una capacidad incorrecta, la capacidad de otra sesión y una sesión caducada no guardan nada.
- Con el puente caído, el dato queda guardado y la confirmación pendiente. Al volver el puente, llega una vez.
- Una página cerrada sin «Guardar» deja `load` y `pagehide`, pero no hay envío ni mensaje del bot.

### Clientes reales

El puente aceptó las cinco variantes el 2026-10-11 (ejecuciones `r5ovgpla3`, `rjj4hr5ko`, `rwtrkuaze`, `r2ckvzzp7`, `roxncg3fg`).
Que el servidor acepte el mensaje no demuestra que el cliente lo muestre ni dónde lo abre.

Valores de apertura: `embedded` (dentro de WhatsApp), `external_browser` (otra app), `external_tab` (otra pestaña de Web),
`unsupported` (el cliente no muestra la acción), `not_tested` (nadie lo comprobó).

| Variante | Android | iPhone | WhatsApp Web | Envío al backend | Confirmación del bot |
|---|---|---|---|---|---|
| `plain_url` | `not_tested` | `external_browser` | `external_tab` | iPhone y Web: sí | iPhone y Web: sí, al primer intento |
| `cta_url` | `not_tested` | `external_browser` | `external_tab` | iPhone y Web: sí | iPhone y Web: sí, al primer intento |
| `cta_url_webview` | `not_tested` | `embedded` | `external_tab` | iPhone y Web: sí | iPhone y Web: sí, al primer intento |
| `cta_url_webview_fork` | `not_tested` | `embedded` | `external_tab` | iPhone y Web: sí | iPhone y Web: sí, al primer intento |
| `open_webview` | `not_tested` | `unsupported` | `unsupported` | No aplica | No aplica |

iPhone: iOS 17.5.1, WhatsApp 2.26.39 (lo dice el agente del navegador del webview). Observación del usuario el 2026-10-11.

- `plain_url` y `cta_url`: el usuario vio la página fuera de WhatsApp. El agente del navegador dice `CriOS`,
  es decir, el navegador predeterminado del teléfono (Chrome para iOS), no WhatsApp.
- `cta_url_webview` y `cta_url_webview_fork`: el usuario vio la página dentro de WhatsApp.
  El agente del navegador termina en `[WAiOS/2.26.39]`, la marca del webview de WhatsApp. Las dos señales coinciden.
- `open_webview`: WhatsApp muestra «recibiste un mensaje, pero no es compatible con tu versión de WhatsApp».
  La app tiene una versión reciente. La causa más probable es la estructura, que elaina declara solo para Android.
  No lo comprobamos en otra versión de iOS.
- WhatsApp Web (observación del usuario el 2026-10-11, Chrome 155 en Linux): las cuatro variantes que cargaron
  abrieron en otra pestaña. El servidor lo confirma: `framed=0` y el agente es el Chrome normal del escritorio.
  Los campos de webview no cambian nada en Web. El usuario cree que Web siempre abre los enlaces en otra pestaña;
  ninguna de las fuentes revisadas documenta otra forma de abrirlos.
- `open_webview` en Web: WhatsApp muestra «No se pudo cargar este mensaje. Abre el mensaje en tu teléfono para verlo».
  El servidor no registró ninguna carga de la página.
- Lo que separa `cta_url` de `cta_url_webview` son los campos del botón (`webview_interaction`, `landing_page_url`)
  y los `tap_target` de `messageParamsJson`. El nodo `biz` es el mismo en las dos.

Android queda `not_tested`: el usuario no tiene un teléfono Android para esta prueba.

## Veredicto

**Cumple parcialmente.** No demuestra el objetivo en los tres clientes.

| Requisito | Resultado |
|---|---|
| Sin Cloud API ni Flow registrado | Cumple: puente Baileys existente y nuestro backend. |
| Dentro de Android | Sin comprobar: no hubo un teléfono Android. |
| Dentro de iPhone | Cumple con `cta_url_webview` y `cta_url_webview_fork`. |
| Dentro de WhatsApp Web | No cumple: todas las variantes abren en otra pestaña. |
| Datos en nuestro backend | Cumple en iPhone y Web, con el identificador de ejecución. |
| Continuación en el mismo chat | Cumple: el bot confirmó en el chat, citando el mensaje de apertura. |
| Reintentos seguros | Cumple en la prueba E2E. |
| Cierre sin guardar | Cumple en la prueba E2E: el bot no anuncia nada. |

El límite exacto es WhatsApp Web: abre la URL del botón en una pestaña nueva del navegador, con o sin los campos de webview.
El recorrido formulario → backend → confirmación sí funciona desde esa pestaña, porque no depende de dónde abre la página.
Si se usa, la receta para el iPhone es `cta_url_webview`: es la más pequeña de las dos que abren dentro.

## Qué pasó después

Vinci usa ahora la receta `cta_url_webview` para el formulario del token y el panel de entregas.
La ruta definitiva es `POST /send-url-button` (`hermes/whatsapp/url_button.js`), que `setup.sh` instala.
Lo que la página manda de vuelta pasa por el relé de Vinci en Cloudflare Workers (`relay/`), no por este backend.

Para repetir este experimento, `bridge/install.sh` reemplaza el `bridge_script` que deja `setup.sh`.
Al terminar, corre `bridge/uninstall.sh` y después `./setup.sh` para volver al puente de Vinci.
