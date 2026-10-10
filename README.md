# heif-image-plugin

[![Linux](https://github.com/uploadcare/heif-image-plugin/actions/workflows/Linux.yaml/badge.svg)](https://github.com/uploadcare/heif-image-plugin/actions/workflows/Linux.yaml)
[![macOS](https://github.com/uploadcare/heif-image-plugin/actions/workflows/MacOS.yaml/badge.svg)](https://github.com/uploadcare/heif-image-plugin/actions/workflows/MacOS.yaml)
[![Python](https://github.com/uploadcare/heif-image-plugin/actions/workflows/Python.yaml/badge.svg)](https://github.com/uploadcare/heif-image-plugin/actions/workflows/Python.yaml)
[![coverage](https://img.shields.io/codecov/c/gh/uploadcare/heif-image-plugin)](https://app.codecov.io/gh/uploadcare/heif-image-plugin)
[![Py Versions](https://img.shields.io/pypi/pyversions/heif-image-plugin)](https://pypi.org/project/heif-image-plugin/)
[![license](https://img.shields.io/github/license/uploadcare/heif-image-plugin)](https://github.com/uploadcare/heif-image-plugin/blob/main/LICENSE)

A HEIF/HEIC and AVIF plugin for [Pillow](https://pillow.readthedocs.io/)
based on [libheif](https://github.com/strukturag/libheif).


## Installation

You can install **heif-image-plugin** from *PyPI*:

`pip install heif-image-plugin`

### Bundled libheif and codecs

```bash
pip install 'heif-image-plugin[libheif]'
```

The `[libheif]` extra installs the `libheif-binary` package, which provides libheif
and codecs. The plugin uses this package when installed; otherwise, it requires
system libheif.

### Ubuntu system libheif

Ubuntu 24.04:

```bash
apt-get install --no-install-recommends \
    libheif1 \
    libheif-plugin-libde265 \
    libheif-plugin-x265 \
    libheif-plugin-aomenc
```

Minimal supported libheif version is 1.17.x.

### macOS with Homebrew

The macOS wheel expects `@rpath/libheif.1.dylib`, while Homebrew's libheif uses
an absolute install name. Build the extension against Homebrew's library so it
records the correct path.

With a C compiler and Python development headers available, run the following
from the repository root in a Python environment without `libheif-binary`:

```bash
brew install libheif
pip install 'setuptools>=77.0.3' 'cffi>=1.15.1'
LIBHEIF_PREFIX=$(brew --prefix libheif)
CPPFLAGS="-I${LIBHEIF_PREFIX}/include" LDFLAGS="-L${LIBHEIF_PREFIX}/lib" \
  pip install --no-build-isolation .
```

`--no-build-isolation` prevents pip from installing `libheif-binary`
as a build dependency.


## How to use

Just import once before opening an image.

```python
from PIL import Image, ImageOps
import HeifImagePlugin

image = Image.open('test.heic')
ImageOps.exif_transpose(image, in_place=True)
# requires libheif with a HEVC or AV1 encoder
image.save('test.avif')
```

Decoding errors are exposed as `HeifImagePlugin.HeifError`, with `code`,
`subcode` and `message` fields.

Downsampling defaults to `'best'`, which selects `'sharp-yuv'` for RGB/RGBA images
with 4:2:0 subsampling when supported, and `'average'` otherwise.

Encoder-specific parameters can be passed when saving:

```python
image.save(
    'test.avif',
    quality=90,
    subsampling='420',
    downsampling='average',
    encoder='aom',
    concurrency=4,
    encoder_params={'speed': 6},
)
```

To encode AVIF with SVT-AV1, use `encoder='svt'`. SVT supports only 4:2:0
subsampling; omit `subsampling` or set it to `'420'`:

```python
image.save('test.avif', encoder='svt', subsampling='420')
```


## How to contribute

Contributions are welcome:

1. Clone the repository: `git clone https://github.com/uploadcare/heif-image-plugin.git`.
2. Build the development image: `make docker_build`.
3. Start a development shell: `make docker_shell`.
4. Make your changes and add tests.
5. Run `make lint` and `make test` inside the container.
6. Commit your changes on a new branch and open a pull request against
   [uploadcare/heif-image-plugin](https://github.com/uploadcare/heif-image-plugin).

### Building from source

Building from source requires a C compiler and Python development headers.
On Linux and macOS, a normal `pip install .` automatically installs libheif
headers and libraries in an isolated build environment. Install runtime libheif
separately, using the `[libheif]` extra or system packages described above.

To build against system libheif without `libheif-binary`, install libheif
development headers and its library, plus setuptools and CFFI, then run:

```bash
pip install --no-build-isolation .
```


## Changelog

### 0.9.0

* Reading and saving now use libheif directly. The `pyheif` dependency is removed.
  The `heif-enc` executable and `HEIF_ENC_BIN` setting are no longer used.
* Added the `[libheif]` installation extra, which installs `libheif-binary`.
  Without this extra, system libheif 1.17 or later is required.
* Wheels for CPython 3.9+ are provided for Linux (glibc 2.28+ and musl 1.2+, on
  x86_64 and ARM64) and macOS 11+ (universal2).
  Other platforms require a source build, as does using libheif from Homebrew.
* Decoding errors now use `HeifImagePlugin.HeifError` instead of
  `pyheif.error.HeifError`.
* Changed default chroma downsampling from `average` to `best`: uses `sharp-yuv`
  when possible, and `average` otherwise.
* Added saving of palette images (`P` and `PA` modes), including transparency.
* Saving now preserves the displayed EXIF orientation across supported libheif versions.

### 0.8.1

* Added SVT-AV1 support for AVIF encoding with `encoder='svt'` (4:2:0 subsampling only)

### 0.8.0

* Minimal supported Python version is 3.9
* Minimal supported libheif version is 1.17.x
* Added `encoder_params` parameter for passing custom encoder parameters when saving
* Changed the default chroma downsampling algorithm from `nn` to `average`
* Default chroma subsampling is now explicitly set to 4:2:0

### 0.7.0

* Depends on pyheif>=0.8.0; dropped support for older versions

### 0.6.2

* Fix for buggy LA mode in libheif 1.17.0 - 1.18.2
* Fixed unsupported color conversion for some images

### 0.6.1

* Added compatibility with Pillow 10.1+

### 0.6.0

* Minimal supported pyheif is 0.7.1
* Added `downsampling` parameter for saving. Works only with `subsampling` == 2.
* Transformations support updated to the latest libheif and pyheif

### 0.5.1

* Fixed HEIF saving in '1' mode

### 0.5.0

* Added HEIF saving support if `heif-enc` is installed (part of libheif)
* Fixed `HeifImageFile.verify()` call
* Extensions `.heic`, `.avif`, `.heif`, `.hif` are handled by the plugin

### 0.4.0

* Bypass some decoding errors when `ImageFile.LOAD_TRUNCATED_IMAGES` is True.

### 0.3.2

* Depends on latest pyheif.

### 0.3.1

! This version requires pyheif with `pyheif.open` API. As of 2021.11.25 this API
isn't released and is in pyheif's master. See `install-pyheif-master-pillow-latest`
target in the `Makefile` to install it.

* Fixed potential vulnerability with arbitrary data in exif metadata.

### 0.3.0

! This version requires pyheif with `pyheif.open` API. As of 2021.11.25 this API
isn't released and is in pyheif's master. See `install-pyheif-master-pillow-latest`
target in the `Makefile` to install it.

* `pyheif.open` API is used for lazy images loading.
* Fixed an error when the plugin tries to load any ISOBMFF files.
* AVIF files should work before, but now this is official.
* Patched versions of `pyheif` and `libheif` with exposed transformations are supported.
  In this case opened image isn't transformed on loading and orientation is stored
  in EXIF `Orientation` tag like for all other image formats.
  This is faster and consumes less memory.

### 0.2.0

* No need to register, works after import.
* Fill `info['icc_profile']` on loading.
* Close and release file pointer after loading.
* Decoding without custom HeifDecoder(ImageFile.PyDecoder).


## Acknowledgments

This project started with Christian Bianciotto’s
[pyheif-pillow-opener](https://github.com/ciotto/pyheif-pillow-opener).
