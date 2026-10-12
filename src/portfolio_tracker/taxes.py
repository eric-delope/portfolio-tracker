"""German capital gains tax estimate (Abgeltungsteuer) per calendar year.

Simplified model for a private investor, not tax advice:
- 25 % Abgeltungsteuer + 5.5 % Solidaritätszuschlag = 26.375 % (no church tax)
- Losses from selling stocks only offset gains from selling stocks
  (Aktienverlusttopf, § 20 Abs. 6 S. 4 EStG); all other losses go into the
  general pot and offset any positive income.
- Equity funds/ETFs: 30 % Teilfreistellung, i.e. only 70 % of gains and
  distributions are taxable (§ 20 InvStG). All funds are assumed to be equity funds.
- Sparerpauschbetrag of 1,000 EUR per year (single filer).
- Vorabpauschale and foreign withholding tax credits are not modelled.
"""

from __future__ import annotations

import pandas as pd

TAX_RATE = 0.25 * 1.055
SAVER_ALLOWANCE = 1000.0
EQUITY_FUND_TAXABLE_SHARE = 0.70


def yearly_tax_estimate(
    tx: pd.DataFrame,
    realized: pd.DataFrame,
    allowance: float = SAVER_ALLOWANCE,
    rate: float = TAX_RATE,
) -> pd.DataFrame:
    """One row per calendar year: income by pot, loss carry-forwards, estimated vs. withheld tax."""
    years = sorted(set(tx["date"].dt.year))
    rows = []
    carry_stock = carry_general = 0.0
    for year in years:
        r = realized[realized["sell_date"].dt.year == year]
        stocks = r[r["asset_class"] != "FUND"]["gain"]
        funds = r[r["asset_class"] == "FUND"]["gain"]
        t = tx[tx["date"].dt.year == year]
        divs = t[t["event"] == "dividend"]
        fund_divs = divs[divs["asset_class"] == "FUND"]["amount"].sum()
        stock_divs = divs[divs["asset_class"] != "FUND"]["amount"].sum()
        interest = t.loc[t["event"] == "interest", "amount"].sum()

        stock_gains = stocks[stocks > 0].sum()
        stock_losses = stocks[stocks < 0].sum()
        fund_taxable = funds.sum() * EQUITY_FUND_TAXABLE_SHARE
        fund_div_taxable = fund_divs * EQUITY_FUND_TAXABLE_SHARE

        stock_net = stock_gains + stock_losses + carry_stock
        stock_pot = max(stock_net, 0.0)
        new_carry_stock = min(stock_net, 0.0)

        general = fund_taxable + stock_divs + fund_div_taxable + interest + carry_general
        total = stock_pot + general
        new_carry_general = min(total, 0.0) if general < 0 else 0.0
        taxable = max(total, 0.0)
        allowance_used = min(taxable, allowance)
        estimated_tax = (taxable - allowance_used) * rate

        rows.append({
            "year": year,
            "stock_gains": stock_gains,
            "stock_losses": stock_losses,
            "fund_gains_taxable": fund_taxable,
            "dividends": stock_divs + fund_divs,
            "interest": interest,
            "taxable_before_allowance": taxable,
            "allowance_used": allowance_used,
            "stock_loss_carryforward": new_carry_stock,
            "general_loss_carryforward": new_carry_general,
            "estimated_tax": estimated_tax,
            "withheld_tax": -t["tax"].sum(),
        })
        carry_stock, carry_general = new_carry_stock, new_carry_general
    return pd.DataFrame(rows).set_index("year")


def latent_tax(open_lots: pd.DataFrame, prices_eur: pd.Series, rate: float = TAX_RATE) -> pd.DataFrame:
    """Tax that would be due on unrealized gains if every open lot were sold today.

    ``prices_eur`` maps ISIN -> current price in EUR. Ignores the allowance and
    loss carry-forwards, so it is an upper bound per position.
    """
    lots = open_lots.copy()
    lots["value"] = lots["shares"] * lots["isin"].map(prices_eur)
    lots["unrealized"] = lots["value"] - lots["cost"]
    share = lots["asset_class"].eq("FUND").map({True: EQUITY_FUND_TAXABLE_SHARE, False: 1.0})
    lots["taxable"] = lots["unrealized"] * share
    per_isin = lots.groupby("isin").agg(
        name=("name", "first"), value=("value", "sum"),
        unrealized=("unrealized", "sum"), taxable=("taxable", "sum"),
    )
    per_isin["latent_tax"] = per_isin["taxable"].clip(lower=0) * rate
    return per_isin
