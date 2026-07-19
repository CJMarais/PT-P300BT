import unittest

from ptp300bt.printer import bluetooth_address_from_hwid, _decode_bluetooth_name


class BluetoothPortMetadataTests(unittest.TestCase):
    def test_extracts_outgoing_device_address(self):
        hwid = (
            r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_VID&00020430_PID&0211"
            r"\7&28E98569&1&986EE847BEE9_C00000000"
        )
        self.assertEqual(bluetooth_address_from_hwid(hwid), "986EE847BEE9")

    def test_does_not_assign_remote_device_to_incoming_port(self):
        hwid = (
            r"BTHENUM\{00001101-0000-1000-8000-00805F9B34FB}_LOCALMFG&0000"
            r"\7&28E98569&1&000000000000_00000000"
        )
        self.assertIsNone(bluetooth_address_from_hwid(hwid))

    def test_decodes_windows_registry_name(self):
        self.assertEqual(_decode_bluetooth_name(b"PT-P300BT3490\x00"), "PT-P300BT3490")


if __name__ == "__main__":
    unittest.main()
