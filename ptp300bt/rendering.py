from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import LabelSpec

PRINTABLE_HEIGHT = 64
TAPE_IMAGE_HEIGHT = 88
DOT_PITCH_MM = 0.149
LEADER_AND_FOOTER_MM = 26.0
MAX_USED_LENGTH_MM = 499.0


@dataclass(frozen=True, slots=True)
class LabelRenderResult:
    preview: Image.Image
    printer_image: Image.Image
    raster_data: bytes
    font_size: int
    printed_length_mm: float
    used_length_mm: float


def _measure(lines: list[str], font: ImageFont.FreeTypeFont, spacing: float) -> tuple[int, int, int]:
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    boxes = [probe.textbbox((0, 0), line or " ", font=font, anchor="lt") for line in lines]
    widths = [box[2] - box[0] for box in boxes]
    heights = [box[3] - box[1] for box in boxes]
    line_height = max(heights)
    total_height = line_height if len(lines) == 1 else line_height + round(line_height * spacing) * (len(lines) - 1)
    return max(widths), total_height, line_height


def _fit_font(lines: list[str], font_path: str, spacing: float) -> tuple[ImageFont.FreeTypeFont, int, tuple[int, int, int]]:
    if not Path(font_path).is_file():
        raise ValueError(f'Font file not found: "{font_path}"')
    best = None
    for size in range(1, 257):
        font = ImageFont.truetype(font_path, size, encoding="utf-8")
        dimensions = _measure(lines, font, spacing)
        if dimensions[1] > PRINTABLE_HEIGHT:
            break
        best = font, size, dimensions
    if best is None:
        raise ValueError("The text cannot fit in the printable area.")
    return best


def render_label(spec: LabelSpec) -> LabelRenderResult:
    """Render a preview and the exact 1-bit raster expected by the printer."""
    spec.validate()
    lines = spec.text.replace("\\n", "\n").splitlines() or [spec.text]
    font, font_size, (text_width, text_height, line_height) = _fit_font(
        lines, spec.font_path, spec.line_spacing
    )

    natural_width = text_width + spec.horizontal_padding * 2 + spec.end_margin + 1
    if spec.fixed_width_mm is None:
        width = natural_width
    else:
        width = max(natural_width, round(spec.fixed_width_mm / DOT_PITCH_MM))

    preview = Image.new("RGB", (width, TAPE_IMAGE_HEIGHT), "white")
    draw = ImageDraw.Draw(preview)
    y = (TAPE_IMAGE_HEIGHT - text_height) // 2 + spec.vertical_shift
    line_step = round(line_height * spec.line_spacing)

    for index, line in enumerate(lines):
        line_box = draw.textbbox((0, 0), line or " ", font=font, anchor="lt")
        line_width = line_box[2] - line_box[0]
        if spec.alignment == "center":
            x = (width - spec.end_margin - line_width) // 2
        elif spec.alignment == "right":
            x = width - spec.horizontal_padding - spec.end_margin - line_width
        else:
            x = spec.horizontal_padding
        draw.text((x, y + index * line_step), line, font=font, fill="black", anchor="lt")

    rotated = ImageOps.mirror(
        ImageOps.invert(
            preview.convert("L", dither=Image.Dither.FLOYDSTEINBERG).rotate(
                -90, expand=True, resample=Image.Resampling.BICUBIC
            )
        )
    )
    binary = rotated.point(lambda pixel: 255 if pixel > spec.threshold else 0).convert("1")
    printer_image = Image.new("1", (128, binary.height))
    printer_image.paste(binary, ((128 - binary.width) // 2, 0))

    printed_length = printer_image.height * DOT_PITCH_MM
    used_length = printed_length + LEADER_AND_FOOTER_MM
    if used_length > MAX_USED_LENGTH_MM:
        raise ValueError("The label exceeds the printer's maximum 499 mm tape length.")

    return LabelRenderResult(
        preview=preview,
        printer_image=printer_image,
        raster_data=printer_image.tobytes(),
        font_size=font_size,
        printed_length_mm=printed_length,
        used_length_mm=used_length,
    )
