from __future__ import annotations

from functools import lru_cache
from io import BytesIO

from PIL import ExifTags, Image, ImageFile, ImageOps

from _heif_image_plugin import reader, writer
from _heif_image_plugin._native import libheif_version
from _heif_image_plugin.errors import Errors, HeifError, LibheifError  # noqa: F401
from _heif_image_plugin.metadata import (
    extract_heif_exif as _extract_heif_exif, rotate_heif_file as _rotate_heif_file)
from _heif_image_plugin.transformations import crop_heif_file as _crop_heif_file


class HeifImageFile(ImageFile.ImageFile):
    format = 'HEIF'
    format_description = "HEIF/HEIC image"

    def _open_heif_file(self, apply_transformations):
        try:
            heif_file = reader.open(
                self.fp.read(), apply_transformations=apply_transformations)
        except HeifError as e:
            raise SyntaxError(str(e))

        _extract_heif_exif(heif_file)

        if apply_transformations:
            self._size = heif_file.size
        else:
            heif_file = _rotate_heif_file(heif_file)
            self._size = heif_file.transformations.crop[2:4]

        if hasattr(self, "_mode"):
            self._mode = heif_file.mode
        else:
            # Fallback for Pillow < 10.1.0
            # https://pillow.readthedocs.io/en/stable/releasenotes/10.1.0.html#setting-image-mode
            self.mode = heif_file.mode

        self.info.pop('exif', None)
        self.info.pop('icc_profile', None)

        if heif_file.exif:
            self.info['exif'] = heif_file.exif

        if heif_file.color_profile:
            # rICC is Restricted ICC. Still not sure can it be used.
            # ISO/IEC 23008-12 says: The colour information 'colr' descriptive
            # item property has the same syntax as the ColourInformationBox
            # as defined in ISO/IEC 14496-12.
            # ISO/IEC 14496-12 says: Restricted profile shall be of either
            # the Monochrome or Three‐Component Matrix‐Based class of
            # input profiles, as defined by ISO 15076‐1.
            # We need to go deeper...
            if heif_file.color_profile['type'] in ('rICC', 'prof'):
                self.info['icc_profile'] = heif_file.color_profile['data']
        return heif_file

    def _open(self):
        self.tile = []
        self.heif_file = self._open_heif_file(False)

    def load(self):
        heif_file, self.heif_file = self.heif_file, None
        if heif_file:
            try:
                try:
                    heif_file = heif_file.load(
                        strict_decoding=not ImageFile.LOAD_TRUNCATED_IMAGES)
                except HeifError as e:
                    if e != Errors.unsupported_color_conversion:
                        raise
                    # Unsupported feature: Unsupported color conversion
                    # https://github.com/strukturag/libheif/issues/1273
                    self.fp.seek(0)
                    heif_file = self._open_heif_file(True).load(
                        strict_decoding=not ImageFile.LOAD_TRUNCATED_IMAGES)
            except HeifError as e:
                # Ignore EOF error and return blank image otherwise
                cropped_file = e == Errors.end_of_file
                if not cropped_file or not ImageFile.LOAD_TRUNCATED_IMAGES:
                    raise

            self.load_prepare()

            if heif_file.data:
                heif_file = _crop_heif_file(heif_file)
                self.frombytes(heif_file.data, "raw", (self.mode, heif_file.stride))

            heif_file.data = None

        return super().load()


def check_heif_magic(data):
    return reader.check(data)


is_buggy_orientation_save = libheif_version < (1, 19, 8)


@lru_cache()
def _supports_sharp_yuv(avif: bool, encoder: str | None) -> bool:
    try:
        writer.write(
            BytesIO(), bytes(8 * 8 * 3), (8, 8), channels=3,
            avif=avif, encoder=encoder, quality=50, downsampling='sharp-yuv',
            encoder_params={} if encoder == 'svt' else {'chroma': '420'})
    except HeifError as error:
        if error == Errors.unsupported_color_conversion:
            return False
        raise OSError(str(error)) from error
    return True


