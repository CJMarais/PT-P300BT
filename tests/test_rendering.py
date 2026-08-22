import unittest
import math
from pathlib import Path

from ptp300bt import LabelSpec, add_preview_guides, colorize_preview, render_label, valid_font_sizes


FONT = Path("C:/Windows/Fonts/arial.ttf")


@unittest.skipUnless(FONT.is_file(), "Arial is required for rendering tests")
class RenderLabelTests(unittest.TestCase):
    def test_builds_printer_ready_raster(self):
        result = render_label(LabelSpec(text="PATCH PANEL 2", font_path=str(FONT)))

        self.assertEqual(result.preview.height, 88)
        self.assertEqual(result.printer_image.width, 128)
        self.assertEqual(len(result.raster_data), result.printer_image.height * 16)
        self.assertGreater(result.font_size, 0)
        self.assertGreater(result.used_length_mm, result.printed_length_mm)

    def test_fixed_width_is_a_minimum(self):
        result = render_label(
            LabelSpec(text="A", font_path=str(FONT), fixed_width_mm=50)
        )

        self.assertGreaterEqual(result.printed_length_mm, 49.9)

    def test_rejects_empty_text(self):
        with self.assertRaisesRegex(ValueError, "label text"):
            render_label(LabelSpec(text="   ", font_path=str(FONT)))

    def test_guides_only_modify_a_preview_copy(self):
        result = render_label(LabelSpec(text="GUIDED", font_path=str(FONT)))
        original_bytes = result.preview.tobytes()

        guided = add_preview_guides(result.preview)

        self.assertEqual(guided.size, result.preview.size)
        self.assertEqual(result.preview.tobytes(), original_bytes)
        self.assertNotEqual(guided.tobytes(), original_bytes)
        self.assertNotEqual(guided.getpixel((0, 0)), result.preview.getpixel((0, 0)))

    def test_colorizes_preview_without_changing_print_raster(self):
        result = render_label(LabelSpec(text="BLUE", font_path=str(FONT)))
        raster = result.raster_data

        colored = colorize_preview(result.preview, "#ffffff", "#4c8fd5")

        self.assertEqual(colored.getpixel((0, 0)), (255, 255, 255))
        self.assertIn((76, 143, 213), {color for _count, color in colored.getcolors()})
        self.assertEqual(result.raster_data, raster)

    def test_guides_remain_visible_on_blue_tape(self):
        result = render_label(LabelSpec(text="GUIDED", font_path=str(FONT)))
        colored = colorize_preview(result.preview, "#2155a5", "#ffffff")

        guided = add_preview_guides(colored)

        self.assertNotEqual(guided.getpixel((0, 0)), colored.getpixel((0, 0)))

    def test_transparent_tape_uses_checkerboard_canvas(self):
        result = render_label(LabelSpec(text="CLEAR", font_path=str(FONT)))

        colored = colorize_preview(result.preview, "transparent", "#1a1a1a")

        colors = {color for _count, color in colored.getcolors(maxcolors=256)}
        self.assertIn((244, 244, 244), colors)
        self.assertIn((220, 220, 220), colors)
        self.assertIn((26, 26, 26), colors)

    def test_transparent_cleaning_ink_does_not_draw_label_text(self):
        result = render_label(LabelSpec(text="CLEAN", font_path=str(FONT)))

        colored = colorize_preview(result.preview, "#ffffff", "transparent")

        self.assertEqual(colored.getcolors(), [(colored.width * colored.height, (255, 255, 255))])

    def test_semitransparent_tape_is_composited_over_checkerboard(self):
        result = render_label(LabelSpec(text="MATTE", font_path=str(FONT)))

        colored = colorize_preview(
            result.preview, "rgba(245,245,245,0.4)", "#1a1a1a"
        )

        background_colors = {
            colored.getpixel((0, 0)),
            colored.getpixel((8, 0)),
        }
        self.assertEqual(background_colors, {(244, 244, 244), (230, 230, 230)})

    def test_valid_font_sizes_fit_current_text_layout(self):
        single_line = valid_font_sizes("LABEL", str(FONT))
        multiline = valid_font_sizes("LINE 1\\nLINE 2", str(FONT))

        self.assertTrue(single_line)
        self.assertTrue(multiline)
        self.assertLess(max(multiline), max(single_line))

    def test_renders_selected_valid_font_size(self):
        sizes = valid_font_sizes("LABEL", str(FONT))
        selected = sizes[len(sizes) // 2]

        result = render_label(LabelSpec(text="LABEL", font_path=str(FONT), font_size=selected))

        self.assertEqual(result.font_size, selected)

    def test_rejects_selected_font_size_that_does_not_fit(self):
        with self.assertRaisesRegex(ValueError, "printable height"):
            render_label(LabelSpec(text="LINE 1\\nLINE 2", font_path=str(FONT), font_size=256))

    def test_cable_label_duplicates_text_with_circumference_gap(self):
        standard = render_label(LabelSpec(text="CABLE 01", font_path=str(FONT)))
        cable = render_label(
            LabelSpec(
                text="CABLE 01",
                font_path=str(FONT),
                cable_diameter_mm=6,
                cable_buffer_mm=2,
            )
        )
        expected_gap_mm = math.pi * 6 + 4
        expected_gap_dots = round(expected_gap_mm / 0.149)

        self.assertEqual(cable.preview.width, standard.preview.width * 2 + expected_gap_dots)
        self.assertAlmostEqual(cable.cable_gap_mm, expected_gap_mm)
        self.assertEqual(
            cable.preview.crop((0, 0, standard.preview.width, 88)).tobytes(),
            standard.preview.tobytes(),
        )
        second_start = standard.preview.width + expected_gap_dots
        self.assertEqual(
            cable.preview.crop((second_start, 0, cable.preview.width, 88)).tobytes(),
            standard.preview.tobytes(),
        )

    def test_cable_label_marks_centre_of_wrap_gap(self):
        standard = render_label(LabelSpec(text="CABLE", font_path=str(FONT)))
        cable = render_label(
            LabelSpec(text="CABLE", font_path=str(FONT), cable_diameter_mm=5)
        )
        gap_dots = round(cable.cable_gap_mm / 0.149)
        centre_x = standard.preview.width + gap_dots // 2

        self.assertEqual(cable.preview.getpixel((centre_x, 12)), (0, 0, 0))
        self.assertEqual(cable.preview.getpixel((centre_x, 75)), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
