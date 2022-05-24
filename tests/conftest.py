import pytest
from PIL import Image

from . import respath


@pytest.fixture(scope="session")
def orientation_ref_image():
    return Image.open(respath('orientation', 'Landscape_1.heic'))


@pytest.fixture(scope="session")
def fox_ref_image():
    return Image.open(respath('avif-sample-images', 'fox.jpg'))


@pytest.fixture(scope="session")
def jungle_ref_image(fox_ref_image):
    return Image.open(respath('jungle.png'))


@pytest.fixture(scope="session")
def dices_ref_image(fox_ref_image):
    return Image.open(respath('dices.png'))
