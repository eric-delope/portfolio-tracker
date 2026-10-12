"""Entry point of the public live demo (Streamlit Community Cloud).

Runs the regular dashboard with three switches set before anything is imported:
- PORTFOLIO_HOSTED: synthetic demo portfolio only, no uploads, nothing is written on the server;
- PORTFOLIO_OFFLINE: no request to any third party – every figure comes from the bundled snapshot;
- PORTFOLIO_CACHE_DIR: that snapshot (``data/demo_cache``, rebuilt with ``scripts/make_demo_snapshot.py``).

Locally, ``streamlit run app/dashboard.py`` stays the way to use the tool with your own data.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["PORTFOLIO_HOSTED"] = "1"
os.environ["PORTFOLIO_OFFLINE"] = "1"
os.environ["PORTFOLIO_CACHE_DIR"] = str(ROOT / "data" / "demo_cache")

_dashboard = Path(__file__).with_name("dashboard.py")
exec(compile(_dashboard.read_text(), str(_dashboard), "exec"))  # noqa: S102 – run the dashboard as this script
