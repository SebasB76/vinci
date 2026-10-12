# Contribuir

## Hoja de ruta

- Videos de las clases: transcribirlos para poder preguntar sobre ellos.
- OCR para las fotos de la pizarra del cuaderno, para poder buscar en su texto.
- Buscar por significado (búsqueda semántica local), además de por palabras.
- Dejar instalado desde el setup un modelo local para transcribir notas de voz (faster-whisper).
- Contador de tareas pendientes en la barra de Omarchy y notificaciones de escritorio.
- Sincronizar entregas y clases con tu calendario; tarjetas de estudio (flashcards).
- Un resumen la noche antes de cada día de clases.
- Cierre de semestre más completo: exportar los cuadernos y proponer el equipo nuevo.

## Trabajar en el código

Los issues y pull requests son bienvenidos. Para trabajar en el código:

```bash
uv sync                          # dependencias, con las de desarrollo
uv run pytest                    # la prueba de punta a punta
.venv/bin/vinci-check smoke      # prueba tus bots en vivo, como lo harías desde el celular (unos 45 s)
python3 scripts/docs_check.py    # te avisa si cambiaste código sin su documentación
```

`vinci-check` es la herramienta con la que un agente (o tú) comprueba un cambio en los bots reales: les escribe
desde tu cuenta de Telegram con `tg`, lee lo que Vinci contestó por WhatsApp, abre el formulario del token y el
dashboard en un Chrome sin ventana. Solo escribe a tus bots de Vinci. `vinci-check --help` lista sus comandos.

**La prueba de punta a punta** está en [`tests/e2e/test_e2e.py`](../../tests/e2e/test_e2e.py); su encabezado
describe cada paso. Son cuatro pruebas que corren en paralelo, cada una con su propia instalación: Canvas y el
token (sin gateway), el chat del capitán en WhatsApp, el Vinci de un amigo en un grupo, y el Académico. Cada una
levanta un Canvas falso con datos grabados (`tests/e2e/fixtures/`), un puente de WhatsApp falso y un modelo con
guion, y corre los comandos reales, el `setup.sh` real y el gateway real de Hermes (si está instalado), en un HOME
temporal: nunca toca tu `~/.hermes`. Si algo intenta hablar con Telegram, la prueba falla. Deja un reporte
repetible en `artifacts/e2e/`: `REPORTE.md`, `tiempos.md` (dónde espera cada prueba) y un archivo por tema. Si una
prueba falla, deja también `fallo-<prueba>.md` con el error y lo último que pasó. Toma unos 3 minutos.

Al contribuir:

- **El código nuevo va en inglés** (nombres, comentarios, claves nuevas de configuración); el español queda para
  lo que lee el estudiante (mensajes de Telegram, textos del CLI, el README y estas guías).
- **Commits y títulos de PR** con [Conventional Commits](https://www.conventionalcommits.org/es/)
  (`feat: …`, `fix: …`, `docs: …`).
- **Prueba de punta a punta**: si cambias un comportamiento, extiende la prueba E2E para que lo verifique y
  corre `uv run pytest` antes de abrir el PR.
- **Documentación al día**: si tu cambio vuelve falso algo del README, de estas guías o de
  [`AGENTS.md`](../../AGENTS.md), corrígelo en el mismo PR.
- **Nada de datos reales** en fixtures, capturas ni issues: ni tokens, ni notas, ni horarios, ni nombres de
  estudiantes o profesores. Los datos de prueba son inventados.
