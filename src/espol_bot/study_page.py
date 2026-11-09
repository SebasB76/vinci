"""Study pages: a review or a long explanation as an interactive page (docs/repaso/), sent as a WhatsApp URL button.

The model never writes HTML: it fills a catalog of blocks (text, formulas, plots with sliders, a sequence or an
architecture diagram walked step by step, flashcards, a quiz…) through `send_study_page`. This module checks every
field and says in Spanish what to fix, so a small model gets it right on its second call; the page owns each block's
look and behavior. As on «Tus notas» (grades_page.py), the page asks no server for anything: the content rides in the
URL's fragment, and what the student answers stays on the page.
"""

from __future__ import annotations

import ast
import math
import re

from espol_bot.config import BotConfig
from espol_bot.dashboard import encode

VERSION = 1
BUTTON = "📚 Abrir el repaso"
# The 4,000 of the other pages is for Telegram's Mini Apps; these only go out as WhatsApp's URL button, which documents
# no limit. A full review (8 blocks) takes about 4,000.
MAX_URL = 8000
MIN_BLOCKS, MAX_BLOCKS = 2, 12

BLOCKS = ("text", "callout", "formula", "function_plot", "distribution", "steps", "flashcards", "quiz", "sequence",
          "compare", "classify", "order", "code", "diagram")
INTERACTIVE = {"function_plot", "distribution", "steps", "flashcards", "quiz", "sequence", "classify", "order", "code",
               "diagram"}
CALLOUTS = ("tip", "warning", "key")
DISTRIBUTIONS = {"normal": ("mu", "sigma"), "binomial": ("n", "p"), "poisson": ("lambda",)}
QUERIES = ("less", "greater", "between")

FUNCTIONS = {"sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos,
             "atan": math.atan, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh, "exp": math.exp,
             "ln": math.log, "log": math.log10, "sqrt": math.sqrt, "abs": abs, "floor": math.floor, "ceil": math.ceil}
CONSTANTS = {"pi": math.pi, "e": math.e}
PARAM_NAME = re.compile(r"^[a-zA-Z]\w{0,9}$")
LINK = re.compile(r"\[([^\]]+)\]\((https://[^)\s]+)\)")


class StudyPageError(Exception):
    pass


class _Check:
    """Collects every problem at once, each with where it is, so one retry fixes them all."""

    def __init__(self):
        self.errors: list[str] = []

    def fail(self, where: str, what: str) -> None:
        self.errors.append(f"{where}: {what}")

    def text(self, value, where: str, limit: int, required: bool = True) -> str:
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self.fail(where, "falta el texto")
            return ""
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            self.fail(where, "debe ser un texto")
            return ""
        text = re.sub(r"\n{3,}", "\n\n", str(value).strip())
        if len(text) > limit:
            self.fail(where, f"tiene {len(text)} caracteres y el máximo es {limit}: acórtalo")
        return text

    def items(self, value, where: str, lo: int, hi: int) -> list:
        if not isinstance(value, list):
            self.fail(where, f"debe ser una lista de {lo} a {hi} elementos")
            return []
        if not lo <= len(value) <= hi:
            self.fail(where, f"tiene {len(value)} elementos y van de {lo} a {hi}")
        return value[:hi]

    def number(self, value, where: str, lo: float | None = None, hi: float | None = None,
               integer: bool = False) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            self.fail(where, "debe ser un número")
            return None
        if integer and int(value) != value:
            self.fail(where, "debe ser un número entero")
            return None
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            self.fail(where, f"es {value} y va de {lo} a {hi}")
            return None
        return int(value) if integer else float(value)

    def answer(self, value, options: list[str], where: str) -> int:
        """The right option, written as one of the options (as in send_quiz); its position on the page."""
        if isinstance(value, str):
            wanted = value.strip().casefold()
            for i, option in enumerate(options):
                if option.casefold() == wanted:
                    return i
        self.fail(where, f"«answer» debe ser una de las opciones, escrita igual: {', '.join(options)}")
        return 0


