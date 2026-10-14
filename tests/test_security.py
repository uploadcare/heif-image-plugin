from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from _heif_image_plugin import _native, _security, reader
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


@pytest.mark.skipif(_security.get_context_limits is None,
                    reason='Requires libheif security-limits API')
@pytest.mark.parametrize('field', ['max_memory_block_size', 'max_total_memory'])
@pytest.mark.parametrize('memory_limit', [1, 2_000_000])
def test_native_memory_limit_rejects_decoding_and_larger_limit_allows_it(
        field, memory_limit):
    data = Path(respath('test2.heic')).read_bytes()
    image = reader.open(data)
    try:
        image.set_max_pixels(2_000_000)
        abi_context = _security.ffi.cast(
            'struct heif_context*', int(reader.ffi.cast('uintptr_t', image._context)))
        limits = _security.get_context_limits(abi_context)
        if field == 'max_total_memory' and limits.version < 2:
            pytest.skip('Requires libheif total-memory limit')
        setattr(limits, field, memory_limit)
        message = 'total memory' if field == 'max_total_memory' else 'security limit'
        with pytest.raises(HeifError, match=message) as caught:
            image.load()
        assert (caught.value.code, caught.value.subcode) == (6, 1000)
        assert image.data is None
        if memory_limit == 2_000_000:
            assert 'image data' in caught.value.message
    finally:
        image.close()

    # A fresh context with the derived 8 MB caps must decode the same file.
    image = reader.open(data)
    try:
        image.set_max_pixels(2_000_000)
        image.load()
        assert image.size == (1280, 720)
        assert len(image.data) == image.stride * 720
    finally:
        image.close()


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


def test_pixel_limit_rejects_oversized_native_image(context):
    _security.set_max_pixels(context, 1)
    if _security.get_context_limits is not None:
        abi_context = _security.ffi.cast(
            'struct heif_context*', int(_native.ffi.cast('uintptr_t', context)))
        limits = _security.get_context_limits(abi_context)
        # Isolate the pixel check from earlier metadata-memory allocations.
        limits.max_memory_block_size = 0
        if limits.version >= 2:
            limits.max_total_memory = 0
    data = Path(respath('test2.heic')).read_bytes()
    buffer = _native.ffi.from_buffer(data)
    handle = _native.ffi.new('struct heif_image_handle**')
    image = _native.ffi.new('struct heif_image**')
    try:
        with pytest.raises(HeifError, match='maximum image size') as caught:
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
    with pytest.raises(ValueError, match='after loading or closing'):
        image.set_max_pixels(100)
