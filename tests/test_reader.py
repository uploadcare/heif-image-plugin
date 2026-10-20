import gc
from pathlib import Path

import piexif
import pytest
from PIL import Image

from _heif_image_plugin import reader
from _heif_image_plugin.errors import assert_success

from . import respath


@pytest.fixture(params=sorted(
    path for path in Path(respath()).rglob('*')
    if path.suffix.lower() in ('.heic', '.heif', '.hif', '.avif')
    and path.name not in ('test-crop.heic', 'unreadable-wo-transf.heic')
), ids=lambda path: str(path.relative_to(respath())))
def image_path(request):
    return request.param


def test_reader_image_contract(image_path):
    image = reader.open(image_path.read_bytes())
    assert image.size[0] > 0
    assert image.size[1] > 0
    assert isinstance(image.has_alpha, bool)
    assert image.mode == ('RGBA' if image.has_alpha else 'RGB')
    assert image.bit_depth in (8, 10, 12, 16)
    assert image.data is None
    assert image.stride is None

    assert image.load() is image
    assert image.stride >= image.size[0] * len(image.mode)
    assert len(image.data) >= image.stride * image.size[1]
    pixels = Image.frombytes(
        image.mode, image.size, image.data, 'raw', (image.mode, image.stride))
    assert pixels.size == image.size
    assert pixels.mode == image.mode
    data = bytes(image.data)
    stride = image.stride
    assert image.load() is image
    assert image.stride == stride
    assert bytes(image.data) == data


@pytest.mark.parametrize('version', [(1, 17, 0), (1, 19, 0), (1, 23, 5), (1, 23, 6)])
@pytest.mark.parametrize('subsampling, bit_depth, profile', [
    ('420', 8, 0), ('420', 10, 0), ('420', 12, 2),
    ('422', 8, 2), ('422', 10, 2), ('422', 12, 2),
])
def test_reader_pixels_match_selected_chroma_upsampling(
        monkeypatch, version, subsampling, bit_depth, profile):
    runtime_version = reader.libheif_version
    if runtime_version < (1, 19, 0) and version >= (1, 19, 0):
        pytest.skip('Reliable AVIF chroma reporting requires libheif 1.19.0')
    if (subsampling == '420' and version >= (1, 23, 6)
            and runtime_version < (1, 23, 6)):
        pytest.skip('Correct 4:2:0 bilinear output requires libheif 1.23.6')
    monkeypatch.setattr(reader, 'is_buggy_avif_chroma_reporting', version < (1, 19, 0))
    monkeypatch.setattr(reader, 'is_buggy_420_bilinear', version < (1, 23, 6))
    filename = f'fox.profile{profile}.{bit_depth}bpc.yuv{subsampling}.avif'
    data = bytearray(Path(respath('avif-sample-images', filename)).read_bytes())
    if subsampling == '422':
        # These fixtures incorrectly declare 4:4:4 in av1C. Match the bitstream.
        assert data.count(b'av1C') == 1
        flags = data.index(b'av1C') + 6
        data[flags] = (data[flags] & ~0x0c) | 0x08
    image = reader.open(bytes(data))
    bilinear = (version >= (1, 19, 0)
                and (subsampling == '422' or version >= (1, 23, 6)))
    references = {}
    try:
        algorithms = ('bilinear', 'nearest_neighbor') if bilinear else ('default',)
        for algorithm in algorithms:
            options = reader.ffi.gc(reader.lib.heif_decoding_options_alloc(),
                                    reader.lib.heif_decoding_options_free)
            options.convert_hdr_to_8bit = 1
            options.strict_decoding = 1
            if algorithm != 'default':
                conversion = options.color_conversion_options
                conversion.preferred_chroma_upsampling_algorithm = getattr(
                    reader.lib, 'heif_chroma_upsampling_' + algorithm)
                conversion.only_use_preferred_chroma_algorithm = 1
            out = reader.ffi.new('struct heif_image **')
            try:
                assert_success(reader.lib.heif_decode_image(
                    image._handle, out, reader.lib.heif_colorspace_RGB,
                    reader.lib.heif_chroma_interleaved_RGB, options,
                ))
                stride = reader.ffi.new('int *')
                plane = reader.lib.heif_image_get_plane_readonly(
                    out[0], reader.lib.heif_channel_interleaved, stride)
                pixels = reader.ffi.buffer(plane, stride[0] * image.size[1])
                references[algorithm] = Image.frombytes(
                    'RGB', image.size, pixels, 'raw', ('RGB', stride[0])).tobytes()
            finally:
                if out[0] != reader.ffi.NULL:
                    reader.lib.heif_image_release(out[0])

        image.load()
        actual = Image.frombytes(
            image.mode, image.size, image.data, 'raw',
            (image.mode, image.stride)).tobytes()
        assert actual == references['bilinear' if bilinear else 'default']
        if bilinear:
            assert actual != references['nearest_neighbor']
    finally:
        image.close()


def test_input_bytes_survive_collection_before_loading(image_path):
    data = image_path.read_bytes()
    image = reader.open(data)
    del data
    gc.collect()
    image.load()
    pixels = Image.frombytes(
        image.mode, image.size, image.data, 'raw', (image.mode, image.stride))
    reference = reader.open(image_path.read_bytes()).load()
    expected = Image.frombytes(
        reference.mode, reference.size, reference.data, 'raw',
        (reference.mode, reference.stride))
    assert pixels == expected


def test_real_exif_blocks_are_parseable(image_path):
    image = reader.open(image_path.read_bytes())
    metadata = image.metadata
    image.close()
    for item in metadata or []:
        if item['type'] == 'Exif':
            exif = piexif.load(item['data'])
            assert '0th' in exif
            assert 'Exif' in exif


def test_real_exif_contains_image_and_camera_metadata():
    image = reader.open(Path(respath('test3.heic')).read_bytes())
    metadata = image.metadata
    image.close()
    blocks = [item['data'] for item in metadata or [] if item['type'] == 'Exif']
    assert blocks
    exif = piexif.load(blocks[0])
    assert exif['0th']
    assert exif['Exif']
