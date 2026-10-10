from __future__ import annotations

from typing import Protocol

from ._native import ffi, lib
from .errors import HeifError, assert_success


class Output(Protocol):
    def write(self, data: bytes) -> int | None: ...


def write(fp: Output, data: bytes, size: tuple[int, int], *, channels: int,
          avif: bool, encoder: str | None, quality: int,
          downsampling: str, encoder_params: dict[str, str],
          icc_profile: bytes | None = None, exif: bytes | None = None,
          orientation: int = 1) -> None:
    """Encode packed grayscale or RGB pixels, with an optional alpha channel.

    Samples use eight bits and rows are packed without padding.
    EXIF is supplied as a complete metadata payload.
    Orientation uses EXIF values 1-8 and leaves pixel data unchanged.
    """
    compression = lib.heif_compression_AV1 if avif else lib.heif_compression_HEVC
    algorithms = {
        'nn': lib.heif_chroma_downsampling_nearest_neighbor,
        'nearest-neighbor': lib.heif_chroma_downsampling_nearest_neighbor,
        'average': lib.heif_chroma_downsampling_average,
        'sharp-yuv': lib.heif_chroma_downsampling_sharp_yuv,
    }
    image = ffi.new('struct heif_image **')
    native_encoder = ffi.new('struct heif_encoder **')
    handle = ffi.new('struct heif_image_handle **')
    options = ffi.NULL
    nclx = ffi.NULL
    context = lib.heif_context_alloc()
    try:
        if context == ffi.NULL:
            raise MemoryError('Cannot allocate libheif context')
        count = lib.heif_get_encoder_descriptors(compression, ffi.NULL, ffi.NULL, 0)
        descriptors = ffi.new('const struct heif_encoder_descriptor *[]', count)
        count = lib.heif_get_encoder_descriptors(
            compression, ffi.NULL, descriptors, count)
        descriptor = descriptors[0] if count else ffi.NULL
        if encoder:
            descriptor = next((item for item in descriptors[0:count]
                               if ffi.string(
                                   lib.heif_encoder_descriptor_get_id_name(item))
                               == encoder.encode()), ffi.NULL)
        if descriptor == ffi.NULL:
            codec = 'AV1' if avif else 'HEVC'
            raise HeifError(
                code=4, subcode=3000,
                message=f'No {codec} encoder available for {encoder or "default"}')
        assert_success(lib.heif_context_get_encoder(
            context, descriptor, native_encoder))
        assert_success(lib.heif_encoder_set_lossy_quality(native_encoder[0], quality))
        for key, value in encoder_params.items():
            assert_success(lib.heif_encoder_set_parameter(
                native_encoder[0], key.encode(), value.encode()))

        width, height = size
        if channels in (1, 2):
            colorspace = lib.heif_colorspace_monochrome
            chroma = lib.heif_chroma_monochrome
            channel = lib.heif_channel_Y
        else:
            colorspace = lib.heif_colorspace_RGB
            chroma = (lib.heif_chroma_interleaved_RGBA if channels == 4
                      else lib.heif_chroma_interleaved_RGB)
            channel = lib.heif_channel_interleaved
        assert_success(lib.heif_image_create(width, height, colorspace, chroma, image))
        if channels == 2:
            planes = (
                (lib.heif_channel_Y, data[0::2], width),
                (lib.heif_channel_Alpha, data[1::2], width),
            )
        else:
            planes = ((channel, data, width * channels),)
        for channel, pixels, row_bytes in planes:
            assert_success(lib.heif_image_add_plane(
                image[0], channel, width, height, 8))
            stride = ffi.new('int *')
            plane = lib.heif_image_get_plane(image[0], channel, stride)
            for row in range(height):
                ffi.buffer(plane + row * stride[0], row_bytes)[:] = (
                    pixels[row * row_bytes:(row + 1) * row_bytes])

        if icc_profile:
            assert_success(lib.heif_image_set_raw_color_profile(
                image[0], b'prof', icc_profile, len(icc_profile)))
        options = lib.heif_encoding_options_alloc()
        nclx = lib.heif_nclx_color_profile_alloc()
        if options == ffi.NULL or nclx == ffi.NULL:
            raise MemoryError('Cannot allocate libheif encoding options')
        # Match heif-enc's default sRGB, BT.601 matrix and full-range output.
        assert_success(lib.heif_nclx_color_profile_set_color_primaries(nclx, 1))
        assert_success(lib.heif_nclx_color_profile_set_transfer_characteristics(
            nclx, 13))
        assert_success(lib.heif_nclx_color_profile_set_matrix_coefficients(nclx, 6))
        nclx.full_range_flag = 1
        options.output_nclx_profile = nclx
        options.image_orientation = orientation
        conversion = options.color_conversion_options
        conversion.preferred_chroma_downsampling_algorithm = algorithms[downsampling]
        conversion.only_use_preferred_chroma_algorithm = 1
        assert_success(lib.heif_context_encode_image(
            context, image[0], native_encoder[0], options, handle))
        if exif:
            assert_success(lib.heif_context_add_exif_metadata(
                context, handle[0], exif, len(exif)))

        write_errors: list[BaseException] = []
        message = ffi.new('char[]', b'Cannot write output data')
        failure = ffi.new('struct heif_error *', {
            'code': lib.heif_error_Encoding_error,
            'subcode': lib.heif_suberror_Cannot_write_output_data,
            'message': message,
        })
        success_message = ffi.new('char[]', b'Success')
        success = ffi.new('struct heif_error *', {'message': success_message})

        @ffi.callback(
            'struct heif_error(struct heif_context *, const void *, size_t, void *)')
        def write_chunk(ctx, data, size, userdata):
            try:
                fp.write(bytes(ffi.buffer(data, size)))
                return success[0]
            except BaseException as error:
                write_errors.append(error)
                return failure[0]

        native_writer = ffi.new('struct heif_writer *', {
            'writer_api_version': 1, 'write': write_chunk,
        })
        error = lib.heif_context_write(context, native_writer, ffi.NULL)
        if write_errors:
            raise write_errors[0]
        assert_success(error)
    finally:
        if handle[0] != ffi.NULL:
            lib.heif_image_handle_release(handle[0])
        if options != ffi.NULL:
            lib.heif_encoding_options_free(options)
        if nclx != ffi.NULL:
            lib.heif_nclx_color_profile_free(nclx)
        if image[0] != ffi.NULL:
            lib.heif_image_release(image[0])
        if native_encoder[0] != ffi.NULL:
            lib.heif_encoder_release(native_encoder[0])
        if context != ffi.NULL:
            lib.heif_context_free(context)
