"""Smoke test: the package imports and exposes a version."""

import ringsentinel
from ringsentinel import config


def test_package_imports_and_has_version():
    assert ringsentinel.__version__ == "0.2.0"


def test_config_module_exposes_api():
    assert callable(config.get_settings)
    assert "HI-Small" in config.SUPPORTED_VARIANTS
