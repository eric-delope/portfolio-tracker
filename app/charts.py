"""Plotly figure builders for the dashboard.

Colors come from a validated categorical palette (fixed slot order, CVD-safe
for adjacent series). Signed values (P&L, returns) use a blue <-> red
diverging pair with a neutral gray midpoint, so gains and losses stay
distinguishable for red-green colorblind readers; every signed value also
carries an explicit +/- sign in labels and tooltips.
"""

from __future__ import annotations

import contextvars
import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from i18n import tr

from portfolio_tracker import fmt

# Categorical slots, in this order only (never cycled).
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
DEPOT, BENCH, BENCH2, BENCH3 = SERIES[0], SERIES[1], SERIES[2], SERIES[3]
OTHER = "#b5b3ab"

POS, NEG, NEUTRAL = "#2a78d6", "#e34948", "#f0efec"
DIVERGING = [[0.0, "#d65554"], [0.25, "#efa3a2"], [0.5, NEUTRAL], [0.75, "#a7cbf5"], [1.0, "#4a90e6"]]
SEQUENTIAL = [[0.0, "#cde2fb"], [0.5, "#5598e7"], [1.0, "#104281"]]

TEXT, TEXT2, MUTED = "#0b0b0b", "#52514e", "#898781"
# Dark text on coloured tiles (treemap, stacked bar): deliberately not one of the neutral greys above, so the
# dark-mode stylesheet – which lightens those greys – leaves it alone.
ON_FILL = "#1c1c1b"
GRID, AXIS, SURFACE = "#ebeae4", "#c3c2b7", "#fcfcfb"
# Same typeface as the Streamlit app, so charts and page read as one document.
FONT = 'Inter, system-ui, -apple-system, "Segoe UI", sans-serif'

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


# Currency symbol of the reporting currency; set once per run by the dashboard (thread-safe per session).
_SYMBOL: contextvars.ContextVar[str] = contextvars.ContextVar("currency_symbol", default="€")


def set_currency(symbol: str) -> None:
    _SYMBOL.set(symbol)


_LANG: contextvars.ContextVar[str] = contextvars.ContextVar("chart_language", default="en")


def set_language(lang: str) -> None:
    """German: decimal comma and the currency symbol after the number (applied in ``localize``)."""
    _LANG.set(lang)


def _cur() -> str:
    return _SYMBOL.get()


def _eur(x: float, decimals: int = 0, sign: bool = False) -> str:
    """€1,234 / +€1,234 / −€56 (reporting-currency symbol) for text labels inside figures."""
    prefix = ("+" if x > 0 else "−" if x < 0 else "") if sign else ("−" if x < 0 else "")
    if _LANG.get() == "de":
        return f"{prefix}{f'{abs(x):,.{decimals}f}'.translate(_DE_DIGITS)} {_cur()}"
    return f"{prefix}{_cur()}{abs(x):,.{decimals}f}"


_DE_DIGITS = str.maketrans({",": ".", ".": ","})


def localize(fig: go.Figure) -> go.Figure:
    """German number conventions for a finished figure: 1.234,5 and '1.234 €' instead of '€1,234'."""
    if _LANG.get() != "de":
        return fig
    fig.update_layout(separators=",.")
    sym = re.escape(_cur())
    for t in fig.data:
        if isinstance(getattr(t, "hovertemplate", None), str):
            t.hovertemplate = re.sub(rf"([+−-]?){sym}(%\{{[^}}]*\}})", r"\1\2 " + _cur(), t.hovertemplate)
        if isinstance(getattr(t, "texttemplate", None), str):
            t.texttemplate = re.sub(rf"{sym}(%\{{[^}}]*\}})", r"\1 " + _cur(), t.texttemplate)
    for name in ("xaxis", "yaxis", "xaxis2", "yaxis2"):
        ax = getattr(fig.layout, name, None)
        if ax is not None and ax.tickprefix == _cur():
            ax.tickprefix, ax.ticksuffix = None, " " + _cur()
    return fig


def _layout(fig: go.Figure, height: int = 360, hover: str = "x unified", legend: bool = True) -> go.Figure:
    fig.update_layout(
        height=height,
        margin=dict(l=4, r=4, t=8, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, size=12.5, color=TEXT2),
        separators=".,",  # decimal point, thousands comma
        hovermode=hover,
        hoverlabel=dict(bgcolor=SURFACE, bordercolor=GRID, font=dict(family=FONT, size=12.5, color=TEXT)),
        dragmode=False,   # no drag-zoom: charts never capture scroll or drag gestures
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="left", x=0, title_text="",
                    font=dict(color=TEXT2, size=12), bgcolor="rgba(0,0,0,0)", itemwidth=30),
        bargap=0.35,
    )
    fig.update_xaxes(spikecolor=MUTED, spikethickness=1, spikedash="dot", spikemode="across")
    fig.update_xaxes(showgrid=False, showline=True, linecolor=AXIS, linewidth=1, ticks="outside", ticklen=4,
                     tickcolor=AXIS, tickfont=dict(color=MUTED, size=11.5), zeroline=False, automargin=True,
                     title_font=dict(color=MUTED, size=11.5))
    fig.update_yaxes(gridcolor=GRID, gridwidth=1, showline=False, ticks="", tickfont=dict(color=MUTED, size=11.5),
                     zeroline=True, zerolinecolor=AXIS, zerolinewidth=1, automargin=True,
                     title_font=dict(color=MUTED, size=11.5))
    fig.update_traces(marker_cornerradius=3, selector=dict(type="bar"))
    return fig


def titled(fig: go.Figure, title: str, subtitle: str | None = None, source: str | None = None) -> go.Figure:
    """Attach a report-style header (title, subtitle) and source line; rendered by common.plot as page text.

    Kept outside the Plotly canvas: in-figure titles get clipped by the Streamlit container, and page
    typography keeps every chart header identical.
    """
    fig.update_layout(meta={"title": title, "subtitle": subtitle, "source": source})
    return fig


def _month_dates(index) -> list:
    """Monthly periods as mid-month dates: a real time axis with a few readable ticks instead of 36 labels."""
    return [p.to_timestamp() + pd.Timedelta(days=14) if hasattr(p, "to_timestamp") else p for p in index]


def _signed_colors(values) -> list[str]:
    return [POS if v >= 0 else NEG for v in values]


