import os
import subprocess
import tempfile
from io import BytesIO
from types import SimpleNamespace
from unittest import mock

import pytest
from PIL import Image, ImageOps

import HeifImagePlugin
from _heif_image_plugin import reader, writer

from . import avg_diff


def compare_with_original(fp, original, threshold=10, max_diff=0.02):
    image = Image.open(fp)
    assert image.format == HeifImagePlugin.HeifImageFile.format, 'format'
    avg_diffs = avg_diff(image, original, threshold=threshold)
    assert max(avg_diffs) <= max_diff, 'diff'
    return image


def test_encoder_not_found(jungle_ref_image):
    with BytesIO() as fp:
        with pytest.raises(OSError, match='encoder available'):
            jungle_ref_image.save(fp, 'HEIF', avif=True, encoder='ensure_not_found')


@pytest.fixture
def native_writer_spy(monkeypatch):
    monkeypatch.setattr(HeifImagePlugin, '_supports_sharp_yuv', lambda *args: True)
    attributes = {}
    for name in dir(writer.lib):
        if not name.startswith('_'):
            value = getattr(writer.lib, name)
            attributes[name] = mock.Mock(wraps=value) if callable(value) else value
    proxy = SimpleNamespace(**attributes)
    monkeypatch.setattr(writer, 'lib', proxy)
    return proxy


def test_encoder_error(native_writer_spy):
    message = writer.ffi.new('char[]', b'encoder failure details')
    error = writer.ffi.new('struct heif_error *', {
        'code': 8, 'subcode': 5002, 'message': message,
    })
    native_writer_spy.heif_context_encode_image.return_value = error[0]
    with BytesIO() as fp:
        with pytest.raises(OSError, match='encoder failure details'):
            Image.new('RGB', (1, 1)).save(fp, 'HEIF', avif=True)
    native_writer_spy.heif_image_release.assert_called_once()
    native_writer_spy.heif_encoder_release.assert_called_once()
    native_writer_spy.heif_encoding_options_free.assert_called_once()
    native_writer_spy.heif_nclx_color_profile_free.assert_called_once()
    native_writer_spy.heif_context_free.assert_called_once()


def test_save_to_filename(jungle_ref_image):
    f, filename = tempfile.mkstemp('.avif')
    os.close(f)
    try:
        jungle_ref_image.save(filename)
        compare_with_original(filename, jungle_ref_image)
    finally:
        os.unlink(filename)


def test_save_to_fp(jungle_ref_image):
    f, filename = tempfile.mkstemp('.avif')
    os.close(f)
    try:
        with open(filename, 'wb') as fp:
            jungle_ref_image.save(fp)
        compare_with_original(filename, jungle_ref_image)
    finally:
        os.unlink(filename)


def test_save_to_bytesio(jungle_ref_image):
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True)
        image = compare_with_original(fp, jungle_ref_image)

    assert image.info.get('icc_profile')
    assert image.info['icc_profile'] == jungle_ref_image.info['icc_profile']


def test_encoder(jungle_ref_image):
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, encoder='aom')
        compare_with_original(fp, jungle_ref_image)


@pytest.fixture(scope='module')
def svt_available():
    descriptors = writer.ffi.new('const struct heif_encoder_descriptor *[1]')
    count = writer.lib.heif_get_encoder_descriptors(
        writer.lib.heif_compression_AV1, b'svt', descriptors, 1)
    if not count:
        pytest.skip('SVT encoder is not available')


@pytest.mark.parametrize('subsampling', [None, 2, '420'])
def test_svt_subsampling(svt_available, jungle_ref_image, subsampling):
    with BytesIO() as fp:
        jungle_ref_image.save(
            fp, 'HEIF', avif=True, encoder='svt', subsampling=subsampling)
        image = Image.open(fp)
        image.load()
        assert image.format == 'HEIF'
        assert image.size == jungle_ref_image.size


@pytest.mark.parametrize('subsampling', [0, 1, '444', '422'])
def test_svt_rejects_other_subsampling(subsampling):
    with BytesIO() as fp:
        with pytest.raises(ValueError, match='subsampling=420'):
            Image.new('RGB', (2, 2)).save(
                fp, 'HEIF', avif=True, encoder='svt', subsampling=subsampling)


