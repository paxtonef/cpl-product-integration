"""Loggers that actually write under uvicorn.

uvicorn configures only its own loggers; a record of ours left to the root
logger is dropped at INFO. These loggers carry their own handler on the
standard error of the moment (redirections included), and still propagate
(tests read them through the root logger).
"""
from __future__ import annotations

import logging
import sys


class StderrHandler(logging.StreamHandler):
    @property
    def stream(self):
        return sys.stderr

    @stream.setter
    def stream(self, value):
        pass


def stderr_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(h, StderrHandler) for h in logger.handlers):
        handler = StderrHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
