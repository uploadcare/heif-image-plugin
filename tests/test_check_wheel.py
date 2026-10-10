import runpy
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest


@pytest.mark.parametrize('dependency', [
    '@rpath/libheif.1.dylib', '/tmp/build/libheif.1.dylib',
])
def test_universal2_dependencies_check_both_architectures(
        tmp_path, monkeypatch, dependency):
    platform = 'macosx_11_0_universal2'
    wheel = tmp_path / f'heif_image_plugin-0.8.1-cp39-abi3-{platform}.whl'
    with ZipFile(wheel, 'w') as archive:
        archive.writestr('heif_image_plugin-0.8.1.dist-info/WHEEL',
                         f'Tag: cp39-abi3-{platform}\n')
        archive.writestr('_heif_image_plugin/_libheif.abi3.so', b'')
    output = (
        'extension (architecture x86_64):\n'
        '\t@rpath/libheif.1.dylib (compatibility version 17.0.0)\n'
        '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
        'extension (architecture arm64):\n'
        f'\t{dependency} (compatibility version 17.0.0)\n'
        '\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n'
    )
    monkeypatch.setattr(subprocess, 'run', lambda *args, **kwargs: None)
    monkeypatch.setattr(subprocess, 'check_output',
                        lambda args, **kwargs: output if '-L' in args else '')
    monkeypatch.setattr(sys, 'argv', ['check-wheel.py', str(wheel), platform])
    script = Path(__file__).resolve().parents[1] / '.github/scripts/check-wheel.py'
    if dependency.startswith('/tmp/'):
        with pytest.raises(AssertionError):
            runpy.run_path(str(script))
    else:
        runpy.run_path(str(script))
