"""`aula`: read-only command line for the ESPOL aula virtual.

    aula cursos
    aula tareas    [--curso X] [--dias N]
    aula anuncios  [--curso X] [-n N]
    aula notas     [--curso X]
    aula archivos  [listar] [--curso X] [--nombre Y]
    aula archivos  bajar <id>... | --curso X [--nombre Y]
    aula archivos  leer <id> [--paginas 3-5]
    aula buscar    "pregunta" [--curso X] [-n N]
    aula sincronizar [--material]

Human-readable Spanish by default; `--json` for agents. Nothing here can submit,
post, or change anything on Canvas: the core client only issues GET requests.
"""

from __future__ import annotations

import argparse
import json
import sys

from aula_core import Aula, queries, search, timefmt
from aula_core.canvas import CanvasError
from aula_core.config import ConfigError


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="salida JSON (para agentes)")
    p.add_argument("--sin-actualizar", action="store_true", default=argparse.SUPPRESS,
                   help="usar solo los datos locales, sin leer el aula virtual")
    p.add_argument("--actualizar", action="store_true", default=argparse.SUPPRESS,
                   help="leer el aula virtual aunque los datos locales sean recientes")
    return p


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(prog="aula", parents=[common],
                                     description="Consulta tu aula virtual de ESPOL (solo lectura).")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="comando")

    sub.add_parser("cursos", parents=[common], help="materias activas")

    p = sub.add_parser("tareas", parents=[common], help="tareas pendientes, por fecha de entrega")
    p.add_argument("--curso", help="parte del nombre o código de la materia")
    p.add_argument("--dias", type=int, help="solo las que vencen en los próximos N días")

    p = sub.add_parser("anuncios", parents=[common], help="anuncios recientes")
    p.add_argument("--curso")
    p.add_argument("-n", type=int, default=10, help="cuántos (por defecto 10)")

    p = sub.add_parser("notas", parents=[common], help="calificaciones publicadas")
    p.add_argument("--curso")

    p = sub.add_parser("archivos", parents=[common], help="material del curso: listar, bajar, leer")
    p.add_argument("accion", nargs="?", choices=["listar", "bajar", "leer"], default="listar")
    p.add_argument("ids", nargs="*", type=int, help="ID de archivo (de `aula archivos`)")
    p.add_argument("--curso")
    p.add_argument("--nombre", help="parte del nombre del archivo o del módulo (ej. 'semana 3')")
    p.add_argument("--paginas", help="para leer: rango de páginas, ej. 3-5")

    p = sub.add_parser("buscar", parents=[common], help="buscar en el material descargado")
    p.add_argument("pregunta")
    p.add_argument("--curso")
    p.add_argument("-n", type=int, default=5)

    p = sub.add_parser("sincronizar", parents=[common], help="leer el aula virtual ahora")
    p.add_argument("--material", action="store_true", help="también descargar e indexar el material nuevo")
    return parser


# -- rendering ------------------------------------------------------------------------


def _out(data, as_json: bool, render) -> None:
    if as_json:
        json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        text = render(data)
        sys.stdout.write(text.rstrip() + "\n")


def _size(value) -> str:
    if not value:
        return ""
    return f"{value / 1024 / 1024:.1f} MB" if value >= 1024 * 1024 else f"{max(1, round(value / 1024))} KB"


def render_courses(rows) -> str:
    if not rows:
        return "No tienes materias activas."
    lines = []
    for c in rows:
        score = f" · nota actual {c['nota_actual']:g}" if c["nota_actual"] is not None else ""
        lines.append(f"• {c['nombre']} ({c['codigo'] or 's/c'}){score}\n  {c['url']}")
    return "\n".join(lines)


def render_tasks(rows, aula: Aula) -> str:
    if not rows:
        return "No tienes tareas pendientes. 🎉"
    now, tz = aula.now(), aula.cfg.tz
    lines = []
    for t in rows:
        if t["vence"]:
            when = f"{timefmt.human(t['vence'], tz)} ({timefmt.until(t['vence'], now)})"
        else:
            when = "sin fecha de entrega"
        flags = []
        if t["atrasada"]:
            flags.append("ATRASADA")
        if t["sin_entrega_en_linea"]:
            flags.append("sin entrega en línea")
        flag = f" [{', '.join(flags)}]" if flags else ""
        lines.append(f"• {when} — {t['curso']}: {t['tarea']}{flag}\n  {t['url']}")
    return "\n".join(lines)


def render_announcements(rows, aula: Aula) -> str:
    if not rows:
        return "No hay anuncios."
    blocks = []
    for a in rows:
        text = (a["texto"] or "").strip()
        if len(text) > 400:
            text = text[:400].rstrip() + "…"
        blocks.append(f"• {timefmt.human(a['publicado'], aula.cfg.tz)} — {a['curso']}: {a['titulo']}"
                      f"{' (' + a['autor'] + ')' if a['autor'] else ''}\n  {text}\n  {a['url']}")
    return "\n\n".join(blocks)


def _grade(value, grade, points) -> str:
    if value is None:
        return grade or "—"
    score = f"{value:g}" + (f"/{points:g}" if points else "")
    return score + (f" ({grade})" if grade and grade != f"{value:g}" else "")


