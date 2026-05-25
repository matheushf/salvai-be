"""Logging configuration for salvai-be."""

from __future__ import annotations

import logging.config
from copy import deepcopy

from uvicorn.config import LOGGING_CONFIG

_DATE_FMT = "%Y-%m-%d %H:%M:%S"


def get_logging_config() -> dict:
    config = deepcopy(LOGGING_CONFIG)
    config["formatters"]["default"]["fmt"] = "%(asctime)s %(levelprefix)s %(message)s"
    config["formatters"]["default"]["datefmt"] = _DATE_FMT
    config["formatters"]["access"]["fmt"] = (
        '%(asctime)s %(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s'
    )
    config["formatters"]["access"]["datefmt"] = _DATE_FMT
    return config


def configure_logging() -> None:
    logging.config.dictConfig(get_logging_config())
