import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.mark.parametrize('implementation, free_threaded, expected', [
    ('CPython', False, {'bdist_wheel': {'py_limited_api': 'cp39'}}),
    ('CPython', True, {}),
    ('PyPy', False, {}),
])
def test_wheel_uses_stable_abi_only_for_gil_enabled_cpython(
        monkeypatch, implementation, free_threaded, expected):
    setup = mock.Mock()
    monkeypatch.setitem(sys.modules, 'setuptools', SimpleNamespace(setup=setup))
    monkeypatch.setattr('platform.python_implementation', lambda: implementation)
    monkeypatch.setattr('sysconfig.get_config_var', lambda name: free_threaded)
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'setup.py'))
    assert setup.call_args.kwargs['options'] == expected
