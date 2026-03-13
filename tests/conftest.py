import os
import sys

import pytest

# Ensure gateway package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override settings before any gateway module import
os.environ.setdefault("GATEWAY_AUTH_TOKEN", "test-token-12345")
os.environ.setdefault("GATEWAY_REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("GATEWAY_SEARXNG_URL", "http://localhost:8888")
os.environ.setdefault("GATEWAY_RATE_LIMIT_RPM", "1000")
