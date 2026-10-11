from __future__ import annotations
import logging
from datetime import datetime
from config import LOG_DIR

def configure_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile = LOG_DIR / f"receipt-{datetime.now():%Y-%m-%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(logfile, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger("thermal_receipt")
