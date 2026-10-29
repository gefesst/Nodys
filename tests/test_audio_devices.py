import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))
from audio.devices import resolve_device


class DeviceSelectionTests(unittest.TestCase):
    def backend(self, rows):
        return SimpleNamespace(
            query_hostapis=lambda: [{"name": "Core Audio"}], query_devices=lambda: rows
        )

    def test_system_default_does_not_enumerate_hardware(self):
        self.assertIsNone(resolve_device(None, None, "input"))

    def test_saved_identity_survives_index_change(self):
        rows = [
            {
                "name": "Speaker",
                "hostapi": 0,
                "max_input_channels": 0,
                "max_output_channels": 2,
            },
            {
                "name": "Mic",
                "hostapi": 0,
                "max_input_channels": 1,
                "max_output_channels": 0,
            },
        ]
        selected = {"name": "Mic", "host": "Core Audio"}
        self.assertEqual(resolve_device(self.backend(rows), selected, "input"), 1)
        self.assertEqual(
            resolve_device(self.backend(list(reversed(rows))), selected, "input"), 0
        )

    def test_missing_ambiguous_and_wrong_direction_do_not_silently_select_another_device(
        self,
    ):
        row = {
            "name": "Mic",
            "hostapi": 0,
            "max_input_channels": 1,
            "max_output_channels": 0,
        }
        selected = {"name": "Mic", "host": "Core Audio"}
        for rows, direction in [
            ([], "input"),
            ([row, row], "input"),
            ([row], "output"),
        ]:
            with self.assertRaises(ValueError):
                resolve_device(self.backend(rows), selected, direction)