def _spread(values: list[float], min_gap: float) -> list[float]:
    """Nudge label positions apart so no two are closer than ``min_gap`` (keeps their order)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    placed = [0.0] * len(values)
    last = -np.inf
    for i in order:
        placed[i] = max(values[i], last + min_gap)
        last = placed[i]
    shift = (sum(placed) - sum(values)) / len(values)  # re-center the block
    return [v - shift for v in placed]


def _end_labels(fig: go.Figure, x, ys: list[float], texts: list[str], colors: list[str], min_gap: float) -> None:
    for y_label, text, color in zip(_spread(ys, min_gap), texts, colors):
        fig.add_annotation(x=x, y=y_label, text=f"<b>{text}</b>", showarrow=False, xanchor="left", xshift=8,
                           font=dict(color=color, size=12))


# --------------------------------------------------------------- overview
def value_vs_invested(daily: pd.DataFrame, privacy: bool = False) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["net_invested"], name="Net invested",
        line=dict(color=MUTED, width=2, shape="hv"),
        hovertemplate=_cur() + "%{y:,.0f}<extra>Net invested</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["value"], name="Portfolio value", fill="tozeroy",
        line=dict(color=DEPOT, width=2), fillcolor="rgba(42,120,214,0.10)",
        hovertemplate=_cur() + "%{y:,.0f}<extra>Portfolio value</extra>",
    ))
    _layout(fig)
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy)
    if privacy:
        fig.update_traces(hovertemplate="•••<extra>%{fullData.name}</extra>")
    return fig


def performance_lines(series: dict[str, pd.Series], height: int = 360) -> go.Figure:
    """Cumulative return lines (in %, starting at 0), first entry = the portfolio."""
    fig = go.Figure()
    ends = []
    for i, (name, s) in enumerate(series.items()):
        fig.add_trace(go.Scatter(
            x=s.index, y=s * 100, name=name, line=dict(color=SERIES[i], width=2.5 if i == 0 else 2),
            hovertemplate="%{y:+.1f}%<extra>" + name + "</extra>",
        ))
        ends.append(float(s.iloc[-1] * 100))
    span = max(float(max(x.max() for x in series.values()) - min(x.min() for x in series.values())) * 100, 1.0)
    _end_labels(fig, s.index[-1], ends, [f"{fmt.spec(e, '+.1f')}%" for e in ends],
                SERIES[: len(ends)], min_gap=span * 0.075)
    _layout(fig, height)
    fig.update_layout(margin=dict(r=58))  # room for the end labels
    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(range=[s.index[0], s.index[-1] + (s.index[-1] - s.index[0]) * 0.14])
    return fig


def contribution_bars(contrib: pd.Series, privacy: bool = False, height: int | None = None) -> go.Figure:
    """Horizontal bars of P&L contribution per position (EUR), sorted."""
    c = contrib.sort_values()
    fig = go.Figure(go.Bar(
        x=c.values, y=c.index, orientation="h", marker=dict(color=_signed_colors(c.values)),
        text=[("•••" if privacy else _eur(v, sign=True)) for v in c.values],
        textposition="outside", cliponaxis=False, textfont=dict(color=TEXT2),
        hovertemplate=("•••" if privacy else "%{x:+,.2f} " + _cur()) + "<extra>%{y}</extra>",
    ))
    _layout(fig, height or max(240, 26 * len(c) + 40), hover="closest", legend=False)
    lo, hi = min(float(c.min()), 0.0), max(float(c.max()), 0.0)
    pad = (hi - lo) * 0.32  # room for the outside value labels on both sides
    fig.update_xaxes(showticklabels=False, showgrid=False, zeroline=True, zerolinecolor=AXIS,
                     range=[lo - (pad if lo < 0 else 0), hi + pad], showline=False, ticks="")
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2), ticks="")
    fig.update_layout(bargap=0.35)
    return fig


def waterfall(steps: list[tuple[str, float, str]], privacy: bool = False) -> go.Figure:
    """steps = [(label, value, 'relative'|'total'), ...]."""
    labels, values, measure = zip(*steps)
    shown, running = [], 0.0
    for v, kind in zip(values, measure):
        running = running + v if kind == "relative" else running
        shown.append(running if kind == "total" else v)
    text = ["•••" if privacy else _eur(v, sign=k == "relative") for v, k in zip(shown, measure)]
    fig = go.Figure(go.Waterfall(
        x=list(labels), y=list(values), measure=list(measure), text=text, textposition="outside",
        increasing=dict(marker=dict(color=POS)), decreasing=dict(marker=dict(color=NEG)),
        totals=dict(marker=dict(color=MUTED)), connector=dict(line=dict(color=AXIS, width=1)),
        hovertemplate="%{text}<extra>%{x}</extra>", cliponaxis=False,
    ))
    _layout(fig, 340, hover="closest", legend=False)
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy)
    return fig


# ------------------------------------------------------------ performance
def monthly_heatmap(monthly: pd.Series) -> go.Figure:
    """Years x months grid of returns with a yearly total column."""
    df = monthly.to_frame("r")
    df["year"], df["month"] = df.index.year, df.index.month
    grid = df.pivot(index="year", columns="month", values="r").reindex(columns=range(1, 13))
    yearly = (1 + grid.fillna(0)).prod(axis=1) - 1
    z = np.column_stack([grid.to_numpy(), yearly.to_numpy()]) * 100
    x = MONTHS + ["Year"]
    text = [[("" if np.isnan(v) else f"{fmt.spec(v, '+.1f')}") for v in row] for row in z]
    lim = float(np.nanmax(np.abs(z[:, :12]))) if np.isfinite(z[:, :12]).any() else 1.0
    fig = go.Figure(go.Heatmap(
        z=z, x=x, y=[str(y) for y in grid.index], colorscale=DIVERGING, zmid=0, zmin=-lim, zmax=lim,
        text=text, texttemplate="%{text}", textfont=dict(size=12),
        xgap=2, ygap=2, colorbar=dict(ticksuffix="%", thickness=10, outlinewidth=0),
        hovertemplate="%{y} %{x}: %{z:+.2f}%<extra></extra>",
    ))
    _layout(fig, 60 + 46 * len(grid), hover="closest", legend=False)
    fig.update_yaxes(autorange="reversed", showgrid=False, zeroline=False, type="category")
    fig.update_xaxes(side="top", ticks="", linecolor="rgba(0,0,0,0)")
    return fig


def grouped_monthly_bars(depot: pd.Series, bench: pd.Series, bench_name: str) -> go.Figure:
    labels = [f"{MONTHS[d.month - 1]} {str(d.year)[2:]}" for d in depot.index]
    fig = go.Figure([
        go.Bar(x=labels, y=depot * 100, name="Portfolio", marker_color=DEPOT,
               hovertemplate="%{y:+.1f}%<extra>Portfolio</extra>"),
        go.Bar(x=labels, y=bench.reindex(depot.index) * 100, name=bench_name, marker_color=BENCH,
               hovertemplate="%{y:+.1f}%<extra>" + bench_name + "</extra>"),
    ])
    _layout(fig, 320)
    fig.update_layout(bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(ticksuffix="%")
    return fig


def two_lines(a: pd.Series, b: pd.Series, name_a: str, name_b: str, suffix: str = "%",
              scale: float = 100, privacy: bool = False, height: int = 320) -> go.Figure:
    fig = go.Figure()
    fmt = _cur() + "%{y:,.0f}" if suffix.strip() == "€" else "%{y:+.1f}" + suffix
    for s, name, color in [(a, name_a, DEPOT), (b, name_b, BENCH)]:
        fig.add_trace(go.Scatter(x=s.index, y=s * scale, name=name, line=dict(color=color, width=2),
                                 hovertemplate=("•••" if privacy else fmt) + "<extra>" + name + "</extra>"))
    _layout(fig, height)
    fig.update_yaxes(**({"tickprefix": _cur()} if suffix.strip() == "€" else {"ticksuffix": suffix}),
                     showticklabels=not privacy)
    return fig


# ------------------------------------------------------------------- risk
def underwater(dd_depot: pd.Series, dd_bench: pd.Series, bench_name: str) -> go.Figure:
    fig = go.Figure([
        go.Scatter(x=dd_depot.index, y=dd_depot * 100, name="Portfolio", fill="tozeroy",
                   line=dict(color=NEG, width=2), fillcolor="rgba(227,73,72,0.12)",
                   hovertemplate="%{y:.1f}%<extra>Portfolio</extra>"),
        go.Scatter(x=dd_bench.index, y=dd_bench * 100, name=bench_name,
                   line=dict(color=MUTED, width=2), hovertemplate="%{y:.1f}%<extra>" + bench_name + "</extra>"),
    ])
    _layout(fig, 300)
    fig.update_yaxes(ticksuffix="%")
    return fig


def _short(name: str, n: int = 20) -> str:
    return name if len(name) <= n else name[: n - 1].rstrip() + "…"


def weight_vs_risk(contrib: pd.DataFrame, names: pd.Series) -> go.Figure:
    c = contrib[contrib["weight"] > 0.001].sort_values("risk_contribution")
    y = [_short(names.get(i, i), 24) for i in c.index]
    fig = go.Figure([
        go.Bar(y=y, x=c["weight"] * 100, name="Share of value", orientation="h", marker_color=DEPOT,
               hovertemplate="%{x:.1f}%<extra>Weight</extra>"),
        go.Bar(y=y, x=c["risk_contribution"] * 100, name="Share of risk", orientation="h",
               marker_color=BENCH, hovertemplate="%{x:.1f}%<extra>Risk contribution</extra>"),
    ])
    _layout(fig, max(260, 44 * len(c) + 60), hover="y unified")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_xaxes(ticksuffix="%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2))
    return fig


def correlation_heatmap(corr: pd.DataFrame, names: pd.Series) -> go.Figure:
    labels = [_short(names.get(i, i), 16) for i in corr.index]
    z = corr.to_numpy()
    fig = go.Figure(go.Heatmap(
        z=z, x=labels, y=labels, colorscale=DIVERGING, zmin=-1, zmax=1, zmid=0,
        text=[[f"{fmt.spec(v, '.2f')}" for v in row] for row in z], texttemplate="%{text}",
        xgap=2, ygap=2, colorbar=dict(thickness=10, outlinewidth=0),
        hovertemplate="%{y} × %{x}: %{z:.2f}<extra></extra>",
    ))
    _layout(fig, 70 + 44 * len(labels), hover="closest", legend=False)
    fig.update_yaxes(autorange="reversed", showgrid=False, zeroline=False)
    fig.update_xaxes(tickangle=-30)
    return fig


def return_histogram(returns: pd.Series, var95: float) -> go.Figure:
    r = returns[returns != 0] * 100
    fig = go.Figure(go.Histogram(x=r, nbinsx=50, marker=dict(color=DEPOT, line=dict(color=SURFACE, width=1)),
                                 hovertemplate="%{x}%: %{y} days<extra></extra>", name="Days"))
    fig.add_vline(x=-var95 * 100, line=dict(color=NEG, width=2),
                  annotation=dict(text=f"VaR 95%: −{fmt.spec(var95 * 100, '.1f')}%",
                                  font=dict(color=TEXT), xanchor="right", yanchor="top"))
    _layout(fig, 300, hover="closest", legend=False)
    fig.update_xaxes(ticksuffix="%")
    fig.update_yaxes(title=dict(text="Number of days", font=dict(color=MUTED)))
    return fig


def stress_bars(stress: pd.DataFrame, privacy: bool = False) -> go.Figure:
    s = stress.sort_values("impact_eur", ascending=False)
    text = [("" if privacy else _eur(e) + " · ") + f"{p * 100:+.1f}%".replace("-", "−")
            for e, p in zip(s["impact_eur"], s["impact_pct"])]
    fig = go.Figure(go.Bar(x=s["impact_pct"] * 100, y=s.index, orientation="h", marker_color=NEG,
                           text=text, textposition="outside", cliponaxis=False,
                           hovertemplate="%{x:.1f}%<extra>%{y}</extra>"))
    _layout(fig, 40 * len(s) + 40, hover="closest", legend=False)
    fig.update_layout(bargap=0.4, margin=dict(l=8, r=8, t=8, b=8))
    fig.update_xaxes(ticksuffix="%", range=[s["impact_pct"].min() * 100 * 2.1, 0])  # room for the value labels
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2))
    return fig


# -------------------------------------------------------------- structure
def share_bars(shares: pd.Series, height: int | None = None) -> go.Figure:
    """Single-series horizontal bars of portfolio shares (fractions)."""
    s = shares.sort_values()
    fig = go.Figure(go.Bar(
        x=s.values * 100, y=s.index, orientation="h", marker_color=DEPOT,
        text=[f"{fmt.spec(v * 100, '.1f')}%" for v in s.values], textposition="outside",
        cliponaxis=False, textfont=dict(color=TEXT2), hovertemplate="%{x:.1f}%<extra>%{y}</extra>",
    ))
    _layout(fig, height or max(180, 34 * len(s) + 30), hover="closest", legend=False)
    fig.update_layout(bargap=0.35, margin=dict(l=8, r=48, t=8, b=8))
    fig.update_xaxes(showticklabels=False, showgrid=False, range=[0, s.max() * 100 * 1.18])
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2))
    return fig


def allocation_area(values: pd.DataFrame, names: pd.Series, keep: list[str]) -> go.Figure:
    """Stacked area of position weights over time; positions outside ``keep`` fold into 'Other'."""
    total = values.sum(axis=1).replace(0, np.nan)
    shares = values.div(total, axis=0)
    cols = [c for c in keep if c in shares.columns][: len(SERIES) - 1]
    other = shares.drop(columns=cols).sum(axis=1)
    fig = go.Figure()
    for i, c in enumerate(cols):
        fig.add_trace(go.Scatter(x=shares.index, y=shares[c] * 100, name=names.get(c, c), stackgroup="a",
                                 line=dict(width=0.5, color=SURFACE), fillcolor=SERIES[i],
                                 hovertemplate="%{y:.1f}%<extra>" + names.get(c, c) + "</extra>"))
    fig.add_trace(go.Scatter(x=shares.index, y=other * 100, name="Other / sold", stackgroup="a",
                             line=dict(width=0.5, color=SURFACE), fillcolor=OTHER,
                             hovertemplate="%{y:.1f}%<extra>Other</extra>"))
    _layout(fig, 380)
    fig.update_layout(legend=dict(traceorder="normal"))
    fig.update_yaxes(ticksuffix="%", range=[0, 100])
    return fig


def treemap(pos: pd.DataFrame, privacy: bool = False) -> go.Figure:
    """Positions sized by value, colored by unrealized return; explicit neutral root node."""
    lim = max(float(pos["unrealized_pct"].abs().max()), 0.05)
    custom = np.column_stack([pos["weight"] * 100, pos["unrealized_pct"] * 100, pos["value"], pos["unrealized"]])
    custom = np.vstack([[100.0, 0.0, pos["value"].sum(), pos["unrealized"].sum()], custom])
    value_part = "" if privacy else "<br>Value: " + _cur() + "%{customdata[2]:,.0f}<br>P&L: %{customdata[3]:+,.0f} " + _cur()
    leaf_text = "<b>%{label}</b><br>%{customdata[0]:.1f}% · %{customdata[1]:+.1f}%"
    fig = go.Figure(go.Treemap(
        labels=["Portfolio"] + list(pos["name"]), parents=[""] + ["Portfolio"] * len(pos),
        values=[pos["value"].sum()] + list(pos["value"]), branchvalues="total",
        marker=dict(colors=[0.0] + list(pos["unrealized_pct"]), colorscale=DIVERGING, cmid=0, cmin=-lim, cmax=lim,
                    line=dict(color=SURFACE, width=2), pad=dict(t=0, l=0, r=0, b=0),
                    colorbar=dict(thickness=10, outlinewidth=0, tickformat="+.0%")),
        customdata=custom, texttemplate=[""] + [leaf_text] * len(pos),
        hovertemplate="<b>%{label}</b><br>Weight: %{customdata[0]:.1f}%<br>Unrealized: %{customdata[1]:+.1f}%"
                      + value_part + "<extra></extra>",
        textfont=dict(family=FONT, size=13), tiling=dict(pad=2), pathbar=dict(visible=False),   # auto contrast
    ))
    _layout(fig, 380, hover="closest", legend=False)
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return fig


# --------------------------------------------------------------- position
def price_with_trades(price: pd.Series, trades: pd.DataFrame, avg_cost: float | None, name: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=price.index, y=price, name="Price", line=dict(color=DEPOT, width=2),
                             hovertemplate=_cur() + "%{y:,.2f}<extra>Price</extra>"))
    if avg_cost:
        fig.add_hline(y=avg_cost, line=dict(color=MUTED, width=1.5),
                      annotation=dict(text=f"Avg. cost {_eur(avg_cost, 2)}",
                                      font=dict(color=TEXT2), xanchor="left", x=0))
    for event, symbol, color, label in [("buy", "triangle-up", POS, "Buy"), ("sell", "triangle-down", NEG, "Sell")]:
        t = trades[trades["event"] == event]
        if t.empty:
            continue
        size = 9 + 9 * np.sqrt(t["amount"].abs() / trades["amount"].abs().max())
        fig.add_trace(go.Scatter(
            x=t["date"], y=t["price"], mode="markers", name=label,
            marker=dict(symbol=symbol, size=size, color=color, line=dict(color=SURFACE, width=2)),
            customdata=np.column_stack([t["shares"].abs(), t["amount"].abs()]),
            hovertemplate=(label + ": %{customdata[0]:.4f} sh. at " + _cur() + "%{y:,.2f} ("
                           + _cur() + "%{customdata[1]:,.0f})<extra></extra>"),
        ))
    _layout(fig, 360, hover="closest")
    fig.update_yaxes(tickprefix=_cur(), zeroline=False)
    return fig


def return_decomposition(df: pd.DataFrame) -> go.Figure:
    """Grouped bars per position: local price return vs. currency return."""
    fig = go.Figure([
        go.Bar(x=df["name"], y=df["local_return"] * 100, name="Price return (local currency)",
               marker_color=DEPOT, hovertemplate="%{y:+.1f}%<extra>Price</extra>"),
        go.Bar(x=df["name"], y=df["fx_return"] * 100, name="Currency effect",
               marker_color=BENCH, hovertemplate="%{y:+.1f}%<extra>Currency</extra>"),
    ])
    _layout(fig, 320, hover="x unified")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(ticksuffix="%")
    return fig


# ----------------------------------------------------------------- trades
def holding_vs_return(sells: pd.DataFrame, privacy: bool = False) -> go.Figure:
    s = sells.dropna(subset=["return_pct"])
    size = 8 + 18 * np.sqrt(s["proceeds"] / s["proceeds"].max())
    gain_part = "" if privacy else "<br>%{customdata[1]:+,.2f} " + _cur()
    fig = go.Figure(go.Scatter(
        x=s["holding_days"], y=s["return_pct"] * 100, mode="markers",
        marker=dict(size=size, color=_signed_colors(s["return_pct"]), opacity=0.85,
                    line=dict(color=SURFACE, width=2)),
        customdata=np.column_stack([s["name"], s["gain"], s["date"].dt.strftime("%d %b %Y")]),
        hovertemplate="<b>%{customdata[0]}</b> (%{customdata[2]})<br>held %{x:.0f} days<br>%{y:+.1f}%"
                      + gain_part + "<extra></extra>",
    ))
    _layout(fig, 340, hover="closest", legend=False)
    fig.update_xaxes(title=dict(text="Avg. holding period (days)", font=dict(color=MUTED)), showgrid=True, gridcolor=GRID)
    fig.update_yaxes(ticksuffix="%", title=dict(text="Return of the sale", font=dict(color=MUTED)))
    return fig


# ----------------------------------------------------------------- cashflows
def signed_monthly_bars(series: dict[str, pd.Series], privacy: bool = False, height: int = 320) -> go.Figure:
    """Monthly bars; up to two series, positive and negative stacked around zero."""
    fig = go.Figure()
    for i, (name, s) in enumerate(series.items()):
        x = _month_dates(s.index)
        fig.add_trace(go.Bar(x=x, y=s.values, name=name, marker_color=SERIES[i],
                             hovertemplate=("•••" if privacy else "%{y:+,.0f} " + _cur()) + "<extra>" + name + "</extra>"))
    _layout(fig, height)
    fig.update_layout(barmode="relative", bargap=0.3)
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy)
    return fig


def single_bars(s: pd.Series, name: str, color: str = DEPOT, privacy: bool = False, suffix: str = " €",
                height: int = 300) -> go.Figure:
    x = _month_dates(s.index)
    value = _cur() + "%{y:,.0f}" if suffix.strip() == "€" else "%{y:,.0f}" + suffix
    fig = go.Figure(go.Bar(x=x, y=s.values, name=name, marker_color=color,
                           hovertemplate=("•••" if privacy else value) + "<extra>" + name + "</extra>"))
    _layout(fig, height, legend=False)
    fig.update_layout(bargap=0.3)
    fig.update_yaxes(**({"tickprefix": _cur()} if suffix.strip() == "€" else {"ticksuffix": suffix}),
                     showticklabels=not privacy)
    return fig


# --------------------------------------------------------------- research
def football_field(ranges: list[tuple[str, float, float]], price: float, fair: float | None, currency: str) -> go.Figure:
    """Valuation ranges as horizontal bars (low-high) with the current price and fair value as lines."""
    labels = [r[0] for r in ranges][::-1]
    lows = [r[1] for r in ranges][::-1]
    highs = [r[2] for r in ranges][::-1]
    fig = go.Figure(go.Bar(
        y=labels, x=[h - lo for lo, h in zip(lows, highs)], base=lows, orientation="h",
        marker=dict(color="rgba(42,120,214,0.55)", line=dict(color=DEPOT, width=1)),
        customdata=np.column_stack([lows, highs]),
        hovertemplate="%{y}: %{customdata[0]:,.2f} – %{customdata[1]:,.2f} " + currency + "<extra></extra>",
    ))
    left_first = fair is not None and fair < price  # put the lower value's label on the left
    fig.add_vline(x=price, line=dict(color=TEXT, width=2),
                  annotation=dict(text=f"Price {fmt.spec(price, ',.2f')}",
                                  font=dict(color=TEXT), yanchor="bottom", y=1.0,
                                  xanchor="left" if left_first else "right"))
    if fair:
        fig.add_vline(x=fair, line=dict(color=BENCH, width=2),
                      annotation=dict(text=f"Fair value {fmt.spec(fair, ',.2f')}",
                                      font=dict(color=BENCH), yanchor="bottom", y=1.0,
                                      xanchor="right" if left_first else "left"))
    _layout(fig, 70 + 46 * len(ranges), hover="closest", legend=False)
    fig.update_layout(bargap=0.45, margin=dict(l=8, r=8, t=28, b=28))
    fig.update_xaxes(ticksuffix=f" {currency}", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2))
    return fig


def sensitivity_heatmap(grid: pd.DataFrame, price: float, currency: str) -> go.Figure:
    """Fair values for EPS growth (rows) x exit P/E (columns); color = up/downside vs. current price."""
    upside = grid.to_numpy() / price - 1
    lim = max(float(np.nanmax(np.abs(upside))), 0.1)
    text = [[f"{fmt.spec(v, ',.0f')}" for v in row] for row in grid.to_numpy()]
    fig = go.Figure(go.Heatmap(
        z=upside * 100, x=[f"P/E {fmt.spec(pe, '.0f')}" for pe in grid.columns],
        y=[f"{fmt.spec(g * 100, '+.0f')}% p.a." for g in grid.index],
        colorscale=DIVERGING, zmid=0, zmin=-lim * 100, zmax=lim * 100, text=text, texttemplate="%{text}",
        xgap=2, ygap=2, colorbar=dict(ticksuffix="%", thickness=10, outlinewidth=0, title=dict(text="vs. price")),
        customdata=grid.to_numpy(),
        hovertemplate="EPS growth %{y}, %{x}<br>Fair value %{customdata:,.2f} " + currency
                      + " (%{z:+.0f}% vs. price)<extra></extra>",
    ))
    _layout(fig, 60 + 40 * len(grid), hover="closest", legend=False)
    fig.update_yaxes(showgrid=False, zeroline=False, type="category")
    fig.update_xaxes(side="top", ticks="", linecolor="rgba(0,0,0,0)")
    return fig


def annual_bars(annual: pd.DataFrame, columns: dict[str, str], currency: str, scale: float = 1e9,
                unit: str = "bn") -> go.Figure:
    """Grouped bars per fiscal year; ``columns`` maps column -> label (max. 3 series)."""
    years = [str(d.year) for d in annual.index]
    fig = go.Figure()
    for i, (col, label) in enumerate(columns.items()):
        if col not in annual:
            continue
        fig.add_trace(go.Bar(x=years, y=annual[col] / scale, name=label, marker_color=SERIES[i],
                             hovertemplate="%{y:,.2f} " + f"{unit} {currency}<extra>{label}</extra>"))
    _layout(fig, 280, hover="x unified")
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(ticksuffix=f" {unit}")
    return fig


def reference_line(fig: go.Figure, y: float, label: str, color: str = MUTED, dash: str = "dash",
                   anchor: str = "left", row_shift: int = 0) -> None:
    """Dashed horizontal reference with a small boxed label – e.g. "Median 15.1" or "Your exit P/E 15.0"."""
    fig.add_hline(y=y, line=dict(color=color, width=1.2, dash=dash), layer="below")
    fig.add_annotation(x=0 if anchor == "left" else 1, xref="paper", y=y, yref="y", text=label, showarrow=False,
                       xanchor=anchor, yanchor="middle", xshift=6 if anchor == "left" else -6, yshift=row_shift,
                       font=dict(size=11, color=color), bgcolor=SURFACE, bordercolor=color, borderwidth=1,
                       borderpad=3, opacity=1)


def multiple_history(s: pd.Series, name: str = "P/E", yours: float | None = None, height: int = 330,
                     color: str = BENCH2) -> go.Figure:
    """A valuation multiple over its own history with the median and your assumption as labelled reference lines."""
    s = s[s < s.quantile(0.99)]
    med = float(s.median())
    fig = go.Figure(go.Scatter(x=s.index, y=s, name=name, line=dict(color=color, width=1.6),
                               hovertemplate="%{x|%b %Y}: %{y:.1f}×<extra></extra>"))
    close = yours is not None and abs(yours - med) < (s.max() - s.min()) * 0.06   # keep the two labels apart
    reference_line(fig, med, f"Median {fmt.spec(med, '.1f')}", MUTED)
    if yours is not None:
        reference_line(fig, yours, f"Your {name} {fmt.spec(yours, '.1f')}", DEPOT, dash="dot",
                       row_shift=-18 if close and yours <= med else
                       (18 if close else 0))
    _layout(fig, height, legend=False)
    lo, hi = min(float(s.min()), yours or med), max(float(s.max()), yours or med)
    fig.update_yaxes(zeroline=False, ticksuffix="×", range=[lo * 0.92, hi * 1.06], showgrid=True)
    fig.update_xaxes(showgrid=True, gridcolor=GRID)
    return fig


def pe_history(pe: pd.Series, current: float | None = None, yours: float | None = None) -> go.Figure:
    """Trailing P/E over its own history with median and your exit P/E (Qualtrim-style)."""
    return multiple_history(pe, "P/E", yours, height=300)


def price_projection(prices: pd.Series, horizon: int, scenarios: dict[str, float], fair: float, max_price: float,
                     currency: str, height: int = 330) -> go.Figure:
    """Price history and, from today, the path to the expected price in ``horizon`` years per scenario.

    The paths are straight compounding lines – an illustration of what the assumptions imply, not a forecast.
    """
    p = prices.dropna()
    p = p[p.index >= p.index.max() - pd.DateOffset(years=5)]
    today, last = p.index.max(), float(p.iloc[-1])
    end = today + pd.DateOffset(years=horizon)
    fig = go.Figure(go.Scatter(x=p.index, y=p, name="Price", line=dict(color=TEXT2, width=1.4),
                               hovertemplate="%{x|%b %Y}: %{y:,.2f} " + currency + "<extra></extra>"))
    styles = {"Bear": (NEG, "dot"), "Base": (MUTED, "dot"), "Bull": (BENCH2, "dot"), "Expected": (DEPOT, "solid")}
    span = max(max(scenarios.values()), float(p.max())) - min(min(scenarios.values()), float(p.min()))
    label_y = dict(zip(scenarios, _spread(list(scenarios.values()), span * 0.07)))
    for name, target in scenarios.items():
        color, dash = styles.get(name, (MUTED, "dot"))
        dates = pd.date_range(today, end, periods=24)
        path = last * (target / last) ** (np.linspace(0, 1, len(dates)))
        fig.add_trace(go.Scatter(x=dates, y=path, name=name, mode="lines",
                                 line=dict(color=color, width=2 if name == "Expected" else 1.3, dash=dash),
                                 hovertemplate=tr(name) + ": %{y:,.0f} " + currency + "<extra></extra>"))
        fig.add_annotation(x=end, y=label_y[name], text=f"{tr(name)} {fmt.spec(target, ',.0f')}", showarrow=False, xanchor="left",
                           xshift=6, font=dict(size=11, color=color))
    close = abs(fair - max_price) < span * 0.07
    reference_line(fig, fair, f"Fair value {fmt.spec(fair, ',.0f')}", BENCH, row_shift=9 if close else 0)
    reference_line(fig, max_price, f"Max. price {fmt.spec(max_price, ',.0f')}", DEPOT, dash="dot", row_shift=-9 if close else 0)
    _layout(fig, height, hover="x unified")
    fig.update_layout(margin=dict(r=90), showlegend=False)
    fig.update_yaxes(zeroline=False, ticksuffix=f" {currency}", showgrid=True)
    fig.update_xaxes(showgrid=True, gridcolor=GRID, range=[p.index.min(), end + pd.DateOffset(months=3)])
    fig.add_vline(x=today, line=dict(color=AXIS, width=1))
    return fig


def eps_projection(history: pd.Series, paths: dict[str, list[float]], currency: str, height: int = 330) -> go.Figure:
    """Reported earnings per share (bars) and the scenario paths you assume (lines)."""
    h = history.dropna()
    years = [d.year for d in h.index]
    fig = go.Figure(go.Bar(x=years, y=h.values, name="Reported", marker_color=DEPOT,
                           hovertemplate="%{x}: %{y:.2f} " + currency + "<extra>Reported</extra>"))
    styles = {"Bear": NEG, "Base": MUTED, "Bull": BENCH2, "Expected": BENCH}
    start = years[-1] if years else 0
    for name, path in paths.items():
        xs = [start + i for i in range(len(path) + 1)]
        ys = [float(h.iloc[-1]) if len(h) else path[0]] + list(path)
        fig.add_trace(go.Scatter(x=xs, y=ys, name=name, mode="lines+markers",
                                 line=dict(color=styles.get(name, MUTED), width=2 if name == "Expected" else 1.3,
                                           dash="solid" if name == "Expected" else "dot"),
                                 marker=dict(size=5), hovertemplate=name + " %{x}: %{y:.2f}<extra></extra>"))
    _layout(fig, height)
    fig.update_xaxes(dtick=1)
    fig.update_yaxes(zeroline=False, showgrid=True)
    return fig


def watch_chart(prices: pd.Series, currency: str, fair: float | None,
                alerts: list[tuple[str, float, bool]]) -> go.Figure:
    """Price history with fair value and alert levels; alerts = [(label, price, hit)]."""
    fig = go.Figure(go.Scatter(x=prices.index, y=prices, name="Price", line=dict(color=DEPOT, width=2),
                               hovertemplate="%{y:,.2f} " + currency + "<extra>Price</extra>"))
    if fair:
        fig.add_hline(y=fair, line=dict(color=BENCH, width=2),
                      annotation=dict(text=f"Fair value {fmt.spec(fair, ',.2f')}",
                                      font=dict(color=BENCH), xanchor="left", x=0, yanchor="bottom"))
    for label, level, hit in alerts:
        level_txt = f"{fmt.spec(level, ',.2f')}"
        fig.add_hline(y=level, line=dict(color=BENCH2 if hit else MUTED, width=1.5),
                      annotation=dict(text=f"{label}: {level_txt}" + (" ✓" if hit else ""),
                                      font=dict(color=TEXT2), xanchor="right", x=1, yanchor="bottom"))
    lo = min([prices.min()] + [a[1] for a in alerts] + ([fair] if fair else []))
    hi = max([prices.max()] + [a[1] for a in alerts] + ([fair] if fair else []))
    _layout(fig, 360, legend=False)
    fig.update_yaxes(range=[lo * 0.95, hi * 1.05], zeroline=False, ticksuffix=f" {currency}")
    return fig


def scenario_bars(df: pd.DataFrame, price: float, currency: str) -> go.Figure:
    """Fair value per scenario vs. current price."""
    names = list(df.index)
    colors = [NEG if n.lower().startswith("bear") else (POS if n.lower().startswith("bull") else MUTED) for n in names]
    colors[-1] = BENCH  # expected value
    fig = go.Figure(go.Bar(
        x=names, y=df["fair_value"], marker_color=colors,
        text=[f"{fmt.spec(v, ',.0f')}" for v in df["fair_value"]], textposition="outside", cliponaxis=False,
        hovertemplate="%{x}: %{y:,.2f} " + currency + "<extra></extra>",
    ))
    fig.add_hline(y=price, line=dict(color=TEXT, width=2),
                  annotation=dict(text="current price", font=dict(color=TEXT), xanchor="left", x=0))
    _layout(fig, 280, hover="closest", legend=False)
    fig.update_layout(bargap=0.45)
    fig.update_yaxes(ticksuffix=f" {currency}")
    return fig


# -------------------------------------------------------------- decisions
GROUP_COLORS = {"Buy": SERIES[0], "Sell": SERIES[1], "Savings plan": SERIES[2]}


def decision_dots(sc: pd.DataFrame, col: str, privacy: bool = False) -> go.Figure:
    """Every decision's edge vs. the market over time; one color per decision type."""
    fig = go.Figure()
    for group, color in GROUP_COLORS.items():
        g = sc[(sc["group"] == group) & sc[col].notna()]
        if g.empty:
            continue
        size = 7 + 12 * np.sqrt(g["amount"] / sc["amount"].max())
        amount = "" if privacy else "<br>" + _cur() + "%{customdata[1]:,.0f}"
        fig.add_trace(go.Scatter(
            x=g["date"], y=g[col] * 100, mode="markers", name=group,
            marker=dict(color=color, size=size, opacity=0.8, line=dict(color=SURFACE, width=1.5)),
            customdata=np.column_stack([g["name"], g["amount"]]),
            hovertemplate="<b>%{customdata[0]}</b> · " + group + "<br>%{x|%d %b %Y}<br>%{y:+.1f} pp vs. market"
                          + amount + "<extra></extra>",
        ))
    _layout(fig, 340, hover="closest")
    fig.update_yaxes(ticksuffix=" pp", title=dict(text="better than the market ↑", font=dict(color=MUTED)))
    return fig


