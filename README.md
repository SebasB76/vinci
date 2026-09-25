# espol-academic-bot

Tu bot académico para las materias de ESPOL. Lee tu aula virtual
([aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec), que es Canvas) y:

- **Te avisa por Telegram** de tareas nuevas, cambios de fecha, anuncios, notas publicadas y material nuevo
  (revisa cada 30 minutos).
- **Te recuerda** cada entrega que aún no enviaste, 24 horas y 3 horas antes.
- **Te manda un resumen de la semana** todos los días a las 7:00.
- **Responde «¿qué tengo pendiente?»** y **preguntas sobre el material** (PDF, diapositivas PPTX y DOCX):
  explicar un tema, resumir un capítulo o hacerte preguntas tipo examen, citando archivo, página y el enlace
  del aula virtual.
- Trae el comando **`aula`** para consultar todo desde la terminal, y una skill para que **Claude Code** en tu
  PC también pueda usarlo.

Es **solo lectura**: nunca entrega, publica, comenta ni cambia nada en el aula virtual. Solo te responde a ti,
y todos los datos se quedan en tu PC.

## Cómo está armado

```
aula_core   núcleo reutilizable: cliente de Canvas (solo GET), base de datos local (SQLite),
            descarga e indexado del material. No sabe nada de Telegram ni de Hermes.
aula        la herramienta de línea de comandos, encima del núcleo.
espol_bot   el bot: sondeo + notificaciones (sin gastar tokens) y la skill de Hermes que usa `aula`.
```

El bot corre en tu **Hermes Agent** (el mismo que ya usas, con tu mismo login de Anthropic), pero en un
**perfil aparte llamado `espol`** con su propio bot de Telegram. No toca tu perfil por defecto ni tu bot de X.
Las notificaciones las genera un script fijo (cron «no-agent» de Hermes): **no usan el modelo ni gastan tokens**.
Solo las preguntas que le haces por chat usan el modelo.

## Instalación

