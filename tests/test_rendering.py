import unittest
from pathlib import Path

from ptp300bt import LabelSpec, render_label


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


if __name__ == "__main__":
    unittest.main()
