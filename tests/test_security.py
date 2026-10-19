from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from cffi import FFI
from PIL import Image

import HeifImagePlugin
from _heif_image_plugin import _native, _security, reader, writer
from _heif_image_plugin.errors import HeifError, assert_success

from . import respath


@pytest.fixture
def context():
    context = _native.ffi.gc(_native.lib.heif_context_alloc(),
                             _native.lib.heif_context_free)
    try:
        yield context
    finally:
        _native.ffi.release(context)


def test_security_getter_is_available_from_libheif_119():
    assert (_security.get_context_limits is not None) == (
        _native.libheif_version >= (1, 19, 0))


@pytest.mark.skipif(_security.get_context_limits is None,
                    reason='Requires libheif security-limits API')
@pytest.mark.parametrize('max_pixels', [12345, 0, None])
def test_pixel_limit_sets_memory_limits_and_preserves_other_fields(
        context, max_pixels):
    abi_context = _security.ffi.cast(
        'struct heif_context*', int(_native.ffi.cast('uintptr_t', context)))
    limits = _security.get_context_limits(abi_context)
    untouched = {
        name: getattr(limits, name) for name in (
            'version', 'max_number_of_tiles', 'max_bayer_pattern_pixels',
            'max_items', 'max_color_profile_size', 'max_components',
            'max_iloc_extents_per_item', 'max_size_entity_group',
            'max_children_per_box')
    }
    _security.set_max_pixels(context, max_pixels)

    pixels = max_pixels or 0
    assert limits.max_image_size_pixels == pixels
    assert limits.max_memory_block_size == pixels * 4
    if limits.version >= 2:
        assert limits.max_total_memory == pixels * 4
    assert {name: getattr(limits, name) for name in untouched} == untouched


@pytest.mark.parametrize('max_pixels, width', [
    (1, 1), (16, 4), (17, 5), (24, 5), (25, 5), (26, 6),
    (None, None), (0, None), (1 << 128, None),
])
def test_legacy_pixel_limit_rounds_up_and_caps_dimension(
        monkeypatch, context, max_pixels, width):
    setter = mock.Mock()
    monkeypatch.setattr(_security, 'get_context_limits', None)
    monkeypatch.setattr(_security, 'native_lib', SimpleNamespace(
        heif_context_set_maximum_image_size_limit=setter))

    _security.set_max_pixels(context, max_pixels)

    maximum_int = (1 << (_native.ffi.sizeof('int') * 8 - 1)) - 1
    setter.assert_called_once_with(context, maximum_int if width is None else width)


@pytest.mark.parametrize('max_pixels, error', [
    (-1, ValueError), (1.5, TypeError), ('100', TypeError),
])
def test_invalid_pixel_limit_does_not_change_context(
        monkeypatch, context, max_pixels, error):
    getter = mock.Mock()
    setter = mock.Mock()
    monkeypatch.setattr(_security, 'get_context_limits', getter)
    monkeypatch.setattr(_security, 'native_lib', SimpleNamespace(
        heif_context_set_maximum_image_size_limit=setter))

    with pytest.raises(error):
        _security.set_max_pixels(context, max_pixels)
    getter.assert_not_called()
    setter.assert_not_called()


def test_small_pixel_limit_rejects_native_image(context):
    _security.set_max_pixels(context, 1)
    data = Path(respath('test2.heic')).read_bytes()
    buffer = _native.ffi.from_buffer(data)
    handle = _native.ffi.new('struct heif_image_handle**')
    image = _native.ffi.new('struct heif_image**')
    try:
        with pytest.raises(HeifError) as caught:
            assert_success(_native.lib.heif_context_read_from_memory_without_copy(
                context, buffer, len(data), _native.ffi.NULL))
            assert_success(_native.lib.heif_context_get_primary_image_handle(
                context, handle))
            assert_success(_native.lib.heif_decode_image(
                handle[0], image, _native.lib.heif_colorspace_RGB,
                _native.lib.heif_chroma_interleaved_RGB, _native.ffi.NULL))
    finally:
        if image[0] != _native.ffi.NULL:
            _native.lib.heif_image_release(image[0])
        if handle[0] != _native.ffi.NULL:
            _native.lib.heif_image_handle_release(handle[0])
    assert caught.value.code == 6
    assert caught.value.subcode == 1000


@pytest.mark.parametrize('max_pixels', [2_000_000, None, 0])
def test_reader_decodes_with_permissive_pixel_limit(max_pixels):
    image = reader.open(Path(respath('test2.heic')).read_bytes())
    try:
        assert image.set_max_pixels(max_pixels) is None
        image.load()
        assert image.data is not None
        assert len(image.data) == image.stride * image.size[1]
    finally:
        image.close()