def test_svt_rejects_chroma_encoder_param():
    with BytesIO() as fp:
        with pytest.raises(ValueError, match='chroma'):
            Image.new('RGB', (2, 2)).save(
                fp, 'HEIF', avif=True, encoder='svt',
                encoder_params={'chroma': '420'})


def test_quality(jungle_ref_image):
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, quality=10)
        with pytest.raises(AssertionError, match='diff'):
            # Should fail with quality=10
            compare_with_original(fp, jungle_ref_image, threshold=0)

    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, quality=90)
        # Should be ok for quality=90
        compare_with_original(fp, jungle_ref_image, threshold=0)


def test_downsampling(jungle_ref_image):
    with BytesIO() as fp:
        with pytest.raises(OSError, match='chroma'):
            jungle_ref_image.save(fp, 'HEIF', avif=True, downsampling=2)

    def get_diff_for_downsampling(downsampling):
        with BytesIO() as fp:
            jungle_ref_image.save(fp, 'HEIF', avif=True,
                                  quality=90, subsampling=2, downsampling=downsampling)
            return sum(avg_diff(Image.open(fp), jungle_ref_image))

    default_diff = get_diff_for_downsampling(None)
    nn_diff = get_diff_for_downsampling('nn')
    average_diff = get_diff_for_downsampling('average')
    sharp_diff = get_diff_for_downsampling('sharp-yuv')

    assert default_diff == sharp_diff, "best should select supported SharpYUV"
    assert default_diff not in (nn_diff, average_diff)
    assert sharp_diff not in (nn_diff, average_diff)


@pytest.fixture
def sharp_yuv_probe():
    probe = HeifImagePlugin._supports_sharp_yuv
    probe.cache_clear()
    yield probe
    probe.cache_clear()


@pytest.mark.parametrize('supported', [False, True])
def test_sharp_yuv_probe_caches_availability(sharp_yuv_probe, supported):
    error = HeifImagePlugin.HeifError(
        code=4, subcode=3003, message='Unsupported color conversion')
    with mock.patch.object(writer, 'write',
                           side_effect=None if supported else error) as save:
        assert sharp_yuv_probe(True, None) is supported
        assert sharp_yuv_probe(True, None) is supported
    save.assert_called_once()
    assert save.call_args.args[2] == (8, 8)
    assert save.call_args.kwargs['downsampling'] == 'sharp-yuv'


def test_sharp_yuv_probe_separates_format_and_encoder(sharp_yuv_probe):
    keys = [(True, None), (False, None), (True, 'svt')]
    with mock.patch.object(writer, 'write') as save:
        for key in keys * 2:
            assert sharp_yuv_probe(*key)
    assert save.call_count == len(keys)


@pytest.mark.parametrize('code, subcode', [(4, 3000), (8, 4000)])
def test_sharp_yuv_probe_propagates_other_errors(sharp_yuv_probe, code, subcode):
    error = HeifImagePlugin.HeifError(
        code=code, subcode=subcode, message='Probe failed')
    with mock.patch.object(writer, 'write', side_effect=error) as save:
        for _ in range(2):
            with pytest.raises(OSError, match='Probe failed') as caught:
                sharp_yuv_probe(True, None)
            assert caught.value.__cause__ is error
    assert save.call_count == 2


