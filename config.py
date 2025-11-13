#!/usr/bin/python3
# -*- coding: utf-8 -*-

import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "jwt_secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
RATE = os.getenv("RATE_LIMIT", "5/minute")

# DataBase configuration
DB_FILE = os.getenv("SQLITE_DB_FILE", "traffic.db")
DB_URL = f"sqlite+aiosqlite:///{DB_FILE}"  # f"sqlite:///{DB_FILE}"

# Proxy Settings
PROXY_SERVER = os.getenv("PLAYWRIGHT_PROXY_SERVER")
PROXY_BYPASS = os.getenv("PLAYWRIGHT_PROXY_BYPASS")
PROXY_USERNAME = os.getenv("PLAYWRIGHT_PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PLAYWRIGHT_PROXY_PASSWORD")

# logging
# logging.basicConfig(
#     level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
# )
# logger = logging.getLogger("traffic_api")


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        return json.dumps(log_entry)


# Configure in config.py
LOG_LEVEL = "INFO"
logging.basicConfig(level=LOG_LEVEL, format="%(message)s")
logger = logging.getLogger("traffic_api")
logger.handlers[0].setFormatter(JSONFormatter())
