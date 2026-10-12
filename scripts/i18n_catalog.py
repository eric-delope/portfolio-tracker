"""Collect every user-visible English text of the dashboard for translation.

    python scripts/i18n_catalog.py            # list texts that have no German translation yet
    python scripts/i18n_catalog.py --json     # the same as JSON (input for translating)

Plain string literals become exact entries; f-strings become templates with ``{}`` for every inserted value
("in {} years"), which ``app/i18n.py`` matches at runtime. Code-like strings (identifiers, tickers, HTML, CSS,
format codes, Plotly hover templates) are skipped. ``tests/test_i18n.py`` runs the same scan, so a new English
text without a German translation fails CI.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = [ROOT / "app", ROOT / "src" / "portfolio_tracker"]
SKIP_FILES = {"memo.py", "i18n.py", "fmt.py"}      # the PDF memo stays English; i18n and fmt hold no UI text
CATALOG = ROOT / "app" / "locales" / "de.json"

_WORD = re.compile(r"[A-Za-z]{2,}")
_CODE = [
    re.compile(r"^[a-z0-9_\-.:]+$"),               # identifiers, keys, enums, format kinds
    re.compile(r"^[A-Z0-9.\-=^_:]+$"),             # tickers, currency codes, constants
    re.compile(r"^\s*<"),                           # HTML / scripts (helpers translate their parts)
    re.compile(r"%\{|%[YmdbBHMS]|\\"),              # Plotly hover templates, date formats, regex
    re.compile(r"^[\w.\-]+/[\w.\-/]*$"),            # paths and URLs
    re.compile(r"^https?://"),
    re.compile(r"^#[0-9a-fA-F]{3,8}$|^rgba?\("),    # colours
    re.compile(r"^:material/"),                     # icons
    re.compile(r"^[a-z]+[A-Z]\w*$"),               # camelCase data keys
    re.compile(r"%[sdr]\b|\(\?|\([^()\s]*\|[^()]*\)"),  # log formats, regular expressions
    re.compile(r"^(Mozilla|User-Agent)"),
]


def is_text(s: str) -> bool:
    return bool(_WORD.search(s)) and not any(p.search(s) for p in _CODE)


def _template(node: ast.JoinedStr) -> str | None:
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(str(v.value).replace("{", "{{").replace("}", "}}"))
        else:
            parts.append("{}")
    tpl = "".join(parts)
    literal = "".join(str(v.value) for v in node.values if isinstance(v, ast.Constant))
    # a single lowercase word around a value ("{} months", "goal {}") is text, unlike a lone identifier
    if not re.search(r"[A-Za-z]{3,}", literal) or (not is_text(literal.strip() or "x")
                                                   and not re.fullmatch(r"[\s·,.:;()+−-]*[a-z]{3,}[\s·,.:;()+−-]*", literal)):
        return None
    return tpl


def _docstrings(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                out.add(id(first.value))
    return out


def _not_ui(tree: ast.AST) -> set[int]:
    """Strings that never reach the UI: log messages, exception texts, dictionary lookups by key."""
    out = set()
    for n in ast.walk(tree):
        args = []
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in (
                "debug", "info", "warning", "error", "exception") and isinstance(n.func.value, ast.Name) \
                and n.func.value.id in ("log", "logger", "logging"):
            args = n.args
        elif isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
            args = n.exc.args
        elif isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load):
            args = [n.slice]
        for a in args:
            out.update(id(x) for x in ast.walk(a))
    return out


def scan() -> list[str]:
    """Every English text and template, in source order, without duplicates."""
    seen: dict[str, None] = {}
    for base in SOURCES:
        for path in sorted(base.rglob("*.py")):
            if path.name in SKIP_FILES:
                continue
            tree = ast.parse(path.read_text())
            docs = _docstrings(tree) | _not_ui(tree)
            inside_fstring = {id(v) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for v in n.values}
            for n in ast.walk(tree):
                if isinstance(n, ast.JoinedStr) and id(n) not in docs:
                    tpl = _template(n)
                    if tpl:
                        seen.setdefault(tpl, None)
                elif (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
                      and id(n) not in inside_fstring and is_text(n.value)):
                    seen.setdefault(n.value, None)
    return list(seen)


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text()) if CATALOG.exists() else {"translations": {}, "keep": []}


def missing() -> list[str]:
    cat = load_catalog()
    known = set(cat.get("translations", {})) | set(cat.get("keep", []))
    return [s for s in scan() if s not in known]


if __name__ == "__main__":
    todo = missing()
    if "--json" in sys.argv:
        print(json.dumps(todo, ensure_ascii=False, indent=1))
    else:
        for s in todo:
            print(repr(s))
        print(f"\n{len(todo)} texts without a German translation", file=sys.stderr)
