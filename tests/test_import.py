import subprocess
import sys
from pathlib import Path

import pytest

import _heif_image_plugin


@pytest.mark.parametrize('local_extension', [False, True])
@pytest.mark.parametrize('extend_path_value', [None, '0', '1'])
def test_extension_search_requires_opt_in_and_keeps_local_priority(
        tmp_path, monkeypatch, local_extension, extend_path_value):
    if extend_path_value is None:
        monkeypatch.delenv('HEIF_IMAGE_PLUGIN_EXTEND_PATH', raising=False)
    else:
        monkeypatch.setenv('HEIF_IMAGE_PLUGIN_EXTEND_PATH', extend_path_value)
    # Use a distinct package name so editable installs cannot supply submodules.
    local = tmp_path / 'local' / '_test_heif_image_plugin'
    installed = tmp_path / 'installed' / '_test_heif_image_plugin'
    local.mkdir(parents=True)
    installed.mkdir(parents=True)
    local.joinpath('__init__.py').write_text(
        Path(_heif_image_plugin.__file__).read_text())
    local.joinpath('_native.py').write_text(
        Path(_heif_image_plugin._native.__file__).read_text())
    local.parent.joinpath('libheif_binary.py').write_text(
        'import sys\n'
        'def load_library():\n'
        '    sys.modules["_test_heif_image_plugin"].native_preloaded = True\n')
    local.joinpath('reader.py').write_text('source = "local"')
    installed.joinpath('__init__.py').write_text(
        'raise AssertionError("installed initializer must not run")')
    installed.joinpath('reader.py').write_text('source = "installed"')
    extension_source = (
        'import sys\n'
        'assert sys.modules[__package__].native_preloaded\n'
        'ffi = None\n'
        'class lib:\n'
        '    @staticmethod\n'
        '    def heif_get_version_number():\n'
        '        return 0x01170000\n'
        'source = {!r}\n')
    installed.joinpath('_libheif.py').write_text(
        extension_source.format('installed'))
    if local_extension:
        local.joinpath('_libheif.py').write_text(extension_source.format('local'))

    result = subprocess.run(
        [sys.executable, '-c',
         'import sys\n'
         'sys.path[:0] = sys.argv[1:]\n'
         'try:\n'
         '    from _test_heif_image_plugin import reader, _libheif\n'
         'except ImportError:\n'
         '    sys.exit(2)\n'
         'print(reader.source, _libheif.source)\n',
         str(local.parent), str(installed.parent)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    if not local_extension and extend_path_value != '1':
        assert result.returncode == 2, result.stderr
        return
    assert result.returncode == 0, result.stderr
    expected_extension = 'local' if local_extension else 'installed'
    assert result.stdout.strip() == f'local {expected_extension}'


def test_native_writer_does_not_import_pillow():
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys; from _heif_image_plugin import writer; '
         'assert not any(name == "PIL" or name.startswith("PIL.") '
         'for name in sys.modules)'],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
