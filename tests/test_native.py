import builtins
import gc
import sys
import sysconfig
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image, ImageFile

import HeifImagePlugin
from _heif_image_plugin import _native, reader
from _heif_image_plugin.errors import HeifError
from _heif_image_plugin.transformations import crop_heif_file

from . import respath


@pytest.mark.skipif(not sysconfig.get_config_var('Py_GIL_DISABLED'),
                    reason='Requires free-threaded Python')
def test_free_threaded_python_runs_without_gil():
    assert not sys._is_gil_enabled(), 'GIL is enabled'


@pytest.fixture
def bundled(monkeypatch):
    module = SimpleNamespace(load_library=mock.Mock())
    monkeypatch.setitem(sys.modules, 'libheif_binary', module)
    return module


@pytest.fixture
def import_native(monkeypatch):
    original_import = builtins.__import__
    extension = SimpleNamespace(
        ffi=mock.Mock(),
        lib=SimpleNamespace(
            heif_get_version_number=mock.Mock(return_value=0x01170000)),
    )
    extension_import = mock.Mock(return_value=extension)

    def intercept(name, *args, **kwargs):
        if name == '_libheif':
            return extension_import()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', intercept)

    def execute():
        namespace = {'__package__': '_heif_image_plugin'}
        source = Path(_native.__file__).read_text()
        exec(compile(source, _native.__file__, 'exec'), namespace)
        return namespace

    return execute, extension_import, extension


def test_bundled_library_loading_requires_only_loader_api(bundled):
    module = bundled
    handle = _native._load_bundled_library()
    assert handle is module.load_library.return_value


def test_bundled_load_error_warns_and_uses_system(bundled):
    module = bundled
    module.load_library.side_effect = OSError('broken bundle')
    with pytest.warns(RuntimeWarning):
        assert _native._load_bundled_library() is None


def test_absent_bundle_imports_system_without_preloading(
        monkeypatch, import_native):
    monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    execute, extension_import, _ = import_native
    namespace = execute()
    assert namespace['_library_handle'] is None
    assert namespace['lib'] is extension_import.return_value.lib


@pytest.mark.parametrize('bundled_library', [False, True])
@pytest.mark.parametrize('version, expected', [
    (0x01100200, None), (0x01110000, (1, 17, 0)), (0x01170000, (1, 23, 0)),
])
def test_loaded_extension_version_is_checked(
        monkeypatch, bundled, import_native, bundled_library, version, expected):
    module = bundled
    if not bundled_library:
        monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    execute, extension_import, extension = import_native
    extension.lib.heif_get_version_number.return_value = version
    if expected is None:
        with pytest.raises(ImportError):
            execute()
    else:
        namespace = execute()
        assert namespace['libheif_version'] == expected
        assert namespace['_library_handle'] is (
            module.load_library.return_value if bundled_library else None)


def test_unresolved_import_preserves_cause(monkeypatch, import_native):
    monkeypatch.setitem(sys.modules, 'libheif_binary', None)
    execute, extension_import, _ = import_native
    error = ImportError('missing dependency')
    extension_import.side_effect = error
    with pytest.raises(ImportError) as caught:
        execute()
    assert caught.value.__cause__ is error


@pytest.fixture
def native_spy(monkeypatch):
    attributes = {}
    for name in dir(reader.lib):
        if not name.startswith('_'):
            value = getattr(reader.lib, name)
            attributes[name] = mock.Mock(wraps=value) if callable(value) else value
    proxy = SimpleNamespace(**attributes)
    monkeypatch.setattr(reader, 'lib', proxy)
    return proxy


def test_reader_decodes_lazily_and_only_once(native_spy):
    image = reader.open(Path(respath('test2.heic')).read_bytes(),
                        apply_transformations=False)
    assert image.size == (1280, 720)
    assert image.data is None
    native_spy.heif_decode_image.assert_not_called()
    assert image.load() is image
    pixels = bytes(image.data)
    stride = image.stride
    assert image.load() is image
    assert bytes(image.data) == pixels
    assert image.stride == stride
    native_spy.heif_decode_image.assert_called_once()


