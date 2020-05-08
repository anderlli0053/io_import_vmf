from .utils import truncate_name, bilinear_interpolate
from .cube2equi import find_corresponding_pixels
from vmfpy.fs import AnyBinaryIO
from pyvtflib import VTFLib, VTFImageFlag, VTFImageFormat
import numpy
from typing import Dict, List
import bpy


class VTFImporter():
    def __init__(self) -> None:
        self._cache: Dict[str, bpy.types.Image] = {}

    def load(self, image_name: str, file: AnyBinaryIO,
             colorspace: str = 'sRGB', alpha_mode: str = 'CHANNEL_PACKED') -> bpy.types.Image:
        image_name = image_name.lower()
        if image_name in self._cache:
            return self._cache[image_name]
        with VTFLib() as vtflib:
            with file:
                vtflib.load_image_bytes(file.read())
            alpha = bool(vtflib.image_flags() & (VTFImageFlag.TEXTUREFLAGS_ONEBITALPHA |
                                                 VTFImageFlag.TEXTUREFLAGS_EIGHTBITALPHA))
            width, height = vtflib.image_width(), vtflib.image_height()
            image: bpy.types.Image = bpy.data.images.new(truncate_name(image_name + ".png"), width, height,
                                                         alpha=alpha)
            pixels = numpy.frombuffer(vtflib.flip_image(vtflib.image_as_rgba8888(), width, height), dtype=numpy.uint8)
        pixels = pixels.astype(numpy.float16, copy=False)
        pixels /= 255
        image.pixels = pixels
        image.file_format = 'PNG'
        image.pack()
        image.colorspace_settings.name = colorspace
        image.alpha_mode = alpha_mode
        self._cache[image_name] = image
        return image


def load_as_equi(cubemap_name: str, files: List[AnyBinaryIO], out_height: int, hdr: bool = False) -> bpy.types.Image:
    cubemap_name = cubemap_name.lower()
    out_width = 2 * out_height
    images: List[numpy.ndarray] = []
    cubemap_dim: int = -1
    with VTFLib() as vtflib:
        for file in files:
            with file:
                vtflib.load_image_bytes(file.read())
            width, height = vtflib.image_width(), vtflib.image_height()
            if width > cubemap_dim:
                cubemap_dim = width
            if hdr:
                image_format = vtflib.image_format()
                if image_format == VTFImageFormat.IMAGE_FORMAT_RGBA16161616F:  # floating point HDR
                    pixels: numpy.ndarray = numpy.fromstring(
                        vtflib.image_get_data(), dtype=numpy.float16,
                    )
                    pixels.shape = (-1, 4)
                    pixels[:, 3] = 1.0
                elif image_format == VTFImageFormat.IMAGE_FORMAT_BGRA8888:  # compressed HDR
                    pixels = numpy.frombuffer(
                        vtflib.image_get_data(), dtype=numpy.uint8
                    )
                    pixels = pixels.astype(numpy.float16, copy=False)
                    pixels.shape = (-1, 4)
                    pixels[:, :3] = pixels[:, 2::-1] * (pixels[:, 3:] * (16 / 262144))
                    pixels[:, 3] = 1.0
                else:  # don't know what this is, just treat is as a normal texture
                    pixels = numpy.frombuffer(
                        vtflib.image_as_rgba8888(), dtype=numpy.uint8
                    )
                    pixels = pixels.astype(numpy.float16, copy=False)
                    pixels /= 255
                    hdr = False
            else:
                pixels = numpy.frombuffer(
                    vtflib.image_as_rgba8888(), dtype=numpy.uint8
                )
                pixels = pixels.astype(numpy.float16, copy=False)
                pixels /= 255
            pixels.shape = (height, width, 4)
            images.append(pixels)

    faces, (input_xs, input_ys) = find_corresponding_pixels(out_width, out_height, cubemap_dim)
    output_pixels = numpy.empty((out_height, out_width, 4), dtype=numpy.float16)
    for idx, img in enumerate(images):
        face_mask: numpy.ndarray = faces == idx
        output_pixels[face_mask] = bilinear_interpolate(img, input_xs[face_mask], input_ys[face_mask])
    output_pixels.shape = (-1,)

    image: bpy.types.Image = bpy.data.images.new(
        truncate_name(cubemap_name + (".exr" if hdr else ".png")), out_width, out_height, float_buffer=hdr
    )
    image.pixels = output_pixels
    if hdr:
        image.file_format = 'OPEN_EXR'
    else:
        image.file_format = 'PNG'
    image.pack()
    image.colorspace_settings.name = 'sRGB'
    return image
