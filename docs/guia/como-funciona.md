# Cómo funciona

Todo lo automático (revisar el aula, avisar, recordar, decidir cuándo toca un brief) lo hacen scripts fijos que
**no usan el modelo de IA ni gastan tokens**. Solo gastan tokens tus preguntas y lo que un bot tiene que escribir.

- **Hermes Agent** es el agente de IA sobre el que corre todo. Cada bot es un
  [perfil de Hermes](https://hermes-agent.nousresearch.com/docs/): `vinci` para Vinci y `vinci-<código>` para
  cada materia (por ejemplo `vinci-matg1049`), cada uno con su propia memoria, su token de Telegram y su lista
  cerrada de herramientas. Un solo gateway de Hermes los atiende a todos. Tu perfil por defecto de Hermes no se
  toca.
- **El sondeo** (`espol-bot sondeo`) es un cron de Hermes sin modelo: lee el aula, compara con lo que ya tenía,
  actualiza el catálogo del material, baja los sílabos nuevos y te manda los avisos por el chat de Vinci. Después
  lee con OCR, unos minutos, las páginas escaneadas que esperan. La
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
- **El plugin `vinci-botones`** atiende, sin el modelo, los botones, el `/start`, el `/estado` y el `/token` de Vinci
  y cualquier mensaje con un token de bot o del aula, antes de que Hermes los vea, y revisa las citas de cada respuesta antes de que salga
  (`espol-bot citas`). A cada bot de materia, además, le da `ver_pagina`: una página de un PDF como imagen, para
  leer escaneos. También cuenta tus respuestas a un quiz y te manda el puntaje, sin el modelo.

Así está organizado el repositorio:

| Carpeta | Qué hay |
|---|---|
| `src/aula_core/` | El núcleo: cliente de Canvas que solo sabe hacer GET, la base local (SQLite), la sincronización, el catálogo del material, el sílabo, la descarga e indexado, la búsqueda de texto completo y los exámenes de DSpace. No sabe nada de Telegram ni de Hermes. |
| `src/aula/` | El comando `aula`, encima del núcleo. |
| `src/espol_bot/` | Vinci y los bots de materia: sondeo y avisos, agenda de briefs, cuadernos, horario, libro principal, el equipo de bots, WhatsApp y los amigos, el token, el Académico, las herramientas MCP y la configuración de los perfiles de Hermes. |
| `hermes/` | Las plantillas de cada bot (su `SOUL.md` y su skill), los plugins `vinci-botones` y `vinci-whatsapp`, el parche del puente de WhatsApp, las fotos de perfil (`avatars/`) y `characters.toml`. |
| `docs/token/`, `docs/dashboard/`, `docs/academico/` | Las páginas que abren los botones, en GitHub Pages. No guardan nada. |
| `relay/` | El relé: un Worker de Cloudflare que lleva de vuelta lo que mandan esas páginas desde WhatsApp. |
| `tests/e2e/` | La prueba de punta a punta, con su Canvas, su Telegram y su Académico falsos. |
| `claude/skills/aula/` | La skill para Claude Code. |
