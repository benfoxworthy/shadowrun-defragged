"""Tests for Genesis Game Genie code generation."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from patch_framework import (  # noqa: E402
    Edit,
    PreimageGuard,
    encode_game_genie_code,
    game_genie_codes_for_edits,
)


EMPTY_PREIMAGE = PreimageGuard(genesis_sum=0, crc32_influence=0)


class GameGenieTests(unittest.TestCase):
    def test_encoder_matches_known_shadowrun_codes(self) -> None:
        known_codes = (
            (0x055CEE, 0x4887, "T7RA-LT1R"),
            (0x055CF0, 0xBE46, "J3RA-M7ST"),
            (0x055CF2, 0x6A02, "AKRA-LY9W"),
            (0x055E62, 0x0829, "FFSA-LTDC"),
            (0x055E70, 0x2449, "KFSA-LJMT"),
            (0x022478, 0x6900, "AAWA-EW52"),
        )
        for address, value, expected in known_codes:
            with self.subTest(address=address, value=value):
                self.assertEqual(expected, encode_game_genie_code(address, value))

    def test_edit_plan_expands_each_big_endian_word(self) -> None:
        edits = (
            Edit(0x055CEE, EMPTY_PREIMAGE, bytes.fromhex("4887BE46"), "test"),
            Edit(0x055CF2, EMPTY_PREIMAGE, bytes.fromhex("6A02"), "test"),
        )
        self.assertEqual(
            ("T7RA-LT1R", "J3RA-M7ST", "AKRA-LY9W"),
            game_genie_codes_for_edits(edits),
        )

    def test_partial_word_edit_is_ineligible(self) -> None:
        for edit in (
            Edit(0x1001, EMPTY_PREIMAGE, b"\x12", "test"),
            Edit(0x1000, EMPTY_PREIMAGE, b"\x12", "test"),
        ):
            with self.subTest(edit=edit):
                self.assertIsNone(game_genie_codes_for_edits([edit]))

    def test_more_than_five_words_is_ineligible(self) -> None:
        edit = Edit(0x1000, EMPTY_PREIMAGE, bytes(12), "test")
        self.assertIsNone(game_genie_codes_for_edits([edit]))

    def test_encoder_rejects_invalid_words(self) -> None:
        for address, value in ((1, 0), (-2, 0), (0x1000000, 0), (0, -1), (0, 0x10000)):
            with self.subTest(address=address, value=value):
                with self.assertRaises(ValueError):
                    encode_game_genie_code(address, value)


if __name__ == "__main__":
    unittest.main()
