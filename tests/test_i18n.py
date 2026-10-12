"""German user interface: catalog coverage, template matching and German number formats."""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))

import i18n  # noqa: E402
import i18n_catalog  # noqa: E402

from portfolio_tracker import fmt  # noqa: E402


@pytest.fixture
def german(monkeypatch):
    monkeypatch.setattr(i18n, "lang", lambda: "de")
    fmt.set_language("de")
    yield
    fmt.set_language("en")


def test_every_ui_text_has_a_german_translation():
    assert i18n_catalog.missing() == []


def test_templates_keep_their_placeholders():
    cat = json.loads(i18n.CATALOG.read_text())["translations"]
    for en, de in cat.items():
        n_en = len(re.findall(r"(?<!\{)\{\}(?!\})", en))
        numbered = re.findall(r"\{(\d)\}", de)
        n_de = len(re.findall(r"(?<!\{)\{\}(?!\})", de))
        if numbered:
            assert max(int(i) for i in numbered) < n_en, en
        else:
            assert n_de == n_en, en


def test_exact_text_template_and_nested_values(german):
    assert i18n.tr("Monthly report") == "Monatsbericht"
    assert i18n.tr("in 20 years") == "in 20 Jahren"
    # the inserted value is translated too, the name stays
    assert i18n.tr("**ASML** – Buy zone") == "**ASML** – Kaufzone"
    assert i18n.tr("Unknown company name") == "Unknown company name"
    assert "Unknown company name" in i18n.missed()


def test_dates_and_arrows(german):
    assert i18n.tr("12 Oct 2026") == "12. Okt. 2026"
    assert i18n.tr("prices to 01 May 2026") == "Kurse bis 1. Mai 2026"
    assert i18n.tr("October 2026") == "Oktober 2026"
    assert i18n.tr("← 2 · Financials") == "← 2 · Finanzen"


def test_english_mode_is_untouched():
    assert i18n.tr("Monthly report") == "Monthly report"


def test_german_number_formats(german):
    assert fmt.eur(-1234.5, 2, True) == "-1.234,50 €"
    assert fmt.pct(0.1234) == "+12,3 %"
    assert fmt.num(1234567.891, 2) == "1.234.567,89"
    assert fmt.spec(1234.5, ",.1f") == "1.234,5"