def quarter_bars(q: pd.DataFrame) -> go.Figure:
    labels = [f"Q{p.quarter} {str(p.year)[2:]}" for p in q.index]
    fig = go.Figure([
        go.Bar(x=labels, y=q[g] * 100, name=g, marker_color=GROUP_COLORS[g],
               hovertemplate="%{y:+.1f} pp<extra>" + g + "</extra>")
        for g in GROUP_COLORS if g in q
    ])
    _layout(fig, 300)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_yaxes(ticksuffix=" pp")
    return fig


def valuation_history(prices: pd.Series, history: list[dict], currency: str) -> go.Figure:
    """Share price vs. your fair value estimates over time."""
    h = pd.DataFrame(history)
    h["date"] = pd.to_datetime(h["date"])
    h = h.dropna(subset=["fair_value"]).sort_values("date")
    fig = go.Figure(go.Scatter(x=prices.index, y=prices, name="Price", line=dict(color=DEPOT, width=2),
                               hovertemplate="%{y:,.2f} " + currency + "<extra>Price</extra>"))
    if not h.empty:
        x = list(h["date"]) + [prices.index.max()]
        y = list(h["fair_value"]) + [h["fair_value"].iloc[-1]]
        fig.add_trace(go.Scatter(x=x, y=y, name="Your fair value", mode="lines", line=dict(color=BENCH, width=2, shape="hv"),
                                 hovertemplate="%{y:,.2f} " + currency + "<extra>Fair value</extra>"))
        fig.add_trace(go.Scatter(x=h["date"], y=h["fair_value"], mode="markers", showlegend=False,
                                 marker=dict(color=BENCH, size=9, line=dict(color=SURFACE, width=2)),
                                 hovertemplate="Valuation %{x|%d %b %Y}: %{y:,.2f} " + currency + "<extra></extra>"))
    _layout(fig, 300)
    fig.update_yaxes(zeroline=False, ticksuffix=f" {currency}")
    return fig


