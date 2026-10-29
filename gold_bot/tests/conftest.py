import pytest

try:
    import pyarrow  # noqa: F401
except ImportError:                                           # the system Python has pytest but not our dependencies
    pytest.exit("pyarrow is missing: you are not in the project environment. "
                "Run: cd gold_bot && source .venv/bin/activate && python -m pytest -q", returncode=3)
