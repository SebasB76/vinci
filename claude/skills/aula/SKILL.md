---
name: aula
description: Read-only access to the user's ESPOL courses in Canvas (aulavirtual.espol.edu.ec) through the `aula` CLI - pending assignments ordered by due date, announcements, grades, course files (list, download, read page by page), and full-text search over downloaded course material. Use when the user asks about their university courses, deadlines, "what do I have pending", professors' announcements, grades, or wants help studying a PDF/slide deck from a course ("bájate el PDF de la semana 3 de Cálculo y explícame el ejercicio 4").
---

<!-- Installed by espol-academic-bot's setup.sh. Re-run setup.sh to update it. -->

# aula: the user's ESPOL aula virtual

`aula` is on PATH (`~/.local/bin/aula`). It only reads Canvas; nothing can submit, post, or change
anything. Reply to the user in Spanish unless they write in another language.

Always pass `--json` and parse the output.

| Need | Command |
|---|---|
| Active courses | `aula cursos --json` |
| Pending work, by due date | `aula tareas --json` (`--dias 7`, `--curso calculo`) |
| Announcements | `aula anuncios --json` (`--curso fisica -n 5`) |
| Grades | `aula notas --json` |
| Course files (the catalog, read or not) | `aula archivos --json` (`--curso ... --nombre "semana 3"`) |
| Download (and index) files | `aula archivos bajar <id> [<id>...] --json` → `ruta_local` |
| Read an indexed file | `aula archivos leer <id> --paginas 3-6 --json` |
| Links outside the aula (Dropbox, SharePoint, videos) | `aula enlaces --json` (`--curso ...`) |
| Search course material | `aula buscar "regla de la cadena" --json` (`--curso ... -n 8`) |
| Refresh now | `aula sincronizar --json` (`--material` also downloads each course's new syllabus) |

`--curso` matches any fragment of the course name or code, ignoring accents and case. Data refreshes
automatically when older than a few minutes (falling back to the local copy when the aula virtual can't be
read); `--sin-actualizar` uses only the local copy, and `--actualizar` reads it now or fails.

## Workflows

- **"¿Qué me falta entregar esta semana y en qué orden lo hago?"** — `aula tareas --dias 7 --json`;
  order by `vence`, weigh `puntos`, flag `atrasada` and `sin_entrega_en_linea`, link each `url`.
- **"Bájate el PDF de la semana 3 de Cálculo y explícame el ejercicio 4"** —
  `aula archivos --curso calculo --nombre "semana 3" --json` → `aula archivos bajar <id> --json`
  → read the local PDF at `ruta_local` directly (you can open it with your Read tool) or
  `aula archivos leer <id> --json`, then find the exercise and explain it.
- **Study questions** — `aula buscar "<keywords>" --json`, read the `texto` of the top hits, answer
  from that text, and cite `archivo`, `unidad` + `pagina`, and `url`. Search only covers downloaded
  files: the catalog lists every document, and only syllabi download on their own, so `aula archivos
  bajar` the ones on the topic first. Much material is in English: search with English keywords too.
  Hits marked `prioridad: libro principal` come from the syllabus' main book.

## Limits

- Never try to submit, post, or message on Canvas; there is no command for it by design. If asked,
  tell the user to do it themselves and share the `url`.
- Do not read `secrets.env` or call the Canvas API with curl; use `aula`.
- Videos are not processed yet (PDF, PPTX, DOCX and web pages only). A scanned PDF (`indexado:
  escaneado`) has next to no text: open the local file at `ruta_local` and read its pages as images.