def entry_scatter(eq: pd.DataFrame, privacy: bool = False) -> go.Figure:
    """Distance to the 52-week high at purchase vs. 12-month return relative to the market."""
    d = eq.dropna(subset=["off_high", "edge_12M"])
    size = 7 + 14 * np.sqrt(d["amount"] / d["amount"].max()) if len(d) else 8
    amount = "" if privacy else "<br>" + _cur() + "%{customdata[1]:,.0f}"
    fig = go.Figure(go.Scatter(
        x=d["off_high"] * 100, y=d["edge_12M"] * 100, mode="markers",
        marker=dict(size=size, color=_signed_colors(d["edge_12M"]), opacity=0.8, line=dict(color=SURFACE, width=1.5)),
        customdata=np.column_stack([d["name"], d["amount"], d["date"].dt.strftime("%d %b %Y")]) if len(d) else None,
        hovertemplate="<b>%{customdata[0]}</b> (%{customdata[2]})<br>bought %{x:.0f}% vs. the 52-week high"
                      "<br>%{y:+.1f} pp vs. market 12 months later" + amount + "<extra></extra>",
    ))
    fig.add_vline(x=-15, line=dict(color=MUTED, width=1),
                  annotation=dict(text="← bought after a pullback", font=dict(color=TEXT2), xanchor="right", yanchor="top", y=1))
    _layout(fig, 320, hover="closest", legend=False)
    fig.update_xaxes(ticksuffix="%", title=dict(text="Distance to 52-week high at purchase", font=dict(color=MUTED)),
                     showgrid=True, gridcolor=GRID)
    fig.update_yaxes(ticksuffix=" pp", title=dict(text="12 months later vs. market", font=dict(color=MUTED)))
    return fig


