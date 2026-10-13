import shutil
import subprocess
from pathlib import Path

from cffi import FFI


try:
    import libheif_binary
except ModuleNotFoundError as error:
    if error.name != 'libheif_binary':
        raise
    libheif_binary = None

build_config = {'libraries': ['heif']}

if libheif_binary is not None:
    build_config = libheif_binary.get_build_config()
elif brew := shutil.which('brew'):
    try:
        prefix = Path(subprocess.check_output(
            [brew, '--prefix', '--installed', 'libheif'], text=True,
        ).strip())
    except subprocess.CalledProcessError:
        pass
    else:
        build_config['include_dirs'] = [str(prefix / 'include')]
        build_config['library_dirs'] = [str(prefix / 'lib')]


ffibuilder = FFI()
ffibuilder.cdef(Path(__file__).with_name('libheif_api.h').read_text())
ffibuilder.set_source(
    '_heif_image_plugin._libheif',
    '#include <libheif/heif.h>\n'
    '#include <libheif/heif_properties.h>\n',
    **build_config,
)


if __name__ == '__main__':
    ffibuilder.compile(verbose=True)
