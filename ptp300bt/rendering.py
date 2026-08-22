from dataclasses import dataclass
import math
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import LabelSpec

PRINTABLE_HEIGHT = 64
TAPE_IMAGE_HEIGHT = 88
DOT_PITCH_MM = 0.149
LEADER_AND_FOOTER_MM = 26.0
MAX_USED_LENGTH_MM = 499.0
TAPE_HEIGHT = 86
TRANSPARENT_CANVAS = "#f4f4f4"
CHECKERBOARD_SECONDARY = "#dcdcdc"
CHECKER_SIZE = 8


@dataclass(frozen=True, slots=True)
class LabelRenderResult:
    preview: Image.Image
    printer_image: Image.Image
    raster_data: bytes
    font_size: int
    printed_length_mm: float
    used_length_mm: float
    cable_gap_mm: float | None = None


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    checkerboard = Image.new("RGB", size, TRANSPARENT_CANVAS)
    checker_draw = ImageDraw.Draw(checkerboard)
    for y in range(0, size[1], CHECKER_SIZE):
        for x in range(0, size[0], CHECKER_SIZE):
            if (x // CHECKER_SIZE + y // CHECKER_SIZE) % 2:
                checker_draw.rectangle(
                    (x, y, x + CHECKER_SIZE - 1, y + CHECKER_SIZE - 1),
                    fill=CHECKERBOARD_SECONDARY,
                )
    return checkerboard


def _preview_background(size: tuple[int, int], color: str) -> Image.Image:
    if color == "transparent":
        return _checkerboard(size)
    rgba = re.fullmatch(
        r"rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(0(?:\.\d+)?|1(?:\.0+)?)\s*\)",
        color,
        re.IGNORECASE,
    )
    if rgba:
        red, green, blue = (int(rgba.group(index)) for index in range(1, 4))
        alpha = round(float(rgba.group(4)) * 255)
        overlay = Image.new("RGBA", size, (red, green, blue, alpha))
        return Image.alpha_composite(_checkerboard(size).convert("RGBA"), overlay).convert("RGB")
    return Image.new("RGB", size, color)


def colorize_preview(image: Image.Image, background: str, foreground: str) -> Image.Image:
    """Apply cassette colours to a monochrome preview without changing print data."""
    background_image = _preview_background(image.size, background)
    if foreground == "transparent":
        return background_image
    ink = Image.new("RGB", image.size, foreground)
    ink_mask = ImageOps.invert(image.convert("L"))
    return Image.composite(ink, background_image, ink_mask)


def add_preview_guides(image: Image.Image) -> Image.Image:
    """Add the CLI's non-printing rulers and tape boundaries to a preview copy."""
    guided = image.convert("RGB").copy()
    draw = ImageDraw.Draw(guided)
    print_border = (TAPE_IMAGE_HEIGHT - PRINTABLE_HEIGHT) // 2

    draw.text((0, 1), "in", anchor="la", fill="magenta")
    x = -1.0
    index = 0
    while x < guided.width:
        if x > 0:
            draw.line(
                (int(x), print_border - (4 if index % 4 else 9), int(x), print_border - 2),
                fill="magenta",
                width=2,
            )
        x += 43.18
        index += 1

    draw.text((0, TAPE_IMAGE_HEIGHT - 12), "cm", anchor="la", fill="magenta")
    x = -1.0
    index = 0
    while x < guided.width:
        if x > 0:
            draw.line(
                (
                    int(x),
                    TAPE_IMAGE_HEIGHT - print_border + 1,
                    int(x),
                    TAPE_IMAGE_HEIGHT - print_border + (5 if index % 10 else 9),
                ),
                fill="magenta",
                width=2,
            )
        x += 68
        index += 1

    for x in range(0, guided.width, 5):
        draw.line((x, print_border - 1, x + 1, print_border - 1), fill="red")
        draw.line(
            (x, TAPE_IMAGE_HEIGHT - print_border, x + 1, TAPE_IMAGE_HEIGHT - print_border),
            fill="red",
        )

    tape_border = (TAPE_IMAGE_HEIGHT - TAPE_HEIGHT) // 2
    if tape_border > 0:
        draw.line((0, tape_border - 1, guided.width, tape_border - 1), fill="cyan")
        draw.line(
            (0, TAPE_IMAGE_HEIGHT - tape_border, guided.width, TAPE_IMAGE_HEIGHT - tape_border),
            fill="cyan",
        )
    return guided


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


def valid_font_sizes(text: str, font_path: str, spacing: float = 1.2) -> list[int]:
    """Return font sizes whose rendered text fits the printable tape height."""
    if not Path(font_path).is_file() or not text.strip():
        return []
    lines = text.replace("\\n", "\n").splitlines() or [text]
    sizes: list[int] = []
    for size in range(1, 257):
        font = ImageFont.truetype(font_path, size, encoding="utf-8")
        if _measure(lines, font, spacing)[1] > PRINTABLE_HEIGHT:
            break
        sizes.append(size)
    return sizes


def render_label(spec: LabelSpec) -> LabelRenderResult:
    """Render a preview and the exact 1-bit raster expected by the printer."""
    spec.validate()
    lines = spec.text.replace("\\n", "\n").splitlines() or [spec.text]
    if spec.font_size is None:
        font, font_size, (text_width, text_height, line_height) = _fit_font(
            lines, spec.font_path, spec.line_spacing
        )
    else:
        if not Path(spec.font_path).is_file():
            raise ValueError(f'Font file not found: "{spec.font_path}"')
        font_size = spec.font_size
        font = ImageFont.truetype(spec.font_path, font_size, encoding="utf-8")
        text_width, text_height, line_height = _measure(lines, font, spec.line_spacing)
        if text_height > PRINTABLE_HEIGHT:
            raise ValueError(
                f"Font size {font_size} exceeds the {PRINTABLE_HEIGHT}-dot printable height."
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

    cable_gap_mm = None
    if spec.cable_diameter_mm is not None:
        label_panel = preview
        circumference_mm = math.pi * spec.cable_diameter_mm
        cable_gap_mm = circumference_mm + spec.cable_buffer_mm * 2
        gap_dots = max(1, round(cable_gap_mm / DOT_PITCH_MM))
        preview = Image.new(
            "RGB",
            (label_panel.width * 2 + gap_dots, TAPE_IMAGE_HEIGHT),
            "white",
        )
        preview.paste(label_panel, (0, 0))
        preview.paste(label_panel, (label_panel.width + gap_dots, 0))

        # Small printed ticks mark the centre of the cable wrap without drawing
        # through the label's main printable area.
        centre_x = label_panel.width + gap_dots // 2
        guide_draw = ImageDraw.Draw(preview)
        print_top = (TAPE_IMAGE_HEIGHT - PRINTABLE_HEIGHT) // 2
        print_bottom = TAPE_IMAGE_HEIGHT - print_top
        guide_draw.line((centre_x, print_top, centre_x, print_top + 6), fill="black")
        guide_draw.line((centre_x, print_bottom - 6, centre_x, print_bottom), fill="black")

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
        cable_gap_mm=cable_gap_mm,
    )