# ------------------------------------------------------------- research v2
ESTIMATE = "#86b6ef"   # lighter step of the portfolio blue: same series, but a forecast


def history_and_estimates(history: pd.Series, estimates: dict[str, dict], scale: float, unit: str,
                          currency: str) -> go.Figure:
    """Reported annual values (solid) followed by analyst consensus with low–high range (light, with whiskers)."""
    hx = [str(d.year) for d in history.index]
    fig = go.Figure(go.Bar(x=hx, y=history / scale, name="Reported", marker_color=DEPOT,
                           hovertemplate="%{x}: %{y:,.2f} " + f"{unit} {currency}".strip() + "<extra>Reported</extra>"))
    last_year = history.index[-1].year if len(history) else 0
    ex, ey, lo, hi = [], [], [], []
    for i, key in enumerate(["0y", "+1y"]):
        e = estimates.get(key) or {}
        if e.get("avg") is None:
            continue
        ex.append(f"{last_year + i + 1}e")
        ey.append(e["avg"] / scale)
        lo.append((e["avg"] - (e.get("low") or e["avg"])) / scale)
        hi.append(((e.get("high") or e["avg"]) - e["avg"]) / scale)
    if ex:
        fig.add_trace(go.Bar(
            x=ex, y=ey, name="Analyst consensus", marker_color=ESTIMATE,
            error_y=dict(type="data", symmetric=False, array=hi, arrayminus=lo, color=TEXT2, thickness=1.2, width=6),
            hovertemplate="%{x}: %{y:,.2f} " + f"{unit} {currency}".strip() + "<extra>Consensus (range: error bars)</extra>",
        ))
    _layout(fig, 270, hover="closest")
    fig.update_yaxes(ticksuffix=f" {unit}" if unit else "")
    fig.update_xaxes(type="category")  # "2026e" must not be parsed away as a number
    return fig


