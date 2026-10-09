import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

from packaging.utils import parse_wheel_filename


wheel = Path(sys.argv[1])
platform = sys.argv[2]
_, _, _, tags = parse_wheel_filename(wheel.name)
assert tags
assert all(tag.interpreter == 'cp39' and tag.abi == 'abi3'
           and tag.platform == platform for tag in tags), tags

with ZipFile(wheel) as archive, tempfile.TemporaryDirectory() as directory:
    metadata, = [name for name in archive.namelist()
                 if name.endswith('.dist-info/WHEEL')]
    metadata_tags = {line.removeprefix('Tag: ') for line in
                     archive.read(metadata).decode().splitlines()
                     if line.startswith('Tag: ')}
    assert metadata_tags == {str(tag) for tag in tags}
    extension, = [name for name in archive.namelist()
                  if name.endswith('/_libheif.abi3.so')]
    assert not any('libheif_binary/' in name or name.endswith('.dylib')
                   or 'libheif.so' in name for name in archive.namelist())
    path = Path(directory) / '_libheif.abi3.so'
    path.write_bytes(archive.read(extension))
    path = str(path)
    if platform.endswith('universal2'):
        subprocess.run(['lipo', path, '-verify_arch', 'arm64', 'x86_64'],
                       check=True)
        dependencies = subprocess.check_output(['otool', '-L', path], text=True)
        print(dependencies)
        assert '@rpath/libheif.1.dylib' in dependencies
        for line in dependencies.splitlines()[1:]:
            if line.endswith(':'):
                continue
            dependency = line.strip().split()[0]
            assert dependency.startswith(('@', '/usr/lib/', '/System/Library/'))
        commands = subprocess.check_output(['otool', '-l', path], text=True)
        for line in commands.splitlines():
            if line.strip().startswith('path '):
                assert line.strip().split()[1].startswith('@')
    else:
        header = subprocess.check_output(['readelf', '-h', path], text=True)
        assert ('AArch64' if platform.endswith('aarch64') else
                'Advanced Micro Devices X86-64') in header
        dynamic = subprocess.check_output(['readelf', '-d', path], text=True)
        print(dynamic)
        assert 'Shared library: [libheif.so.1]' in dynamic
        for line in dynamic.splitlines():
            if '(RPATH)' in line or '(RUNPATH)' in line:
                paths = line.split('[', 1)[1].split(']', 1)[0].split(':')
                assert all(value.startswith('$ORIGIN') for value in paths)
