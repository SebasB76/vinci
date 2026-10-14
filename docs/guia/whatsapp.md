# Vinci en WhatsApp

WhatsApp es el canal principal de Vinci, a través del puente de WhatsApp de Hermes. Con `[channels] telegram = false`
en `config.toml` (lo normal), Vinci te habla solo por aquí: lleva todas tus materias en un solo chat, y los bots de
materia de Telegram quedan apagados sin borrarse. Con `telegram = true` vuelven, y WhatsApp recibe una copia de cada
aviso. Usa un número aparte (un chip
prepago basta): el puente es un cliente no oficial, y WhatsApp puede bloquear el número que lo usa. No pongas tu
número personal.

1. Pon tu número en `secrets.env`: `WHATSAPP_CAPTAIN=593…` (código de país, sin «+» y sin el 0 inicial).
2. Detén el gateway: `hermes gateway stop`.
3. Corre `.venv/bin/espol-bot whatsapp-vincular 593…` con el número de Vinci. Te muestra un código de 8 letras.
4. En el celular con el chip de Vinci, abre WhatsApp → Dispositivos vinculados → Vincular con el número de
   teléfono, y escribe el código.
5. Corre `./setup.sh` y arranca el gateway: `hermes gateway start`.

**Páginas dentro de WhatsApp.** El formulario del token y el panel de entregas llegan como un botón. En el iPhone,
el botón abre la página dentro de WhatsApp, como un Mini App de Telegram. En WhatsApp Web abre otra pestaña: Web no
tiene otra forma de abrir una página. En Android no lo probamos. `setup.sh` agrega la ruta del botón al puente de
Hermes sin editar su `bridge.js` (`hermes/whatsapp/vinci-bridge.js`). Si el puente no la tiene, la página llega
como enlace. Las pruebas están en `experiments/whatsapp-webview/`.

**El relé: lo que la página manda de vuelta.** WhatsApp no tiene la forma de Telegram de pasarle al bot lo que hace
una página. El relé es un Worker de Cloudflare, gratis y sin tarjeta, que hace de buzón. La página deja ahí tu token
cifrado o la entrega que marcaste. Tu PC lo recoge cada 3 segundos mientras un enlace está abierto, sin abrir
ningún puerto. Vinci te confirma en el chat. El relé solo ve el texto cifrado, que únicamente tu PC puede abrir.
Sin relé, la página te da el texto cifrado para pegar en el chat, y marcar una entrega abre el chat con `/marca …`
escrito. La página del Académico también usa el relé en los dos sentidos: deja ahí tus datos cifrados y lee de ahí la
imagen del CAPTCHA y cómo va el ingreso; sin relé no funciona.

Para publicar tu relé:

