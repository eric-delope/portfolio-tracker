"""Privacy guarantees as executable checks: no personal data in outputs, no network in the analytics core,
offline mode really offline, nothing personal in the repository."""

import os
import pickle
import re
import socket
import subprocess
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_analytics import SAMPLE, FakeMarket

from portfolio_tracker import decisions, privacy, taxes
from portfolio_tracker import reverse_dcf as rd
from portfolio_tracker import valuation as v
from portfolio_tracker.importer import load_transactions
from portfolio_tracker.memo import Memo, build_pdf
from portfolio_tracker.portfolio import Portfolio
from portfolio_tracker.report import available_months, build_report, to_markdown

ROOT = Path(__file__).parents[1]
# Personal details contained in the sample export (names, IBAN, card merchants, merchant category code)
PERSONAL = ["Max Mustermann", "DE00000000000000000000", "Baeckerei Beispiel", "Ramen Shop Tokyo", "5462"]


@pytest.fixture
def no_sockets(monkeypatch):
    """Any attempt to open a network connection fails the test."""
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def test_personal_data_never_reaches_any_output():
    tx = load_transactions(SAMPLE)
    p = Portfolio.build(tx, FakeMarket())
    outputs = [tx.to_csv(), p.positions.to_csv(), p.daily.to_csv(), p.monthly_cashflows.to_csv()]
    outputs += [to_markdown(build_report(p, mo)) for mo in available_months(p)]
    for text in outputs:
        for secret in PERSONAL:
            assert secret not in text, f"{secret!r} leaked"


def test_analytics_core_works_without_network(no_sockets):
    before = len(privacy.requests_log())
    p = Portfolio.build(load_transactions(SAMPLE), FakeMarket())
    p.ex_ante_risk(), p.stress_tests(), p.shadow_portfolio("MSCI World", p.index[0])
    taxes.yearly_tax_estimate(p.tx, p.realized)
    decisions.scorecard(p, "MSCI World")
    to_markdown(build_report(p, available_months(p)[0]))
    sv = v.scenario_valuation(5.0, [v.Scenario("Base", 1.0, 0.08, 20)], 5, 0.10)
    rd.implied_growth(1e11, 2e10, 0.2, 0.2, 0.09)
    build_pdf(Memo(name="X", ticker="X", currency="EUR", price=90, fair_value=float(sv.loc["Expected", "fair_value"]),
                   max_price=80, expected_return=0.1, required_return=0.1, margin_of_safety=0.15, horizon=5,
                   verdict="ok", prices=pd.Series(np.linspace(80, 100, 50), index=pd.bdate_range("2025-01-01", periods=50))))
    assert len(privacy.requests_log()) == before


def test_offline_mode_blocks_every_request(monkeypatch, tmp_path, no_sockets):
    from portfolio_tracker.market import MarketData
    from portfolio_tracker.research import Research
    monkeypatch.setenv("PORTFOLIO_OFFLINE", "1")
    before = len(privacy.requests_log())
    with pytest.raises(privacy.OfflineError):
        privacy.network("example.org", "test")
    assert MarketData(tmp_path)._search_ticker("US0378331005") is None
    research = Research(tmp_path)
    assert research.search("Apple") == []
    assert research.quotes(["AAPL"]).loc["AAPL", "price"] is None
    assert research.eur_rate("USD") == 1.0      # no cached rate yet: neutral fallback, no request
    assert len(privacy.requests_log()) == before


def test_offline_mode_prefers_stale_cache(monkeypatch, tmp_path):
    from portfolio_tracker.market import _load_pickle
    path = tmp_path / "old.pkl"
    path.write_bytes(pickle.dumps({"prices": 1}))
    old = time.time() - 30 * 86400
    os.utime(path, (old, old))
    max_age = pd.Timedelta(days=1).to_pytimedelta()
    assert _load_pickle(path, max_age=max_age) is None           # online: too old, refetch
    monkeypatch.setenv("PORTFOLIO_OFFLINE", "1")
    assert _load_pickle(path, max_age=max_age) == {"prices": 1}  # offline: old data beats none


def test_request_log_shows_what_was_sent(monkeypatch):
    monkeypatch.setattr(privacy, "_LOG", [])
    privacy.network(privacy.YAHOO, "price history", "AAPL", "MSFT")
    privacy.network(privacy.YAHOO, "price history", "AAPL")
    (group,) = privacy.summary()
    assert group["requests"] == 2 and group["sent"] == ["AAPL", "MSFT"]


def _publishable_files() -> list[Path]:
    """Files git would publish: tracked plus untracked-but-not-ignored."""
    try:
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    return [ROOT / f for f in out.splitlines() if (ROOT / f).is_file()]


def test_repository_contains_no_personal_data():
    files = _publishable_files()
    rel = [f.relative_to(ROOT).as_posix() for f in files]
    assert not [f for f in rel if f.startswith(("data/raw/", "data/user/", "data/cache/", "reports/"))]
    assert not [f for f in rel if f.endswith(".csv") and not f.startswith("data/sample/")]
    assert "CV_BULLETS.md" not in rel
    iban = re.compile(r"\b[A-Z]{2}\d{2}(?: ?\d{4}){4} ?\d{2}\b")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
    for f in files:
        if f.suffix not in {".py", ".md", ".toml", ".txt", ".csv", ".json", ".yml", ".cfg"}:
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        ibans = [m for m in iban.findall(text) if set(m[2:].replace(" ", "")) != {"0"}]  # DE00 000… = placeholder
        assert not ibans, f"IBAN-like number in {f.name}: {ibans[:1]}"
        mails = [m for m in email.findall(text) if not m.split("@")[1].startswith(("example.", "anthropic.", "users.noreply"))]
        assert not mails, f"e-mail address in {f.name}: {mails[:1]}"