@pytest.mark.parametrize('finish', ['load', 'close'])
def test_reader_rejects_pixel_limit_after_loading_or_closing(finish):
    image = reader.open(Path(respath('test2.heic')).read_bytes())
    getattr(image, finish)()
    with pytest.raises(ValueError):
        image.set_max_pixels(100)


@pytest.mark.parametrize('version', [1, 2])
@pytest.mark.parametrize('max_pixels', [12345, None])
@pytest.mark.parametrize('budget', [4096, 0])
def test_opening_budget_is_independent_of_pixels(
        monkeypatch, context, version, max_pixels, budget):
    limits = SimpleNamespace(
        version=version, max_image_size_pixels=123, max_memory_block_size=456,
        max_color_profile_size=789, max_total_memory=987, max_items=1000)
    monkeypatch.setattr(_security, 'get_context_limits', lambda ctx: limits)

    _security.set_max_pixels(context, max_pixels, max_metadata_bytes=budget)

    assert limits.max_image_size_pixels == (max_pixels or 0)
    assert limits.max_memory_block_size == budget
    assert limits.max_color_profile_size == budget
    assert limits.max_total_memory == (budget if version >= 2 else 987)
    assert limits.max_items == 1000

    _security.set_max_pixels(context, max_pixels)

    assert limits.max_memory_block_size == (max_pixels or 0) * 4
    assert limits.max_total_memory == ((max_pixels or 0) * 4 if version >= 2 else 987)
    assert limits.max_color_profile_size == budget


@pytest.mark.parametrize('budget, error', [
    (-1, ValueError), (1.5, TypeError), ('100', TypeError),
])
def test_invalid_opening_budget_does_not_change_context(
        monkeypatch, context, budget, error):
    getter = mock.Mock()
    monkeypatch.setattr(_security, 'get_context_limits', getter)
    with pytest.raises(error):
        _security.set_max_pixels(context, 100, max_metadata_bytes=budget)
    getter.assert_not_called()


def test_legacy_opening_budget_keeps_pixel_fallback(monkeypatch, context):
    setter = mock.Mock()
    monkeypatch.setattr(_security, 'get_context_limits', None)
    monkeypatch.setattr(_security, 'native_lib', SimpleNamespace(
        heif_context_set_maximum_image_size_limit=setter))
    _security.set_max_pixels(context, 25, max_metadata_bytes=4096)
    setter.assert_called_once_with(context, 5)


@pytest.mark.skipif(_security.get_context_limits is None,
                    reason='Requires libheif security-limits API')
@pytest.mark.parametrize('max_pixels', [2_000_000_000, None])
def test_pillow_limits_apply_before_parsing_and_through_metadata_extraction(
        monkeypatch, max_pixels):
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', max_pixels)
    monkeypatch.setattr(HeifImagePlugin, 'MAX_METADATA_BYTES', 65536)
    native_read = reader.lib.heif_context_read_from_memory_without_copy
    read_metadata = reader.read_metadata
    snapshots = []
    contexts = []

    def record(context):
        abi_context = _security.ffi.cast(
            'struct heif_context*', int(_native.ffi.cast('uintptr_t', context)))
        limits = _security.get_context_limits(abi_context)
        snapshots.append((limits.max_image_size_pixels,
                          limits.max_memory_block_size,
                          limits.max_color_profile_size,
                          limits.max_total_memory if limits.version >= 2 else None))

    def read(context, *args):
        contexts.append(context)
        record(context)
        return native_read(context, *args)

    def metadata(handle):
        record(contexts[0])
        return read_metadata(handle)

    proxy = SimpleNamespace(**{name: getattr(reader.lib, name)
                               for name in dir(reader.lib) if not name.startswith('_')})
    proxy.heif_context_read_from_memory_without_copy = read
    monkeypatch.setattr(reader, 'lib', proxy)
    monkeypatch.setattr(reader, 'read_metadata', metadata)
    with Image.open(respath('test2.heic')) as image:
        pixels = 0 if max_pixels is None else 2 * max_pixels
        assert len(snapshots) == 2
        assert all(values[:3] == (pixels, 65536, 65536) for values in snapshots)
        assert all(values[3] in (None, 65536) for values in snapshots)
        record(image.heif_file._context)
        assert snapshots[-1][:3] == (pixels, pixels * 4, 65536)
        assert snapshots[-1][3] in (None, pixels * 4)
        image.load()


@pytest.mark.skipif(_security.get_context_limits is None,
                    reason='Requires libheif security-limits API')
