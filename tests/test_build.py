import runpy
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cffi
import pytest


BUILD_SCRIPT = Path(__file__).resolve().parents[1] / 'bindings' / 'build.py'


def test_build_uses_bundled_configuration(monkeypatch):
    brew_lookup = mock.Mock(return_value='/opt/homebrew/bin/brew')
    monkeypatch.setattr(shutil, 'which', brew_lookup)
    config = {
        'include_dirs': ['/bundled/headers'],
        'library_dirs': ['/bundled/libraries'],
        'libraries': ['heif.1.17.6'],
    }
    bundled = SimpleNamespace(get_build_config=mock.Mock(return_value=config))
    monkeypatch.setitem(sys.modules, 'libheif_binary', bundled)
    builder = mock.Mock()
    monkeypatch.setattr(cffi, 'FFI', mock.Mock(return_value=builder))
    runpy.run_path(str(BUILD_SCRIPT))
    assert builder.set_source.call_args.kwargs == config
    brew_lookup.assert_not_called()


def test_build_without_brew_uses_standard_library_search(monkeypatch):
    monkeypatch.setattr(shutil, 'which', mock.Mock(return_value=None))
    monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    builder = mock.Mock()
    monkeypatch.setattr(cffi, 'FFI', mock.Mock(return_value=builder))
    runpy.run_path(str(BUILD_SCRIPT))
    assert builder.set_source.call_args.kwargs == {'libraries': ['heif']}


@pytest.mark.parametrize('prefix', [
    '/opt/homebrew/opt/libheif', '/usr/local/opt/libheif',
])
def test_build_uses_homebrew_configuration(monkeypatch, prefix):
    monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    monkeypatch.setattr(shutil, 'which', mock.Mock(return_value='/brew/bin/brew'))
    lookup = mock.Mock(return_value=prefix + '\n')
    monkeypatch.setattr(subprocess, 'check_output', lookup)
    builder = mock.Mock()
    monkeypatch.setattr(cffi, 'FFI', mock.Mock(return_value=builder))
    runpy.run_path(str(BUILD_SCRIPT))
    assert builder.set_source.call_args.kwargs == {
        'libraries': ['heif'],
        'include_dirs': [prefix + '/include'],
        'library_dirs': [prefix + '/lib'],
    }


def test_build_without_homebrew_libheif_uses_standard_library_search(monkeypatch):
    monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    monkeypatch.setattr(shutil, 'which', mock.Mock(return_value='/brew/bin/brew'))
    monkeypatch.setattr(subprocess, 'check_output', mock.Mock(
        side_effect=subprocess.CalledProcessError(1, 'brew'),
    ))
    builder = mock.Mock()
    monkeypatch.setattr(cffi, 'FFI', mock.Mock(return_value=builder))
    runpy.run_path(str(BUILD_SCRIPT))
    assert builder.set_source.call_args.kwargs == {'libraries': ['heif']}


def test_build_does_not_hide_bundled_configuration_errors(monkeypatch):
    error = OSError('missing bundled library')
    bundled = SimpleNamespace(
        get_build_config=mock.Mock(side_effect=error),
    )
    monkeypatch.setitem(sys.modules, 'libheif_binary', bundled)
    with pytest.raises(OSError) as caught:
        runpy.run_path(str(BUILD_SCRIPT))
    assert caught.value is error
