# espol-academic-bot

**Vinci** y tu equipo de bots de materia para ESPOL. Leen tu aula virtual
([aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec), que es Canvas) y te acompañan por Telegram:

- **Vinci** es el bot principal. Le preguntas lo que quieras de cualquier materia, le mandas «tengo esto de
  Estadística» (texto, foto, PDF o nota de voz) y se lo pasa al bot de esa materia. También es el que **crea tu
  equipo de bots** desde el chat.
- **Un bot por materia** («El Analítico · Estadística», «El Programador · Ing. Software I»…), que cubre su teórico
  y su práctico (en el aula son dos cursos, como `Paralelo5_ESTG1034` y `Paralelo105_ESTG1034`), cada uno con su propia
  memoria y su **cuaderno** (lo que se vio en clase, fotos de la pizarra, audios, dudas). Le puedes escribir
  directo a cualquiera.
- **Cada bot con su personaje** ([tu party](#tu-party-el-personaje-de-cada-bot)): Vinci es el «Guía Académico»
  (un mago azul) y cada materia tiene el suyo, «El Programador», «El Estratega», «El Conector», «El Analítico» y
  «El Equilibrio», que le da su nombre, su foto de perfil en Telegram y su forma de hablar. Es solo el tono: lo
  que cada bot puede hacer no cambia.
- **Llegas listo a cada clase**: 30 minutos antes, el bot de la materia te manda un brief con un repaso de la
  clase anterior, lo que vence, el material nuevo, 3 a 5 conceptos clave y una pregunta para la clase.
- **Avisos del aula virtual** (revisa cada 30 minutos): tareas nuevas, cambios de fecha, anuncios, notas y
  material nuevo; recordatorios 24 h y 3 h antes de cada entrega que aún no enviaste, y un resumen de la semana
  a las 7:00. Te los manda Vinci, con un botón para **consultarlo con el bot de la materia**.
- **Preguntas sobre el material** (PDF, PPTX y DOCX): explicar un tema, resumir un capítulo o hacerte preguntas
  tipo examen, citando archivo, página y el enlace del aula virtual.
- El comando **`aula`** para consultar todo desde la terminal, y una skill para que **Claude Code** en tu PC
  también pueda usarlo.

Es **solo lectura**: nunca entrega, publica, comenta ni cambia nada en el aula virtual. Todos los bots te
responden solo a ti, y todos los datos se quedan en tu PC.

## Cómo está armado

```
aula_core   núcleo reutilizable: cliente de Canvas (solo GET), base de datos local (SQLite),
            descarga e indexado del material. No sabe nada de Telegram ni de Hermes.
aula        la herramienta de línea de comandos, encima del núcleo.
espol_bot   Vinci y los bots de materia: sondeo y avisos, agenda de briefs, cuadernos, horario,
            el equipo de bots y las herramientas fijas que usa cada bot.
hermes/     las plantillas de cada bot (personalidad, instrucciones y el filtro de botones y tokens),
            los personajes de tu party (characters.toml) y sus fotos (avatars/).
```

Todo corre en tu **Hermes Agent** (el mismo que ya usas, con tu mismo login), cada bot en **su propio perfil**:
`vinci` para Vinci y `vinci-<código>` para cada materia (ej. `vinci-estg1034`). No toca tu perfil por defecto.

Lo que no necesita pensar **no usa el modelo ni gasta tokens**: los avisos, los recordatorios, el resumen de las
7:00 y la agenda que decide cuándo toca un brief son scripts fijos. Solo gastan tokens tus preguntas, lo que le
pasas a un bot y escribir cada brief.

Los bots no tienen terminal ni acceso libre a tus archivos: solo un juego fijo de herramientas. Vinci lee el
aula virtual de todas tus materias, lee (sin poder escribir) los cuadernos y busca en la web. Cada bot de materia
ve solo su materia, escribe solo en su cuaderno y no busca en la web.

## Instalación

Necesitas: tu PC con Arch/Omarchy, Hermes Agent instalado (`~/.local/bin/hermes`), Python 3.11+ y
[uv](https://docs.astral.sh/uv/) (`sudo pacman -S uv`; sin uv el setup usa `python -m venv`).

Vas a tener **6 bots de Telegram**: Vinci y uno por cada una de tus 5 materias. El de Vinci lo creas tú a mano
(paso 1); los otros 5 los crea Vinci contigo desde el chat (paso 7).

### 1. Crea el bot de Vinci con @BotFather

1. En Telegram abre [@BotFather](https://t.me/BotFather) y envía `/newbot`.
2. Ponle de nombre **Vinci** y un usuario que termine en `bot` (ej. `mi_vinci_bot`).
3. BotFather te da un **token** como `123456789:ABCdef...`. Guárdalo: va en `TELEGRAM_BOT_TOKEN`.
4. Usa un bot **nuevo**, distinto al de tu bot de X (Hermes no deja que dos perfiles usen el mismo token).
5. Abre el chat con tu nuevo bot y envíale `/start` (Telegram no deja que un bot te escriba primero).
6. **Recomendado:** en @BotFather abre la Mini App (el botón para abrir la app), elige a Vinci y activa la opción
   que le permite **gestionar otros bots**. Así Vinci crea cada bot de materia con un solo toque tuyo. Si no la
   activas (o tu Telegram no la muestra), también funciona: Vinci te guía para crearlos con `/newbot`.

### 2. Averigua tu ID de Telegram

Escríbele a [@userinfobot](https://t.me/userinfobot); te responde con tu **ID numérico** (ej. `987654321`).
No es tu @usuario. Va en `TELEGRAM_USER_ID` y es el único usuario al que responderán tus bots.

### 3. Crea el token del aula virtual

1. Entra a [aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec) con tu cuenta institucional.
2. Ve a **Cuenta → Configuración** y baja hasta la sección **Integraciones aprobadas**.
3. Pulsa **Nuevo token de acceso**. En *Propósito* escribe «Bot académico» y en *Fecha de vencimiento*
   pon el **fin del término** (unos 4 meses). Así, si algún día se filtra, deja de servir solo.
4. Pulsa **Generar token** y copia el token **en ese momento** (Canvas no lo vuelve a mostrar).
   Va en `CANVAS_TOKEN`.

Ese token puede hacer lo mismo que tú en el aula virtual, así que trátalo como una contraseña: no lo
compartas ni lo subas a ningún lado. Los bots solo lo usan para leer. Cuando venza, Vinci te avisa por Telegram;
crea otro, cámbialo en `secrets.env` y listo (no hace falta reiniciar nada).

### 4. Completa `secrets.env`

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
nano secrets.env        # CANVAS_TOKEN, TELEGRAM_BOT_TOKEN (el de Vinci), TELEGRAM_USER_ID
```

`secrets.env` está en `.gitignore`: nunca se sube a GitHub. Los tokens de los bots de materia no los escribes
tú: Vinci los agrega aquí cuando crea cada bot.

### 5. Corre el setup

```bash
./setup.sh
```

Puedes correrlo las veces que quieras (por ejemplo, después de cambiar `config.toml`). Hace esto:

- instala las dependencias de Python en `.venv/`;
- si a Hermes le falta su conector de Telegram, lo instala (`hermes pm install --extra telegram`);
- instala el comando `aula` en `~/.local/bin/` y la skill de Claude Code en `~/.claude/skills/aula/`;
- crea o actualiza el perfil de Hermes `vinci` (modelo, zona horaria, Telegram solo para tu ID, sus herramientas
  y los cron del sondeo cada 30 min y el resumen de las 7:00), y el perfil de cada bot de materia que ya exista;
- le pone a cada bot la foto de su personaje en Telegram, y a cada bot de materia su nombre (una sola vez; mira
  [Tu party](#tu-party-el-personaje-de-cada-bot));
- prueba que Canvas responde y Vinci te manda un mensaje de prueba por Telegram (y te dice si todavía falta
  activar lo de gestionar otros bots del paso 1).

Si venías del bot anterior (el perfil `espol`), lo convierte en Vinci conservando su memoria.
No modifica tu perfil por defecto de Hermes (`~/.hermes/config.yaml`, `~/.hermes/.env`) ni otros perfiles.

### 6. Enciende el gateway de Hermes

Un solo gateway de Hermes atiende a Vinci y a todos tus bots de materia (y a tu Hermes personal, si lo usas):

```bash
hermes gateway install     # una sola vez (si ya usas el gateway de Hermes, sáltate esto)
hermes gateway start
```

Queda en segundo plano y arranca con tu sesión. Para que siga funcionando con la sesión cerrada:
`sudo loginctl enable-linger "$USER"`.

### 7. Arma tu equipo de bots desde el chat

Escríbele a Vinci **«arma mi equipo»**. Lee tus materias del aula virtual y te muestra el equipo propuesto, con
un botón **«➕ Crear»** por materia (el teórico y el práctico de una materia van juntos en un solo bot: sus tareas,
anuncios, archivos, notas y clases). Un bot se crea solo cuando tú pulsas su botón:

- **Si activaste «gestionar otros bots»** (paso 1): Vinci te manda un botón «🤖 Crear <bot>» (ej. «🤖 Crear El
  Analítico · Estadística»).
  Al pulsarlo, Telegram te muestra el bot nuevo con su nombre y usuario ya sugeridos (puedes cambiarlos);
  confirmas y listo: Vinci recibe el bot directamente de Telegram y lo configura solo.
- **Si no**: Vinci te dice el nombre y el usuario que le puedes poner. En @BotFather envía `/newbot`, créalo y
  **reenvíale a Vinci la respuesta de BotFather** (la que trae el token). Vinci guarda el token, **borra ese
  mensaje del chat** y configura el bot.

En los dos casos, Vinci te confirma «✅ <bot> quedó creado y activo», y el bot ya tiene el nombre, la foto y
la personalidad de su personaje. Abre el bot nuevo y mándale
`/start`. Repite con cada materia (5 en total). Si el gateway ya estaba encendido, toma cada bot nuevo en
unos 30 segundos; no hace falta reiniciar nada.

Vinci nunca ve los tokens: un filtro los atrapa antes de que lleguen al modelo, los guarda en `secrets.env`
(permisos 600) y borra el mensaje. No le pegues tokens en otros lados.

### 8. Mándale tu horario a Vinci (una sola vez)

Toma una **captura de tu horario de clases** donde se vea **la columna de las horas** (sin ella no se sabe a qué
hora empieza cada clase) y mándasela a Vinci. Te muestra cómo lo entendió, clase por clase, con dos botones:

- **✅ Guardar horario**: lo guarda (en `horario.toml`, en la carpeta de datos).
- **✏️ Corregir**: dile qué está mal («Estadística el jueves es de 9:00») y te muestra otra propuesta.

No se guarda nada hasta que pulses Guardar. Desde ahí, cada bot de materia te manda su brief 30 minutos antes de
cada clase (hora de Ecuador). Una clase que no está en el horario no recibe brief. Si tu horario cambia, mándale
otra captura.

## Encender y apagar

```bash
hermes gateway start       # encender
hermes gateway stop        # apagar (apaga también tu Hermes personal en Telegram, si lo usas)
hermes gateway status      # ¿está corriendo?
vinci cron list            # los trabajos de Vinci: sondeo y resumen
tail -f ~/.hermes/logs/gateway.log                    # registro del gateway de Hermes
tail -f ~/.local/share/espol-academic-bot/bot.log     # registro del sondeo, la agenda y los botones
```

`vinci` es el alias que Hermes crea para el perfil; si no está en tu PATH usa `hermes -p vinci ...`.

El primer sondeo te manda un mensaje de bienvenida con tus materias; desde ahí Vinci solo te escribe cuando hay
algo nuevo o algo falla. Si una parte de una materia (sus tareas, anuncios o archivos) no se puede leer tres veces
seguidas, te avisa una sola vez nombrando la materia y la parte, sigue reintentando y el resto funciona normal;
si vuelve a fallar después de recuperarse, te avisa de nuevo. Para forzar una revisión ahora:
`vinci cron run vinci-sondeo`.

## Uso

**Con Vinci** (en Telegram):

- «¿Qué tengo pendiente esta semana y en qué orden lo hago?» / «¿Qué dijo el profe de Estadística?»
- «Tengo esto de Sistemas Distribuidos» + una foto, un PDF o una nota de voz → te dice a qué bot se lo pasó. Si
  no le queda claro de qué materia es, te pregunta antes.
- «¿Qué hay en el cuaderno de Ingeniería de Software?» (Vinci lee los cuadernos, pero no los cambia).
- Bajo cada aviso del aula hay un botón **«🎓 Consultar con <bot>»** (ej. «🎓 Consultar con El Analítico ·
  Estadística»): el bot de esa materia recibe el
  aviso y te escribe en su chat. También puedes responder al aviso con «pásaselo al de la materia».
- «Arma mi equipo» / «archiva el bot de Estadística» (siempre te pide confirmar con un botón).

**Con cada bot de materia** (escríbele directo):

- «Hoy vimos intervalos de confianza» → lo anota en su cuaderno.
- Una foto de la pizarra o una nota de voz → la guarda en el cuaderno con un resumen.
- «No entendí la prueba de hipótesis» → te lo explica con el material del curso y lo anota como duda.
- «Explícame el capítulo 3» / «Hazme 5 preguntas tipo examen».

Cada bot recuerda sus conversaciones (memoria propia) y usa su cuaderno para los briefs.

**En la terminal** con `aula` (añade `--json` para salida de máquina):

```bash
aula cursos
aula tareas                       # pendientes, por fecha de entrega
aula tareas --curso estadistica --dias 7
aula anuncios --curso software
aula notas
aula archivos --curso nube --nombre "semana 3"
aula archivos bajar 5001          # descarga (y lo indexa) en ~/.local/share/espol-academic-bot/materiales/
aula archivos leer 5001 --paginas 2-3
aula buscar "teorema del límite central"
aula sincronizar --material       # leer todo ahora y bajar el material nuevo
```

`--curso` acepta cualquier parte del nombre o del código, sin tildes. `aula` reutiliza los datos guardados si
tienen menos de 10 minutos; si no, vuelve a leer el aula virtual.

**Con Claude Code**: en cualquier sesión de Claude Code en tu PC puedes pedir
«bájate el PDF de la semana 3 de Estadística y explícame el ejercicio 4»; la skill `aula` le enseña a usar el
comando.

## Tu party: el personaje de cada bot

| | Bot | Materia | Personaje |
|---|---|---|---|
| <img src="hermes/avatars/wizard.jpg" width="56" alt=""> | **Vinci** | todas | «Guía Académico», un mago azul con su báculo |
| <img src="hermes/avatars/robot.jpg" width="56" alt=""> | **El Programador · Ing. Software I** | Ingeniería de Software I (SOFG1007) | un robot verde |
| <img src="hermes/avatars/builder.jpg" width="56" alt=""> | **El Estratega · Dir. Proyectos** | Dirección de Proyectos Informáticos (CCPG1041) | con casco de obra y engranaje |
| <img src="hermes/avatars/server.jpg" width="56" alt=""> | **El Conector · Sist. Distribuidos** | Sistemas Distribuidos y Computación en la Nube (CCPG1055) | un servidor morado |
| <img src="hermes/avatars/book.jpg" width="56" alt=""> | **El Analítico · Estadística** | Estadística (ESTG1034) | un libro azul con lentes |
| <img src="hermes/avatars/sprout.jpg" width="56" alt=""> | **El Equilibrio · Sostenibilidad** | Ciencias de la Sostenibilidad (ADSG1026) | un brote verde |

Solo el bot principal se llama Vinci. Cada bot de materia se llama como su personaje y su materia, en corto (como
en el arte de la party), para que tu lista de chats de Telegram se lea sola.

- **La foto y el nombre** los pone cada bot con su propio token (`setMyProfilePhoto` y `setMyName` del Bot API
  de Telegram): los de Vinci cuando corres `./setup.sh` (a Vinci solo la foto) y los de cada bot de materia
  cuando Vinci lo crea, lo hayas creado con un toque o con @BotFather. No tienes que hacer nada. Se ponen una
  sola vez por bot: si después le cambias la foto o el nombre a mano, se queda lo tuyo.
- **Si ya tenías bots de materia** con el nombre de antes («Vinci · Estadística»), `./setup.sh` les cambia el
  nombre y les pone su foto ahí mismo: son los mismos bots, con su chat, su memoria y su cuaderno; no se crea
  ninguno nuevo. Su usuario (@…) no cambia: Telegram no deja cambiarlo.
- **Si Telegram no lo acepta** (por ejemplo, sin internet), `setup.sh` te avisa y lo reintenta la próxima vez que
  lo corras. También puedes hacerlo a mano en @BotFather: `/setuserpic` (elige el bot y mándale su foto de
  [`hermes/avatars/`](hermes/avatars)) y `/setname`.
- **La personalidad** va en el `SOUL.md` de cada bot: su tono y su estilo. No cambia sus herramientas ni sus
  reglas (solo lectura del aula virtual, solo te responde a ti, sin terminal ni archivos).
- Los personajes van por el **código de la materia**, así que el teórico y el práctico comparten el suyo. Una
  materia sin personaje (por ejemplo, las del próximo semestre) tiene un bot con el tono de siempre y la foto que
  ya tenga, y se llama como la materia (el `nombre` de `materias.toml`). Para darle uno: pon su foto cuadrada en
  JPG (ej. 640×640) en `hermes/avatars/`, agrega una sección `[subjects.<CÓDIGO>]` en
  [`hermes/characters.toml`](hermes/characters.toml) y corre `./setup.sh`.
- Si cambias la foto o el nombre de un personaje, `./setup.sh` los pone otra vez. Para volver a poner los mismos,
  borra `~/.hermes/profiles/<perfil del bot>/telegram-profile.json` (el registro de qué ya se puso) y corre
  `./setup.sh`.

## Fin de semestre: archivar los bots

Pídele a Vinci «archiva el bot de Estadística» y confirma con el botón. Un bot archivado deja de responder y de
mandar briefs, pero **conserva su memoria y su cuaderno**. Para volver a usarlo: «reactiva el bot de Estadística»
y confirma con el botón.
El semestre siguiente, «arma mi equipo» te propone las materias nuevas.

## Configuración

Todo lo ajustable está en [`config.toml`](config.toml):

| Clave | Por defecto | Qué hace |
|---|---|---|
| `notificaciones.intervalo_minutos` | `30` | cada cuánto revisa el aula virtual |
| `notificaciones.recordatorios_horas` | `[24, 3]` | recordatorios antes de cada entrega no enviada |
| `notificaciones.resumen_diario` | `"07:00"` | hora del resumen de la semana |
| `clases.brief_minutos_antes` | `30` | cuántos minutos antes de cada clase llega el brief |
| `general.zona_horaria` | `America/Guayaquil` | zona para fechas, horarios y briefs |
| `material.extensiones` | `pdf, pptx, docx` | qué archivos se descargan e indexan |
| `material.tamano_maximo_mb` | `60` | archivos más grandes no se descargan |
| `almacenamiento.carpeta_datos` | `~/.local/share/espol-academic-bot` | base de datos, material y cuadernos |
| `hermes.perfil` | `vinci` | perfil de Vinci; cada materia usa `<perfil>-<código>` |
| `hermes.modelo` | `claude-sonnet-5` | modelo de Vinci y de los bots de materia |

Después de cambiarlo corre `./setup.sh` otra vez (la frecuencia y la hora del resumen viven en los cron de Hermes).

## Tus datos

Todo queda en tu PC, en `~/.local/share/espol-academic-bot/`:

- `espol.db`: tus materias, tareas, anuncios, notas, archivos y el índice del material;
- `materiales/<código de la materia>/`: los archivos descargados;
- `materias.toml`: tu equipo de bots, con los cursos del aula de cada materia (puedes cambiar el `nombre` de una
  materia a mano; un bot sin personaje se llama así);
- `horario.toml`: tu horario guardado (puedes editarlo a mano; Vinci guarda una copia del anterior cada vez que
  lo cambia);
- `cuadernos/<CÓDIGO>/`: el cuaderno de cada materia (`cuaderno.db`) y sus fotos, audios y documentos;
- `bot.log`: registro del sondeo, la agenda y los botones.

La memoria y las conversaciones de cada bot las guarda Hermes en su perfil (`~/.hermes/profiles/vinci-<código>/`).

## Seguridad

- El cliente de Canvas solo sabe hacer peticiones `GET`: no hay forma de entregar, publicar o escribir.
- Telegram: cada bot solo acepta mensajes de tu ID (`TELEGRAM_ALLOWED_USERS`); a cualquier otra persona no le
  contesta nada. Los botones también revisan que seas tú.
- Los bots no tienen terminal, ni herramientas de archivos, ni pueden instalar skills: solo sus herramientas
  fijas, que leen los datos ya sincronizados. No pueden leer `secrets.env` ni llamar a Canvas directamente.
- Crear, archivar un bot o guardar el horario pasa solo cuando tú pulsas el botón; el modelo solo puede
  mostrarte el botón.
- Los tokens de los bots de materia nunca llegan al modelo ni a los registros de las conversaciones: un filtro
  que corre antes que Hermes los atrapa, los guarda en `secrets.env` (permisos 600) y borra el mensaje del chat.
  Con «gestionar otros bots» activado, el token ni siquiera pasa por el chat.

## Pruebas

```bash
uv run pytest
```

Una sola prueba de punta a punta (`tests/e2e/test_e2e.py`; su encabezado describe cada paso): levanta un Canvas
falso con datos grabados (`tests/e2e/fixtures/`), un Telegram falso y un modelo falso con guion, y recorre todo el
flujo con los comandos reales y el gateway real de Hermes (si está instalado), en un HOME temporal; nunca toca tu
`~/.hermes`. El aula falsa usa los códigos y nombres reales de ESPOL, con una materia que tiene teórico y
práctico (un solo bot recibe los avisos y las entregas de los dos). Cubre crear el equipo desde el chat (con un
toque y reenviando a BotFather), repartir a un bot de materia, el botón de un aviso, guardar el horario solo tras
confirmar, el brief 30 min antes de una clase sin repetirse tras reiniciar, el cuaderno con una foto y una nota de voz, que Vinci lee los cuadernos sin poder
escribirlos ni usar una terminal, archivar y reactivar un bot, y que cada bot quede con su personaje: su
nombre (los bots de materia que ya se llamaban «Vinci · …» se renombran ahí mismo al actualizar, sin crear
ninguno nuevo), la foto que sube a Telegram y su personalidad, sin cambiar sus reglas. Deja el resultado en **`artifacts/e2e/`**: `REPORTE.md`,
`notificaciones.md` (todos los mensajes), `equipo.md`, `horario.md`, `briefs.md`, `cuadernos.md`, `party.md`
(con la foto que subió cada bot, `foto-<bot>.jpg`),
`hermes_herramientas.json`, `resumen_diario.txt`, `recuperacion.json`, `cli.md`, `canvas_requests.log` y
`setup.log`.

## Desinstalar

```bash
hermes gateway stop                              # si solo lo usabas para Vinci: hermes gateway uninstall
hermes profile list                              # vinci y un vinci-<código> por materia
hermes profile delete vinci                      # y lo mismo con cada vinci-<código>
rm ~/.local/bin/aula && rm -r ~/.claude/skills/aula
rm -r ~/.local/share/espol-academic-bot          # borra también el material y los cuadernos
```

Los bots de Telegram los borras en @BotFather (`/deletebot`).

## Próximos pasos (aún no incluidos)

- Videos de las clases: transcribirlos para poder preguntar sobre ellos.
- PDFs escaneados y fotos de la pizarra con texto: OCR.
- Notas de voz: Hermes las transcribe (en español) si tiene con qué; si no, el bot guarda el audio sin
  transcribir. Dejar instalado un modelo local (faster-whisper) desde el setup.
- Contador de tareas pendientes en la barra de Omarchy y notificaciones de escritorio.
- Sincronizar entregas y clases con tu calendario; tarjetas de estudio (flashcards).
- Un resumen la noche antes de cada día de clases.
- Cierre de semestre automático más allá de archivar (exportar cuadernos, proponer el equipo nuevo).