@pytest.mark.parametrize('version, avif_bug, bilinear_bug', [
    ((1, 17, 0), True, True), ((1, 18, 2), True, True),
    ((1, 19, 0), False, True), ((1, 23, 5), False, True),
    ((1, 23, 6), False, False),
])
def test_reader_chroma_bug_version_boundaries(
        monkeypatch, version, avif_bug, bilinear_bug):
    monkeypatch.setattr(_native, 'libheif_version', version)
    namespace = {'__package__': '_heif_image_plugin'}
    source = Path(reader.__file__).read_text()
    library = SimpleNamespace(
        heif_init=mock.Mock(return_value=SimpleNamespace(code=0)),
        heif_deinit=mock.Mock(),
    )
    with mock.patch.object(_native, 'lib', library), mock.patch('atexit.register'):
        exec(compile(source, reader.__file__, 'exec'), namespace)
    assert namespace['is_buggy_avif_chroma_reporting'] is avif_bug
    assert namespace['is_buggy_420_bilinear'] is bilinear_bug


@pytest.mark.parametrize('version', [
    (1, 17, 0), (1, 18, 2), (1, 19, 0), (1, 23, 5), (1, 23, 6),
])
@pytest.mark.parametrize('colorspace, chroma, query_error', [
    ('YCbCr', '420', False), ('YCbCr', '422', False),
    ('YCbCr', '444', False), ('monochrome', 'monochrome', False),
    ('RGB', '422', False), ('YCbCr', 'undefined', False),
    ('YCbCr', '422', True),
])
def test_reader_selects_bilinear_for_safe_source_formats(
        monkeypatch, native_spy, version, colorspace, chroma, query_error):
    monkeypatch.setattr(reader, 'is_buggy_avif_chroma_reporting', version < (1, 19, 0))
    monkeypatch.setattr(reader, 'is_buggy_420_bilinear', version < (1, 23, 6))
    defaults = reader.ffi.gc(_native.lib.heif_decoding_options_alloc(),
                             _native.lib.heif_decoding_options_free)
    conversion = defaults.color_conversion_options
    expected = (conversion.preferred_chroma_upsampling_algorithm,
                conversion.only_use_preferred_chroma_algorithm)
    if (version >= (1, 19, 0) and not query_error and colorspace == 'YCbCr'
            and (chroma in ('422', '444')
                 or (chroma == '420' and version >= (1, 23, 6)))):
        expected = (_native.lib.heif_chroma_upsampling_bilinear, 1)

    def query(handle, out_colorspace, out_chroma):
        out_colorspace[0] = getattr(_native.lib, 'heif_colorspace_' + colorspace)
        out_chroma[0] = getattr(_native.lib, 'heif_chroma_' + chroma)
        return SimpleNamespace(code=4 if query_error else 0)

    observed = []

    def decode(*args):
        conversion = args[-1].color_conversion_options
        observed.append((conversion.preferred_chroma_upsampling_algorithm,
                         conversion.only_use_preferred_chroma_algorithm))
        return _native.lib.heif_decode_image(*args)

    native_spy.heif_image_handle_get_preferred_decoding_colorspace.side_effect = query
    native_spy.heif_decode_image.side_effect = decode
    image = reader.open(Path(respath('test2.heic')).read_bytes())
    assert image.load() is image
    assert image.data is not None
    assert observed == [expected]
    native_spy.heif_image_handle_release.assert_called_once()


def test_pixel_buffer_survives_reader_and_crop_collection():
    image = reader.open(Path(respath('test2.heic')).read_bytes(),
                        apply_transformations=False).load()
    image.transformations.crop = (99, 33, 512, 256)
    cropped = crop_heif_file(image)
    data = cropped.data
    expected = bytes(data)
    image.close()
    del cropped, image
    gc.collect()
    assert bytes(data) == expected


def test_pixel_buffer_keeps_context_until_image_is_released(native_spy):
    for _ in range(3):
        gc.collect()
    releases = mock.Mock()
    releases.attach_mock(native_spy.heif_image_release, 'image')
    releases.attach_mock(native_spy.heif_context_free, 'context')
    image = reader.open(Path(respath('test2.heic')).read_bytes()).load()
    data = image.data
    image.close()
    # The spy's call history must not retain the native image owner.
    native_spy.heif_image_get_plane_readonly.reset_mock()
    del image
    gc.collect()
    assert releases.mock_calls == []

    del data
    # PyPy may collect the buffer and its native owners in successive cycles.
    for _ in range(3):
        gc.collect()
    assert releases.mock_calls == [mock.call.image(mock.ANY),
                                   mock.call.context(mock.ANY)]


