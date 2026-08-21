import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from labelmaker import printer_not_ready_message
from ptp300bt.printer import PrinterOptions, print_raster


class PrintRasterTests(unittest.TestCase):
    @patch("ptp300bt.printer.reset_printer")
    @patch("ptp300bt.printer.do_print_job", side_effect=SystemExit("Load a tape cassette."))
    @patch("ptp300bt.printer.serial.Serial")
    def test_converts_command_line_exit_to_recoverable_error(
        self, serial_factory, _do_print_job, reset_printer
    ):
        connection = Mock()
        serial_factory.return_value = connection

        with self.assertRaisesRegex(RuntimeError, "Load a tape cassette"):
            print_raster("COM4", b"raster", PrinterOptions())

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
