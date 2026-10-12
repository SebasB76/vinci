# Tus datos, seguridad y privacidad

## Tus datos

Todo se guarda en tu PC, en `~/.local/share/espol-academic-bot/`:

| Archivo | Qué es |
|---|---|
| `espol.db` | Tus materias, tareas, anuncios, notas, el catálogo y el índice del material, el libro principal de cada materia, cómo se evalúa cada materia y las notas que le contaste a un bot, los avisos enviados, tu lista de pendientes, las tareas que marcaste como entregadas, las páginas del material que leyó cada bot (con eso se revisan sus citas) y de qué materia es cada nota de tu carpeta de apuntes |
| `materiales/<curso>/` | Los archivos descargados del aula, una carpeta por curso (y en `recibidos/`, el material que le mandaste a un bot) |
| `libros/<CÓDIGO>/` | Donde pones el PDF del libro principal de una materia si pesa más de 20 MB |
| `tessdata/` | Los modelos de OCR de español e inglés que bajó `setup.sh` |
| `materias.toml` | Tu equipo de bots, con los cursos del aula de cada materia |
| `horario.toml` | Tu horario (y sus copias anteriores, `horario.anterior-*.toml`) |
| `cuadernos/<CÓDIGO>/` | El cuaderno de cada materia (`cuaderno.db`, con sus quiz y tus respuestas) y sus adjuntos |
| `entregas/<CÓDIGO>/` | Lo que Vinci le pasó a un bot y todavía no llegó a su cuaderno |
| `submissions/<CÓDIGO>/` | Los PDF que un bot de materia armó con tus fotos para entregar |
| `bot.log` | Registro del sondeo, la agenda y los botones |

Hermes guarda las conversaciones y la memoria de cada bot en su perfil: `~/.hermes/profiles/vinci/` y
`~/.hermes/profiles/vinci-<código>/`.

## Seguridad y privacidad

- **Datos académicos de solo lectura, salvo tus entregas.** El cliente académico de Canvas
  ([`src/aula_core/canvas.py`](../../src/aula_core/canvas.py)) solo sabe hacer `GET`. Lo único que Vinci escribe en tus
  cursos es una entrega: [`src/espol_bot/submission.py`](../../src/espol_bot/submission.py) sube un PDF a una tarea
  solo cuando pulsas «📤 Entregar» debajo de ese PDF, nunca porque el modelo lo pida. No publica, no comenta y no
  cambia nada más. Otro componente hace `POST` y `DELETE` únicamente sobre los tokens propios de Vinci, verifica
  el reemplazo antes del cambio y nunca manda un token o una URL de feed fuera del aula.
- **Tus apuntes salen solo si son de clase.** Vinci lee tu carpeta de notas en tu PC, sin el modelo. Al modelo
  solo llegan las notas que quedaron de una materia (por su título, por la clase y su material, o por tu botón) y
  las líneas `//vinci`; una nota sin relación con ninguna clase no sale de tu PC. Tus archivos nunca se cambian:
  el cuaderno guarda una copia.
- **Solo tú.** Cada bot acepta mensajes solo de tu ID de Telegram. A cualquier otra persona no le contesta nada (ni
  un código de emparejamiento), y los botones también revisan que seas tú. Una instalación es para un estudiante.
- **En WhatsApp, cada uno con lo suyo.** Hermes manda cada mensaje al Vinci de quien lo escribe: el tuyo o el de
  un amigo que agregaste. Un amigo nunca llega a tu Vinci, y si alguien llegara al Vinci de otro, el plugin le
  niega las herramientas con datos del dueño (su aula, sus notas, sus listas). A quien no tiene su Vinci le
  contesta el plugin, sin el modelo. El token de un amigo viaja cifrado como el tuyo en `/token`, y un token del
  aula pegado tal cual en WhatsApp no se usa: Vinci le pide que lo borre.