def margin_lines(annual: pd.DataFrame) -> go.Figure:
    """Operating, net and free-cash-flow margin per fiscal year."""
    a = annual[annual["revenue"] > 0] if "revenue" in annual else annual.iloc[0:0]
    years = [str(d.year) for d in a.index]
    fig = go.Figure()
    for i, (col, label) in enumerate([("operating_income", "Operating margin"), ("net_income", "Net margin"),
                                      ("fcf", "FCF margin")]):
        if col in a and a[col].notna().any():
            y = a[col] / a["revenue"] * 100
            fig.add_trace(go.Scatter(x=years, y=y, name=label, mode="lines+markers",
                                     line=dict(color=SERIES[i], width=2), marker=dict(size=7, line=dict(color=SURFACE, width=1.5)),
                                     hovertemplate="%{y:.1f}%<extra>" + label + "</extra>"))
    _layout(fig, 270)
    fig.update_yaxes(ticksuffix="%")
    fig.update_xaxes(type="category")
    return fig


def recommendation_bar(recs: dict) -> go.Figure:
    """Analyst recommendations as one stacked bar: buy (blue shades), hold (gray), sell (red shades)."""
    parts = [("Strong buy", recs.get("strongBuy", 0), "#1c5cab"), ("Buy", recs.get("buy", 0), "#86b6ef"),
             ("Hold", recs.get("hold", 0), "#d6d4cc"), ("Sell", recs.get("sell", 0), "#efa3a2"),
             ("Strong sell", recs.get("strongSell", 0), "#d65554")]
    total = sum(n for _, n, _ in parts) or 1
    fig = go.Figure()
    for label, n, color in parts:
        if not n:
            continue
        fig.add_trace(go.Bar(y=[""], x=[n / total * 100], orientation="h", name=f"{label} ({n})", marker_color=color,
                             text=[str(n)], textposition="inside", insidetextanchor="middle",
                             textfont=dict(color=ON_FILL if color in ("#86b6ef", "#d6d4cc", "#efa3a2") else "white"),
                             hovertemplate=f"{label}: {n} analysts<extra></extra>"))
    _layout(fig, 70, hover="closest")
    fig.update_layout(barmode="stack", bargap=0.2, margin=dict(l=0, r=0, t=0, b=0),
                      legend=dict(y=-0.25, yanchor="top", font=dict(size=11)))
    fig.update_traces(marker_cornerradius=0)
    fig.update_xaxes(visible=False, range=[0, 100])
    fig.update_yaxes(visible=False)
    fig.update_layout(height=110)
    return fig


# ------------------------------------------------------------- research v3
def _period_labels(index, quarterly: bool) -> list[str]:
    return [f"Q{(d.month - 1) // 3 + 1} {str(d.year)[2:]}" if quarterly else str(d.year) for d in index]


def small_bars(s: pd.Series, quarterly: bool = False, scale: float = 1.0, unit: str = "", pct: bool = False,
               color: str = DEPOT, height: int = 200) -> go.Figure:
    """Compact bar chart for one metric over periods (Qualtrim-style tile). Negative values in red."""
    s = s.dropna()
    y = s * (100 if pct else 1) / scale
    colors = [color if v >= 0 else NEG for v in y]
    fmt = "%{y:.1f}%" if pct else "%{y:,.2f}" + (f" {unit}" if unit else "")
    fig = go.Figure(go.Bar(x=_period_labels(s.index, quarterly), y=y, marker_color=colors,
                           hovertemplate=fmt + "<extra></extra>"))
    _layout(fig, height, hover="closest", legend=False)
    fig.update_xaxes(type="category", tickfont=dict(size=10.5))
    fig.update_yaxes(ticksuffix="%" if pct else (f" {unit}" if unit else ""), tickfont=dict(size=10.5), nticks=5)
    fig.update_layout(bargap=0.3)
    return fig