def _node(tree: ast.AST, names: set[str]) -> None:
    """Only arithmetic over x, the sliders' names, pi, e and FUNCTIONS: the page evaluates the same grammar."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS or len(node.args) != 1 \
                    or node.keywords:
                raise ValueError("solo funciones de una variable: " + ", ".join(FUNCTIONS))
        elif isinstance(node, ast.Name):
            if node.id not in names and node.id not in CONSTANTS and node.id not in FUNCTIONS:
                raise ValueError(f"«{node.id}» no es x, pi, e ni un parámetro de «params»")
        elif isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("solo números")
        elif not isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Add, ast.Sub, ast.Mult, ast.Div,
                                   ast.Pow, ast.USub, ast.UAdd, ast.Load)):
            raise ValueError("solo + - * / ^, paréntesis y funciones")


def _evaluate(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, env)
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return env.get(node.id, CONSTANTS.get(node.id, math.nan))
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, env)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Call):
        return float(FUNCTIONS[node.func.id](_evaluate(node.args[0], env)))
    left, right = _evaluate(node.left, env), _evaluate(node.right, env)
    if isinstance(node.op, ast.Add):
        return left + right
    if isinstance(node.op, ast.Sub):
        return left - right
    if isinstance(node.op, ast.Mult):
        return left * right
    if isinstance(node.op, ast.Div):
        return left / right
    return math.pow(left, right)


def _expression(expr: str, params: dict[str, float], x_range: tuple[float, float]) -> str | None:
    """Why the curve cannot be drawn, or None: it parses, uses known names and has a value somewhere in x_range."""
    if re.search(r"\d\s*[a-zA-Z(]|\)\s*[\w(]", expr):
        return "escribe cada multiplicación con «*» (2*x, no 2x; (x+1)*(x-1), no (x+1)(x-1))"
    try:
        tree = ast.parse(expr.replace("^", "**"), mode="eval")
        _node(tree, set(params) | {"x"})
    except SyntaxError:
        return "no se entiende la expresión"
    except ValueError as exc:
        return str(exc)
    lo, hi = x_range
    for k in range(41):
        try:
            value = _evaluate(tree, {**params, "x": lo + (hi - lo) * k / 40})
        except (ValueError, ZeroDivisionError, OverflowError):
            continue
        if math.isfinite(value):
            return None
    return "no tiene ningún valor en ese rango de x"


def _range(check: _Check, value, where: str) -> tuple[float, float] | None:
    if not isinstance(value, list) or len(value) != 2:
        check.fail(where, "debe ser [mínimo, máximo]")
        return None
    lo, hi = check.number(value[0], where), check.number(value[1], where)
    if lo is None or hi is None:
        return None
    if lo >= hi:
        check.fail(where, "el mínimo debe ser menor que el máximo")
        return None
    return lo, hi


def _text_block(check: _Check, block: dict, where: str) -> dict:
    return {"body": check.text(block.get("body"), f"{where} «body»", 1500)}


def _callout(check: _Check, block: dict, where: str) -> dict:
    kind = block.get("kind") or "tip"
    if kind not in CALLOUTS:
        check.fail(f"{where} «kind»", "es tip (un consejo), warning (un error común) o key (lo que no puede olvidar)")
    return {"kind": kind, "body": check.text(block.get("body"), f"{where} «body»", 500)}


def _formula(check: _Check, block: dict, where: str) -> dict:
    legend = []
    for i, row in enumerate(check.items(block.get("legend") or [], f"{where} «legend»", 0, 8), 1):
        row = row if isinstance(row, dict) else {}
        legend.append({"symbol": check.text(row.get("symbol"), f"{where} «legend» {i} «symbol»", 40),
                       "meaning": check.text(row.get("meaning"), f"{where} «legend» {i} «meaning»", 120)})
    return {"latex": check.text(block.get("latex"), f"{where} «latex»", 300), "legend": legend}


def _function_plot(check: _Check, block: dict, where: str) -> dict:
    x_range = _range(check, block.get("x"), f"{where} «x»") or (-10.0, 10.0)
    y_range = _range(check, block["y"], f"{where} «y»") if block.get("y") is not None else None
    params, values = [], {}
    for i, raw in enumerate(check.items(block.get("params") or [], f"{where} «params»", 0, 4), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} parámetro {i}"
        name = str(raw.get("name") or "")
        if not PARAM_NAME.match(name) or name in {"x", *CONSTANTS, *FUNCTIONS}:
            check.fail(f"{at} «name»", "una letra o palabra corta que no sea x, pi, e ni una función")
        lo, hi = check.number(raw.get("min"), f"{at} «min»"), check.number(raw.get("max"), f"{at} «max»")
        value = check.number(raw.get("value"), f"{at} «value»")
        if None not in (lo, hi, value) and not lo <= value <= hi:
            check.fail(at, "«value» debe estar entre «min» y «max»")
        step = raw.get("step")
        if step is not None:
            step = check.number(step, f"{at} «step»", 1e-9)
        params.append({"name": name, "min": lo, "max": hi, "value": value,
                       "label": check.text(raw.get("label"), f"{at} «label»", 30, required=False),
                       **({"step": step} if step else {})})
        values[name] = value if value is not None else 0.0
    curves = []
    for i, raw in enumerate(check.items(block.get("curves"), f"{where} «curves»", 1, 3), 1):
        raw = raw if isinstance(raw, dict) else {}
        expr = check.text(raw.get("expr"), f"{where} curva {i} «expr»", 120)
        if expr and (why := _expression(expr, values, x_range)):
            check.fail(f"{where} curva {i} «expr» ({expr})", why)
        curves.append({"expr": expr, "label": check.text(raw.get("label"), f"{where} curva {i} «label»", 30,
                                                         required=False)})
    return {"curves": curves, "x": list(x_range), **({"y": list(y_range)} if y_range else {}), "params": params}


def _distribution(check: _Check, block: dict, where: str) -> dict:
    dist = block.get("dist")
    if dist not in DISTRIBUTIONS:
        check.fail(f"{where} «dist»", "es normal (mu, sigma), binomial (n, p) o poisson (lambda)")
        return {"dist": "normal", "mu": 0, "sigma": 1, "query": {"kind": "less", "a": 0}}
    out = {"dist": dist}
    limits = {"mu": (-1e6, 1e6, False), "sigma": (1e-6, 1e6, False), "n": (1, 100, True), "p": (0, 1, False),
              "lambda": (0.01, 50, False)}
    for name in DISTRIBUTIONS[dist]:
        lo, hi, integer = limits[name]
        out[name] = check.number(block.get(name), f"{where} «{name}»", lo, hi, integer)
    query = block.get("query") if isinstance(block.get("query"), dict) else {"kind": "less", "a": None}
    kind = query.get("kind") or "less"
    if kind not in QUERIES:
        check.fail(f"{where} «query» «kind»", "es less (P(X ≤ a)), greater (P(X ≥ a)) o between (P(a ≤ X ≤ b))")
    a = check.number(query.get("a"), f"{where} «query» «a»")
    out["query"] = {"kind": kind, "a": a}
    if kind == "between":
        b = check.number(query.get("b"), f"{where} «query» «b»")
        if a is not None and b is not None and b <= a:
            check.fail(f"{where} «query»", "«b» debe ser mayor que «a»")
        out["query"]["b"] = b
    return out


def _steps(check: _Check, block: dict, where: str) -> dict:
    return {"problem": check.text(block.get("problem"), f"{where} «problem»", 500),
            "steps": [check.text(s, f"{where} paso {i}", 400)
                      for i, s in enumerate(check.items(block.get("steps"), f"{where} «steps»", 2, 10), 1)],
            "answer": check.text(block.get("answer"), f"{where} «answer»", 200, required=False)}


def _flashcards(check: _Check, block: dict, where: str) -> dict:
    cards = []
    for i, raw in enumerate(check.items(block.get("cards"), f"{where} «cards»", 2, 12), 1):
        raw = raw if isinstance(raw, dict) else {}
        cards.append({"front": check.text(raw.get("front"), f"{where} tarjeta {i} «front»", 200),
                      "back": check.text(raw.get("back"), f"{where} tarjeta {i} «back»", 300)})
    return {"cards": cards}


def _quiz(check: _Check, block: dict, where: str) -> dict:
    questions = []
    for i, raw in enumerate(check.items(block.get("questions"), f"{where} «questions»", 1, 8), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} pregunta {i}"
        options = [check.text(o, f"{at} opción {k}", 150)
                   for k, o in enumerate(check.items(raw.get("options"), f"{at} «options»", 2, 5), 1)]
        if len({o.casefold() for o in options}) < len(options):
            check.fail(f"{at} «options»", "hay opciones repetidas")
        questions.append({"question": check.text(raw.get("question"), f"{at} «question»", 300), "options": options,
                          "answer": check.answer(raw.get("answer"), options, at) if options else 0,
                          "explanation": check.text(raw.get("explanation"), f"{at} «explanation»", 400)})
    return {"questions": questions}


def _sequence(check: _Check, block: dict, where: str) -> dict:
    actors = [check.text(a, f"{where} actor {i}", 24)
              for i, a in enumerate(check.items(block.get("actors"), f"{where} «actors»", 2, 4), 1)]
    index = {a.casefold(): i for i, a in enumerate(actors)}
    if len(index) < len(actors):
        check.fail(f"{where} «actors»", "hay actores repetidos")
    scenarios = []
    for s, raw in enumerate(check.items(block.get("scenarios"), f"{where} «scenarios»", 1, 3), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} escenario {s}"
        messages = []
        for m, msg in enumerate(check.items(raw.get("messages"), f"{at} «messages»", 1, 12), 1):
            msg, here = msg if isinstance(msg, dict) else {}, f"{at} mensaje {m}"
            ends = []
            for key in ("from", "to"):
                found = index.get(str(msg.get(key) or "").strip().casefold())
                if found is None:
                    check.fail(f"{here} «{key}»", f"debe ser uno de los actores: {', '.join(actors)}")
                ends.append(found or 0)
            messages.append({"from": ends[0], "to": ends[1], "label": check.text(msg.get("label"), f"{here} «label»", 24),
                             "note": check.text(msg.get("note"), f"{here} «note»", 300),
                             **({"fail": True} if msg.get("fail") else {})})
        scenarios.append({"name": check.text(raw.get("name"), f"{at} «name»", 30, required=len(block.get("scenarios")
                                                                                                 or []) > 1),
                          "messages": messages})
    return {"actors": actors, "scenarios": scenarios}


def _compare(check: _Check, block: dict, where: str) -> dict:
    columns = [check.text(c, f"{where} columna {i}", 30)
               for i, c in enumerate(check.items(block.get("columns"), f"{where} «columns»", 2, 3), 1)]
    rows = []
    for i, raw in enumerate(check.items(block.get("rows"), f"{where} «rows»", 1, 8), 1):
        raw = raw if isinstance(raw, dict) else {}
        values = [check.text(v, f"{where} fila {i} valor {k}", 120)
                  for k, v in enumerate(check.items(raw.get("values"), f"{where} fila {i} «values»", len(columns),
                                                    len(columns)), 1)]
        rows.append({"aspect": check.text(raw.get("aspect"), f"{where} fila {i} «aspect»", 40), "values": values})
    return {"columns": columns, "rows": rows}


def _classify(check: _Check, block: dict, where: str) -> dict:
    options = [check.text(o, f"{where} opción {i}", 40)
               for i, o in enumerate(check.items(block.get("options"), f"{where} «options»", 2, 6), 1)]
    cases = []
    for i, raw in enumerate(check.items(block.get("cases"), f"{where} «cases»", 1, 6), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} caso {i}"
        cases.append({"text": check.text(raw.get("text"), f"{at} «text»", 300),
                      "answer": check.answer(raw.get("answer"), options, at) if options else 0,
                      "explanation": check.text(raw.get("explanation"), f"{at} «explanation»", 300)})
    return {"options": options, "cases": cases}


def _order(check: _Check, block: dict, where: str) -> dict:
    items = [check.text(t, f"{where} elemento {i}", 60)
             for i, t in enumerate(check.items(block.get("items"), f"{where} «items»", 3, 8), 1)]
    if len({t.casefold() for t in items}) < len(items):
        check.fail(f"{where} «items»", "hay elementos repetidos")
    return {"items": items, "explanation": check.text(block.get("explanation"), f"{where} «explanation»", 400)}


def _code(check: _Check, block: dict, where: str) -> dict:
    code = check.text(block.get("code"), f"{where} «code»", 2000).replace("\t", "    ")
    lines = code.split("\n")
    if len(lines) > 30:
        check.fail(f"{where} «code»", f"tiene {len(lines)} líneas y el máximo es 30: deja solo lo que explica la idea")
    walk = []
    for i, raw in enumerate(check.items(block.get("walkthrough"), f"{where} «walkthrough»", 1, 8), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} explicación {i}"
        marked = []
        for n in check.items(raw.get("lines"), f"{at} «lines»", 1, 30):
            number = check.number(n, f"{at} «lines»", 1, len(lines), integer=True)
            if number is not None:
                marked.append(number)
        walk.append({"lines": marked, "note": check.text(raw.get("note"), f"{at} «note»", 300)})
    return {"language": check.text(block.get("language"), f"{where} «language»", 20, required=False),
            "code": code, "walkthrough": walk}


def _diagram(check: _Check, block: dict, where: str) -> dict:
    nodes, ids = [], {}
    for i, raw in enumerate(check.items(block.get("nodes"), f"{where} «nodes»", 2, 10), 1):
        raw = raw if isinstance(raw, dict) else {}
        node_id = str(raw.get("id") or "").strip()
        if not node_id:
            check.fail(f"{where} nodo {i} «id»", "falta el id")
        elif node_id in ids:
            check.fail(f"{where} nodo {i} «id»", f"«{node_id}» está repetido")
        ids[node_id] = len(nodes)
        nodes.append({"label": check.text(raw.get("label"), f"{where} nodo {i} «label»", 40)})

    def ref(value, at: str) -> int:
        found = ids.get(str(value or "").strip())
        if found is None:
            check.fail(at, f"«{value}» no es el id de un nodo ({', '.join(ids)})")
            return 0
        return found

    edges = []
    for i, raw in enumerate(check.items(block.get("edges") or [], f"{where} «edges»", 0, 16), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} arista {i}"
        ends = ref(raw.get("from"), f"{at} «from»"), ref(raw.get("to"), f"{at} «to»")
        if raw.get("from") == raw.get("to"):
            check.fail(at, "una flecha une dos nodos distintos")
        edges.append({"from": ends[0], "to": ends[1],
                      "label": check.text(raw.get("label"), f"{at} «label»", 20, required=False)})
    tour = []
    for i, raw in enumerate(check.items(block.get("tour") or [], f"{where} «tour»", 0, 10), 1):
        raw, at = raw if isinstance(raw, dict) else {}, f"{where} paso {i}"
        tour.append({"nodes": [ref(n, f"{at} «nodes»") for n in check.items(raw.get("nodes"), f"{at} «nodes»", 1, 10)],
                     "note": check.text(raw.get("note"), f"{at} «note»", 300)})
    return {"nodes": nodes, "edges": edges, "tour": tour}


CHECKS = {"text": _text_block, "callout": _callout, "formula": _formula, "function_plot": _function_plot,
          "distribution": _distribution, "steps": _steps, "flashcards": _flashcards, "quiz": _quiz,
          "sequence": _sequence, "compare": _compare, "classify": _classify, "order": _order, "code": _code,
          "diagram": _diagram}


def _words(value) -> int:
    if isinstance(value, str):
        return len(value.split())
    if isinstance(value, dict):
        return sum(_words(v) for v in value.values())
    if isinstance(value, list):
        return sum(_words(v) for v in value)
    return 0


def build(args: dict) -> dict:
    """The page's content from the tool's arguments, every field checked; StudyPageError lists all that is wrong."""
    check = _Check()
    title = check.text(args.get("title"), "«title»", 80)
    subject = check.text(args.get("subject"), "«subject»", 60, required=False)
    blocks = []
    for i, raw in enumerate(check.items(args.get("blocks"), "«blocks»", MIN_BLOCKS, MAX_BLOCKS), 1):
        if not isinstance(raw, dict) or raw.get("type") not in CHECKS:
            check.fail(f"bloque {i}", f"«type» es uno de: {', '.join(BLOCKS)}")
            continue
        where = f"bloque {i} ({raw['type']})"
        blocks.append({"type": raw["type"],
                       "title": check.text(raw.get("title"), f"{where} «title»", 50, required=False),
                       **CHECKS[raw["type"]](check, raw, where)})
    if blocks and not any(b["type"] in INTERACTIVE for b in blocks):
        check.fail("«blocks»", "ninguno es interactivo: agrega al menos un quiz, tarjetas, pasos, un gráfico o un "
                               "diagrama; si solo es texto, contéstalo en el chat")
    sources = [check.text(s, f"fuente {i}", 300)
               for i, s in enumerate(check.items(args.get("sources") or [], "«sources»", 0, 8), 1)]
    if check.errors:
        raise StudyPageError("; ".join(check.errors[:12]) + (f" (y {len(check.errors) - 12} más)"
                                                               if len(check.errors) > 12 else ""))
    minutes = max(2, round(_words(blocks) / 160 + 0.75 * sum(b["type"] in INTERACTIVE for b in blocks)))
    return {"v": VERSION, "title": title, "subject": subject, "minutes": minutes, "blocks": blocks,
            "sources": [{"label": m[1], "url": m[2]} if (m := LINK.search(s)) else {"label": s.removeprefix("📄 ")}
                        for s in sources]}


def page_url(cfg: BotConfig, data: dict) -> str:
    url = f"{cfg.study_page}#d={encode(data)}"
    if len(url) > MAX_URL:
        raise StudyPageError(f"el repaso no cabe en el enlace ({len(url)} caracteres de {MAX_URL}): quita un bloque o "
                             "acorta los textos más largos")
    return url