- **Herramientas cerradas de fábrica.** Ningún bot trae terminal, acceso a archivos, ejecución de código ni
  navegador: solo sus herramientas fijas, su memoria y las skills de Hermes. Vinci además busca en la web; un bot
  de materia ve solo su materia y no busca en la web: solo abre los enlaces que muestra el aula de su materia,
  nunca una dirección de tu red o de tu PC. Un bot solo toma como adjunto lo que tú le mandaste por Telegram.
  Las demás herramientas de Hermes están apagadas, pero tú decides: [las enciendes por bot](#herramientas-de-hermes-que-puedes-encender).
- **Las skills pueden escribir.** `skill_manage` deja que un bot cree o edite skills, pero solo dentro de la carpeta
  `skills/` de su propio perfil. El texto no confiable del aula (un anuncio, un documento) podría intentar dirigirlo
  a que escriba una skill; `setup.sh` reescribe la skill de cada bot en cada corrida.
- **El dashboard no lee de ningún servidor.** Tus entregas y novedades viajan en el enlace del botón «📋 Entregas»,
  después del `#`, y solo ese botón de tu chat lo tiene. El navegador nunca le manda esa parte del enlace a GitHub
  Pages. La política de seguridad de la página solo le deja conectarse al relé de Vinci (`workers.dev`). Lo que
  marcas se queda en tu celular y le llega a Vinci como un `/start` en su chat de Telegram, o por el relé desde
  WhatsApp. El plugin lo atiende sin el modelo.
- **El relé no puede leer tu token.** Cada enlace que Vinci manda por WhatsApp lleva un buzón al azar después del
  `#`, y ese buzón es el permiso para escribirle a Vinci. El relé guarda lo que llega como máximo 48 horas. Tu PC lo
  lee con una clave que solo está en tu `secrets.env`. Vinci atiende un buzón solo para la persona a la que se lo
  mandó, un buzón de token sirve una vez, y lo que llega a un buzón que Vinci no abrió se borra sin usarse. Quien
  consiga un enlace todavía abierto puede usarlo, igual que hoy con el enlace mismo.
- **Un enlace se abre sin tu cuenta.** Un bot pide el documento de un enlace de forma anónima: sin tu token del
  aula, sin cookies (ni las que el sitio pone en el camino), sin credenciales de tu PC, revisando cada redirección y
  con tope de tamaño (`material.tamano_maximo_mb`) y de tiempo. Lo que trae es material para leer, nunca
  instrucciones para el bot.
- **DSpace, también sin cuenta.** La búsqueda de exámenes usa la API pública de DSpace: solo `GET`, sin tu token,
  sin cookies ni credenciales, y solo cuando le preguntas por exámenes.
- **Las acciones importantes pasan por tu botón.** Crear, archivar o reactivar un bot, guardar el horario o cómo se
  evalúa una materia y entregar una actividad en el aula ocurren solo cuando pulsas el botón; el modelo solo puede
  mostrártelo.
- **Tu contraseña del Académico tampoco.** La página del botón «🎓 Conectar Académico» cifra tu usuario, tu
  contraseña y el CAPTCHA en tu celular con una llave de un solo uso que solo tiene el proceso de tu PC que hace ese
  ingreso. Ese proceso entra, guarda la copia (`academico.json`, permisos 600, sin cookies ni contraseña) y termina:
  la llave, la contraseña y la sesión del portal solo vivieron en su memoria.
- **Los tokens de los bots nunca llegan al modelo.** El plugin atrapa cualquier mensaje con un token antes que
  Hermes, lo guarda y borra el mensaje del chat. Con «gestionar otros bots», el token ni siquiera pasa por el chat.
- **El token del aula tampoco.** `/token` lo cifra en tu celular y Telegram solo lleva el texto cifrado. Un token del
  aula pegado en un chat se borra sin usarse.

**Dónde viven los secretos:**

| Dónde | Qué guarda |
|---|---|
| `secrets.env` (en esta carpeta, permisos 600, fuera de git) | Tokens de Canvas y Telegram, las URLs secretas de los feeds iCal/Atom y, mientras un `/token` espera, su llave privada de un uso |
| `~/.hermes/profiles/<perfil>/.env` | El token del bot de ese perfil y tu ID como único usuario permitido |
| `amigos/<nombre>/secrets.env` (en la carpeta de datos, permisos 600) | El token del aula de ese amigo y su número de WhatsApp |
| `~/.hermes/platforms/whatsapp/session/` | La sesión de WhatsApp del número de Vinci: quien la tenga escribe como Vinci |
| Hermes | Tu acceso al modelo, según cómo lo configuraste con `hermes model` |

**Qué sale de tu PC:** las consultas al aula virtual (con tu token), el ingreso al Académico que haces desde su botón y el PDF de una entrega que confirmaste; los mensajes y archivos que van y
vienen por Telegram; y, cuando un bot usa el modelo, tu mensaje, lo que le mandaste y lo que sus herramientas
leyeron para responderte (tareas, notas, anuncios, partes del material, entradas del cuaderno) van al proveedor
del modelo a través de Hermes. Vinci también puede buscar en la web con el buscador de tu Hermes, un bot abre un
enlace del aula (sin tu cuenta) cuando le hace falta, y busca y baja exámenes de DSpace cuando se los pides. Los datos guardados se quedan en tu PC.

Si encuentras un problema de seguridad, no lo publiques en un issue con detalles: avísale primero al dueño del
repositorio en privado. Y nunca pegues tokens ni datos personales en un issue.

### Herramientas de Hermes que puedes encender

Todas están apagadas salvo lo que cada bot necesita. Para encender una en un bot, escribe su nombre en
`config.toml`, corre `./setup.sh` y reinicia el gateway (`hermes gateway restart`); para apagarla, quítala de la lista.

```toml
[hermes.herramientas]
vinci = ["terminal", "file"]     # solo Vinci
materias = ["code_execution"]    # todos los bots de materia

[hermes.herramientas.por_materia]
ESTG1034 = ["web"]               # un solo bot de materia (se suma a `materias`)
```

| Herramienta | Qué le da al bot | Riesgo |
|---|---|---|
| `terminal` | Comandos de shell y procesos en tu PC | Corre como tu usuario: puede leer o borrar tus archivos, `secrets.env` y el token del aula. El filtro `approvals.deny` solo frena unos patrones |
| `file` | Leer, escribir y editar archivos | Puede leer `secrets.env` y la base de datos, y modificar cualquier archivo que tu usuario pueda |
| `code_execution` | Scripts de Python que llaman herramientas | Equivale a una terminal |
| `browser` | Navegar, hacer clic y escribir en páginas | Páginas con instrucciones ocultas pueden dirigir al bot; actúa con la sesión del navegador que use |
| `computer_use` | Controlar el escritorio (ratón y teclado) | Actúa sobre lo que tengas abierto en tu PC |
| `delegation` | Lanzar sub-agentes con las mismas herramientas | Multiplica el gasto de tokens y el alcance de las demás herramientas |
| `cronjob` | Crear y cambiar tareas programadas | Pueden correr sin ti, gastar tokens y escribirte por Telegram |
| `kanban` | Tablero de tareas para agentes | Encola trabajo para agentes de Hermes que corre sin que estés en el chat |
| `vision`, `video`, `image_gen`, `video_gen`, `tts` | Analizar y generar imágenes, video y voz | Mandan contenido a proveedores externos y cobran aparte |
| `todo` | Lista de pasos de una tarea | Ninguno relevante |
| `connections` | Conectores a cuentas y servicios remotos | Puede autorizar y usar cuentas externas |
| `homeassistant`, `spotify` | Casa inteligente y Spotify | Actúan sobre esas cuentas o dispositivos |
| `x_search` | Buscar en X (Twitter) con xAI | Trae texto no confiable y cobra aparte |
| `a2a` | Hablar con otros agentes | Recibe mensajes de terceros como si fueran instrucciones |
| `web`, `search` (solo materias; Vinci ya busca en la web) | Buscar y leer páginas | Texto no confiable de internet; `web` puede abrir cualquier dirección que alcance tu PC |