def margin_tile(df: pd.DataFrame, quarterly: bool = False, height: int = 200) -> go.Figure:
    a = df[df["revenue"] > 0] if "revenue" in df else df.iloc[0:0]
    x = _period_labels(a.index, quarterly)
    fig = go.Figure()
    for i, (col, label) in enumerate([("operating_income", "Operating"), ("net_income", "Net"), ("fcf", "FCF")]):
        if col in a and a[col].notna().any():
            fig.add_trace(go.Scatter(x=x, y=a[col] / a["revenue"] * 100, name=label, mode="lines+markers",
                                     line=dict(color=SERIES[i], width=2), marker=dict(size=6),
                                     hovertemplate="%{y:.1f}%<extra>" + label + "</extra>"))
    _layout(fig, height)
    fig.update_xaxes(type="category", tickfont=dict(size=10.5))
    fig.update_yaxes(ticksuffix="%", tickfont=dict(size=10.5), nticks=5)
    fig.update_layout(legend=dict(font=dict(size=10.5)))
    return fig


def surprise_bars(df: pd.DataFrame) -> go.Figure:
    """EPS estimate vs. reported per quarter, surprise in % above the bars."""
    x = [f"Q{(d.month - 1) // 3 + 1} {str(d.year)[2:]}" for d in df.index]
    fig = go.Figure([
        go.Bar(x=x, y=df["estimate"], name="Expected", marker_color=ESTIMATE,
               hovertemplate="%{y:.2f}<extra>Expected</extra>"),
        go.Bar(x=x, y=df["reported"], name="Reported", marker_color=DEPOT,
               text=[f"{fmt.spec(v * 100, '+.0f')}%" for v in df["surprise"]], textposition="outside",
               textfont=dict(color=[POS if v >= 0 else NEG for v in df["surprise"]], size=11), cliponaxis=False,
               hovertemplate="%{y:.2f}<extra>Reported</extra>"),
    ])
    _layout(fig, 260)
    fig.update_layout(barmode="group", bargap=0.3, bargroupgap=0.08)
    fig.update_xaxes(type="category")
    return fig


def multiple_tile(s: pd.Series, current: float | None, height: int = 200) -> go.Figure:
    """A valuation multiple over time with its median."""
    med = float(s.median())
    fig = go.Figure(go.Scatter(x=s.index, y=s, line=dict(color=DEPOT, width=1.8), hovertemplate="%{y:.1f}×<extra></extra>"))
    reference_line(fig, med, f"Median {fmt.spec(med, '.1f')}", MUTED)
    _layout(fig, height, legend=False)
    fig.update_yaxes(zeroline=False, tickfont=dict(size=10.5), nticks=5, ticksuffix="×")
    fig.update_xaxes(tickfont=dict(size=10.5), nticks=4)
    return fig


def rdcf_heatmap(grid: pd.DataFrame, hurdle: float, rf: float, current_margin: float) -> go.Figure:
    """Implied annual return per scenario; color centered on the hurdle (blue above, red below)."""
    z = grid.to_numpy() * 100
    lim = max(float(np.nanmax(np.abs(z - hurdle * 100))), 4.0)
    cols = [f"Margin {fmt.spec(m * 100, '.0f')}% (today)" if abs(m - current_margin) < 1e-9
            else f"Margin {fmt.spec(m * 100, '.0f')}%" for m in grid.columns]
    rows = [f"{fmt.spec(g * 100, '+.0f')}% growth" for g in grid.index]
    text = [["–" if not np.isfinite(v) else f"{v:.1f}%" for v in row] for row in z]
    fig = go.Figure(go.Heatmap(
        z=z, x=cols, y=rows, text=text, texttemplate="%{text}", textfont=dict(size=13),
        colorscale=DIVERGING, zmid=hurdle * 100, zmin=hurdle * 100 - lim, zmax=hurdle * 100 + lim, xgap=3, ygap=3,
        colorbar=dict(ticksuffix="%", thickness=10, outlinewidth=0, title=dict(text="Return p.a.", font=dict(size=11))),
        hovertemplate="%{y}, %{x}: %{z:.1f}% p.a.<extra></extra>",
    ))
    _layout(fig, 60 + 44 * len(rows), hover="closest", legend=False)
    fig.update_yaxes(autorange="reversed", showgrid=False, zeroline=False, type="category")
    fig.update_xaxes(side="top", ticks="", showline=False, type="category")
    return fig