def test_crop_at_bottom_edge_stays_within_buffer():
    image = reader.open(Path(respath('test2.heic')).read_bytes(),
                        apply_transformations=False).load()
    image.transformations.crop = (99, 719, 512, 1)
    cropped = crop_heif_file(image)
    offset = 719 * image.stride + 99 * 3
    assert bytes(cropped.data) == bytes(image.data)[offset:]
    expected = Image.frombytes(
        'RGB', image.size, image.data, 'raw', ('RGB', image.stride))
    actual = Image.frombytes(
        'RGB', cropped.size, cropped.data, 'raw', ('RGB', cropped.stride))
    assert actual == expected.crop((99, 719, 611, 720))


def test_open_error_releases_context(native_spy):
    with pytest.raises(HeifError):
        reader.open(b'not a HEIF file')
    native_spy.heif_context_free.assert_called_once()


def test_image_initialization_error_releases_handle_and_context(
        monkeypatch, native_spy):
    error = ValueError('invalid metadata')
    monkeypatch.setattr(reader, 'read_metadata', mock.Mock(side_effect=error))
    releases = mock.Mock()
    releases.attach_mock(native_spy.heif_image_handle_release, 'handle')
    releases.attach_mock(native_spy.heif_context_free, 'context')

    with pytest.raises(ValueError) as caught:
        reader.open(Path(respath('test2.heic')).read_bytes())
    assert caught.value is error
    assert releases.mock_calls == [mock.call.handle(mock.ANY),
                                   mock.call.context(mock.ANY)]


def test_handle_acquisition_error_releases_allocated_handle_and_context(native_spy):
    message = reader.ffi.new('char[]', b'handle failure')
    error = reader.ffi.new('struct heif_error *', {
        'code': 7, 'subcode': 100, 'message': message,
    })

    def fail_after_allocating(*args):
        result = _native.lib.heif_context_get_primary_image_handle(*args)
        assert result.code == 0
        return error[0]

    native_spy.heif_context_get_primary_image_handle.side_effect = fail_after_allocating
    releases = mock.Mock()
    releases.attach_mock(native_spy.heif_image_handle_release, 'handle')
    releases.attach_mock(native_spy.heif_context_free, 'context')

    with pytest.raises(HeifError) as caught:
        reader.open(Path(respath('test2.heic')).read_bytes())
    assert (caught.value.code, caught.value.subcode, caught.value.message) == (
        7, 100, 'handle failure')
    assert releases.mock_calls == [mock.call.handle(mock.ANY),
                                   mock.call.context(mock.ANY)]


def test_decode_error_releases_image_handle_and_context(native_spy):
    message = reader.ffi.new('char[]', b'decode failure')
    error = reader.ffi.new('struct heif_error *', {
        'code': 7, 'subcode': 100, 'message': message,
    })

    def fail_after_allocating(*args):
        result = _native.lib.heif_decode_image(*args)
        assert result.code == 0
        return error[0]

    native_spy.heif_decode_image.side_effect = fail_after_allocating
    image = reader.open(Path(respath('test2.heic')).read_bytes())
    with pytest.raises(HeifError) as caught:
        image.load()
    assert (caught.value.code, caught.value.subcode, caught.value.message) == (
        7, 100, 'decode failure')
    assert image.data is None
    native_spy.heif_image_release.assert_called_once()
    native_spy.heif_image_handle_release.assert_called_once()
    native_spy.heif_context_free.assert_called_once()


@pytest.mark.parametrize('allow_truncated', [False, True])
def test_strict_decoding_uses_flag_at_open_time(
        monkeypatch, native_spy, allow_truncated):
    strict_values = []

    def decode(*args):
        strict_values.append(args[-1].strict_decoding)
        if len(strict_values) == 1:
            raise HeifError(code=4, subcode=3003,
                            message='Unsupported color conversion')
        return _native.lib.heif_decode_image(*args)

    native_spy.heif_decode_image.side_effect = decode
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', allow_truncated)
    image = Image.open(respath('test2.heic'))
    monkeypatch.setattr(ImageFile, 'LOAD_TRUNCATED_IMAGES', not allow_truncated)
    image.load()
    assert strict_values == [int(not allow_truncated)] * 2


def test_error_fields_and_classification_are_preserved():
    error = HeifError(code=7, subcode=100, message='End of file')
    assert (error.code, error.subcode, error.message) == (7, 100, 'End of file')
    assert error == HeifImagePlugin.Errors.end_of_file