@pytest.mark.parametrize('supported', [False, True])
@pytest.mark.parametrize('mode, subsampling, params, encoder, applicable', [
    ('RGB', None, {}, None, True),
    ('RGBA', 2, {}, None, True),
    ('RGB', 0, {}, None, False),
    ('RGB', 1, {}, None, False),
    ('RGB', '444', {'chroma': '420'}, None, True),
    ('RGB', '420', {'chroma': '422'}, None, False),
    ('RGB', None, {}, 'svt', True),
    ('L', None, {}, None, False),
    ('LA', None, {}, None, False),
])
def test_best_downsampling_selection(supported, mode, subsampling, params,
                                     encoder, applicable, monkeypatch):
    probe = mock.Mock(return_value=supported)
    monkeypatch.setattr(HeifImagePlugin, '_supports_sharp_yuv', probe)
    original_params = params.copy()
    with mock.patch.object(writer, 'write') as save:
        Image.new(mode, (31, 23)).save(
            BytesIO(), 'HEIF', avif=True, subsampling=subsampling,
            encoder=encoder, encoder_params=params)
    assert save.call_args.kwargs['downsampling'] == (
        'sharp-yuv' if applicable and supported else 'average')
    if applicable:
        probe.assert_called_once_with(True, encoder)
    else:
        probe.assert_not_called()
    assert params == original_params


@pytest.mark.parametrize('downsampling',
                         ['nn', 'nearest-neighbor', 'average', 'sharp-yuv'])
def test_explicit_downsampling_does_not_probe(downsampling, monkeypatch):
    probe = mock.Mock(side_effect=AssertionError('Unexpected capability probe'))
    monkeypatch.setattr(HeifImagePlugin, '_supports_sharp_yuv', probe)
    with mock.patch.object(writer, 'write') as save:
        Image.new('RGB', (31, 23)).save(
            BytesIO(), 'HEIF', avif=True, downsampling=downsampling)
    assert save.call_args.kwargs['downsampling'] == downsampling
    probe.assert_not_called()


def test_subsampling(jungle_ref_image):
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, subsampling=None)

    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, quality=90, subsampling=2)
        with pytest.raises(AssertionError, match='diff'):
            # Should fail with subsampling=2
            compare_with_original(fp, jungle_ref_image, threshold=0, max_diff=0.01)

    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, quality=90, subsampling=0)
        # Should be ok for subsampling=0
        compare_with_original(fp, jungle_ref_image, threshold=0, max_diff=0.01)

    for subsampling in [1, '444', '422', '420']:
        with BytesIO() as fp:
            jungle_ref_image.save(fp, 'HEIF', avif=True, subsampling=subsampling)


def test_speed(jungle_ref_image):
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, speed=9)
        compare_with_original(fp, jungle_ref_image)
        speed_9_len = fp.tell()

    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, speed=5)
        compare_with_original(fp, jungle_ref_image)
        speed_5_len = fp.tell()

    params = {'speed': 5}
    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, encoder_params=params)
        compare_with_original(fp, jungle_ref_image)
        params_speed_5_len = fp.tell()

    assert speed_5_len != speed_9_len
    assert speed_5_len == params_speed_5_len
    assert params == {'speed': 5}


def test_concurrency(jungle_ref_image):
    with BytesIO() as fp:
        with pytest.raises(OSError):
            jungle_ref_image.save(fp, 'HEIF', avif=True, concurrency='please')

    with BytesIO() as fp:
        jungle_ref_image.save(fp, 'HEIF', avif=True, concurrency=1)
        compare_with_original(fp, jungle_ref_image)


@pytest.mark.parametrize('mode', ['RGB', 'RGBA', 'L', 'LA', '1'])
def test_good_modes(mode, dices_ref_image):
    ref = dices_ref_image.convert(mode)
    with BytesIO() as fp:
        ref.save(fp, 'HEIF', avif=True)
        # Coerce ref mode to RGB since loader don't work with L
        compare_with_original(fp, ref.convert('RGBA' if 'A' in mode else 'RGB'))


@pytest.mark.parametrize('avif', [False, True])
def test_save_palette_mode(dices_ref_image, avif):
    ref = dices_ref_image.convert('P', palette=Image.ADAPTIVE)
    with BytesIO() as fp:
        ref.save(fp, 'HEIF', avif=avif, quality=90)
        compare_with_original(fp, ref.convert())


@pytest.mark.parametrize('avif', [False, True])
@pytest.mark.parametrize('transparency',
                         ['opaque', 'index', 'table', 'palette', 'alpha'])
