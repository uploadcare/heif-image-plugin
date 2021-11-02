import os.path
from io import BytesIO
from unittest import mock

import pytest
from PIL import Image, ImageCms
from pyheif.error import HeifError

from HeifImagePlugin import check_heif_magic


def res(*path):
    return os.path.join('tests', 'images', *path)


@pytest.mark.parametrize(
    ['image_name'],
    [
        ('test1.heic',),
        ('test2.heic',),
        ('test3.heic',),
        ('test4.heif',),
    ]
)
def test_open_image(image_name):
    image = Image.open(res(image_name))
    image.load()

    assert image is not None


def test_open_image_exif():
    image = Image.open(res('test1.heic'))

    assert image.info['exif'] is not None


def test_open_image_exif_none():
    image = Image.open(res('test2.heic'))

    assert 'exif' not in image.info


def test_image_color_profile():
    image = Image.open(res('test3.heic'))

    assert image.info['icc_profile'] is not None
    icc_profile = BytesIO(image.info['icc_profile'])

    # Try to parse
    icc_profile = ImageCms.getOpenProfile(icc_profile)


@mock.patch('pyheif.read', side_effect=HeifError(code=1, subcode=2, message='Error'))
def test_open_image_error(read_mock):
    with pytest.raises(IOError):
        Image.open(res('test1.heic'))


@mock.patch('pyheif.read')
def test_open_image_metadata(read_mock):
    m = mock.MagicMock()
    m.size = (10, 20)
    m.mode = 'RGB'
    m.data = b'rgb' * 10 * 20
    m.transformations = {'crop': (0, 0, 10, 20), 'orientation_tag': 0}
    m.metadata = [
        {'type': 'foo', 'data': 'bar'},
        {'type': 'bar', 'data': 'foo'},
    ]
    read_mock.return_value = m

    image = Image.open(res('test1.heic'))

    assert image is not None


@pytest.mark.parametrize(
    ['magic'],
    [
        (b'heic',),
        (b'heix',),
        (b'hevc',),
        (b'hevx',),
        (b'heim',),
        (b'heis',),
        (b'hevm',),
        (b'hevs',),
        (b'mif1',),
    ]
)
def test_check_heif_magic(magic):
    assert check_heif_magic(b'    ftyp%b    ' % magic)


def test_check_heif_magic_wrong():
    assert not check_heif_magic(b'    fty hei     ')

@pytest.mark.parametrize('orientation', list(range(1, 9)))
def test_orientation(orientation):
    image = Image.open(res('orientation', f'Landscape_{orientation}.heic'))

    # There should be exif in each image, even if Orientation is 0
    assert 'exif' in image.info
    exif = image.getexif()

    # There should be Orientation tag for each image
    assert 0x0112 in exif

    # And this orientation should be the same as in filename
    assert exif[0x0112] == orientation
