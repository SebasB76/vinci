<div align="center">

<img src="hermes/avatars/wizard.jpg" width="120" alt="Vinci, un mago azul en pixel art">

# Vinci

**Tu asistente académico en Telegram.** Lee tu aula virtual, te avisa lo nuevo, arma un bot por
cada una de tus materias y te prepara para cada clase.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Hermes Agent](https://img.shields.io/badge/corre%20en-Hermes%20Agent-7c3aed)
![Telegram](https://img.shields.io/badge/Telegram-bots-26A5E4?logo=telegram&logoColor=white)
![Datos académicos: solo lectura](https://img.shields.io/badge/datos%20académicos-solo%20lectura-2e7d32)
![Licencia: pendiente](https://img.shields.io/badge/licencia-pendiente-lightgrey)

[Qué hace](#qué-hace) · [Cómo funciona](#cómo-funciona) · [Instalación](#instalación) ·
[Uso diario](#uso-diario-en-telegram) · [Seguridad](#seguridad-y-privacidad) ·
[Problemas](#solución-de-problemas) · [Contribuir](#contribuir)

</div>

> **In English:** Vinci is a self-hosted Telegram assistant for ESPOL students, built on
> [Hermes Agent](https://github.com/NousResearch/hermes-agent). It reads your Canvas courses
> (aulavirtual.espol.edu.ec) read-only, sends alerts and deadline reminders, and creates one Telegram bot per
> subject from your own courses. Each subject bot sends a brief 30 minutes before every class, keeps a
> notebook of what you covered, and answers questions from the course material with citations. Everything
> runs on your PC and answers only you. The rest of this README is in Spanish.

<p align="center">
  <img src="docs/images/vinci-en-telegram.png" alt="Tres chats de Telegram: Vinci arma el equipo de bots, un aviso del aula con el botón para consultarlo con el bot de la materia, y el brief de una clase" width="100%">
</p>
<p align="center"><sub>Imagen de ejemplo armada con los datos ficticios de la prueba E2E: las materias, tareas y usuarios son inventados.</sub></p>

## ¿Qué es Vinci?

Vinci es un bot de Telegram que se conecta a tu aula virtual de ESPOL
([aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec), que es Canvas) y se encarga de lo que se te
escapa en el semestre: las tareas nuevas, los cambios de fecha, los anuncios del profe, las notas, el material
que suben y lo que vence mañana.

Además, Vinci arma **tu equipo**: lee las materias en las que estás inscrito y crea **un bot de Telegram por
materia**, con el nombre de esa materia. Cada bot de materia se especializa en la suya: te manda un repaso antes
de cada clase, lleva el cuaderno de lo que vieron y te ayuda a estudiar con el material del curso.


## Qué hace

| | |
|---|---|
| 🔔 **Avisos del aula virtual** | Revisa el aula cada 30 minutos y te avisa de tareas nuevas, cambios de fecha, anuncios, notas publicadas o cambiadas, material y enlaces nuevos y materias nuevas. Te recuerda cada entrega que aún no enviaste 24 h y 3 h antes, y a las 7:00 te manda el resumen de tu semana. |
| 🤖 **Un bot por materia** | Le dices «arma mi equipo» y Vinci te propone un bot por cada materia de tu aula, que se crea con un toque tuyo. El teórico y el práctico de una materia comparten un solo bot. |
| 📚 **Brief antes de cada clase** | 30 minutos antes de cada clase de tu horario, el bot de esa materia te manda un repaso de la clase anterior, lo que vence, el material nuevo, 3 a 5 conceptos clave y una pregunta para hacerle al profe. |
| 📓 **Cuaderno de cada materia** | Cuéntale al bot lo que vieron o mándale una foto de la pizarra, una nota de voz o un PDF: lo guarda con un resumen. Lleva tus dudas y los temas que te cuestan, y los usa en los briefs. |
| 📄 **Preguntas sobre el material** | Cada bot tiene el catálogo de todo el material de su materia y baja lo que necesita. Se guía primero por el **libro principal** (el del sílabo, o el que tú le digas), busca en español y en inglés y te explica un tema, resume un capítulo o te hace preguntas tipo examen, citando archivo, página y el enlace del aula. [Más sobre el material](#el-material-de-cada-materia). |
| 🧭 **Vinci ve todo junto** | Contesta sobre cualquier materia, arma planes de estudio con tus entregas y tus clases, lee los cuadernos de todos los bots y busca en la web. Le mandas «tengo esto de Física» con una foto y se lo pasa al bot correcto. |
| 🎓 **Traspaso con un botón** | Debajo de cada aviso hay un botón «🎓 Consultar con …»: el bot de la materia recibe el aviso y te explica qué implica en su chat. |
| 🗓️ **Horario desde una captura** | Le mandas a Vinci una captura de tu horario y te muestra cómo lo entendió; se guarda solo cuando pulsas «Guardar». |
| 💻 **Terminal y Claude Code** | El comando `aula` consulta todo desde la terminal, y una skill le enseña a Claude Code a usarlo. |

Todo lo automático (revisar el aula, avisar, recordar, decidir cuándo toca un brief) lo hacen scripts fijos que
**no usan el modelo de IA ni gastan tokens**. Solo gastan tokens tus preguntas y lo que un bot tiene que escribir.

- **Hermes Agent** es el agente de IA sobre el que corre todo. Cada bot es un
  [perfil de Hermes](https://hermes-agent.nousresearch.com/docs/): `vinci` para Vinci y `vinci-<código>` para
  cada materia (por ejemplo `vinci-matg1049`), cada uno con su propia memoria, su token de Telegram y su lista
  cerrada de herramientas. Un solo gateway de Hermes los atiende a todos. Tu perfil por defecto de Hermes no se
  toca.
- **El sondeo** (`espol-bot sondeo`) es un cron de Hermes sin modelo: lee el aula, compara con lo que ya tenía,
  actualiza el catálogo del material, baja los sílabos nuevos y te manda los avisos por el chat de Vinci. La
  primera vez solo guarda cómo está el aula, así que no te llega todo lo viejo de golpe.
- **El mantenimiento** (`espol-bot mantenimiento`) corre cada 10 minutos, sin modelo. Como el Canvas de ESPOL
  invalida en silencio los tokens personales tras una hora, crea y verifica un sucesor a los 40 minutos, lo guarda
  de forma atómica y recién entonces borra el anterior. Si ESPOL corrige esa configuración, lo detecta y deja de
  renovar. Los feeds iCal y Atom mantienen fechas, eventos y anuncios aunque la cadena se corte.
- **La agenda** de cada bot de materia corre cada minuto y casi siempre contesta «nada que hacer», sin llamar al
  modelo. Solo lo despierta cuando una clase empieza dentro de 30 minutos (con todos los datos del brief ya
  armados) o cuando Vinci le pasó algo.
- **Las herramientas** de cada bot son un servidor MCP propio (`espol-bot mcp vinci|materia`) que lee los datos
  ya sincronizados; el de un bot de materia, además, baja del aula el material que le hace falta. Vinci ve todas
  las materias y lee los cuadernos; un bot de materia ve solo la suya y escribe solo en su cuaderno.
- **El plugin `vinci-botones`** atiende, sin el modelo, los botones, el `/start` y cualquier mensaje con un token
  de bot, antes de que Hermes los vea. A cada bot de materia, además, le da `ver_pagina`: una página de un PDF
  como imagen, para leer escaneos.

Así está organizado el repositorio:

| Carpeta | Qué hay |
|---|---|
| `src/aula_core/` | El núcleo: cliente de Canvas que solo sabe hacer GET, la base local (SQLite), la sincronización, el catálogo del material, el sílabo, la descarga e indexado y la búsqueda de texto completo. No sabe nada de Telegram ni de Hermes. |
| `src/aula/` | El comando `aula`, encima del núcleo. |
| `src/espol_bot/` | Vinci y los bots de materia: sondeo y avisos, agenda de briefs, cuadernos, horario, libro principal, el equipo de bots, las herramientas MCP y la configuración de los perfiles de Hermes. |
| `hermes/` | Las plantillas de cada bot (su `SOUL.md` y su skill), el plugin `vinci-botones`, las fotos de perfil (`avatars/`) y `characters.toml`. |
| `claude/skills/aula/` | La skill para Claude Code. |


## Inicio rápido


```bash
git clone https://github.com/SebasB76/espol-academic-bot.git
cd espol-academic-bot
./setup.sh          # la primera vez instala las dependencias, crea secrets.env y se detiene
nano secrets.env    # CANVAS_TOKEN, TELEGRAM_BOT_TOKEN (el bot de Vinci) y TELEGRAM_USER_ID
# en Telegram: mándale /start a tu bot nuevo
./setup.sh          # configura Vinci en Hermes y prueba el aula y Telegram
hermes gateway install && hermes gateway start
```

Después, en Telegram: escríbele a Vinci **«arma mi equipo»**, pulsa «➕ Crear» en cada materia y mándale una
captura de tu horario. La [instalación paso a paso](#instalación) explica cada parte.


### 4. Completa `secrets.env`

```bash
cp secrets.env.example secrets.env   # o corre ./setup.sh una vez: lo crea por ti
chmod 600 secrets.env
nano secrets.env
```

```ini
CANVAS_TOKEN=…            # paso 3
TELEGRAM_BOT_TOKEN=…      # paso 1, el bot de Vinci
TELEGRAM_USER_ID=…        # paso 2
```

`secrets.env` está en `.gitignore`: nunca se sube a GitHub. Los tokens de los bots de materia
(`TELEGRAM_BOT_TOKEN_<CÓDIGO>`) no los escribes tú: Vinci los agrega cuando crea cada bot.

**Respaldo recomendado sin token (una sola vez):** copia en Canvas la **Fuente del calendario** y el enlace
**RSS** de Anuncios de cada materia, y ejecuta `.venv/bin/espol-bot feeds`. Las entradas se piden de forma oculta
y quedan en `secrets.env`; no las pegues en Telegram. Así las fechas, eventos y anuncios siguen llegando incluso
si la PC estuvo apagada más de una hora y se rompió la cadena de renovación.

### 5. Corre el setup

```bash
./setup.sh
```

Puedes correrlo las veces que quieras: si no cambiaste nada, no cambia nada. Hace esto:

- revisa Python y Hermes, e instala las dependencias en `.venv/`;
- si a Hermes le falta su conector de Telegram, lo instala (`hermes pm install --extra telegram`);
- instala el comando `aula` en `~/.local/bin/` y la skill de Claude Code en `~/.claude/skills/aula/`;
- crea o actualiza el perfil `vinci` de Hermes (modelo, zona horaria, Telegram solo para tu ID, sus
  herramientas, el cron del sondeo y el del resumen de las 7:00) y el perfil de cada bot de materia que ya
  exista;
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

## Uso diario en Telegram

### Con Vinci

- «¿Qué tengo pendiente esta semana y en qué orden lo hago?» · «¿Cómo voy en todo?» · «Hazme un plan para el
  parcial de Física».
- «¿Qué dijo el profe de Cálculo?» · «¿Qué notas me publicaron?»
- «Tengo esto de Física» + una foto, un PDF o una nota de voz → te dice a qué bot se lo pasó. Si no le queda
  claro de qué materia es, te pregunta antes.
- «¿Qué hay en el cuaderno de Cálculo?» (Vinci lee los cuadernos, pero no los cambia).
- «El libro de Física es el Serway» → lo guarda como libro principal de esa materia.
- Responde a un aviso con «pásaselo al de la materia», o pulsa su botón «🎓 Consultar con …».
- «Arma mi equipo» · «archiva el bot de Física» · «reactiva el bot de Física».

### Con cada bot de materia

Escríbele directo, como a un compañero que se sabe la materia:

- «Hoy vimos la regla de la cadena» → lo anota en su cuaderno como lo visto en clase.
- Una foto de la pizarra o una nota de voz → la guarda en el cuaderno con un resumen (y la transcripción, si es
  audio).
- «No entendí las derivadas implícitas» → te lo explica con el material del curso y lo anota como duda.
- «Explícame el capítulo 3» · «Hazme 5 preguntas tipo examen».
- «El libro principal es el Purcell», o el PDF del libro → lo usa primero al explicarte y en los briefs.

Un bot de materia solo sabe de la suya: si le preguntas de otra, te manda con Vinci.

### Los botones

| Botón | Dónde aparece | Qué hace |
|---|---|---|
| 🎓 Consultar con … | Debajo de cada aviso del aula | Le pasa el aviso al bot de esa materia, que te responde en su chat (una sola vez por aviso). |
| ➕ Crear … | En la tarjeta de «arma mi equipo» | Empieza a crear el bot de esa materia. |
| 🤖 Crear … | En el teclado, después de «➕ Crear» | Abre la pantalla de Telegram que crea el bot (si Vinci puede gestionar bots). |
| ✅ Guardar horario · ✏️ Corregir | En la propuesta de horario | Guarda el horario, o lo descarta para que le digas qué corregir. |
| 🗄️ Archivar · ♻️ Reactivar · Cancelar | Cuando pides archivar o reactivar un bot | Apaga o vuelve a encender el bot de esa materia. |

Los botones los atiende el plugin, sin el modelo, y solo responden a tu ID. El modelo puede mostrarte un botón,
pero nunca pulsarlo.

### Comandos

- `/start` en cualquier bot: te saluda y te dice qué hace. En un bot de materia, además, cuándo es tu próxima clase
  y a qué hora te llega el brief.
- Los comandos de Hermes también funcionan en cada chat, por ejemplo `/new` (empieza una conversación de cero;
  la memoria y el cuaderno se quedan), `/usage` (tokens y costo de la conversación), `/stop` y `/help`.

### El material de cada materia

Cada bot de materia tiene un **catálogo** de todo el material del aula y baja solo lo que necesita, sin llenar tu
disco ni el contexto del modelo:

- **El catálogo** reúne cada documento que muestra el aula: la pestaña Archivos (con sus carpetas), los Módulos (con
  las secciones de cada semana, como «ANTES de clase»), las Páginas, el «Programa del curso», los adjuntos y enlaces
  de los anuncios y los enlaces dentro de las tareas. Las copias del mismo archivo se muestran una vez, y el material de un
  semestre anterior (por ejemplo `Slides/2021`) va al final.
- **Qué se baja:** solo el sílabo de cada curso se baja por su cuenta. Lo demás lo baja el bot de la materia cuando le hace
  falta para responderte, y ya bajado se queda.
- **El libro principal:** el bot lo saca de la bibliografía básica del sílabo, o se lo dices tú («el libro de Física
  es el Serway», a Vinci o al bot). La búsqueda lo pone primero. Si su PDF no está en el aula, el bot te lo pide
  **una sola vez**: hasta 20 MB se lo mandas por su chat; si pesa más, lo pones en
  `~/.local/share/espol-academic-bot/libros/<CÓDIGO>/` y lo toma en la siguiente revisión del aula.
- **Buscar:** en el texto de lo ya leído, en español y en inglés (mucho material está en inglés), sin repetir la
  misma página de dos copias.
- **PDFs escaneados:** se detectan porque sus páginas casi no tienen texto; el bot te lo dice y mira sus páginas como
  imagen (`ver_pagina`).
- **Enlaces de fuera:** un Google Docs, Slides, Sheets o Drive, un SharePoint, un Dropbox o la página de un
  profesor, el bot (el de la materia o Vinci) lo abre sin tu cuenta cuando le hace falta, también si viene en un
  anuncio: lo pide como PDF (o su descarga) y, si llega el documento, lo lee como un PDF del aula. Si pide iniciar
  sesión, te dice por qué no se abre y te pide el PDF; lo recuerda, así que no lo vuelve a intentar en cada pregunta
  (dile «ya lo compartieron» y lo prueba otra vez). Un Google Docs se vuelve a leer al día siguiente, porque el
  profe lo sigue editando. Los videos, formularios, carpetas, OneDrive personal y Teams quedan listados con su
  enlace para que los abras tú.
- **Documentos que le mandas:** un PDF, DOCX o PPTX del curso que le mandas al bot pasa a su material y se puede
  buscar; lo que es tuyo (un deber resuelto, tus apuntes) va al cuaderno.

### Qué recuerda cada bot

| | Dónde vive | Quién lo escribe |
|---|---|---|
| **La conversación** | En el perfil de Hermes del bot. Al llegar a unos 80 000 tokens, Hermes la resume (por defecto esperaría a 256 000), porque cada mensaje viaja con todo el chat. | Hermes |
| **La memoria** | En el perfil de Hermes del bot: lo que el bot decide recordar de ti entre conversaciones. | Cada bot, la suya |
| **El cuaderno** | `cuadernos/<CÓDIGO>/` en la carpeta de datos: lo visto en clase, apuntes, dudas, temas débiles, fotos, audios, documentos y lo que Vinci le pasó. | Solo el bot de esa materia (Vinci lo lee) |
| **El aula** | `espol.db`: tus materias, tareas, anuncios, notas, el catálogo del material y su índice. | El sondeo (y el bot que baja un documento) |

### Fin de semestre

Pídele a Vinci «archiva el bot de Física» y confirma con el botón. Un bot archivado deja de responder y de mandar
briefs, pero **conserva su memoria y su cuaderno**. Para volver a usarlo: «reactiva el bot de Física». El
semestre siguiente, «arma mi equipo» te propone las materias nuevas y te avisa de las que ya no están en tu aula.

## Desde la terminal y Claude Code

El comando `aula` consulta lo mismo desde la terminal (añade `--json` para salida de máquina):

```bash
aula cursos
aula tareas                            # pendientes, por fecha de entrega
aula tareas --curso calculo --dias 7
aula anuncios --curso fisica -n 5
aula notas
aula archivos --curso calculo --nombre "semana 3"   # el catálogo: leído o no, con módulo y carpeta
aula archivos bajar 5001               # descarga e indexa el archivo 5001
aula archivos leer 5001 --paginas 2-3
aula enlaces --curso fisica            # lo que está fuera del aula: Dropbox, SharePoint, videos…
aula buscar "regla de la cadena"
aula sincronizar --material            # leer el aula ahora y bajar los sílabos nuevos
```

`--curso` acepta cualquier parte del nombre o del código, sin tildes. `aula` reutiliza los datos guardados si
tienen menos de 10 minutos; si no, vuelve a leer el aula (y si no puede, te muestra lo guardado). Con
`--actualizar` la lee siempre y falla si no puede; con `--sin-actualizar` usa solo lo guardado.

**Con Claude Code:** en cualquier sesión de Claude Code en tu PC puedes pedir «bájate el PDF de la semana 3 de
Cálculo y explícame el ejercicio 4»; la skill `aula` le enseña a usar el comando.

## Configuración

Todo lo ajustable está en [`config.toml`](config.toml). Después de cambiarlo, corre `./setup.sh` otra vez.

| Clave | Por defecto | Qué hace |
|---|---|---|
| `canvas.url` | `https://aulavirtual.espol.edu.ec` | Tu aula virtual |
| `canvas.cache_minutos` | `10` | Cuánto tiempo `aula` y los bots reutilizan los datos guardados antes de volver a leer el aula |
| `canvas.request_interval_seconds` | `1.0` | Pausa mínima entre dos consultas del sondeo al aula (lo que preguntas en Telegram no espera) |
| `general.zona_horaria` | `America/Guayaquil` | Zona para fechas, horarios y briefs |
| `notificaciones.intervalo_minutos` | `30` | Cada cuánto revisa el aula (mínimo 5) |
| `notificaciones.recordatorios_horas` | `[24, 3]` | Recordatorios antes de cada entrega no enviada |
| `notificaciones.resumen_diario` | `"07:00"` | Hora del resumen de la semana |
| `notificaciones.max_mensajes_por_sondeo` | `8` | Con más avisos que esto en una revisión, llegan en un solo mensaje |
| `clases.brief_minutos_antes` | `30` | Minutos antes de cada clase en que llega el brief (entre 5 y 180) |
| `material.extensiones` | `["pdf", "pptx", "docx"]` | Qué archivos del aula leen los bots (además de las páginas web de un enlace) |
| `material.tamano_maximo_mb` | `200` | Nada más grande que esto se baja |
| `material.max_mb_per_sync` | `50` | Cuántos MB de sílabos baja como máximo cada sondeo; los demás, en los siguientes |
| `almacenamiento.carpeta_datos` | `~/.local/share/espol-academic-bot` | Base de datos, material y cuadernos |
| `hermes.perfil` | `vinci` | Perfil de Vinci; cada materia usa `<perfil>-<código>` |
| `hermes.proveedor` · `hermes.modelo` | `anthropic` · `claude-sonnet-5-5` | Modelo de Vinci y de los bots de materia |

Otros archivos que puedes editar:

- **`materias.toml`** (en la carpeta de datos): tu equipo. Lo escribe Vinci; puedes cambiar a mano el `nombre` de
  una materia, y su bot se llama así.
- **`horario.toml`** (en la carpeta de datos): tu horario, una sección `[[clase]]` por bloque, de lunes a sábado.
  Vinci guarda una copia del anterior cada vez que lo cambia.
- **[`hermes/characters.toml`](hermes/characters.toml)**: la foto de perfil de cada bot y, si quieres, un nombre
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
    <td align="center"><img src="hermes/avatars/wizard.jpg" width="64" alt=""><br><sub><b>Vinci</b></sub></td>
    <td align="center"><img src="hermes/avatars/robot.jpg" width="64" alt=""><br><sub>Ingeniería de Software I</sub></td>
    <td align="center"><img src="hermes/avatars/builder.jpg" width="64" alt=""><br><sub>Dirección de Proyectos Informáticos</sub></td>
    <td align="center"><img src="hermes/avatars/server.jpg" width="64" alt=""><br><sub>Sistemas Distribuidos</sub></td>
    <td align="center"><img src="hermes/avatars/book.jpg" width="64" alt=""><br><sub>Estadística</sub></td>
    <td align="center"><img src="hermes/avatars/sprout.jpg" width="64" alt=""><br><sub>Ciencias de la Sostenibilidad</sub></td>
  </tr>
</table>

Cámbialo por tus materias (o deja solo `[vinci]`): Vinci recibe esa lista en sus instrucciones como los nombres de
los bots del semestre. Si una de tus materias tiene el mismo código que una del ejemplo, su bot tomará esa foto y
ese nombre.

## Tus datos

Todo se guarda en tu PC, en `~/.local/share/espol-academic-bot/`:

| Archivo | Qué es |
|---|---|
| `espol.db` | Tus materias, tareas, anuncios, notas, el catálogo y el índice del material, el libro principal de cada materia y los avisos enviados |
| `materiales/<curso>/` | Los archivos descargados del aula, una carpeta por curso (y en `recibidos/`, el material que le mandaste a un bot) |
| `libros/<CÓDIGO>/` | Donde pones el PDF del libro principal de una materia si pesa más de 20 MB |
| `materias.toml` | Tu equipo de bots, con los cursos del aula de cada materia |
| `horario.toml` | Tu horario (y sus copias anteriores, `horario.anterior-*.toml`) |
| `cuadernos/<CÓDIGO>/` | El cuaderno de cada materia (`cuaderno.db`) y sus adjuntos |
| `entregas/<CÓDIGO>/` | Lo que Vinci le pasó a un bot y todavía no llegó a su cuaderno |
| `bot.log` | Registro del sondeo, la agenda y los botones |

Hermes guarda las conversaciones y la memoria de cada bot en su perfil: `~/.hermes/profiles/vinci/` y
`~/.hermes/profiles/vinci-<código>/`.

## Seguridad y privacidad

- **Datos académicos de solo lectura.** El cliente académico de Canvas
  ([`src/aula_core/canvas.py`](src/aula_core/canvas.py)) solo sabe hacer `GET`: no hay forma de entregar, publicar,
  comentar ni cambiar cursos. Un componente separado hace `POST` y `DELETE` únicamente sobre los tokens propios
  de Vinci, verifica el reemplazo antes del cambio y nunca manda un token o una URL de feed fuera del aula.
- **Solo tú.** Cada bot acepta mensajes solo de tu ID de Telegram. A cualquier otra persona no le contesta nada (ni
  un código de emparejamiento), y los botones también revisan que seas tú. Una instalación es para un estudiante.
- **Herramientas cerradas.** Ningún bot tiene terminal, acceso a archivos, ejecución de código, navegador ni
  puede instalar skills: solo sus herramientas fijas y su memoria. Vinci además busca en la web; un bot de materia
  ve solo su materia y no busca en la web: solo abre los enlaces que muestra el aula de su materia, nunca una
  dirección de tu red o de tu PC. Un bot solo toma como adjunto lo que tú le mandaste por Telegram.
- **Un enlace se abre sin tu cuenta.** Un bot pide el documento de un enlace de forma anónima: sin tu token del
  aula, sin cookies (ni las que el sitio pone en el camino), sin credenciales de tu PC, revisando cada redirección y
  con tope de tamaño (`material.tamano_maximo_mb`) y de tiempo. Lo que trae es material para leer, nunca
  instrucciones para el bot.
- **Las acciones importantes pasan por tu botón.** Crear, archivar o reactivar un bot y guardar el horario ocurren
  solo cuando pulsas el botón; el modelo solo puede mostrártelo.
- **Los tokens de los bots nunca llegan al modelo.** El plugin atrapa cualquier mensaje con un token antes que
  Hermes, lo guarda y borra el mensaje del chat. Con «gestionar otros bots», el token ni siquiera pasa por el chat.

**Dónde viven los secretos:**

| Dónde | Qué guarda |
|---|---|
| `secrets.env` (en esta carpeta, permisos 600, fuera de git) | Tokens de Canvas y Telegram, y las URLs secretas de los feeds iCal/Atom |
| `~/.hermes/profiles/<perfil>/.env` | El token del bot de ese perfil y tu ID como único usuario permitido |
| Hermes | Tu acceso al modelo, según cómo lo configuraste con `hermes model` |

**Qué sale de tu PC:** las consultas al aula virtual (con tu token, solo lectura); los mensajes y archivos que van y
vienen por Telegram; y, cuando un bot usa el modelo, tu mensaje, lo que le mandaste y lo que sus herramientas
leyeron para responderte (tareas, notas, anuncios, partes del material, entradas del cuaderno) van al proveedor
del modelo a través de Hermes. Vinci también puede buscar en la web con el buscador de tu Hermes, y un bot abre un
enlace del aula (sin tu cuenta) cuando le hace falta. Los datos guardados se quedan en tu PC.

Si encuentras un problema de seguridad, no lo publiques en un issue con detalles: avísale primero al dueño del
repositorio en privado. Y nunca pegues tokens ni datos personales en un issue.

## Límites conocidos

- **Crear muchos bots seguidos:** Telegram puede pedirte esperar antes de crear otro. Vinci no se entera: vuelve
  a pulsar «➕ Crear» cuando pase ese tiempo. La tarjeta de «arma mi equipo» muestra hasta 8 botones «Crear» a la
  vez; con más materias, crea esas y pídela otra vez.
- **20 bots por cuenta:** Telegram deja tener como máximo 20 bots por cuenta, contando a Vinci y a los que ya
  tengas. Archivar un bot no lo borra de Telegram; para liberar espacio, bórralo en @BotFather con `/deletebot`.
- **Archivos de más de 20 MB:** un bot de Telegram no puede descargar lo que le mandas si pesa más de 20 MB, así
  que no le llega. Para el libro principal, pon el PDF en `libros/<CÓDIGO>/` de la carpeta de datos. El material
  del aula no tiene ese límite: se baja directo del aula (hasta `material.tamano_maximo_mb`).
- **Qué se puede leer:** el texto de PDF, PPTX, DOCX y páginas web. Un PDF escaneado no se puede buscar (no hay
  OCR), pero el bot de su materia mira sus páginas como imagen, de una en una. Un Google Docs, Drive, SharePoint
  o Dropbox se lee solo si se abre sin iniciar sesión («cualquier persona con el enlace»); si pide tu cuenta de
  ESPOL o de Google, el bot te lo dice y te pide el PDF. Los videos, formularios, carpetas, OneDrive personal y
  Teams solo quedan listados con su enlace, para que los abras tú.
- **Solo se busca en lo ya leído:** del catálogo, solo el sílabo se baja por su cuenta; el resto lo baja el bot de
  la materia cuando le hace falta. Para estudiar a fondo, pregúntale a ese bot más que a Vinci.
- **Notas de voz:** se transcriben si tu Hermes tiene cómo; si no, el bot guarda el audio sin transcribir.
- **Tu PC tiene que estar encendida:** con la PC apagada o el gateway detenido no hay avisos ni briefs. Lo que le
  escribas a un bot mientras tanto te lo responde al volver, y los cambios del aula llegan en la siguiente revisión;
  el brief de una clase que ya empezó no se manda.
- **Materias sin código ESPOL:** un curso del aula sin un código reconocible (como `MATG1049`) no recibe bot;
  Vinci te lo dice en la tarjeta del equipo.
- **El aula pide calma:** el sondeo espacia sus consultas, baja solo los sílabos (hasta 50 MB por revisión) y
  sigue a lo más 60 enlaces por revisión hacia el material que solo un enlace muestra; lo demás, en las siguientes.
  La primera vez, el catálogo completo puede tomar varias revisiones. Si el aula pide bajar el ritmo, el sondeo no
  la vuelve a leer durante una hora.

## Solución de problemas

| Síntoma | Qué hacer |
|---|---|
| `No encuentro Hermes Agent en ~/.local/bin/hermes` | Instala Hermes, o indica dónde está: `HERMES_BIN=/ruta/a/hermes ./setup.sh`. |
| `Faltan valores en secrets.env: …` | Completa esas claves (pasos 1 a 4) y vuelve a correr `./setup.sh`. |
| `⚠ Telegram no aceptó el mensaje` | Mándale `/start` a tu bot de Vinci y revisa `TELEGRAM_BOT_TOKEN`. |
| `⚠ No pude leer el aula virtual; revisa CANVAS_TOKEN` | El token inicial no funcionó durante el setup. Crea otro (paso 3) y ejecuta `.venv/bin/espol-bot resembrar`. |
| Vinci dice que la cadena del token se cortó | Pulsa «🔑 Crear token nuevo», créalo y ejecuta `.venv/bin/espol-bot resembrar`: la entrada es oculta y la renovación se reanuda. Si configuraste los feeds, fechas y anuncios siguieron funcionando. |
| Vinci te dice «Llevo un rato sin poder leer … de …» | Una parte de una materia falló tres veces seguidas. Lo sigue intentando y el resto funciona normal; te avisa de nuevo si vuelve a fallar después de recuperarse. |
| `⚠ Agrega ~/.local/bin a tu PATH` | Agrégalo en tu `~/.bashrc` (o el de tu shell) para usar `aula`. |
| `vinci: command not found` | `vinci` es el alias que Hermes crea para el perfil; sin él, usa `hermes -p vinci …`. |
| `⚠ El gateway de Hermes no cargó el plugin …` | Reinicia el gateway: `hermes gateway stop && hermes gateway start`. |
| Vinci te responde «No sé de qué materia es ese bot» | Pulsa primero «➕ Crear» en la materia que es, y revoca en @BotFather (`/revoke`) el token que mandaste. |
| No te llega el brief | Revisa que guardaste el horario y que la clase está en él, que el bot está activo y que el gateway corre. Mándale `/start` al bot: te dice cuándo es tu próxima clase y a qué hora llega el brief. |
| Ningún bot responde | `hermes gateway status`; si está apagado, `hermes gateway start`. Si se apaga al cerrar sesión: `sudo loginctl enable-linger "$USER"`. |
| El modelo no responde o falta la credencial | Configura el modelo en Hermes (`hermes model`). Si usas una `ANTHROPIC_API_KEY` y no el login de Anthropic, cada perfil lee su propio `.env`: agrégala al `.env` de `~/.hermes/profiles/vinci/` y de cada `vinci-<código>` (el setup conserva esa línea). |
| `⚠ No pude ponerle su foto …` o `… el nombre …` | Telegram pidió esperar o no hubo conexión. `./setup.sh` lo reintenta la próxima vez; también puedes hacerlo en @BotFather con `/setuserpic` o `/setname`. |

Para ver qué pasa:

```bash
hermes gateway status                                  # ¿está corriendo?
vinci cron list                                        # sondeo, mantenimiento y resumen de Vinci
tail -f ~/.hermes/logs/gateway.log                     # registro del gateway de Hermes
tail -f ~/.local/share/espol-academic-bot/bot.log      # registro del sondeo, la agenda y los botones
```

## Actualizar y desinstalar

Para actualizar, trae los cambios y corre el setup otra vez; actualiza los perfiles y los cron en su lugar, sin
duplicarlos ni crear bots nuevos:

```bash
git pull
./setup.sh
```

Si venías del bot académico anterior (el perfil `espol`), el setup lo convierte en Vinci conservando su memoria.

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

## Hoja de ruta

- Videos de las clases: transcribirlos para poder preguntar sobre ellos.
- OCR para fotos de la pizarra y PDFs escaneados, para poder buscar en su texto.
- Buscar por significado (búsqueda semántica local), además de por palabras.
- Dejar instalado desde el setup un modelo local para transcribir notas de voz (faster-whisper).
- Contador de tareas pendientes en la barra de Omarchy y notificaciones de escritorio.
- Sincronizar entregas y clases con tu calendario; tarjetas de estudio (flashcards).
- Un resumen la noche antes de cada día de clases.
- Cierre de semestre más completo: exportar los cuadernos y proponer el equipo nuevo.

## Contribuir

Los issues y pull requests son bienvenidos. Para trabajar en el código:

```bash
uv sync           # dependencias, con las de desarrollo
uv run pytest     # la prueba de punta a punta
```

**La prueba** es una sola, de punta a punta ([`tests/e2e/test_e2e.py`](tests/e2e/test_e2e.py); su encabezado
describe cada paso). Levanta un Canvas falso con datos grabados (`tests/e2e/fixtures/`), un Telegram falso y un
modelo con guion, y corre todo con los comandos reales, el `setup.sh` real y el gateway real de Hermes (si está
instalado), en un HOME temporal: nunca toca tu `~/.hermes`. Cubre desde el setup y los avisos hasta crear el
equipo desde el chat, el horario, los briefs, los cuadernos, el catálogo del material y el libro principal,
archivar y reactivar bots y reiniciar el gateway. Deja un reporte repetible en `artifacts/e2e/` (`REPORTE.md` y un
archivo por tema). Toma unos minutos.

Al contribuir:

- **El código nuevo va en inglés** (nombres, comentarios, claves nuevas de configuración); el español queda para
  lo que lee el estudiante (mensajes de Telegram, textos del CLI, este README).
- **Commits y títulos de PR** con [Conventional Commits](https://www.conventionalcommits.org/es/)
  (`feat: …`, `fix: …`, `docs: …`).
- **Prueba de punta a punta**: si cambias un comportamiento, extiende la prueba E2E para que lo verifique y
  corre `uv run pytest` antes de abrir el PR.
- **Nada de datos reales** en fixtures, capturas ni issues: ni tokens, ni notas, ni horarios, ni nombres de
  estudiantes o profesores. Los datos de prueba son inventados.

## Licencia

Este repositorio **todavía no tiene licencia**: su dueño aún la está eligiendo. Mientras no haya un archivo
`LICENSE`, pide permiso antes de reutilizar el código.

## Créditos

- [Hermes Agent](https://github.com/NousResearch/hermes-agent), de Nous Research: el agente sobre el que corre
  Vinci.
- [Canvas LMS](https://www.instructure.com/canvas), la plataforma del aula virtual de ESPOL, y su API REST.
- La [Bot API de Telegram](https://core.telegram.org/bots/api).

Vinci es un proyecto independiente: no está afiliado a ESPOL, a Instructure, a Nous Research ni a Telegram.