def render_grades(rows) -> str:
    if not rows:
        return "No hay materias."
    blocks = []
    for c in rows:
        head = f"{c['curso']}"
        if c["nota_actual"] is not None:
            head += f" — nota actual {c['nota_actual']:g}"
        lines = [head]
        if not c["tareas"]:
            lines.append("  (sin notas publicadas)")
        for t in c["tareas"]:
            lines.append(f"  • {t['tarea']}: {_grade(t['nota'], t['calificacion'], t['puntos'])}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def render_files(rows) -> str:
    if not rows:
        return "No hay archivos."
    lines = []
    current = None
    for f in rows:
        if f["curso"] != current:
            current = f["curso"]
            lines.append(f"{current}:")
        where = f" [{f['modulo']}]" if f["modulo"] else ""
        local = " ✓ descargado" if f["descargado"] else ""
        lines.append(f"  {f['id']}  {f['archivo']}{where} {_size(f['tamano'])}{local}")
    return "\n".join(lines)


def render_downloads(rows) -> str:
    return "\n".join(f"✓ {r['archivo']} → {r['ruta_local']}" if r.get("ruta_local") else f"✗ {r['archivo']}: {r['error']}"
                     for r in rows) or "Nada que bajar."


def render_read(data) -> str:
    lines = [f"{data['archivo']} — {data['curso']}", data["url"], ""]
    if not data["contenido"]:
        lines.append("(sin texto indexado; bájalo primero con `aula archivos bajar "
                     f"{data['id']}`)")
    for page in data["contenido"]:
        lines.append(f"--- {data['unidad']} {page['pagina']} ---")
        lines.append(page["texto"])
    return "\n".join(lines)


def render_search(rows) -> str:
    if not rows:
        return "No encontré nada en el material indexado."
    return "\n\n".join(
        f"{i}. {r['archivo']} — {r['unidad']} {r['pagina']} ({r['curso']})\n   {r['fragmento']}\n   {r['url']}"
        for i, r in enumerate(rows, start=1)
    )


def render_sync(report) -> str:
    text = (f"Listo: {report['cursos']} materias leídas, {report['cambios']} cambios nuevos, "
            f"{report['solicitudes']} consultas al aula virtual.")
    for w in report["avisos"]:
        text += f"\n⚠ {w}"
    return text


# -- commands -------------------------------------------------------------------------


def _refresh(aula: Aula, args) -> None:
    if getattr(args, "sin_actualizar", False):
        return
    try:
        if getattr(args, "actualizar", False):
            aula.sync()
        else:
            aula.ensure_fresh()
    except (CanvasError, ConfigError) as exc:
        if queries.courses(aula.conn):
            print(f"⚠ No pude actualizar desde el aula virtual ({exc}); muestro los últimos datos guardados.",
                  file=sys.stderr)
        else:
            raise


def _parse_range(value: str | None) -> tuple[int | None, int | None]:
    if not value:
        return None, None
    first, _, last = value.partition("-")
    return int(first), int(last or first)


def run(args, aula: Aula) -> int:
    as_json = getattr(args, "json", False)
    cmd = args.cmd

    if cmd == "sincronizar":
        report = aula.sync(materials=args.material)
        data = {"cursos": report.courses, "cambios": report.events, "solicitudes": report.requests,
                "primera_vez": report.first_sync, "avisos": report.warnings}
        _out(data, as_json, render_sync)
        return 0

    if cmd not in ("buscar",) and not (cmd == "archivos" and args.accion == "leer"):
        _refresh(aula, args)
    conn = aula.conn
    ids = queries.course_ids(conn, getattr(args, "curso", None))

    if cmd == "cursos":
        _out(queries.courses(conn), as_json, render_courses)
    elif cmd == "tareas":
        _out(queries.pending(conn, aula.now(), ids, days=args.dias), as_json, lambda r: render_tasks(r, aula))
    elif cmd == "anuncios":
        _out(queries.announcements(conn, ids, limit=args.n), as_json, lambda r: render_announcements(r, aula))
    elif cmd == "notas":
        _out(queries.grades(conn, ids), as_json, render_grades)
    elif cmd == "buscar":
        _out(search.search(conn, args.pregunta, course_ids=ids, limit=args.n), as_json, render_search)
    elif cmd == "archivos":
        if args.accion == "listar":
            _out(queries.files(conn, ids, args.nombre), as_json, render_files)
        elif args.accion == "leer":
            if len(args.ids) != 1:
                raise SystemExit("Uso: aula archivos leer <id> [--paginas 3-5]")
            first, last = _parse_range(args.paginas)
            _out(queries.read_pages(conn, args.ids[0], first, last), as_json, render_read)
        else:
            targets = [queries.file_by_id(conn, i) for i in args.ids] if args.ids else (
                queries.files(conn, ids, args.nombre) if (args.curso or args.nombre) else [])
            if not targets:
                raise SystemExit("Uso: aula archivos bajar <id>...  o  aula archivos bajar --curso X --nombre Y")
            results = []
            for f in targets:
                try:
                    path = aula.download(f["id"])
                    results.append({**queries.file_by_id(conn, f["id"]), "ruta_local": str(path)})
                except CanvasError as exc:
                    results.append({**f, "ruta_local": None, "error": str(exc)})
            _out(results, as_json, render_downloads)
            return 0 if all(r.get("ruta_local") for r in results) else 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    aula = None
    try:
        aula = Aula()
        return run(args, aula)
    except (ConfigError, CanvasError, queries.NotFound) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if aula is not None:
            aula.close()


if __name__ == "__main__":
    raise SystemExit(main())
