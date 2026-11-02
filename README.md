<div align="center">

<img src="docs/images/vinci-logo.png" width="120" alt="El logo de Vinci: un mago sonriente con lentes redondos, cuya cara es una burbuja de chat">

# Vinci

**Tu semestre en ESPOL, en un chat de WhatsApp.**<br>
Vinci lee tu aula virtual, te avisa antes de que algo se te pase y te ayuda a estudiar.

[Qué hace](#qué-hace) · [ESPOL](#conectado-a-espol) · [Empezar](#empezar) · [Guías](#guías) · [Privacidad](#privacidad)

</div>

<br>

<p align="center">
  <img src="docs/images/vinci-pantallas.png" alt="Tres chats de WhatsApp con Vinci: un recordatorio de entrega con la encuesta «¿Ya lo entregaste?»; una nota de voz que pregunta el promedio y Vinci contesta desde el Académico; fotos de un deber que Vinci convierte en PDF y entrega en el aula cuando votas «Entregar»" width="100%">
</p>
<p align="center"><sub>Datos ficticios, con los mensajes que Vinci manda en la prueba E2E.</sub></p>

## Qué hace

| | |
|---|---|
| **Te avisa** | Revisa el aula cada 10 minutos: tareas nuevas, cambios de fecha, anuncios, notas y material. Te recuerda cada entrega 24 h y 3 h antes. |
| **Te ordena la semana** | A las 7:00, lo que vence primero y lo que más pesa en tu nota. `/entregas` abre todo en una página dentro del chat. |
| **Te prepara cada clase** | Media hora antes, un repaso de lo que toca y de lo que vence en esa materia. |
| **Estudia contigo** | Explica tu material citando archivo y página, te toma quizzes, busca exámenes anteriores y te arma resúmenes en PDF y diapositivas. |
| **Saca tus cuentas** | Cuánto necesitas para pasar, con los pesos del sílabo. Tu promedio, tus materias aprobadas y tus horarios, desde el Académico. |
| **Entrega por ti** | Fotos de tu deber → un PDF → al aula, solo cuando confirmas. |
| **Te entiende** | Notas de voz, capturas de tu horario, fotos de la pizarra. También funciona en tus grupos. |
| **Uno para cada amigo** | Cada amigo tiene su propio Vinci en WhatsApp, con su aula y sus datos. |

Lo automático (revisar el aula, avisar, recordar) no usa la IA ni gasta tokens.
[Cada función en detalle →](docs/guia/funciones.md#qué-hace-vinci)

## Conectado a ESPOL

| Fuente | Qué lee |
|---|---|
| **[Aula virtual](https://aulavirtual.espol.edu.ec)** (Canvas) | Tareas, fechas, anuncios, notas y el material de cada curso. También entrega tus deberes hechos a mano. |
| **[Académico](https://www.academico.espol.edu.ec)** | Promedio, avance de la carrera, historial, calificaciones y horarios de clases y exámenes. |
| **[DSpace](https://www.dspace.espol.edu.ec)** | Unos 20 000 exámenes anteriores de todas las facultades, que Vinci busca y resuelve. |

## Empezar

**Si alguien ya tiene su propio Vinci**, pídele que te agregue como amigo. Te llega un mensaje de Vinci por WhatsApp
con una página para conectar tu aula, y desde ahí tienes tu propio Vinci. [Cómo funciona →](docs/guia/whatsapp.md)

**Tu propio Vinci** corre en un servidor, encendido todo el día, con la imagen de Docker de este repo. Con
[Coolify](https://coolify.io) (un panel para desplegar apps en tu servidor):

1. Crea una app desde este repo, con el `Dockerfile` y un volumen en `/opt/data`.
2. Agrega la key de tu proveedor de IA, tu token del aula y tu número de WhatsApp.
3. Pulsa **Deploy** y vincula el número de WhatsApp de Vinci.

[La guía del servidor, paso a paso →](docs/guia/servidor.md#crear-la-app) ·
[Sin Docker, en una laptop →](docs/guia/servidor.md#en-una-laptop-vieja-en-casa-sin-docker)

## Guías

| Guía | Qué tiene |
|---|---|
| [WhatsApp](docs/guia/whatsapp.md) | Tu chat, tus materias, grupos, amigos y comandos |
| [Uso diario](docs/guia/uso.md) | Botones, comandos, `/token` y el Académico |
| [Todas las funciones](docs/guia/funciones.md) | Cada función en detalle |
| [En un servidor](docs/guia/servidor.md) | Vinci en Coolify con Docker |
| [Instalación](docs/guia/instalacion.md) | Configuración, Telegram, actualizar y desinstalar |
| [Privacidad](docs/guia/privacidad.md) | Qué guarda, qué sale de tu servidor y qué puede hacer cada bot |
| [Límites y problemas](docs/guia/problemas.md) | Lo que todavía no hace y cómo arreglar lo común |
| [Cómo funciona](docs/guia/como-funciona.md) | Hermes, el sondeo, la renovación del token y el repositorio |
| [Terminal y Claude Code](docs/guia/terminal.md) | El comando `aula` y `espol-bot` |
| [Contribuir](docs/guia/contribuir.md) | Hoja de ruta, la prueba E2E y `vinci-check` |

## Privacidad

- **Solo lee tu aula.** Lo único que escribe es una entrega que tú confirmaste.
- **Tus datos se quedan en tu servidor.** No hay un servidor central de Vinci.
- **Los tokens y tu contraseña nunca pasan por el chat ni por la IA.** Viajan cifrados desde tu celular.

[Qué sale de tu servidor y por qué →](docs/guia/privacidad.md#seguridad-y-privacidad)

---

<sub>
<b>In English:</b> a self-hosted WhatsApp study assistant for ESPOL students, built on
<a href="https://github.com/NousResearch/hermes-agent">Hermes Agent</a>. It reads your Canvas courses, sends alerts and
reminders, answers questions about your course material and hands in your work. Telegram is an optional channel.
</sub>
<br><br>
<sub>
Proyecto independiente, sin afiliación a ESPOL, Instructure, Nous Research, Telegram ni WhatsApp.
Todavía sin licencia: pide permiso antes de reutilizar el código.
</sub>
