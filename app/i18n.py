"""German user interface.

Texts are written in English in the code and translated where they are rendered: the Streamlit widgets
(patched once in ``install``), the design-system helpers in ``common`` and the charts in ``common.plot``.
The program logic never sees a translated string – option values, column keys and stored data stay English.

The catalog ``locales/de.json`` maps every English text to German. Texts built with f-strings are templates
("in {} years" -> "in {} Jahren"); at runtime a template is matched against the finished text and the inserted
values are translated recursively. ``scripts/i18n_catalog.py`` lists texts without a translation, and in German
mode every miss is recorded (``missed()``) – the UI sweep uses that to prove the German UI complete.
"""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from portfolio_tracker import fmt

CATALOG = Path(__file__).parent / "locales" / "de.json"
LANGUAGES = {"en": "English", "de": "Deutsch"}
_MISSED: set[str] = set()
_MONTHS = {"Jan": "Jan.", "Feb": "Feb.", "Mar": "März", "Apr": "Apr.", "May": "Mai", "Jun": "Juni", "Jul": "Juli",
           "Aug": "Aug.", "Sep": "Sep.", "Oct": "Okt.", "Nov": "Nov.", "Dec": "Dez."}
_FULL_MONTHS = {"January": "Januar", "February": "Februar", "March": "März", "May": "Mai", "June": "Juni",
                "July": "Juli", "October": "Oktober", "December": "Dezember"}
_FULL_MONTH_YEAR = re.compile(r"\b(" + "|".join(_FULL_MONTHS) + r")( \d{4})\b")
_SYMBOLS = re.compile(r"^([←→★·•\s]*)(.*?)([←→★·•\s]*)$", re.DOTALL)
_DATE = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r")\b( \d{4})?")
_MONTH_YEAR = re.compile(r"\b(" + "|".join(_MONTHS) + r") (\d{4})\b")


def lang() -> str:
    return "de" if st.session_state.get("lang") == "de" else "en"


def activate() -> None:
    """Apply the language chosen in the sidebar to number formats and charts (call at the top of every run)."""
    import charts

    fmt.set_language(lang())
    charts.set_language(lang())


@functools.cache
def _catalog() -> tuple[dict[str, str], list[tuple[str, str, str, re.Pattern, str]]]:
    data = json.loads(CATALOG.read_text()) if CATALOG.exists() else {}
    exact, templates = {}, []
    for en, de in data.get("translations", {}).items():
        if "{}" in en.replace("{{", "").replace("}}", ""):
            parts = re.split(r"(?<!\{)\{\}(?!\})", en)
            parts = [p.replace("{{", "{").replace("}}", "}") for p in parts]
            rx = re.compile("^" + "(.*?)".join(re.escape(p) for p in parts) + "$", re.DOTALL)
            templates.append((parts[0], parts[-1], en, rx, de))
            if en != en.strip():
                core = re.split(r"(?<!\{)\{\}(?!\})", en.strip())
                core = [p.replace("{{", "{").replace("}}", "}") for p in core]
                core_rx = re.compile("^" + "(.*?)".join(re.escape(p) for p in core) + "$", re.DOTALL)
                templates.append((core[0], core[-1], en.strip(), core_rx, de.strip()))
        else:
            exact[en] = de
            exact.setdefault(en.strip(), de.strip())   # tr() looks up texts without surrounding whitespace
    # most specific first: more literal text, fewer gaps
    templates.sort(key=lambda t: -len(t[2].replace("{}", "")))
    return exact, templates


def _dates(text: str) -> str:
    text = _DATE.sub(lambda m: f"{int(m[1])}. {_MONTHS[m[2]]}{m[3] or ''}", text)
    text = _FULL_MONTH_YEAR.sub(lambda m: f"{_FULL_MONTHS[m[1]]}{m[2]}", text)
    return _MONTH_YEAR.sub(lambda m: f"{_MONTHS[m[1]]} {m[2]}", text)


def tr(text):
    """German version of an English UI text (unchanged in English mode, for unknown texts and non-strings)."""
    if not isinstance(text, str) or lang() != "de" or not text.strip() or text.startswith("%{"):
        return text
    core = text.strip()
    if core != text:   # keep surrounding whitespace, translate the content
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        return lead + tr(core) + trail
    exact, templates = _catalog()
    hit = exact.get(text)
    if hit is not None:
        return hit
    for head, tail, _, rx, de in templates:
        if text.startswith(head) and text.endswith(tail):
            m = rx.match(text)
            if m:
                try:
                    return de.format(*(_dates(tr(g)) for g in m.groups()))
                except (IndexError, KeyError, ValueError):
                    break
    sym = _SYMBOLS.match(text)
    if sym and (sym[1] or sym[3]) and sym[2]:   # "← 2 · Financials", "Next →", " ★ watchlist"
        return sym[1] + tr(sym[2]) + sym[3]
    dated = _dates(text)
    if dated == text and re.search(r"[a-z]{3,}", text) and not text.lstrip().startswith("<") \
            and not _looks_german(text):
        _MISSED.add(text)
    return dated