Necesitas: tu PC con Arch/Omarchy, Hermes Agent instalado (`~/.local/bin/hermes`), Python 3.11+ y
[uv](https://docs.astral.sh/uv/) (`sudo pacman -S uv`; sin uv el setup usa `python -m venv`).

### 1. Crea el bot de Telegram con @BotFather

1. En Telegram abre [@BotFather](https://t.me/BotFather) y envía `/newbot`.
2. Ponle un nombre (ej. «Mi bot ESPOL») y un usuario que termine en `bot` (ej. `mi_espol_bot`).
3. BotFather te da un **token** como `123456789:ABCdef...`. Guárdalo: va en `TELEGRAM_BOT_TOKEN`.
4. Usa un bot **nuevo**, distinto al de tu bot de X (Hermes no deja que dos perfiles usen el mismo token).
5. Abre el chat con tu nuevo bot y envíale `/start` (Telegram no deja que un bot te escriba primero).

### 2. Averigua tu ID de Telegram

Escríbele a [@userinfobot](https://t.me/userinfobot); te responde con tu **ID numérico** (ej. `987654321`).
No es tu @usuario. Va en `TELEGRAM_USER_ID` y es el único usuario al que el bot responderá.

### 3. Crea el token del aula virtual

1. Entra a [aulavirtual.espol.edu.ec](https://aulavirtual.espol.edu.ec) con tu cuenta institucional.
2. Ve a **Cuenta → Configuración** y baja hasta la sección **Integraciones aprobadas**.
3. Pulsa **Nuevo token de acceso**. En *Propósito* escribe «Bot académico» y en *Fecha de vencimiento*
   pon el **fin del término** (unos 4 meses). Así, si algún día se filtra, deja de servir solo.
4. Pulsa **Generar token** y copia el token **en ese momento** (Canvas no lo vuelve a mostrar).
   Va en `CANVAS_TOKEN`.

Ese token puede hacer lo mismo que tú en el aula virtual, así que trátalo como una contraseña: no lo
compartas ni lo subas a ningún lado. El bot solo lo usa para leer. Cuando venza, el bot te avisa por Telegram;
crea otro, cámbialo en `secrets.env` y listo (no hace falta reiniciar nada).

### 4. Completa `secrets.env`

```bash
cp secrets.env.example secrets.env
chmod 600 secrets.env
nano secrets.env        # CANVAS_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID
```

`secrets.env` está en `.gitignore`: nunca se sube a GitHub.

### 5. Corre el setup

```bash
./setup.sh
```

Puedes correrlo las veces que quieras (por ejemplo, después de cambiar `config.toml`). Hace esto:

- instala las dependencias de Python en `.venv/`;
- instala el comando `aula` en `~/.local/bin/aula` y la skill de Claude Code en `~/.claude/skills/aula/`;
- crea o actualiza el perfil de Hermes `espol` (`~/.hermes/profiles/espol/`): modelo, zona horaria,
  Telegram solo para tu ID, la skill `espol-academico` y los dos cron jobs (sondeo cada 30 min y resumen a las 7:00);
- prueba que Canvas responde y te manda un mensaje de prueba por Telegram.

No modifica tu perfil por defecto de Hermes (`~/.hermes/config.yaml`, `~/.hermes/.env`) ni otros perfiles.

## Encender y apagar el bot

```bash
espol gateway install     # una sola vez: crea el servicio de usuario hermes-gateway-espol
espol gateway start       # encender (queda en segundo plano y arranca con tu sesión)
espol gateway stop        # apagar
espol gateway status      # ¿está corriendo?
espol cron list           # ver los dos trabajos programados y cuándo corren
tail -f ~/.hermes/profiles/espol/logs/gateway.log     # registro de Hermes
tail -f ~/.local/share/espol-academic-bot/bot.log     # registro del sondeo
```

`espol` es el alias que Hermes crea para el perfil; si no está en tu PATH usa `hermes -p espol ...`.
Para que siga funcionando con la sesión cerrada: `sudo loginctl enable-linger "$USER"`.

El primer sondeo te manda un mensaje de bienvenida con tus materias; desde ahí solo te escribe cuando hay algo
nuevo o algo falla. Si una parte de una materia (sus tareas, anuncios o archivos) no se puede leer tres veces
seguidas, te avisa una sola vez nombrando la materia y la parte, sigue reintentando y el resto funciona normal;
si vuelve a fallar después de recuperarse, te avisa de nuevo. Para forzar una revisión ahora:
`espol cron run espol-sondeo`.

## Uso

**En Telegram** (escríbele a tu bot):

- «¿Qué tengo pendiente?» / «¿Qué me falta entregar esta semana y en qué orden lo hago?»
- «Explícame la regla de la cadena» / «Resúmeme el capítulo 3 de Cálculo»
- «Hazme 5 preguntas tipo examen de cinemática»
- «¿Qué dijo el profe de Física en el último anuncio?» / «¿Cómo me fue en la Lección 1?»

**En la terminal** con `aula` (añade `--json` para salida de máquina):

```bash
aula cursos
aula tareas                       # pendientes, por fecha de entrega
aula tareas --curso calculo --dias 7
aula anuncios --curso fisica
aula notas
aula archivos --curso calculo --nombre "semana 3"
aula archivos bajar 5001          # descarga (y lo indexa) en ~/.local/share/espol-academic-bot/materiales/
aula archivos leer 5001 --paginas 2-3
aula buscar "regla de la cadena"
aula sincronizar --material       # leer todo ahora y bajar el material nuevo
```

`--curso` acepta cualquier parte del nombre o del código, sin tildes. `aula` reutiliza los datos guardados si
tienen menos de 10 minutos; si no, vuelve a leer el aula virtual.

**Con Claude Code**: en cualquier sesión de Claude Code en tu PC puedes pedir
«bájate el PDF de la semana 3 de Cálculo y explícame el ejercicio 4»; la skill `aula` le enseña a usar el comando.

## Configuración

Todo lo ajustable está en [`config.toml`](config.toml):

| Clave | Por defecto | Qué hace |
|---|---|---|
| `notificaciones.intervalo_minutos` | `30` | cada cuánto revisa el aula virtual |
| `notificaciones.recordatorios_horas` | `[24, 3]` | recordatorios antes de cada entrega no enviada |
| `notificaciones.resumen_diario` | `"07:00"` | hora del resumen de la semana |
| `general.zona_horaria` | `America/Guayaquil` | zona para fechas y horarios |
| `material.extensiones` | `pdf, pptx, docx` | qué archivos se descargan e indexan |
| `material.tamano_maximo_mb` | `60` | archivos más grandes no se descargan |
| `almacenamiento.carpeta_datos` | `~/.local/share/espol-academic-bot` | base de datos y material |
| `hermes.modelo` | `claude-sonnet-5` | modelo para las preguntas por chat |

Después de cambiarlo corre `./setup.sh` otra vez (la frecuencia y la hora del resumen viven en los cron de Hermes).

## Tus datos

Todo queda en tu PC, en `~/.local/share/espol-academic-bot/`:

- `espol.db`: tus materias, tareas, anuncios, notas, archivos y el índice del material;
- `materiales/<código de la materia>/`: los archivos descargados;
- `bot.log`: registro del sondeo.

## Seguridad

- El cliente de Canvas solo sabe hacer peticiones `GET`: no hay forma de entregar, publicar o escribir.
- Telegram: Hermes solo acepta mensajes de `TELEGRAM_ALLOWED_USERS` (tu ID), y el sondeo solo le escribe a tu chat.
- El agente de Hermes corre con tu usuario, así que técnicamente puede leer archivos de tu PC. Por eso el perfil
  bloquea comandos que mencionen `secrets.env`, `CANVAS_TOKEN` o la API de Canvas, y sus instrucciones le prohíben
  usar otra cosa que `aula`. Es una barrera contra errores, no un sandbox.

## Pruebas

```bash
uv run pytest
```

Una sola prueba de punta a punta (`tests/e2e/test_e2e.py`; su encabezado describe cada paso): levanta un Canvas
falso con datos grabados (`tests/e2e/fixtures/`) y un Telegram falso y recorre todo el flujo con los comandos
reales, en un HOME temporal (usa el Hermes real si está instalado; nunca toca tu `~/.hermes`). Deja el resultado en
**`artifacts/e2e/`**: `REPORTE.md`, `notificaciones.md` (todos los mensajes), `resumen_diario.txt`,
`recuperacion.json`, `cli.md`, `canvas_requests.log` y `setup.log`. Es repetible: dos corridas dan los mismos archivos.

## Desinstalar

```bash
espol gateway stop && espol gateway uninstall
hermes profile delete espol
rm ~/.local/bin/aula && rm -r ~/.claude/skills/aula
rm -r ~/.local/share/espol-academic-bot     # borra también el material descargado
```

## Próximos pasos (aún no incluidos)

- Videos de las clases: transcribirlos para poder preguntar sobre ellos.
- PDFs escaneados (sin texto): OCR.
- Contador de tareas pendientes en la barra de Omarchy y notificaciones de escritorio.
- Sincronizar entregas con tu calendario; tarjetas de estudio (flashcards).
