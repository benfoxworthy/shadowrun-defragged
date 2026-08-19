"""Tests for the emulator save-state diagnostics inspector."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TOOL_PATH = ROOT / "tools" / "inspect_save_state.py"
SPEC = importlib.util.spec_from_file_location("inspect_save_state", TOOL_PATH)
assert SPEC and SPEC.loader
decoder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = decoder
SPEC.loader.exec_module(decoder)

from patches import defragged_diagnostics as producer  # noqa: E402


class SaveStateInspectorTests(unittest.TestCase):
    def test_decoder_layout_matches_diagnostics_patch(self) -> None:
        self.assertEqual(producer.STAMP_START & 0xFFFF, decoder.STAMP_OFFSET)
        self.assertEqual(producer.STAMP_SIZE, decoder.STAMP_SIZE)
        self.assertTrue(producer.STAMP_TEMPLATE_PREFIX.startswith(decoder.STAMP_PREFIX))
        self.assertEqual(producer.LOG_HEADER & 0xFFFF, decoder.HEADER_OFFSET)
        self.assertEqual(
            producer.LOG_RECORDS - producer.LOG_HEADER,
            decoder.HEADER_SIZE,
        )
        self.assertEqual(
            producer.LOG_NEXT_INDEX & 0xFFFF,
            decoder.NEXT_INDEX_OFFSET,
        )
        self.assertEqual(
            producer.LOG_VALID_COUNT & 0xFFFF,
            decoder.VALID_COUNT_OFFSET,
        )
        self.assertEqual(
            producer.LOG_FORMAT_AND_SIZE & 0xFFFF,
            decoder.FORMAT_VERSION_OFFSET,
        )
        self.assertEqual(
            (producer.LOG_FORMAT_AND_SIZE + 1) & 0xFFFF,
            decoder.RECORD_SIZE_OFFSET,
        )
        self.assertEqual(
            producer.LOG_PATCH_CRC & 0xFFFF,
            decoder.PATCH_CRC_OFFSET,
        )
        self.assertEqual(
            producer.LOG_ROM_CHECKSUM & 0xFFFF,
            decoder.ROM_CHECKSUM_OFFSET,
        )
        self.assertEqual(producer.LOG_RECORDS & 0xFFFF, decoder.RECORDS_OFFSET)
        self.assertEqual(producer.LOG_RECORD_SIZE, decoder.RECORD_SIZE)
        self.assertEqual(producer.LOG_RECORD_COUNT, decoder.RECORD_COUNT)
        self.assertEqual(producer.LOG_FORMAT_VERSION, decoder.FORMAT_VERSION)

    def test_decodes_wrapped_records_in_chronological_order(self) -> None:
        prefix_size = 0x123
        state = bytearray(prefix_size + decoder.WORK_RAM_SIZE + 0x45)
        ram = memoryview(state)[prefix_size : prefix_size + decoder.WORK_RAM_SIZE]
        ram[
            decoder.STAMP_OFFSET : decoder.STAMP_OFFSET + decoder.STAMP_SIZE
        ] = b"Defragged 1234-ABCD\x00"
        ram[decoder.HEADER_OFFSET : decoder.HEADER_OFFSET + 8] = bytes.fromhex(
            "02360108ABCD1234"
        )
        for slot in range(decoder.RECORD_COUNT):
            offset = decoder.RECORDS_OFFSET + slot * decoder.RECORD_SIZE
            caller = 0x00055B40 if slot == 2 else 0x00055000 + slot
            ram[offset : offset + decoder.RECORD_SIZE] = (
                caller.to_bytes(4, "big")
                + bytes((slot, 9, 4, slot))
            )

        diagnostics = decoder.decode_state(bytes(state))

        self.assertEqual("Defragged 1234-ABCD", diagnostics.stamp)
        self.assertEqual(0xABCD, diagnostics.patch_crc)
        self.assertEqual(
            [*range(2, decoder.RECORD_COUNT), 0, 1],
            [record.slot for record in diagnostics.records],
        )
        self.assertEqual(0x00055B40, diagnostics.records[0].caller)
        self.assertEqual(0x00055001, diagnostics.records[-1].caller)
        self.assertIn("Hell Hound direct attack", decoder.render(diagnostics))

    def test_rejects_state_without_stamp(self) -> None:
        state = bytearray(0x321 + decoder.WORK_RAM_SIZE)
        with self.assertRaisesRegex(ValueError, "no Defragged"):
            decoder.decode_state(bytes(state))


if __name__ == "__main__":
    unittest.main()