1. Crea una cuenta en [Cloudflare](https://dash.cloudflare.com/sign-up) con tu correo. No pide tarjeta.
2. Corre `npx wrangler login` y pulsa «Allow» en el navegador.
3. Elige el subdominio de tu cuenta en Workers (el panel de Cloudflare lo pide la primera vez).
4. En la carpeta `relay/`, corre `npx wrangler deploy`. Anota la dirección `https://vinci-relay.<subdominio>.workers.dev`.
5. Crea una clave: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
6. Guárdala en el relé: `npx wrangler secret put RELAY_TOKEN` (pega la clave cuando la pida).
7. En `secrets.env`, pon `WHATSAPP_RELAY_URL=<la dirección>` y `WHATSAPP_RELAY_TOKEN=<la clave>`.
8. Corre `./setup.sh` y reinicia el gateway: `hermes gateway restart`.

**Tu chat.** Escríbele a Vinci por privado: tu aula, tu memoria y todas tus materias. WhatsApp no tiene botones, así
que cada tarjeta te llega como mensaje con una **encuesta**: votar «✅ Hecho», «✅ Ya lo entregué», «✅ Guardar
horario», «Guardar esquema» o «📤 Entregar» hace lo mismo que el botón de Telegram, sin pasar por el modelo. Cambiar
el voto lo deshace.

**Tus materias, en un solo chat.** No hay un bot por materia: Vinci sabe de qué materia hablas en cada mensaje.
1. Si nombras la materia («en Estadística: no entendí la varianza»), usa esa.
2. Si respondes a un aviso, a un brief o a un resumen de apuntes, usa la materia de ese mensaje.
3. Si nombraste una materia en las últimas 3 horas («estamos en Física»), lo que mandes sin materia (una foto, una
   nota de voz, «anota…») es de esa. Si a la vez estás en clase de otra, te pregunta cuál.
4. Si mandas una foto o una nota de voz durante tu clase, o hasta una hora después, usa la materia de esa clase
   según tu horario.
5. Si nada de eso alcanza, te pregunta cuál es.

Cada materia tiene su cuaderno: lo que se vio en clase, tus dudas, los temas que te cuestan, las fotos de la pizarra y
tus notas de voz. Vinci te confirma dónde guardó cada cosa («📘 Estadística · guardé la foto»); si se equivocó, dile
«era de Cálculo».

**El brief antes de cada clase.** 30 minutos antes de cada clase de tu horario (`brief_minutos_antes`), Vinci te
manda el brief a este chat: repaso de la clase anterior, lo que vence, material nuevo, conceptos clave y una pregunta
para el profesor. Si le respondes, Vinci sabe que hablas de esa materia. Los apuntes de tu computadora (`[notes]
folder`) también llegan aquí: las preguntas `//vinci` y el resumen con feedback al terminar la clase.

**Tus avisos.** Cada aviso del aula, los recordatorios y el resumen de las 7:00 te llegan a tu chat de WhatsApp, con
su encuesta en vez de botones.

- **Lo que pide una tarea.** «¿Qué pide el taller 2?»: Vinci lee la consigna que escribió el profesor y los
  archivos que trae. No hace falta el nombre exacto: «el taller de integrales» la encuentra entre todas las del
  semestre, también las entregadas; si dos encajan, te pregunta cuál, y si le dices «esa no es», busca otra. Para tus
  dudas sobre esa tarea busca primero en sus anexos, y separa lo que pide la tarea (con su cita) de lo que te sugiere.
- **Lo que de verdad pasó.** Vinci no te dice «ya lo entregué» si solo preparó el PDF: en cada mensaje sabe qué PDF
  espera tu voto y cuál se subió, falló o cancelaste en las últimas 24 horas.
- **Entregar a mano.** Mándale las fotos (o el PDF) y dile de qué tarea es: arma el PDF y te lo manda con la
  encuesta «📤 Entregar / Cancelar». Se sube al aula solo con tu voto.
- **Quiz con encuestas.** `/quiz derivadas`: de 3 a 5 preguntas de tu material, una encuesta por pregunta. Al votar
  te dice si acertaste y por qué, y al final tu puntaje. Si lo dejas a medias para preguntar otra cosa, Vinci te
  contesta eso sin insistir con el quiz; «sigamos con el quiz» te vuelve a mandar solo las preguntas que faltan, al
  final del chat. En un grupo activo, «@vinci /quiz scrum» manda las encuestas al grupo, con opciones 🇦 🇧 🇨 🇩:
  vota quien quiera y cuenta el primer voto de cada uno. Cuando todos los del grupo responden, o a los 15 minutos,
  Vinci manda un solo mensaje con los resultados de todos (con medallas y una mención a cada uno) y las respuestas.
  Esas preguntas salen solo del material del curso, nunca de tu cuaderno.
- **Tengo 20 minutos.** «Tengo 20 minutos para Física»: Vinci mira lo que te cuesta, tus dudas abiertas y lo que
  vence pronto, te propone qué cabe en ese tiempo y lo hacen paso a paso, con ejercicios de tu material. Al final te
  pregunta si guarda en el cuaderno lo que te costó; el próximo quiz o la próxima sesión empiezan por ahí.
- **Jurado de exposición.** «Hazme de jurado para la exposición del proyecto»: dile el documento o la tarea con su
  rúbrica. Vinci te hace una pregunta a la vez, como el profesor, y después de cada respuesta te dice qué estuvo
  bien, qué faltó y dónde está. Al final, tus fortalezas y debilidades. Es práctica: no te pone una nota.
- **Dejar algo y retomarlo.** Lo mismo vale para una sesión de estudio: «tengo 20 minutos, repasemos derivadas»,
  luego otra pregunta, luego «sigamos». Vinci guarda por dónde iban, aunque el chat empiece de cero o se reinicie.
  Lo que dejas más de 3 días ya no te lo recuerda.
- **Notas de voz y audios.** Háblale en vez de escribir: «¿qué tengo esta semana?» por nota de voz recibe la misma
  respuesta que por texto. Un audio reenviado o un archivo `.m4a` también se entiende. Todo se transcribe en tu PC
  con faster-whisper (`setup.sh` lo instala en Hermes); en un servidor, con tu key de OpenAI. Vinci te muestra primero lo que entendió (🎙️). Si no se
  oyó (silencio, ruido), Vinci te lo dice y te pide repetirla o escribirla: no adivina. Si se oyó pero un nombre salió
  raro, lo entiende por el tema y te dice qué entendió; solo pregunta si no sabe qué pides.

**Grupos.** Agrega el número de Vinci a un grupo y escribe ahí «@vinci activa este grupo». Desde entonces Vinci
contesta a quien lo menciona («@vinci …» o «vinci, …»); el resto de la conversación no le llega. Una nota de voz
no puede mencionar a nadie: Vinci contesta la tuya o la de un amigo con su Vinci si dice «Vinci» o responde a un
mensaje suyo. Las notas de voz de quien no tiene su Vinci ni se transcriben. «@vinci desactiva este grupo» lo
apaga. Solo tú puedes encender o apagar un grupo.

**Avisos en un grupo.** Escribe en el grupo «@vinci activa los avisos». Desde entonces Vinci manda ahí, sin que
nadie se lo pida:

- un recordatorio antes de cada clase de tu horario (los mismos `brief_minutos_antes`), con el aula, si es virtual y
  lo que vence esa semana en esa materia;
- los anuncios nuevos de tus profesores, las tareas nuevas y los cambios de fecha, todo lo de una lectura del aula
  en un solo mensaje.

Los avisos nunca llevan notas, entregas hechas ni tu cuaderno. «@vinci desactiva los avisos» los apaga. Solo tú
puedes encenderlos, y funcionan aunque el grupo esté apagado para las preguntas.

**Grupo de confianza.** En un grupo de amigos que comparten su aula entre sí, escribe «@vinci este grupo es de
confianza» (también enciende los avisos). Ahí los avisos usan el aula de cada amigo con su Vinci que está en el
grupo:

- el recordatorio de clase menciona a quienes están en tu mismo paralelo de esa materia, y en una clase virtual
  trae el enlace de Zoom, Teams o Meet si está en el aula;
- en «Vence esta semana», cada tarea dice quién ya la entregó y menciona a quien le falta;
- las novedades también salen del aula de tus amigos, una sola vez aunque varios tengan la materia, y mencionan a
  quien la ve.

Una nota sale en el grupo solo si alguien la pide. «@vinci este grupo ya no es de confianza» vuelve a los avisos
simples.

En un grupo, Vinci sabe quién le escribe y empieza con su nombre cuando habla de su aula. Da entregas, plazos y
notas solo cuando se los piden, y nunca pide el token ahí: ese aviso llega por privado. Vinci no contesta los
stickers. Después de 4 horas sin mensajes, Vinci empieza la charla del grupo desde cero; tus datos y tu lista no
cambian.

Tu chat privado también empieza de cero después de 4 horas sin mensajes: así Vinci arranca con sus reglas y su
memoria al día. Tus datos, tu lista, tus cuadernos y las notas de cada chat siguen ahí, y te puede buscar lo que
hablaron antes si se lo pides.

Lo que pides para un grupo vale solo en ese grupo. Si escribes «@vinci en este grupo háblanos en plural», Vinci lo
guarda como nota de ese chat y lo tiene presente en cada mensaje de ahí; en tu chat privado te sigue hablando como
siempre. Para quitarla, pídele que olvide esa nota del grupo. Lo que vale en todos tus chats (cómo prefieres las
cosas, tus metas) va a su memoria de siempre.

Lo mismo sirve para repartir un trabajo: «@vinci quedamos en que yo hago la intro y Angel el análisis» queda como
acuerdo de ese grupo, con la fecha. Después, «@vinci ¿quién hacía qué?» se contesta desde ahí. Tu Vinci solo lee
tus mensajes: guarda lo que tú le dices que acordaron.

**Recordatorios para el grupo.** Escribe en el grupo «@vinci recuérdanos mañana a las 9 y el viernes a mediodía que
entregamos las historias de usuario». Vinci te confirma el día y la hora de cada uno, y a esa hora el recordatorio
sale en el grupo, para todos. Si no dices la hora, Vinci usa las 9:00 y te lo dice. «@vinci borra el recordatorio
del viernes» quita uno. Si el servidor estuvo apagado y un recordatorio se atrasa más de 6 horas, no sale. Solo tu
Vinci los programa: el Vinci de un amigo no puede escribir en el grupo por su cuenta.

**Un Vinci para cada amigo.** Cada amigo tiene su propio Vinci, con su token del aula, sus datos y sus notas:

1. En tu chat con Vinci por WhatsApp, escribe `/amigo agregar 0991234567 Angel`.
2. Vinci le escribe a Angel por privado con un botón a la página del token (la misma de `/token`, en modo WhatsApp).
3. Angel crea un token en el aula, lo pega en la página y pulsa «Enviar cifrado a Vinci».
4. El token llega cifrado por el relé. Vinci lo verifica, lee el aula de Angel y le confirma sus materias en su chat.
   Sin relé, la página le da un texto cifrado para pegar en el chat.

Desde ahí, «@vinci qué tengo esta semana» le contesta a Angel con lo suyo y a ti con lo tuyo, en el mismo grupo o
por privado. Su Vinci le avisa de sus tareas nuevas por su chat de WhatsApp y renueva su token como el tuyo.
`/amigos` te muestra la lista y `/amigo quitar Angel` borra su Vinci, sus datos y los tokens que creó su cadena.

**Comandos por WhatsApp.** Tú y cada amigo con su Vinci tienen los mismos comandos, cada uno sobre su propia aula,
y Vinci los contesta sin gastar tokens:

| Comando | Qué hace |
|---|---|
| `/start` | Saluda y muestra los comandos |
| `/estado` | La salud del sistema, como en Telegram |
| `/token` | Una imagen con los pasos para crear el token en el aula, y un botón a la página del token: pegas el token nuevo y pulsas «Enviar cifrado a Vinci». Sin relé, pegas en el chat el texto que te da |
| `/entregas` | Un botón a tu panel de entregas (el mismo dashboard de Telegram). Marcar una le llega a Vinci por el relé y te confirma en el chat. Sin relé, abre este chat con `/marca …` escrito: envíalo y cuenta como entregada |
| `/quiz <tema>` | Un quiz corto con encuestas: al votar cada pregunta te dice si acertaste. En un grupo, las encuestas salen en el grupo, y los resultados de todos llegan cuando todos responden o a los 15 minutos |
| `/new`, `/usage`, `/stop`, `/help` | Los comandos de Hermes, igual que en Telegram |

En un grupo, `/estado`, `/token` y `/entregas` te piden escribirlos por privado, y las encuestas de tus tarjetas
(«Ya lo entregué», el horario, una entrega) van a tu chat privado. Las de un quiz sí salen en el grupo.

El Vinci de cada amigo tiene además su lista de pendientes («anota: …», con sus recordatorios), su calculadora de
notas con el esquema que guarda con su voto, y los recordatorios del aula con la encuesta «✅ Ya lo entregué».

En un grupo activo, Vinci también le contesta a quien todavía no tiene su Vinci, como invitado: charla, explica,
busca en la web, el material de los cursos, exámenes anteriores, diapositivas, resúmenes en PDF y un quiz en el grupo. No ve su aula ni le muestra nada
tuyo, y si pide sus tareas o sus notas, le dice que te pida que lo agregues. Esas respuestas usan tu modelo. Los datos de cada amigo viven en `amigos/<nombre>/` de la carpeta de datos, con su propio
`secrets.env`.