def _save(im: Image.Image, fp: writer.Output, filename: str) -> None:
    info = im.encoderinfo

    if im.mode in ('P', 'PA'):
        transparent = (im.mode == 'PA' or 'transparency' in im.info
                       or (im.palette is not None and im.palette.mode == 'RGBA'))
        im = im.convert('RGBA' if transparent else 'RGB')

    if im.mode in ('1', 'I', 'I;16', 'I;16B'):
        im = im.convert('L')

    if im.mode not in ('RGB', 'RGBA', 'L', 'LA'):
        raise OSError(f'cannot write mode {im.mode} as HEIF')

    avif = info.get('avif')
    if avif is None and filename:
        ext = filename.rpartition('.')[2].lower()
        avif = ext == 'avif'

    encoder = str(info['encoder']) if info.get('encoder') else None
    is_svt = info.get('encoder') == 'svt'

    subsampling = info.get('subsampling')
    if subsampling is None:
        subsampling = '420'
    if subsampling == 0:
        subsampling = '444'
    elif subsampling == 1:
        subsampling = '422'
    elif subsampling == 2:
        subsampling = '420'

    native_params: dict[str, str] = {}
    if is_svt:
        if subsampling != '420':
            raise ValueError('SVT encoder supports only subsampling=420')
    else:
        native_params['chroma'] = str(subsampling)

    if avif and info.get('concurrency') is not None:
        native_params['threads'] = str(info['concurrency'])

    params = dict(info.get('encoder_params') or {})
    if is_svt and 'chroma' in params:
        raise ValueError('SVT encoder does not support chroma parameter')
    if (speed := info.get('speed')) is not None:
        params.setdefault('speed', speed)
    for k, v in params.items():
        native_params[str(k)] = str(v)

    downsampling = str(info.get('downsampling') or 'best')
    if downsampling == 'best':
        chroma = native_params.get('chroma', '420')
        downsampling = 'average'
        if (im.mode in ('RGB', 'RGBA') and chroma == '420'
                and _supports_sharp_yuv(bool(avif), encoder)):
            downsampling = 'sharp-yuv'
    if downsampling not in ('nn', 'nearest-neighbor', 'average', 'sharp-yuv'):
        raise OSError('Undefined chroma downsampling algorithm.')

    quality = info.get('quality')
    try:
        quality = 50 if quality is None else int(quality)
    except (TypeError, ValueError, OverflowError) as error:
        raise OSError('Invalid quality factor. Must be between 0 and 100.') from error
    if not 0 <= quality <= 100:
        raise OSError('Invalid quality factor. Must be between 0 and 100.')

    icc = info.get('icc_profile', im.info.get('icc_profile'))
    exif = info.get('exif', im.info.get('exif'))
    orientation = 1
    if exif:
        metadata = Image.Exif()
        metadata.load(exif.tobytes() if isinstance(exif, Image.Exif) else exif)
        value = metadata.get(ExifTags.Base.Orientation, 1)
        if value in range(1, 9):
            orientation = value
        if is_buggy_orientation_save and orientation != 1:
            # Older libheif writes unreliable orientation properties.
            im = im.copy()
            im.info['exif'] = metadata.tobytes()
            im = ImageOps.exif_transpose(im)
            orientation = 1
        if ExifTags.Base.Orientation in metadata:
            del metadata[ExifTags.Base.Orientation]
        exif = metadata.tobytes()

    try:
        writer.write(
            fp, im.tobytes(), im.size, channels=len(im.getbands()), avif=bool(avif),
            encoder=encoder, quality=quality, downsampling=downsampling,
            encoder_params=native_params, icc_profile=icc, exif=exif,
            orientation=orientation)
    except HeifError as error:
        raise OSError(str(error)) from error


Image.register_open(HeifImageFile.format, HeifImageFile, check_heif_magic)
Image.register_save(HeifImageFile.format, _save)
Image.register_mime(HeifImageFile.format, 'image/heif')
Image.register_extensions(HeifImageFile.format, [".heic", ".avif"])

# Don't use this extensions for saving images, use the ones above.
# They have added for quick file type detection only (i.g. by Django).
Image.register_extensions(HeifImageFile.format, [".heif", ".hif"])