def test_save_palette_transparency(avif, transparency):
    image = Image.new('P', (31, 23))
    image.putpalette([100, 150, 200, 200, 150, 100] + [0] * 762)
    image.putdata([int(x >= 16) for y in range(23) for x in range(31)])
    if transparency == 'index':
        image.info['transparency'] = 0
    elif transparency == 'table':
        image.info['transparency'] = bytes([0, 128] + [255] * 254)
    elif transparency == 'palette':
        image.putpalette([100, 150, 200, 0, 200, 150, 100, 128] + [0] * 1016,
                         rawmode='RGBA')
    elif transparency == 'alpha':
        image = image.convert('PA')
        image.putdata([(int(x >= 16), y * 255 // 22)
                       for y in range(23) for x in range(31)])
    pixels, info = image.tobytes(), image.info.copy()
    expected = image.convert('RGB' if transparency == 'opaque' else 'RGBA')
    fp = BytesIO()
    with mock.patch.object(writer, 'write', wraps=writer.write) as encode:
        image.save(fp, 'HEIF', avif=avif, quality=90)
    assert encode.call_args.args[1] == expected.tobytes()
    assert encode.call_args.kwargs['channels'] == len(expected.getbands())
    result = compare_with_original(fp, expected)
    if transparency != 'opaque':
        assert max(avg_diff(result.getchannel('A'), expected.getchannel('A'),
                            threshold=2)) <= 0.01
    assert image.tobytes() == pixels
    assert image.info == info


@pytest.mark.parametrize('avif', [False, True])
@pytest.mark.parametrize('destination', ['filename', 'file', 'bytesio', 'stream'])
def test_native_save_destinations(avif, destination, tmp_path):
    original = Image.new('RGBA', (31, 23), (100, 150, 200, 80))
    path = tmp_path / ('image.avif' if avif else 'image.heic')
    if destination == 'filename':
        original.save(path)
        data = path.read_bytes()
    elif destination == 'file':
        with path.open('wb') as fp:
            original.save(fp)
        data = path.read_bytes()
    elif destination == 'bytesio':
        fp = BytesIO()
        original.save(fp, 'HEIF', avif=avif)
        data = fp.getvalue()
    else:
        class Stream:
            def __init__(self):
                self.data = bytearray()

            def write(self, data):
                self.data.extend(data)

        fp = Stream()
        original.save(fp, 'HEIF', avif=avif)
        data = bytes(fp.data)
    assert data[8:12] == (b'avif' if avif else b'heic')
    image = compare_with_original(BytesIO(data), original)
    assert image.size == (31, 23)
    assert image.mode == 'RGBA'


@pytest.mark.parametrize('avif', [False, True])
def test_explicit_codec_overrides_extension(avif, tmp_path):
    path = tmp_path / ('image.heic' if avif else 'image.avif')
    Image.new('RGB', (16, 16)).save(path, 'HEIF', avif=avif)
    assert path.read_bytes()[8:12] == (b'avif' if avif else b'heic')


def test_save_without_executable_or_temporary_files(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail('Native writing must not use subprocesses or temporary files')

    monkeypatch.setattr(subprocess, 'Popen', fail)
    monkeypatch.setattr(tempfile, 'NamedTemporaryFile', fail)
    monkeypatch.setattr(tempfile, 'TemporaryFile', fail)
    Image.new('RGB', (16, 16)).save(BytesIO(), 'HEIF', avif=True)


@pytest.mark.parametrize('orientation', range(1, 9))
@pytest.mark.parametrize('as_object', [False, True])
@pytest.mark.parametrize('avif', [False, True])
def test_save_preserves_displayed_exif_orientation(orientation, as_object, avif):
    image = Image.new('RGB', (31, 23))
    image.putdata([(x * 255 // 30, y * 255 // 22, 100)
                   for y in range(23) for x in range(31)])
    exif = Image.Exif()
    exif[274] = orientation
    exif[315] = 'Native writer'
    image.info['exif'] = exif.tobytes()
    original_pixels = image.tobytes()
    original_info = image.info.copy()
    expected = ImageOps.exif_transpose(image)
    legacy = HeifImagePlugin.is_buggy_orientation_save
    fp = BytesIO()
    options = {'exif': exif} if as_object else {}
    image.save(fp, 'HEIF', avif=avif, quality=90, **options)
    raw = reader.open(fp.getvalue(), apply_transformations=False)
    try:
        assert raw.transformations.crop[2:4] == (
            expected.size if legacy else image.size)
        assert raw.transformations.orientation_tag == (
            0 if legacy or orientation == 1 else orientation)
        stored_exif = Image.Exif()
        stored_exif.load(next(block['data'] for block in raw.metadata
                              if block['type'] == 'Exif'))
        assert 274 not in stored_exif
    finally:
        raw.close()
    result = compare_with_original(fp, expected if legacy else image)
    assert result.getexif().get(274) == (
        orientation if not legacy and orientation != 1 else None)
    assert result.getexif()[315] == 'Native writer'
    transformed = ImageOps.exif_transpose(result)
    assert transformed.size == expected.size
    assert max(avg_diff(transformed, expected, threshold=10)) <= 0.02
    assert exif[274] == orientation
    assert image.tobytes() == original_pixels
    assert image.info == original_info


@pytest.mark.parametrize('orientation', [None, 0, 9])
def test_missing_or_invalid_exif_orientation_uses_normal(orientation):
    exif = Image.Exif()
    exif[315] = 'Native writer'
    if orientation is not None:
        exif[274] = orientation
    fp = BytesIO()
    Image.new('RGB', (31, 23)).save(fp, 'HEIF', avif=True, exif=exif)
    result = Image.open(fp)
    assert 274 not in result.getexif()
    assert result.getexif()[315] == 'Native writer'


def test_suppress_exif_suppresses_orientation():
    image = Image.new('RGB', (31, 23))
    exif = Image.Exif()
    exif[274] = 6
    image.info['exif'] = exif.tobytes()
    fp = BytesIO()
    image.save(fp, 'HEIF', avif=True, exif=None)
    raw = reader.open(fp.getvalue(), apply_transformations=False)
    try:
        assert raw.transformations.orientation_tag == 0
        assert not raw.metadata
    finally:
        raw.close()


@pytest.mark.parametrize('version', [(1, 19, 7), (1, 19, 8)])
@pytest.mark.parametrize('avif', [False, True])
@pytest.mark.parametrize('mode', ['1', 'L', 'LA', 'RGB', 'RGBA', 'I', 'I;16', 'I;16B'])
def test_orientation_version_boundary_and_override(version, avif, mode, monkeypatch):
    monkeypatch.setattr(HeifImagePlugin, '_supports_sharp_yuv', lambda *args: True)
    image = Image.new('RGB', (31, 23))
    image.putdata([(x * 255 // 30, y * 255 // 22, 100)
                   for y in range(23) for x in range(31)])
    image = image.convert(mode)
    image.getexif()[274] = 8
    image.info['exif'] = image.getexif().tobytes()
    original_pixels, original_info = image.tobytes(), image.info.copy()
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = 'Override'
    monkeypatch.setattr(
        HeifImagePlugin, 'is_buggy_orientation_save', version < (1, 19, 8))
    expected = image.convert('L') if mode in ('1', 'I', 'I;16', 'I;16B') else image
    if version < (1, 19, 8):
        expected = expected.transpose(Image.Transpose.ROTATE_270)
    with mock.patch.object(writer, 'write') as encode:
        image.save(BytesIO(), 'HEIF', avif=avif, exif=exif)
    fp, pixels, size = encode.call_args.args
    options = encode.call_args.kwargs
    assert size == expected.size
    assert options['orientation'] == (1 if version < (1, 19, 8) else 6)
    assert options['avif'] is avif
    assert options['downsampling'] == (
        'sharp-yuv' if expected.mode in ('RGB', 'RGBA') else 'average')
    assert pixels == expected.tobytes()
    assert options['channels'] == len(expected.getbands())
    stored_exif = Image.Exif()
    stored_exif.load(options['exif'])
    assert 274 not in stored_exif
    assert stored_exif[315] == 'Override'
    assert exif[274] == 6
    assert image.getexif()[274] == 8
    assert image.tobytes() == original_pixels
    assert image.info == original_info


@pytest.mark.parametrize('metadata', ['icc_profile', 'exif'])
@pytest.mark.parametrize('override', ['replace', 'suppress'])
def test_metadata_option_precedence(metadata, override, jungle_ref_image):
    image = jungle_ref_image.copy()
    exif = Image.Exif()
    exif[315] = 'Original'
    image.info['exif'] = exif.tobytes()
    if metadata == 'exif':
        exif[315] = 'Replacement'
        replacement = exif.tobytes()
    else:
        replacement = image.info['icc_profile']
        if override == 'replace':
            image.info['icc_profile'] = None
    fp = BytesIO()
    value = replacement if override == 'replace' else None
    image.save(fp, 'HEIF', avif=True, **{metadata: value})
    result = Image.open(fp)
    if override == 'suppress':
        assert metadata not in result.info
    elif metadata == 'exif':
        assert result.getexif()[315] == 'Replacement'
    else:
        assert result.info['icc_profile'] == replacement


@pytest.mark.parametrize('avif', [False, True])
@pytest.mark.parametrize('mode', ['I', 'I;16', 'I;16B'])
def test_integer_grayscale_converts_to_8_bit(mode, avif):
    image = Image.new('I', (80, 23))
    values = [0, 64, 128, 254, 255, 256, 1024, 65535]
    image.putdata([values[x // 10] for y in range(23) for x in range(80)])
    if mode != 'I':
        image = image.convert(mode)
    fp = BytesIO()
    image.save(fp, 'HEIF', avif=avif, quality=90)
    result = Image.open(fp)
    assert result.size == image.size
    assert result.heif_file.bit_depth == 8
    result.load()
    expected = image.convert('L').convert('RGB')
    assert max(avg_diff(result, expected, threshold=10)) <= 0.02
    for index, value in enumerate(values):
        assert abs(result.getpixel((index * 10 + 5, 10))[0] - min(value, 255)) <= 10


@pytest.mark.parametrize('quality', [-1, 101])
def test_invalid_quality(quality):
    with pytest.raises(OSError, match='quality'):
        Image.new('RGB', (16, 16)).save(BytesIO(), 'HEIF', avif=True, quality=quality)


def test_unavailable_codec(native_writer_spy):
    native_writer_spy.heif_get_encoder_descriptors.return_value = 0
    with pytest.raises(OSError, match='No AV1 encoder'):
        Image.new('RGB', (16, 16)).save(BytesIO(), 'HEIF', avif=True)
    native_writer_spy.heif_context_free.assert_called_once()


def test_output_exception_releases_native_resources(native_writer_spy):
    failure = OSError('output failure')
    fp = mock.Mock()
    fp.write.side_effect = failure
    with pytest.raises(OSError, match='output failure') as caught:
        Image.new('RGB', (16, 16)).save(fp, 'HEIF', avif=True)
    assert caught.value is failure
    native_writer_spy.heif_image_handle_release.assert_called_once()
    native_writer_spy.heif_image_release.assert_called_once()
    native_writer_spy.heif_encoder_release.assert_called_once()
    native_writer_spy.heif_encoding_options_free.assert_called_once()
    native_writer_spy.heif_nclx_color_profile_free.assert_called_once()
    native_writer_spy.heif_context_free.assert_called_once()


def test_success_releases_native_resources(native_writer_spy):
    Image.new('RGB', (16, 16)).save(BytesIO(), 'HEIF', avif=True)
    native_writer_spy.heif_image_handle_release.assert_called_once()
    native_writer_spy.heif_image_release.assert_called_once()
    native_writer_spy.heif_encoder_release.assert_called_once()
    native_writer_spy.heif_encoding_options_free.assert_called_once()
    native_writer_spy.heif_nclx_color_profile_free.assert_called_once()
    native_writer_spy.heif_context_free.assert_called_once()


def test_default_quality_matches_50(jungle_ref_image):
    default, explicit = BytesIO(), BytesIO()
    jungle_ref_image.save(default, 'HEIF', avif=True)
    jungle_ref_image.save(explicit, 'HEIF', avif=True, quality=50)
    assert default.getvalue() == explicit.getvalue()


def test_custom_parameters_override_save_options(jungle_ref_image):
    explicit, overridden = BytesIO(), BytesIO()
    jungle_ref_image.save(explicit, 'HEIF', avif=True, subsampling='444', speed=5)
    params = {'chroma': '444', 'speed': 5}
    jungle_ref_image.save(overridden, 'HEIF', avif=True, subsampling='420', speed=9,
                          encoder_params=params)
    assert overridden.getvalue() == explicit.getvalue()
    assert params == {'chroma': '444', 'speed': 5}


@pytest.mark.parametrize('mode', ['CMYK', 'F'])
def test_reject_unsupported_modes(mode):
    with pytest.raises(OSError, match='cannot write mode'):
        Image.new(mode, (16, 16)).save(BytesIO(), 'HEIF', avif=True)


def test_raw_writer_accepts_pixels_and_exposes_native_errors():
    fp = BytesIO()
    pixels = bytes((100, 150, 200)) * (31 * 23)
    options = dict(channels=3, avif=True,
                   encoder=None, quality=90,
                   downsampling='average',
                   encoder_params={'chroma': '420'}, icc_profile=None, exif=None)
    writer.write(fp, pixels, (31, 23), **options)
    compare_with_original(fp, Image.frombytes('RGB', (31, 23), pixels))
    options['encoder'] = 'ensure_not_found'
    with pytest.raises(HeifImagePlugin.HeifError, match='encoder available'):
        writer.write(BytesIO(), pixels, (31, 23), **options)


@pytest.mark.parametrize('operation', ['heif_context_get_encoder', 'heif_image_create',
                                       'heif_context_encode_image'])
def test_native_error_after_allocation_releases_output(native_writer_spy, operation):
    message = writer.ffi.new('char[]', b'failure after allocation')
    error = writer.ffi.new('struct heif_error *', {
        'code': 8, 'subcode': 5002, 'message': message,
    })
    native_call = getattr(native_writer_spy, operation)
    original = native_call._mock_wraps

    def fail_after_allocating(*args):
        result = original(*args)
        assert result.code == 0
        assert args[-1][0] != writer.ffi.NULL
        return error[0]

    native_call.side_effect = fail_after_allocating
    with pytest.raises(OSError, match='failure after allocation'):
        Image.new('RGB', (16, 16)).save(BytesIO(), 'HEIF', avif=True)
    native_writer_spy.heif_context_free.assert_called_once()
    native_writer_spy.heif_encoder_release.assert_called_once()
    if operation != 'heif_context_get_encoder':
        native_writer_spy.heif_image_release.assert_called_once()
    if operation == 'heif_context_encode_image':
        native_writer_spy.heif_image_handle_release.assert_called_once()


@pytest.mark.parametrize('avif', [False, True])
def test_raw_grayscale_alpha_writer(avif):
    original = Image.new('LA', (31, 23))
    original.putdata([(x * 255 // 30, y * 255 // 22)
                      for y in range(23) for x in range(31)])
    fp = BytesIO()
    writer.write(
        fp, original.tobytes(), original.size, channels=2,
        avif=avif,
        encoder=None, quality=90,
        downsampling='average',
        encoder_params={'chroma': '420'}, icc_profile=None, exif=None)
    result = compare_with_original(fp, original.convert('RGBA'))
    assert result.mode == 'RGBA'
    assert result.getchannel('A').getextrema() == (0, 255)


def test_save_la_passes_raw_grayscale_alpha(dices_ref_image):
    original = dices_ref_image.convert('LA')
    fp = BytesIO()
    with mock.patch.object(writer, 'write', wraps=writer.write) as encode:
        original.save(fp, 'HEIF', avif=True, quality=90)
    assert encode.call_args.args[1] == original.tobytes()
    assert encode.call_args.kwargs['channels'] == 2
    compare_with_original(fp, original.convert('RGBA'))