@pytest.mark.parametrize('kind', ['exif', 'icc_profile'])
def test_opening_rejects_oversized_metadata(monkeypatch, kind):
    output = BytesIO()
    payload = bytes(4096)
    if kind == 'exif':
        payload = Image.Exif()
        payload[0x9286] = bytes(4096)
    Image.new('RGB', (16, 16)).save(output, 'HEIF', **{kind: payload})
    data = output.getvalue()
    image = reader.open(data)
    try:
        if kind == 'exif':
            assert len(image.metadata[0]['data']) > 1024
        else:
            assert len(image.color_profile['data']) > 1024
    finally:
        image.close()

    with pytest.raises(HeifError) as caught:
        reader.open(data, max_pixels=1_000_000, max_metadata_bytes=1024)
    assert caught.value.subcode == 1000

    monkeypatch.setattr(HeifImagePlugin, 'MAX_METADATA_BYTES', 1024)
    with pytest.raises(OSError):
        Image.open(BytesIO(data))


@pytest.mark.skipif(_security.get_context_limits is None,
                    reason='Requires libheif security-limits API')
def test_opening_rejects_oversized_xmp(monkeypatch):
    abi = FFI()
    abi.cdef('''
        struct heif_context;
        struct heif_image_handle;
        struct heif_error { int code; int subcode; const char* message; };
        struct heif_error heif_context_add_XMP_metadata(
            struct heif_context*, const struct heif_image_handle*, const void*, int);
    ''')
    lib = abi.dlopen(_security._libheif.__file__)
    payload = b'<x:xmpmeta>' + b' ' * 4096 + b'</x:xmpmeta>'
    native_encode = writer.lib.heif_context_encode_image

    def encode(context, image, encoder, options, handle):
        result = native_encode(context, image, encoder, options, handle)
        assert_success(result)
        abi_context = abi.cast('struct heif_context*',
                               int(_native.ffi.cast('uintptr_t', context)))
        abi_handle = abi.cast('struct heif_image_handle*',
                              int(_native.ffi.cast('uintptr_t', handle[0])))
        assert_success(lib.heif_context_add_XMP_metadata(
            abi_context, abi_handle, payload, len(payload)))
        return result

    proxy = SimpleNamespace(**{name: getattr(writer.lib, name)
                               for name in dir(writer.lib) if not name.startswith('_')})
    proxy.heif_context_encode_image = encode
    monkeypatch.setattr(writer, 'lib', proxy)
    output = BytesIO()
    Image.new('RGB', (16, 16)).save(output, 'HEIF')
    data = output.getvalue()
    image = reader.open(data)
    try:
        assert image.metadata == [{'type': 'mime', 'data': payload}]
    finally:
        image.close()

    with pytest.raises(HeifError) as caught:
        reader.open(data, max_pixels=1_000_000, max_metadata_bytes=1024)
    assert caught.value.subcode == 1000


@pytest.mark.parametrize('max_pixels', [2_000_000_000, None])
def test_opening_accepts_dimensions_above_native_default(monkeypatch, max_pixels):
    data = bytearray(Path(respath('test2.heic')).read_bytes())
    offset = data.index(b'ispe')
    data[offset + 8:offset + 16] = (40000).to_bytes(4, 'big') * 2
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', max_pixels)
    with Image.open(BytesIO(data)) as image:
        assert image.size == (40000, 40000)
        image.heif_file.close()


@pytest.mark.parametrize('max_pixels', [2_000_000, None])
def test_decoding_can_exceed_opening_budget(monkeypatch, max_pixels):
    monkeypatch.setattr(HeifImagePlugin, 'MAX_METADATA_BYTES', 65536)
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', max_pixels)
    with Image.open(respath('test2.heic')) as image:
        image.load()
        assert len(image.tobytes()) > HeifImagePlugin.MAX_METADATA_BYTES


@pytest.mark.skipif(_native.libheif_version < (1, 20, 0),
                    reason='Requires libheif total-memory limits')
def test_decoding_retains_pixel_derived_memory_limit():
    image = reader.open(Path(respath('test2.heic')).read_bytes(),
                        max_pixels=2_000_000, max_metadata_bytes=65536)
    image.set_max_pixels(image.size[0] * image.size[1])
    with pytest.raises(HeifError) as caught:
        image.load()
    assert caught.value.subcode == 1000
    assert 'total memory' in caught.value.message.lower()


def test_direct_reader_preserves_native_defaults(monkeypatch):
    setter = mock.Mock()
    monkeypatch.setattr(_security, 'set_max_pixels', setter)
    image = reader.open(Path(respath('test2.heic')).read_bytes())
    image.close()
    setter.assert_not_called()
