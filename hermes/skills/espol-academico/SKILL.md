---
name: espol-academico
description: Materias de ESPOL desde el aula virtual (Canvas) - tareas pendientes, anuncios, notas, archivos del curso y preguntas sobre el material (explicar un tema, resumir un capítulo, preguntas tipo examen) citando archivo y página.
version: 0.1.0
author: espol-academic-bot
platforms: [linux]
metadata:
  hermes:
    tags: [ESPOL, Canvas, universidad, estudio]
    requires_toolsets: [terminal]
---

<!-- {{MARKER}}. Se sobrescribe cada vez que corres setup.sh. -->

# Bot académico de ESPOL

Todo sale del comando `aula` (solo lectura). Úsalo siempre con `--json` y la ruta completa:

    {{AULA}} <comando> --json

## Cuándo usarla

Cualquier pregunta sobre las materias del estudiante: qué tiene pendiente, fechas de entrega,
anuncios de profesores, notas, material del curso, o dudas de estudio sobre ese material.

## Comandos

| Necesitas | Comando |
|---|---|
| Materias activas | `{{AULA}} cursos --json` |
| Pendientes por fecha | `{{AULA}} tareas --json` (`--dias 7`, `--curso calculo`) |
| Anuncios recientes | `{{AULA}} anuncios --json` (`--curso fisica -n 5`) |
| Notas publicadas | `{{AULA}} notas --json` (`--curso ...`) |
| Archivos del curso | `{{AULA}} archivos --json` (`--curso ... --nombre "semana 3"`) |
| Bajar e indexar un archivo | `{{AULA}} archivos bajar <id> --json` |
| Leer un archivo indexado | `{{AULA}} archivos leer <id> --paginas 3-6 --json` |
| Buscar en el material | `{{AULA}} buscar "regla de la cadena" --json` (`--curso ... -n 8`) |

`--curso` acepta cualquier parte del nombre o código, sin tildes ni mayúsculas.
Los datos se actualizan solos; agrega `--sin-actualizar` si solo quieres lo guardado.

## Procedimiento

**«¿Qué tengo pendiente?» / «¿qué me falta esta semana?»**
1. `{{AULA}} tareas --json` (con `--dias 7` si pregunta por la semana).
2. Responde en orden de entrega: fecha y hora, materia, tarea y enlace. Marca las atrasadas
   (`atrasada: true`) y las que no tienen entrega en línea (`sin_entrega_en_linea: true`).
3. Si pide un orden de trabajo, sugiérelo según cercanía de la fecha y puntos (`puntos`).

**Explicar un tema, resumir un capítulo, preguntas tipo examen**
1. `{{AULA}} buscar "<palabras clave de la pregunta>" --json`, con `--curso` si la menciona.
2. Lee el campo `texto` de los mejores resultados. Para resumir un capítulo o ver más contexto,
   usa `{{AULA}} archivos leer <archivo_id> --paginas <rango> --json`.
3. Responde basándote en ese texto y cita cada fuente así:
   📄 <archivo>, <unidad> <pagina> — <url>
4. Para preguntas tipo examen: 3–5 preguntas del contenido citado, con respuestas al final.
5. Si no hay resultados, prueba otras palabras; si el archivo no está indexado, búscalo con
   `{{AULA}} archivos --nombre ... --json` y bájalo con `archivos bajar <id>`.

**«Bájate el PDF de la semana 3 de Cálculo»**
1. `{{AULA}} archivos --curso calculo --nombre "semana 3" --json`
2. `{{AULA}} archivos bajar <id> --json` (queda en `ruta_local` y se indexa).
3. `{{AULA}} archivos leer <id> --json` para trabajar con su contenido.

Para cualquier otra pregunta que los comandos fijos no cubran, combina los `--json` anteriores.

## Límites

- Solo lectura: no existe forma de entregar, publicar, comentar ni escribir mensajes en el aula
  virtual. Si lo piden, explica que lo haga él mismo y comparte el enlace.
- No leas secrets.env ni llames a la API de Canvas con curl: solo `{{AULA}}`.
- Videos todavía no se procesan (solo PDF, PPTX y DOCX).