def _looks_german(text: str) -> bool:
    """Already translated (a German catalog text, or one built from German pieces) – not a miss."""
    exact, _ = _catalog()
    words = set(re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", text))
    german = _german_words()
    return bool(re.search(r"[äöüßÄÖÜ]", text)) or text in exact.values() or bool(words & german)


@functools.cache
def _german_words() -> set[str]:
    exact, templates = _catalog()
    english = {w for en in list(exact) + [t[2] for t in templates] for w in re.findall(r"[A-Za-z]{4,}", en)}
    german = {w for de in list(exact.values()) + [t[4] for t in templates] for w in re.findall(r"[A-Za-zÄÖÜäöüß]{4,}", de)}
    return german - english


def missed() -> set[str]:
    return set(_MISSED)


# ------------------------------------------------------------------ widgets
_TEXT_KWARGS = ("label", "help", "placeholder", "body", "caption", "value_label")


def _translate_call(args: tuple, kwargs: dict, n_text: int, options: bool, skip_html: bool = False):
    args = list(args)
    for i in range(min(n_text, len(args))):
        if isinstance(args[i], str) and not (skip_html and args[i].lstrip().startswith("<")):
            args[i] = tr(args[i])
        elif isinstance(args[i], (list, tuple)) and all(isinstance(a, str) for a in args[i]):
            args[i] = [tr(a) for a in args[i]]
    for k in _TEXT_KWARGS:
        if isinstance(kwargs.get(k), str) and not (skip_html and kwargs[k].lstrip().startswith("<")):
            kwargs[k] = tr(kwargs[k])
    if options:
        shown = kwargs.get("format_func") or str
        kwargs["format_func"] = lambda o, _f=shown: tr(_f(o))
    return args, kwargs


def _patch(name: str, n_text: int = 1, options: bool = False, skip_html: bool = False) -> None:
    original = getattr(DeltaGenerator, name, None)
    if original is None or getattr(original, "_i18n", False):
        return

    @functools.wraps(original)
    def method(self, *args, **kwargs):
        if lang() == "de":
            args, kwargs = _translate_call(args, kwargs, n_text, options, skip_html)
        return original(self, *args, **kwargs)

    method._i18n = True
    setattr(DeltaGenerator, name, method)


def _patch_tables(name: str) -> None:
    original = getattr(DeltaGenerator, name, None)
    if original is None or getattr(original, "_i18n", False):
        return

    @functools.wraps(original)
    def method(self, data=None, *args, **kwargs):
        if lang() == "de" and hasattr(data, "columns"):
            config = dict(kwargs.get("column_config") or {})
            for col in data.columns:
                cfg = config.get(col)
                if cfg is None:
                    config[col] = {"label": tr(str(col))}
                elif isinstance(cfg, dict):
                    cfg = dict(cfg)
                    cfg.setdefault("label", tr(str(col)))
                    if isinstance(cfg.get("help"), str):
                        cfg["help"] = tr(cfg["help"])
                    config[col] = cfg
            kwargs["column_config"] = config
        return original(self, data, *args, **kwargs)

    method._i18n = True
    setattr(DeltaGenerator, name, method)


def install() -> None:
    """Patch the Streamlit elements once per process; they translate only while German is selected."""
    for name in ("markdown", "caption", "subheader", "header", "title", "text"):
        _patch(name, skip_html=True)
    for name in ("info", "success", "warning", "error", "toggle", "button", "checkbox", "expander", "popover",
                 "download_button", "file_uploader", "text_input", "text_area", "number_input", "slider",
                 "date_input", "link_button", "form_submit_button", "metric"):
        _patch(name)
    for name in ("selectbox", "multiselect", "radio", "segmented_control", "pills", "select_slider"):
        _patch(name, options=True)
    _patch("tabs")
    _patch_tables("data_editor")
    _patch_tables("dataframe")
    # st.markdown, st.tabs, … are bound to the main container when Streamlit is imported – rebind them
    for name, value in list(vars(st).items()):
        if getattr(value, "__self__", None) is st._main and getattr(getattr(DeltaGenerator, name, None), "_i18n", False):
            setattr(st, name, getattr(st._main, name))


# ------------------------------------------------------------------ charts
def figure(fig) -> None:
    """Translate a Plotly figure in place: legend names, hover labels, categories, annotations, axis titles."""
    if lang() != "de":
        return
    import charts

    charts.localize(fig)

    def extra(template):
        if not isinstance(template, str):
            return template
        return re.sub(r"<extra>(.*?)</extra>", lambda m: f"<extra>{tr(m[1])}</extra>", template)

    def seq(values):
        if values is None or isinstance(values, str):
            return values
        try:
            items = list(values)
        except TypeError:
            return values
        if items and all(isinstance(v, str) for v in items):
            return [tr(v) for v in items]
        return values

    for t in fig.data:
        if getattr(t, "name", None):
            t.name = tr(t.name)
        if hasattr(t, "hovertemplate"):
            t.hovertemplate = extra(t.hovertemplate)
        for attr in ("x", "y", "labels"):
            if hasattr(t, attr) and t.type in ("bar", "pie", "heatmap", "treemap", "box", "funnel", "waterfall"):
                setattr(t, attr, seq(getattr(t, attr)))
        if t.type == "sankey":
            t.node.label = seq(t.node.label)
        if t.type in ("bar", "scatter") and isinstance(getattr(t, "text", None), (list, tuple)):
            t.text = seq(t.text)
    for a in fig.layout.annotations or ():
        a.text = tr(a.text)
    for ax in (fig.layout.xaxis, fig.layout.yaxis):
        if ax.title and ax.title.text:
            ax.title.text = tr(ax.title.text)
        if ax.ticktext:
            ax.ticktext = seq(ax.ticktext)
