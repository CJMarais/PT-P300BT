import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import io

from labelmaker import printer_not_ready_message
from ptp300bt.printer import PrinterOptions, print_raster, query_printer_status


class PrintRasterTests(unittest.TestCase):
    @patch("ptp300bt.printer.reset_printer")
    @patch("ptp300bt.printer.query_status_register")
    @patch("ptp300bt.printer.serial.Serial")
    def test_queries_status_through_the_requested_output_stream(
        self, serial_factory, query_status_register, reset_printer
    ):
        connection = Mock()
        serial_factory.return_value = connection
        output = io.StringIO()
        query_status_register.return_value = SimpleNamespace(tape_bgcolor=0x01, tape_fgcolor=0x62)

        colors = query_printer_status("COM4", output)

        query_status_register.assert_called_once_with(connection, output=output)
        reset_printer.assert_called_once_with(connection)
        connection.close.assert_called_once_with()
        self.assertEqual(colors.background_hex, "#ffffff")
        self.assertEqual(colors.foreground_hex, "#0033a0")
        self.assertEqual(colors.foreground_name, "Blue (F)")

    def test_maps_clear_tape_to_a_transparent_preview(self):
        from ptp300bt.printer import tape_colors_from_status

        colors = tape_colors_from_status(
            SimpleNamespace(tape_bgcolor=0x03, tape_fgcolor=0x08)
        )

        self.assertEqual(colors.background_hex, "transparent")
        self.assertEqual(colors.foreground_hex, "#1a1a1a")

    def test_maps_special_foreground_status_codes(self):
        from ptp300bt.printer import tape_colors_from_status

        expected = {
            0x02: "#808080",
            0x62: "#0033a0",
            0xF0: "transparent",
            0xF1: "#3f51b5",
            0xFF: "#ff00ff",
        }

        for code, hex_color in expected.items():
            with self.subTest(code=code):
                colors = tape_colors_from_status(
                    SimpleNamespace(tape_bgcolor=0x01, tape_fgcolor=code)
                )
                self.assertEqual(colors.foreground_hex, hex_color)

    def test_maps_special_background_status_codes(self):
        from ptp300bt.printer import tape_colors_from_status

        expected = {
            0x02: "#808080",
            0x21: "rgba(245,245,245,0.4)",
            0x23: "#d4af37",
            0x30: "#0d47a1",
            0x50: "#e0115f",
            0x62: "#b3e5fc",
            0xF0: "transparent",
            0xF1: "rgba(63,81,181,0.6)",
            0xFF: "#ff00ff",
        }

        for code, hex_color in expected.items():
            with self.subTest(code=code):
                colors = tape_colors_from_status(
                    SimpleNamespace(tape_bgcolor=code, tape_fgcolor=0x08)
                )
                self.assertEqual(colors.background_hex, hex_color)

    @patch("ptp300bt.printer.reset_printer")
    @patch("ptp300bt.printer.do_print_job", side_effect=SystemExit("Load a tape cassette."))
    @patch("ptp300bt.printer.serial.Serial")
    def test_converts_command_line_exit_to_recoverable_error(
        self, serial_factory, do_print_job, reset_printer
    ):
        connection = Mock()
        serial_factory.return_value = connection
        output = io.StringIO()

        with self.assertRaisesRegex(RuntimeError, "Load a tape cassette"):
            print_raster("COM4", b"raster", PrinterOptions(), output)

        self.assertIs(do_print_job.call_args.kwargs["output"], output)
        reset_printer.assert_called_once_with(connection)
        connection.close.assert_called_once_with()

    def test_reports_all_active_printer_errors(self):
        status = SimpleNamespace(err=(1 << 4) | (1 << 11), phase_type=0, phase=0)

        message = printer_not_ready_message(status)

        self.assertIn("Close the tape cassette cover", message)
        self.assertIn("battery is low", message)

    def test_reports_known_non_ready_phase_without_error_flags(self):
        status = SimpleNamespace(err=0, phase_type=1, phase=0)

        self.assertIn("printing phase", printer_not_ready_message(status))


if __name__ == "__main__":
    unittest.main()
