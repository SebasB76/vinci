# Instalación

> **Solo WhatsApp (lo normal).** El `config.toml` trae `[channels] telegram = false`: Vinci te habla solo por
> WhatsApp. En ese caso no necesitas Telegram: salta los pasos 1, 2 y 7, y en `secrets.env` pon `CANVAS_TOKEN` y
> `WHATSAPP_CAPTAIN` en vez de los dos de Telegram. Después sigue [whatsapp.md](whatsapp.md) para vincular el
> número de Vinci. Esta guía describe también la instalación con Telegram (`telegram = true`).

## Requisitos

- **Una PC con Linux** que quede encendida mientras quieras que los bots funcionen (se usa en Arch / Omarchy).
- **[Hermes Agent](https://github.com/NousResearch/hermes-agent)** instalado en `~/.local/bin/hermes` (o en la
  ruta que pongas en `HERMES_BIN`), con un modelo de **Anthropic** configurado con `hermes model`. Vinci usa
  `claude-haiku-5-5` (`modelo` en `config.toml`). Si a Hermes le falta su conector de Telegram, el setup lo instala.
- **Python 3.11 o más nuevo** y, de preferencia, [uv](https://docs.astral.sh/uv/) (`sudo pacman -S uv`). Sin uv,
  el setup usa `python -m venv`.
- **Una cuenta de Telegram** y **tu cuenta institucional** del aula virtual.
- Opcional: [Claude Code](https://claude.com/claude-code), para usar la skill `aula`.

## Inicio rápido

Si ya tienes Hermes funcionando y sabes crear un bot con @BotFather:

```bash
git clone https://github.com/SebasB76/vinci.git
cd vinci
./setup.sh          # la primera vez instala las dependencias, crea secrets.env y se detiene
nano secrets.env    # CANVAS_TOKEN, TELEGRAM_BOT_TOKEN (el bot de Vinci) y TELEGRAM_USER_ID
# en Telegram: mándale /start a tu bot nuevo
./setup.sh          # configura Vinci en Hermes y prueba el aula y Telegram
hermes gateway install && hermes gateway start
```

Después, en Telegram: escríbele a Vinci **«arma mi equipo»**, pulsa «➕ Crear» en cada materia y mándale una
captura de tu horario. La [instalación paso a paso](#paso-a-paso) explica cada parte.

## Paso a paso

Vas a tener un bot de Telegram para Vinci y uno por cada materia. El de Vinci lo creas tú (paso 1); los de las
materias los crea Vinci contigo desde el chat (paso 7).

### 1. Crea el bot de Vinci con @BotFather

1. En Telegram abre [@BotFather](https://t.me/BotFather) y envía `/newbot`.
2. Ponle de nombre **Vinci** y un usuario que termine en `bot` (por ejemplo `mi_vinci_bot`).
3. BotFather te da un **token** como `123456789:ABCdef…`. Va en `TELEGRAM_BOT_TOKEN`.
4. Usa un bot **nuevo**, distinto de cualquier otro que ya uses con Hermes: Hermes no deja que dos perfiles usen
   el mismo token.
5. Abre el chat con tu bot nuevo y envíale `/start` (un bot no puede escribirte primero).
6. **Recomendado:** en @BotFather abre la Mini App, elige a Vinci y activa la opción que le permite **gestionar
   otros bots**. Así Vinci crea cada bot de materia con un solo toque tuyo. Si no la activas (o tu Telegram no la
   muestra), también funciona: Vinci te guía para crearlos con `/newbot`.

### 2. Averigua tu ID de Telegram

Escríbele a [@userinfobot](https://t.me/userinfobot): te responde con tu **ID numérico** (no es tu @usuario). Va
en `TELEGRAM_USER_ID` y es la única persona a la que le responderán tus bots.

### 3. Crea el token del aula virtual

1. Entra a [aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec) con tu cuenta institucional.
2. Ve a **Cuenta → Configuración** y baja hasta **Integraciones aprobadas**.
3. Pulsa **Nuevo token de acceso**. En *Propósito* escribe, por ejemplo, «Vinci», y en *Fecha de vencimiento*
   pon el **fin del término**: si algún día se filtra, deja de servir solo.
4. Pulsa **Generar token** y cópialo **en ese momento** (Canvas no lo vuelve a mostrar). Va en `CANVAS_TOKEN`.

Ese token puede hacer en el aula lo mismo que tú, así que trátalo como una contraseña. Vinci lo usa para leer tus
datos académicos y para crear/borrar únicamente sus propios tokens de reemplazo. Nunca publica ni cambia
cursos, y solo entrega una actividad cuando pulsas «📤 Entregar». ESPOL actualmente invalida cada token personal al cabo de una hora aunque muestre otra fecha; Vinci lo
renueva antes de que ocurra.

### 4. Completa `secrets.env`

```bash
cp secrets.env.example secrets.env   # o corre ./setup.sh una vez: lo crea por ti
chmod 600 secrets.env
nano secrets.env
```

```ini
CANVAS_TOKEN=…            # paso 3
TELEGRAM_BOT_TOKEN=…      # paso 1, el bot de Vinci (solo con telegram = true)
TELEGRAM_USER_ID=…        # paso 2 (solo con telegram = true)
WHATSAPP_CAPTAIN=…        # tu número de WhatsApp (con telegram = false; ver whatsapp.md)
```

`secrets.env` está en `.gitignore`: nunca se sube a GitHub. Los tokens de los bots de materia
(`TELEGRAM_BOT_TOKEN_<CÓDIGO>`) no los escribes tú: Vinci los agrega cuando crea cada bot.

### 5. Corre el setup

```bash
./setup.sh
```

Puedes correrlo las veces que quieras: si no cambiaste nada, no cambia nada. Hace esto:

- revisa Python y Hermes, e instala las dependencias en `.venv/`;
- si tienes `tesseract`, le baja los modelos de español e inglés a la carpeta de datos para el OCR de los PDF
  escaneados (si no, te dice cómo instalarlo; es opcional);
- si a Hermes le falta su conector de Telegram, lo instala (`hermes pm install --extra telegram`);
- instala el comando `aula` en `~/.local/bin/` y la skill de Claude Code en `~/.claude/skills/aula/`;
- crea o actualiza el perfil `vinci` de Hermes (modelo, zona horaria, Telegram solo para tu ID, sus
  herramientas, el cron del sondeo y el del resumen de las 7:00) y el perfil de cada bot de materia que ya
  exista, y comprueba que la skill de cada bot llegue de verdad a su prompt (sin llamar al modelo);
- le pone a Vinci su foto de perfil en Telegram, y a cada bot de materia su nombre y su foto (mira
  [La foto de cada bot](#la-foto-de-cada-bot));
- prueba que el aula virtual responde (si rechaza tu token, te lo dice) y Vinci te manda un mensaje de prueba,
  avisándote si todavía falta activar lo de gestionar otros bots.

Opciones: `--skip-deps` no toca el entorno de Python y `--sin-pruebas` no consulta el aula ni manda el mensaje de
prueba. Fuera de esta carpeta solo modifica `~/.hermes/profiles/vinci*/`, `~/.local/bin/vinci`,
`~/.local/bin/aula`, `~/.claude/skills/aula/` y, si le falta, el conector de Telegram de Hermes
(`./setup.sh --help` lo lista). Nunca toca tu perfil por defecto de Hermes.

### 6. Enciende el gateway de Hermes

Un solo gateway atiende a Vinci, a todos tus bots de materia y a tu Hermes personal, si lo usas:

```bash
hermes gateway install     # una sola vez (si ya usas el gateway de Hermes, sáltate esto)
hermes gateway start
```

Si el gateway ya estaba encendido y la instalación cambió las herramientas de un bot, usa
`hermes gateway restart` (con `start` los bots siguen con las herramientas viejas). Un chat ya abierto conserva su
prompt y sus herramientas hasta `/new`.

Queda en segundo plano y arranca con tu sesión. Para que siga funcionando con la sesión cerrada:
`sudo loginctl enable-linger "$USER"`.

### 7. Arma tu equipo de bots desde el chat

Escríbele a Vinci **«arma mi equipo»**. Lee tus materias del aula y te muestra el equipo propuesto, con un botón
**«➕ Crear»** por materia. Un bot se crea solo cuando pulsas su botón:

- **Si activaste «gestionar otros bots»:** Vinci te manda un botón «🤖 Crear …». Al pulsarlo, Telegram te muestra
  el bot nuevo con su nombre y su usuario ya sugeridos (puedes cambiarlos). Confirmas y listo: Vinci recibe el bot
  directo de Telegram y lo configura. El token nunca pasa por el chat.
- **Si no:** Vinci te dice qué nombre y qué usuario ponerle. En @BotFather envía `/newbot`, créalo y **reenvíale a
  Vinci la respuesta de BotFather** (la que trae el token). Vinci guarda el token y **borra ese mensaje del chat**.

En los dos casos Vinci te confirma «✅ … quedó creado y activo», y el bot ya tiene el nombre de su materia. Ábrelo
y mándale `/start`: te saluda y te dice cuándo llega su próximo brief. El gateway toma cada bot nuevo en menos de
un minuto, sin reiniciar nada. Repite con cada materia.

### 8. Mándale tu horario a Vinci (una sola vez)

Toma una **captura de tu horario** donde se vea **la columna de las horas** y mándasela a Vinci. Te muestra cómo
lo entendió, clase por clase, con dos botones:

- **✅ Guardar horario**: lo guarda en `horario.toml`.
- **✏️ Corregir**: le dices qué está mal («Física el jueves es de 14:30») y te muestra otra propuesta.

No se guarda nada hasta que pulses Guardar. Desde ahí, cada bot de materia te manda su brief 30 minutos antes de
cada clase. Dos bloques seguidos de la misma materia (el teórico y justo después el práctico) reciben un solo
brief, antes del primero. Si tu horario cambia, mándale otra captura.

## Configuración

Todo lo ajustable está en [`config.toml`](../../config.toml). Después de cambiarlo, corre `./setup.sh` otra vez.

| Clave | Por defecto | Qué hace |
|---|---|---|
| `canvas.url` | `https://aulavirtual.espol.edu.ec` | Tu aula virtual |
| `canvas.cache_minutos` | `10` | Cuánto tiempo `aula` y los bots reutilizan los datos guardados antes de volver a leer el aula |
| `canvas.request_interval_seconds` | `1.0` | Pausa mínima entre dos consultas del sondeo al aula (lo que preguntas en Telegram no espera) |
| `dashboard.url` | `https://sebasb76.github.io/vinci/dashboard/` | La página del botón «📋 Entregas». Vacío (`""`): sin dashboard, y el chat vuelve a su botón de menú de siempre |
| `dashboard.semester_end` | `"2027-01-15"` | Último día de clases (`AAAA-MM-DD`) para la línea del semestre. Vacío: el fin del periodo según el aula, que también cuenta exámenes y recuperación |
| `general.zona_horaria` | `America/Guayaquil` | Zona para fechas, horarios y briefs |
| `channels.telegram` | `false` | `false`: Vinci te habla solo por WhatsApp (necesita `WHATSAPP_CAPTAIN`) y lleva todas tus materias en un chat; los bots de materia quedan apagados, sin borrarse. `true`: también Telegram, con un bot por materia |
| `notificaciones.intervalo_minutos` | `10` | Cada cuánto revisa el aula (mínimo 5) |
| `notificaciones.recordatorios_horas` | `[24, 3]` | Recordatorios antes de cada entrega no enviada |
| `notificaciones.resumen_diario` | `"07:00"` | Hora del resumen de la semana |
| `notificaciones.max_mensajes_por_sondeo` | `8` | Con más avisos que esto en una revisión, llegan en un solo mensaje |
| `clases.brief_minutos_antes` | `30` | Minutos antes de cada clase en que llega el brief (entre 5 y 180) |
| `material.extensiones` | `["pdf", "pptx", "docx", "doc", "xlsx"]` | Qué archivos del aula leen los bots (además de las páginas web de un enlace) |
| `material.tamano_maximo_mb` | `200` | Nada más grande que esto se baja |
| `material.max_mb_per_sync` | `50` | Cuántos MB de sílabos baja como máximo cada sondeo; los demás, en los siguientes |
| `notes.folder` | `~/Notes` | Tu carpeta de apuntes en Markdown ([cómo](uso.md#tus-apuntes-de-clase)); vacía, no la lee |
| `notes.idle_minutes` | `15` | Minutos sin cambios para dar una nota por terminada (entre 5 y 240) |
| `almacenamiento.carpeta_datos` | `~/.local/share/espol-academic-bot` | Base de datos, material y cuadernos |
| `hermes.perfil` | `vinci` | Perfil de Vinci; cada materia usa `<perfil>-<código>` |
| `hermes.proveedor` · `hermes.modelo` | `anthropic` · `claude-sonnet-5-5` | Modelo de Vinci y de los bots de materia |

Otros archivos que puedes editar:

- **`materias.toml`** (en la carpeta de datos): tu equipo. Lo escribe Vinci; puedes cambiar a mano el `nombre` de
  una materia, y su bot se llama así.
- **`horario.toml`** (en la carpeta de datos): tu horario, una sección `[[clase]]` por bloque, de lunes a sábado.
  Vinci guarda una copia del anterior cada vez que lo cambia.
- **[`hermes/characters.toml`](../../hermes/characters.toml)**: la foto de perfil de cada bot y, si quieres, un nombre
  corto para una materia de nombre largo. Mira [La foto de cada bot](#la-foto-de-cada-bot).

### La foto de cada bot

Vinci es el mago azul. Cada bot de materia puede tener su propia foto, y un nombre corto si el de la materia es
muy largo, por su **código ESPOL** en `hermes/characters.toml` (así el teórico y el práctico comparten la suya):

```toml
[vinci]
avatar = "wizard.jpg"

[subjects.MATG1049]                    # el código de la materia, sin el paralelo
subject = "Cálculo de una Variable"    # su nombre oficial
name = "Cálculo"                       # opcional: el nombre del bot en Telegram (máximo 64 caracteres)
avatar = "calculo.jpg"                 # una foto cuadrada en JPG, en hermes/avatars/
```

Corre `./setup.sh` y cada bot se pone su foto (y su nombre) con su propio token; también lo hace el bot que Vinci
crea desde el chat. Se ponen una sola vez por bot: si después cambias la foto a mano en Telegram, se queda la
tuya. Una materia sin sección se llama como su `nombre` en `materias.toml` y conserva la foto que tenga.

El `characters.toml` que viene en el repositorio es **un ejemplo**: las materias de un semestre del autor, con su
party en pixel art. Así se ve un equipo con fotos:

<table>
  <tr>
    <td align="center"><img src="../../hermes/avatars/wizard.jpg" width="64" alt=""><br><sub><b>Vinci</b></sub></td>
    <td align="center"><img src="../../hermes/avatars/robot.jpg" width="64" alt=""><br><sub>Ingeniería de Software I</sub></td>
    <td align="center"><img src="../../hermes/avatars/builder.jpg" width="64" alt=""><br><sub>Dirección de Proyectos Informáticos</sub></td>
    <td align="center"><img src="../../hermes/avatars/server.jpg" width="64" alt=""><br><sub>Sistemas Distribuidos</sub></td>
    <td align="center"><img src="../../hermes/avatars/book.jpg" width="64" alt=""><br><sub>Estadística</sub></td>
    <td align="center"><img src="../../hermes/avatars/sprout.jpg" width="64" alt=""><br><sub>Ciencias de la Sostenibilidad</sub></td>
  </tr>
</table>

Cámbialo por tus materias (o deja solo `[vinci]`): Vinci recibe esa lista en sus instrucciones como los nombres de
los bots del semestre. Si una de tus materias tiene el mismo código que una del ejemplo, su bot tomará esa foto y
ese nombre.

## Actualizar y desinstalar

Para actualizar, trae los cambios y corre el setup otra vez; actualiza los perfiles y los cron en su lugar, sin
duplicarlos ni crear bots nuevos:

```bash
git pull
./setup.sh
```

Si venías del bot académico anterior (el perfil `espol`), el setup lo convierte en Vinci conservando su memoria.

Con `channels.telegram = false`, el setup apaga cada perfil `vinci-<código>` con un archivo `gateway.parked` y saca
el token de Telegram del perfil de Vinci; no borra nada. Con `true` y otro `./setup.sh`, vuelven los bots.

Para desinstalar:

```bash
hermes gateway stop                              # si solo lo usabas para Vinci: hermes gateway uninstall
hermes profile list                              # vinci y un vinci-<código> por materia
hermes profile delete vinci                      # y lo mismo con cada vinci-<código>
rm ~/.local/bin/aula && rm -r ~/.claude/skills/aula
rm -r ~/.local/share/espol-academic-bot          # borra también el material y los cuadernos
```

Los bots de Telegram los borras en @BotFather (`/deletebot`), y el token del aula en **Cuenta → Configuración →
Integraciones aprobadas**.