def implied_path(history: pd.Series, implied: pd.Series, consensus: dict[int, float], scale: float, unit: str) -> go.Figure:
    """Reported revenue, the path the market price requires, and the analyst consensus."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[d.year for d in history.index], y=history / scale, name="Reported",
                             mode="lines+markers", line=dict(color=DEPOT, width=2.5), marker=dict(size=7),
                             hovertemplate="%{x}: %{y:,.1f} " + unit + "<extra>Reported</extra>"))
    fig.add_trace(go.Scatter(x=list(implied.index), y=implied / scale, name="Priced in (at hurdle)",
                             mode="lines", line=dict(color=BENCH, width=2, dash="dash"),
                             hovertemplate="%{x}: %{y:,.1f} " + unit + "<extra>Priced in</extra>"))
    if consensus:
        fig.add_trace(go.Scatter(x=list(consensus), y=[v / scale for v in consensus.values()], name="Analyst consensus",
                                 mode="markers", marker=dict(color=BENCH2, size=10, symbol="diamond",
                                                             line=dict(color=SURFACE, width=1.5)),
                                 hovertemplate="%{x}: %{y:,.1f} " + unit + "<extra>Consensus</extra>"))
    _layout(fig, 300)
    fig.update_yaxes(ticksuffix=f" {unit}", zeroline=False)
    fig.update_xaxes(dtick=1)
    return fig


def guidance_track(df: pd.DataFrame, scale: float, unit: str) -> go.Figure:
    """Guided revenue range per quarter (bar from low to high) and the reported value (dot)."""
    x = [f"Q{(pd.Timestamp(d).month - 1) // 3 + 1} {str(pd.Timestamp(d).year)[2:]}" for d in df["quarter_end"]]
    colors = [POS if r_ == "above range" else (NEG if r_ == "below range" else MUTED) for r_ in df["result"]]
    fig = go.Figure([
        go.Bar(x=x, y=(df["high"] - df["low"]) / scale, base=df["low"] / scale, name="Guided range",
               marker_color="rgba(42,120,214,0.22)", marker_line=dict(color=DEPOT, width=1),
               customdata=np.column_stack([df["low"] / scale, df["high"] / scale]),
               hovertemplate="Guidance: %{customdata[0]:,.1f} – %{customdata[1]:,.1f} " + unit + "<extra></extra>"),
        go.Scatter(x=x, y=df["actual"] / scale, mode="markers", name="Reported",
                   marker=dict(size=12, color=colors, line=dict(color=SURFACE, width=2)),
                   hovertemplate="Reported: %{y:,.2f} " + unit + "<extra></extra>"),
    ])
    _layout(fig, 260, hover="closest")
    fig.update_yaxes(ticksuffix=f" {unit}", zeroline=False)
    fig.update_xaxes(type="category")
    fig.update_layout(bargap=0.55)
    return fig


# ------------------------------------------------------------- depot v3
def dividend_months(received_monthly: pd.Series, expected_monthly: pd.Series, privacy: bool = False) -> go.Figure:
    """Received dividends per month (solid) followed by expected payments (light)."""
    labels = _month_dates
    fig = go.Figure()
    fmt = "•••" if privacy else _cur() + "%{y:,.2f}"
    if len(received_monthly):
        fig.add_trace(go.Bar(x=labels(received_monthly.index), y=received_monthly.values, name="Received (net)",
                             marker_color=DEPOT, hovertemplate=fmt + "<extra>Received</extra>"))
    if len(expected_monthly):
        fig.add_trace(go.Bar(x=labels(expected_monthly.index), y=expected_monthly.values, name="Expected (gross)",
                             marker_color=ESTIMATE, hovertemplate=fmt + "<extra>Expected</extra>"))
    _layout(fig, 300)
    fig.update_xaxes(tickformat="%b %Y", dtick="M3")
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy)
    return fig


def net_worth(depot: pd.Series, cash: pd.Series, privacy: bool = False) -> go.Figure:
    """Stacked area: portfolio value and cash = total assets at the broker."""
    fmt = "•••" if privacy else _cur() + "%{y:,.0f}"
    fig = go.Figure([
        go.Scatter(x=depot.index, y=depot, name="Portfolio", stackgroup="w", line=dict(width=0.5, color=SURFACE),
                   fillcolor=DEPOT, hovertemplate=fmt + "<extra>Portfolio</extra>"),
        go.Scatter(x=cash.index, y=cash.clip(lower=0), name="Cash", stackgroup="w", line=dict(width=0.5, color=SURFACE),
                   fillcolor=ESTIMATE, hovertemplate=fmt + "<extra>Cash</extra>"),
    ])
    total = depot + cash.clip(lower=0)
    fig.add_trace(go.Scatter(x=total.index, y=total, name="Total", mode="lines", line=dict(color=TEXT, width=1.5),
                             hovertemplate=fmt + "<extra>Total</extra>"))
    _layout(fig, 320)
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy)
    return fig


def money_flow(sources: dict[str, float], uses: dict[str, float], privacy: bool = False) -> go.Figure:
    """Sankey: where the money came from (left), through the cash account, to where it went (right).

    Small streams are grouped so every label has room; amounts sit next to the labels.
    """
    def group(flows: dict[str, float], keep: tuple[str, ...], rest: str) -> dict[str, float]:
        flows = {k: v for k, v in flows.items() if v > 0.5}
        total = sum(flows.values()) or 1
        out = {k: v for k, v in flows.items() if k in keep or v / total >= 0.04}
        small = sum(v for k, v in flows.items() if k not in out)
        return out | ({rest: small} if small > 0.5 else {})

    sources = group(sources, ("Deposits", "Sales"), "Income & other")
    uses = group(uses, ("Portfolio (buys)",), "Other")
    names = list(sources) + ["Cash account"] + list(uses)
    amounts = list(sources.values()) + [sum(sources.values())] + list(uses.values())
    labels = [tr(n) if privacy else f"{tr(n)}  {_eur(a)}" for n, a in zip(names, amounts)]
    hub = len(sources)
    src, dst, val, colors = [], [], [], []
    for i, v in enumerate(sources.values()):
        src.append(i)
        dst.append(hub)
        val.append(v)
        colors.append("rgba(42,120,214,0.22)")
    for k, (name, v) in enumerate(uses.items()):
        src.append(hub)
        dst.append(hub + 1 + k)
        val.append(v)
        colors.append("rgba(42,120,214,0.45)" if name.startswith("Portfolio") else "rgba(137,135,129,0.30)")
    node_colors = [DEPOT if n.startswith(("Portfolio", "Sales")) else (ESTIMATE if n == "Cash account" else MUTED)
                   for n in names]
    fig = go.Figure(go.Sankey(
        arrangement="snap",
        node=dict(label=labels, pad=26, thickness=12, color=node_colors, line=dict(width=0),
                  hovertemplate="%{label}<extra></extra>"),
        link=dict(source=src, target=dst, value=val, color=colors,
                  hovertemplate=("•••" if privacy else _cur() + "%{value:,.0f}") + "<extra></extra>"),
        textfont=dict(family=FONT, size=12.5, color=TEXT2),
    ))
    _layout(fig, 380, hover="closest", legend=False)
    fig.update_layout(margin=dict(l=4, r=4, t=8, b=8))
    return fig


# ------------------------------------------------------------- planning
def wealth_fan(dates: pd.DatetimeIndex, bands: pd.DataFrame, paid: np.ndarray, goal: float | None,
               privacy: bool = False, height: int = 400) -> go.Figure:
    """Monte Carlo fan: 10–90% and 25–75% ranges, the typical path, money paid in, and the goal."""
    fmt = "•••" if privacy else _cur() + "%{y:,.0f}"
    fig = go.Figure()
    for lo, hi, alpha, name in [(0.1, 0.9, 0.12, "1 in 10 – 9 in 10"), (0.25, 0.75, 0.22, "middle half")]:
        fig.add_trace(go.Scatter(x=dates, y=bands[hi], mode="lines", line=dict(width=0), showlegend=False,
                                 hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=dates, y=bands[lo], mode="lines", line=dict(width=0), fill="tonexty",
                                 fillcolor=f"rgba(42,120,214,{alpha})", name=name, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=dates, y=bands[0.9], name="Good case", mode="lines",
                             line=dict(color=DEPOT, width=1, dash="dot"), hovertemplate=fmt + "<extra>Good case</extra>"))
    fig.add_trace(go.Scatter(x=dates, y=bands[0.5], name="Typical", mode="lines", line=dict(color=DEPOT, width=2.4),
                             hovertemplate=fmt + "<extra>Typical</extra>"))
    fig.add_trace(go.Scatter(x=dates, y=bands[0.1], name="Bad case", mode="lines",
                             line=dict(color=DEPOT, width=1, dash="dot"), hovertemplate=fmt + "<extra>Bad case</extra>"))
    fig.add_trace(go.Scatter(x=dates, y=paid, name="Paid in", mode="lines", line=dict(color=MUTED, width=1.6, dash="dash"),
                             hovertemplate=fmt + "<extra>Paid in</extra>"))
    if goal:
        reference_line(fig, goal, "Goal" if privacy else f"Goal {_eur(goal)}", BENCH, anchor="left")
    _layout(fig, height)
    fig.update_yaxes(tickprefix=_cur(), showticklabels=not privacy, zeroline=False, showgrid=True)
    fig.update_xaxes(showgrid=True, gridcolor=GRID)
    return fig


def exposure_bars(df: pd.DataFrame, label_col: str = "name", height: int | None = None) -> go.Figure:
    """Stacked horizontal bars: direct share and share held through ETFs (fractions of the portfolio)."""
    d = df.iloc[::-1]
    fig = go.Figure([
        go.Bar(y=d[label_col].map(lambda n: _short(str(n), 26)), x=d["direct"] * 100, name="Direct", orientation="h",
               marker_color=DEPOT, hovertemplate="%{x:.1f}%<extra>Direct</extra>"),
        go.Bar(y=d[label_col].map(lambda n: _short(str(n), 26)), x=d["via_funds"] * 100, name="Through ETFs",
               orientation="h", marker_color=ESTIMATE, hovertemplate="%{x:.1f}%<extra>Through ETFs</extra>"),
    ])
    _layout(fig, height or max(240, 30 * len(d) + 70), hover="y unified")
    fig.update_layout(barmode="stack", bargap=0.35, legend_traceorder="normal")
    fig.update_xaxes(ticksuffix="%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(showgrid=False, zeroline=False, tickfont=dict(color=TEXT2))
    return fig


def window_bars(windows: pd.DataFrame, years: int, height: int = 320) -> go.Figure:
    """One bar per start month: how much more (or less) waiting for pullbacks ended with than the savings plan."""
    d = windows["difference"] * 100
    fig = go.Figure(go.Bar(x=windows["start"], y=d, marker_color=_signed_colors(d), name="Pullbacks vs. savings plan",
                           customdata=windows["end"],
                           hovertemplate="%{x|%b %Y} – %{customdata|%b %Y}: %{y:+.1f}%<extra></extra>"))
    _layout(fig, height, legend=False)
    fig.update_layout(bargap=0.15)
    fig.update_yaxes(ticksuffix="%", zeroline=True)
    fig.update_xaxes(title_text=f"start of the {years}-year window")
    return fig


def backtest_buys(prices: pd.Series, high: pd.Series, buys: pd.Series, currency: str, height: int = 320) -> go.Figure:
    """Price over one window with its 52-week high and the days the pullback strategy invested (size = amount)."""
    b = buys[buys > 0]
    size = 6 + 14 * np.sqrt(b / b.max()) if len(b) else b
    fig = go.Figure([
        go.Scatter(x=high.index, y=high, name="52-week high", mode="lines", line=dict(color=MUTED, width=1, dash="dot"),
                   hovertemplate="%{y:,.2f}<extra>52-week high</extra>"),
        go.Scatter(x=prices.index, y=prices, name="Price incl. dividends", mode="lines",
                   line=dict(color=DEPOT, width=1.8), hovertemplate="%{y:,.2f} " + currency + "<extra>Price</extra>"),
        go.Scatter(x=b.index, y=prices.reindex(b.index), name="Waiting bought", mode="markers",
                   marker=dict(color=BENCH, size=size, line=dict(color=SURFACE, width=1.5)), customdata=b,
                   hovertemplate=_cur() + "%{customdata:,.0f} invested<extra>Waiting bought</extra>"),
    ])
    _layout(fig, height)
    return fig
