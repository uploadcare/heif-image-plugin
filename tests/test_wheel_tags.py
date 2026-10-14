import runpy
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


@pytest.mark.parametrize('implementation, free_threaded, expected', [
    ('CPython', False, 'cp39'),
    ('CPython', True, None),
    ('PyPy', False, None),
])
def test_wheel_uses_stable_abi_only_for_gil_enabled_cpython(
        monkeypatch, implementation, free_threaded, expected):
    setup = mock.Mock()
    monkeypatch.setitem(sys.modules, 'setuptools', SimpleNamespace(setup=setup))
    monkeypatch.setattr('platform.python_implementation', lambda: implementation)
    get_config_var = sysconfig.get_config_var
    monkeypatch.setattr(sysconfig, 'get_config_var',
                        lambda name: free_threaded if name == 'Py_GIL_DISABLED'
                        else get_config_var(name))
    runpy.run_path(str(Path(__file__).resolve().parents[1] / 'setup.py'))
    options = setup.call_args.kwargs['options']
    assert options.get('bdist_wheel', {}).get('py_limited_api') == expected
