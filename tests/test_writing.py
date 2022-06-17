import os
import subprocess
import tempfile
from io import BytesIO
from unittest import mock

import pytest

from HeifImagePlugin import Image

from . import avg_diff


def compare_with_original(fp, original, threshold=10, max_diff=0.02):
    image = Image.open(fp)
    assert image.format == 'HEIF', 'format'
    avg_diffs = avg_diff(image, original, threshold=threshold)
    assert max(avg_diffs) <= max_diff, 'diff'
    return image


@mock.patch('HeifImagePlugin.HEIF_ENC_BIN', new='ensure_not_found')
def test_binary_not_found(jungle_ref_image):
    with BytesIO() as fp:
        with pytest.raises(FileNotFoundError, match=r'HeifImagePlugin\.HEIF_ENC_BIN'):
            jungle_ref_image.save(fp, 'HEIF', avif=True)


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


def test_subsampling(jungle_ref_image):
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

    assert speed_5_len != speed_9_len


def test_concurrency(jungle_ref_image):
    with BytesIO() as fp:
        with pytest.raises(subprocess.CalledProcessError):
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


def test_deny_palette_mode(dices_ref_image):
    ref = dices_ref_image.convert('P', palette=Image.ADAPTIVE)
    with BytesIO() as fp:
        with pytest.raises(OSError):
            ref.save(fp, 'HEIF', avif=True)
