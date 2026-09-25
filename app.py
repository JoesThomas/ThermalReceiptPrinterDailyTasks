from __future__ import annotations

from services.live_pipeline import run_live_pipeline


def run_live(
    *,
    finance_requested: bool = False,
    only_page: str | None = None,
) -> None:
    """
    Run the live receipt pipeline.

    The existing pipeline still determines finance requests from the configured
    trigger/source. The keyword is retained so main.py has a stable modular API
    while individual collectors continue to be separated further.
    """
    run_live_pipeline(
        force_finance=finance_requested,
        only_page=only_page,
    )
