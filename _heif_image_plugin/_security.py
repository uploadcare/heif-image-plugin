from math import isqrt
from operator import index

from cffi import FFI

from . import _libheif
from ._native import ffi as native_ffi, lib as native_lib


ffi = FFI()
ffi.cdef("""
    struct heif_context;
    typedef struct heif_security_limits {
        uint8_t version;

        /* Version 1 (libheif 1.19). */
        uint64_t max_image_size_pixels;
        uint64_t max_number_of_tiles;
        uint32_t max_bayer_pattern_pixels;
        uint32_t max_items;
        uint32_t max_color_profile_size;
        uint64_t max_memory_block_size;
        uint32_t max_components;
        uint32_t max_iloc_extents_per_item;
        uint32_t max_size_entity_group;
        uint32_t max_children_per_box;

        /* Version 2 (libheif 1.20). */
        uint64_t max_total_memory;
        // uint32_t max_sample_description_box_entries;
        // uint32_t max_sample_group_description_box_entries;

        /* Version 3 (libheif 1.21). */
        // uint32_t max_sequence_frames;
        // uint32_t max_number_of_file_brands;

        /* Version 4, including additions present in libheif 1.23.6. */
        // uint32_t max_bad_pixels;
        // uint32_t max_iso23001_17_pixel_size_bytes;
        // const struct heif_security_limits* parent;
    } heif_security_limits;

    heif_security_limits* heif_context_get_security_limits(
        const struct heif_context*);
""")
lib = ffi.dlopen(_libheif.__file__)
try:
    get_context_limits = lib.heif_context_get_security_limits
except AttributeError:
    get_context_limits = None


def set_max_pixels(context, max_pixels, *, max_metadata_bytes=None):
    max_pixels = 0 if max_pixels is None else index(max_pixels)
    if max_pixels < 0:
        raise ValueError('max_pixels must be nonnegative')
    if max_metadata_bytes is not None:
        max_metadata_bytes = index(max_metadata_bytes)
        if max_metadata_bytes < 0:
            raise ValueError('max_metadata_bytes must be nonnegative')

    if get_context_limits is None:
        maximum_int = (1 << (native_ffi.sizeof('int') * 8 - 1)) - 1
        maximum_width = isqrt(max_pixels - 1) + 1 if max_pixels else maximum_int
        native_lib.heif_context_set_maximum_image_size_limit(
            context, min(maximum_width, maximum_int))
        return

    context = ffi.cast('struct heif_context*',
                       int(native_ffi.cast('uintptr_t', context)))
    limits = get_context_limits(context)
    max_memory = max_pixels * 4 if max_metadata_bytes is None else max_metadata_bytes
    if limits.version >= 1:
        limits.max_image_size_pixels = max_pixels
        limits.max_memory_block_size = max_memory
        if max_metadata_bytes is not None:
            limits.max_color_profile_size = max_metadata_bytes
    if limits.version >= 2:
        limits.max_total_memory = max_memory
