"""Tests for the ROM-optional Shadowrun Defragged builder."""

from __future__ import annotations

import binascii
import contextlib
import importlib.util
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BUILDER_PATH = ROOT / "build_shadowrun_defragged.py"
SPEC = importlib.util.spec_from_file_location(
    "build_shadowrun_defragged", BUILDER_PATH
)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = builder
SPEC.loader.exec_module(builder)

from patch_framework import (  # noqa: E402
    Address,
    Edit,
    PatchBuilder,
    PatchSpec,
    PreimageGuard,
)
from patches import defragged_diagnostics as diagnostics  # noqa: E402
from patches import firearm_zero_success_miss  # noqa: E402
from patches import gas_vent_balance  # noqa: E402


PRIVATE_SOURCE_ROM = ROOT / "roms" / "Shadowrun (USA).gen"
MANIFEST_PATHS = tuple(sorted(ROOT.glob("manifest_*.json")))


def manifest_patch_blocks(path: Path) -> list[list[str]]:
    """Return patch-ID blocks separated by blank lines in a manifest."""

    patch_lines = path.read_text(encoding="utf-8").split('"patches": [', 1)[1]
    patch_lines = patch_lines.split("\n  ]", 1)[0]
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in patch_lines.splitlines():
        match = re.fullmatch(r'\s*"([^"]+)",?\s*', line)
        if match:
            current.append(match.group(1))
        elif not line.strip() and current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


class ShadowrunDefraggedBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = builder.load_patch_catalog()
        cls.core_manifest = builder.load_manifest(
            ROOT / "manifest_core.json", cls.catalog
        )
        cls.full_manifest = builder.load_manifest(
            ROOT / "manifest_full.json", cls.catalog
        )
        cls.core = cls.core_manifest.patches
        cls.full = cls.full_manifest.patches

    def test_catalog_contains_one_authoritative_module_per_patch(self) -> None:
        for patch_id, patch in self.catalog.items():
            self.assertEqual(patch_id, patch.id)
            self.assertTrue(patch.description)
            self.assertTrue(callable(patch.build_patch))
            self.assertTrue(
                (ROOT / "patches" / f"{patch_id.replace('-', '_')}.py").is_file()
            )

    def test_every_patch_supplies_inline_preimage_guards(self) -> None:
        for patch_id, patch in self.catalog.items():
            selected = [*patch.requires, patch_id]
            builder.selected_edits(self.catalog, selected)

    def test_code_cave_helpers_cannot_call_shared_dice_test(self) -> None:
        class DiceCallerPatch(PatchSpec):
            id = "dice-caller"
            description = "Test cave dice-call validation"

            def __init__(self, instruction: bytes) -> None:
                self.instruction = instruction

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                patch_builder.add_cave(self.instruction)

        for instruction in (
            bytes.fromhex("4EB80DBA"),
            bytes.fromhex("4EB900000DBA"),
        ):
            patch = DiceCallerPatch(instruction)
            with self.subTest(instruction=instruction.hex()):
                with self.assertRaisesRegex(
                    builder.PatchBuildError,
                    "preserve the original diagnostic caller",
                ):
                    builder.selected_edits({patch.id: patch}, [patch.id])

        tail_jump = DiceCallerPatch(bytes.fromhex("4EF900000DBA"))
        builder.selected_edits({tail_jump.id: tail_jump}, [tail_jump.id])

    def test_defragged_diagnostics_finalizes_build_stamp_and_hooks(self) -> None:
        class LeadingAllocationPatch(PatchSpec):
            id = "leading-allocation-fixture"
            description = "Place diagnostics later in the shared cave"

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                patch_builder.add_cave(b"fixture")

        leading = LeadingAllocationPatch()
        catalog = {**self.catalog, leading.id: leading}
        edits, allocations = builder.selected_edits(
            catalog,
            [leading.id, "defragged-diagnostics"],
        )
        diagnostic_allocations = [
            item for item in allocations
            if item.patch_id == "defragged-diagnostics"
        ]
        cave_edit = next(
            edit for edit in edits if edit.patch_id == "code-cave"
        )
        stamp_offset = cave_edit.payload.index(diagnostics.STAMP_TEMPLATE_PREFIX)
        stamp_address = cave_edit.offset + stamp_offset
        stamp_payload = cave_edit.payload[
            stamp_offset : stamp_offset + diagnostics.STAMP_SIZE + 2
        ]
        self.assertTrue(
            any(
                item.address <= stamp_address
                and stamp_address + len(stamp_payload) <= item.address + item.size
                for item in diagnostic_allocations
            )
        )
        self.assertRegex(
            stamp_payload[: diagnostics.STAMP_SIZE],
            rb"\ADefragged 0000-[0-9A-F]{4}\x00\Z",
        )
        crc_start = diagnostics.STAMP_PATCH_CRC_OFFSET
        crc_end = crc_start + 4
        embedded_crc = int(stamp_payload[crc_start:crc_end], 16)
        self.assertEqual(
            embedded_crc,
            int.from_bytes(
                stamp_payload[
                    diagnostics.TEMPLATE_BINARY_CRC_OFFSET :
                    diagnostics.TEMPLATE_BINARY_CRC_OFFSET + 2
                ],
                "big",
            ),
        )

        normalized_edits: list[tuple[int, bytes]] = []
        for edit in edits:
            payload = bytearray(edit.payload)
            if edit is cave_edit:
                field = (
                    stamp_address
                    + diagnostics.STAMP_PATCH_CRC_OFFSET
                    - cave_edit.offset
                )
                payload[field : field + 4] = b"0000"
                binary_field = (
                    stamp_address
                    + diagnostics.TEMPLATE_BINARY_CRC_OFFSET
                    - cave_edit.offset
                )
                payload[binary_field : binary_field + 2] = b"\x00\x00"
            normalized_edits.append((edit.offset, bytes(payload)))
        crc = binascii.crc_hqx(
            b"Shadowrun Defragged patch edits v1\x00", 0xFFFF
        )
        for offset, payload in sorted(normalized_edits):
            crc = binascii.crc_hqx(offset.to_bytes(4, "big"), crc)
            crc = binascii.crc_hqx(len(payload).to_bytes(4, "big"), crc)
            crc = binascii.crc_hqx(payload, crc)
        self.assertEqual(crc, embedded_crc)

        payloads = {edit.offset: edit.payload for edit in edits}
        for hook_offset, opcode in (
            (diagnostics.VBLANK_UPDATE_CALL, bytes.fromhex("4EB9")),
            (diagnostics.ROLL_DICE_POOL_SUCCESS_TEST, bytes.fromhex("4EF9")),
        ):
            hook = payloads[hook_offset]
            self.assertEqual(opcode, hook[:2])
            target = int.from_bytes(hook[2:], "big")
            self.assertIn(target, {item.address for item in diagnostic_allocations})
        self.assertEqual(
            diagnostics.LOG_END - diagnostics.LOG_RECORDS,
            diagnostics.LOG_RECORD_COUNT * diagnostics.LOG_RECORD_SIZE,
        )

    def test_defragged_diagnostics_crc_changes_with_patch_contents(self) -> None:
        def embedded_crc(selected: list[str]) -> bytes:
            edits, _ = builder.selected_edits(self.catalog, selected)
            cave = next(
                edit.payload
                for edit in edits
                if edit.patch_id == "code-cave"
            )
            start = cave.index(diagnostics.STAMP_TEMPLATE_PREFIX)
            crc_start = start + diagnostics.STAMP_PATCH_CRC_OFFSET
            return cave[crc_start : crc_start + 4]

        baseline = embedded_crc(["defragged-diagnostics"])
        changed = embedded_crc(
            ["defragged-diagnostics", "caster-item-slot-8-fix"]
        )
        self.assertNotEqual(baseline, changed)

    def test_defragged_diagnostics_inline_branches_land_on_labels(self) -> None:
        def word_target(payload: bytes, branch: int) -> int:
            displacement = int.from_bytes(
                payload[branch + 2 : branch + 4], "big", signed=True
            )
            return branch + 2 + displacement

        def short_target(payload: bytes, branch: int) -> int:
            displacement = int.from_bytes(
                payload[branch + 1 : branch + 2], "big", signed=True
            )
            return branch + 2 + displacement

        stamp = diagnostics._stamp_writer(builder.CODE_CAVE_START)
        copy = stamp.index(bytes.fromhex("20D9"))
        copy_dbf = stamp.index(bytes.fromhex("51C9FFFC"))
        digit = stamp.index(bytes.fromhex("3400"))
        decimal = stamp.index(bytes.fromhex("06020030"))
        self.assertEqual(copy, word_target(stamp, copy_dbf))
        self.assertEqual(
            decimal,
            short_target(stamp, stamp.index(bytes.fromhex("6304"))),
        )
        self.assertEqual(
            digit,
            word_target(stamp, stamp.index(bytes.fromhex("51C9FFE6"))),
        )

        dice_entry = diagnostics._dice_entry_logger(
            builder.CODE_CAVE_START,
            builder.CODE_CAVE_START + 0x80,
        )
        initialize_header = dice_entry.index(bytes.fromhex("4279"))
        header_ready = dice_entry.index(bytes.fromhex("7000"))
        self.assertEqual(
            initialize_header,
            short_target(dice_entry, dice_entry.index(bytes.fromhex("6612"))),
        )
        self.assertEqual(
            initialize_header,
            short_target(dice_entry, dice_entry.index(bytes.fromhex("660A"))),
        )
        self.assertEqual(
            header_ready,
            short_target(dice_entry, dice_entry.index(bytes.fromhex("671A"))),
        )
        first_fits = dice_entry.index(bytes.fromhex("10C0"))
        first_bls = dice_entry.index(bytes.fromhex("6302"))
        second_bls = dice_entry.index(bytes.fromhex("6302"), first_bls + 2)
        second_fits = dice_entry.index(bytes.fromhex("10C0"), first_fits + 2)
        self.assertEqual(first_fits, short_target(dice_entry, first_bls))
        self.assertEqual(second_fits, short_target(dice_entry, second_bls))

        dice_post = diagnostics._dice_post_logger()
        self.assertEqual(
            dice_post.index(bytes.fromhex("13C0")),
            short_target(dice_post, dice_post.index(bytes.fromhex("6502"))),
        )
        self.assertEqual(
            dice_post.index(bytes.fromhex("201F")),
            short_target(dice_post, dice_post.index(bytes.fromhex("6406"))),
        )

    def test_defragged_diagnostics_trampolines_through_stock_dice_body(self) -> None:
        post_logger = builder.CODE_CAVE_START + 0x80
        entry = diagnostics._dice_entry_logger(
            builder.CODE_CAVE_START,
            post_logger,
        )
        self.assertEqual(
            bytes.fromhex(f"4879{post_logger:08X}48E7F800"),
            entry[4:14],
        )
        self.assertTrue(
            entry.endswith(
                bytes.fromhex(f"53464EF9{diagnostics.STOCK_DICE_CONTINUE:08X}")
            )
        )
        self.assertNotIn(bytes.fromhex("4EB900000D3A"), entry)
        self.assertNotIn(bytes.fromhex("4EB900000D3A"), diagnostics._dice_post_logger())

    def test_corp_terminal_helper_loops_over_three_party_slots(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["corp-terminal-computer-skill-fix"]
        )
        helper = allocations[0]
        cave = next(edit.payload for edit in edits if edit.patch_id == "code-cave")
        start = helper.address - builder.CODE_CAVE_START
        payload = cave[start : start + helper.size]
        self.assertEqual(bytes.fromhex("51CFFFE8"), payload[30:34])
        displacement = int.from_bytes(payload[32:34], "big", signed=True)
        self.assertEqual(helper.address + 8, helper.address + 32 + displacement)

    def test_cyberdeck_storage_purchase_and_tooltip_share_calculator(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["cyberdeck-storage-upgrades"]
        )
        payloads = {edit.offset: edit.payload for edit in edits}
        cave = next(edit.payload for edit in edits if edit.patch_id == "code-cave")
        calculator = allocations[0]
        start = calculator.address - builder.CODE_CAVE_START
        calculator_payload = cave[start : start + calculator.size]
        calculator_call = bytes.fromhex(f"4EB9{calculator.address:08X}")

        self.assertEqual(bytes.fromhex("B0434E75"), calculator_payload[-4:])
        purchase_hook = payloads[0x0576AE]
        self.assertEqual(calculator_call + bytes.fromhex("6E5C"), purchase_hook)
        purchase_branch_target = 0x0576B6 + int.from_bytes(
            purchase_hook[-1:], "big", signed=True
        )
        self.assertEqual(0x057712, purchase_branch_target)
        renderer = allocations[1]
        start = renderer.address - builder.CODE_CAVE_START
        renderer_payload = cave[start : start + renderer.size]
        self.assertIn(calculator_call, renderer_payload)
        self.assertNotIn(bytes.fromhex("2EBC00057712"), cave)

    def test_cyberdeck_storage_tooltip_uses_dynamic_step_and_price(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["cyberdeck-storage-upgrades"]
        )
        payloads = {edit.offset: edit.payload for edit in edits}
        cave = next(edit.payload for edit in edits if edit.patch_id == "code-cave")

        def allocation_payload(address: int) -> bytes:
            allocation = next(item for item in allocations if item.address == address)
            start = allocation.address - builder.CODE_CAVE_START
            return cave[start : start + allocation.size]

        self.assertNotIn(0x1AC8A0, payloads)
        self.assertEqual(
            b"\xFFCost is \x8050 Mp \xFF$ for the next\xFF" + b"\xFF" * 3,
            payloads[0x1AB61D],
        )
        self.assertNotIn(b"  ", payloads[0x1AB61D])

        hook = payloads[0x058348]
        self.assertEqual(bytes.fromhex("4EB9"), hook[:2])
        renderer = allocation_payload(int.from_bytes(hook[2:], "big"))
        self.assertTrue(renderer.startswith(bytes.fromhex("48E7F0F040E7")))
        self.assertTrue(renderer.endswith(bytes.fromhex("46DF4CDF0F0F4E75")))
        self.assertIn(bytes.fromhex("0C39000100FFF0D0"), renderer)
        self.assertIn(bytes.fromhex("4EB90000C216"), renderer)
        self.assertIn(bytes.fromhex("0C4303E86502588A"), renderer)
        self.assertIn(bytes.fromhex("43F9001AB61E"), renderer)
        self.assertIn(bytes.fromhex("43F9001AB62E"), renderer)
        self.assertIn(bytes.fromhex("43F9001AB5B1"), renderer)
        self.assertIn(bytes.fromhex("43F9001AA50E"), renderer)
        self.assertIn(bytes.fromhex("247C0000C606"), renderer)
        self.assertIn(bytes.fromhex("247C0000C61A"), renderer)
        self.assertIn(bytes.fromhex("247C0000C692"), renderer)

        maximum_branch = renderer.index(bytes.fromhex("6F4C"))
        maximum_target = maximum_branch + 2 + int.from_bytes(
            renderer[maximum_branch + 1 : maximum_branch + 2], "big", signed=True
        )
        self.assertEqual(
            bytes.fromhex("43F9001AA50E"),
            renderer[maximum_target : maximum_target + 6],
        )
        done_branch = renderer.index(bytes.fromhex("6012"))
        done_target = done_branch + 2 + int.from_bytes(
            renderer[done_branch + 1 : done_branch + 2], "big", signed=True
        )
        self.assertEqual(
            bytes.fromhex("46DF4CDF0F0F4E75"), renderer[done_target:]
        )

        patch_cave = b"".join(
            allocation_payload(allocation.address) for allocation in allocations
        )
        self.assertNotIn(b"This 25 Mp increase", patch_cave)
        self.assertNotIn(b"This 50 Mp increase", patch_cave)

    def test_cyberdeck_storage_cost_sentence_fits_with_every_price(self) -> None:
        first_lines = []
        for rank in range(24):
            price = 200 + 150 * rank
            rendered_price = f"{price:,}"
            first_line = f"Cost is {rendered_price}¥ for the next"
            first_lines.append(first_line)
            self.assertNotIn("  ", first_line)
            self.assertLessEqual(len(first_line), 27)
        self.assertEqual("Cost is 950¥ for the next", first_lines[5])
        self.assertEqual("Cost is 1,100¥ for the next", first_lines[6])

    def test_spell_effect_slot_leak_fix_repairs_compact_ownership_paths(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["spell-effect-slot-leak-fix"]
        )
        payloads = {edit.offset: edit.payload for edit in edits}
        fixed_hooks = [
            edit for edit in edits if edit.offset != builder.CODE_CAVE_START
        ]
        (
            cleanup_orphaned_aoe_state,
            release_existing_target_effect,
            targeted_guard,
            attach_effect_to_selected_target,
            finish_spell_effect_on_target,
            chain_aoe_to_next_target,
            deallocator,
        ) = allocations
        cave = payloads[builder.CODE_CAVE_START]

        def allocation_payload(allocation):
            start = allocation.address - builder.CODE_CAVE_START
            return cave[start : start + allocation.size]

        self.assertEqual(
            [114, 58, 94, 24, 132, 24, 26],
            [allocation.size for allocation in allocations],
        )
        self.assertEqual(472, sum(allocation.size for allocation in allocations))
        self.assertEqual(12, len(fixed_hooks))
        self.assertEqual(118, sum(len(edit.payload) for edit in fixed_hooks))

        def word_branch_target(payload, offset):
            displacement = int.from_bytes(
                payload[offset + 2 : offset + 4], "big", signed=True
            )
            return offset + 2 + displacement

        cleanup_payload = allocation_payload(cleanup_orphaned_aoe_state)
        self.assertEqual(
            [112, 38, 108, 20, 68, 94, 100, 100, 56],
            [
                word_branch_target(cleanup_payload, offset)
                for offset in (2, 24, 34, 42, 60, 72, 80, 90, 104)
            ],
        )
        self.assertEqual(2, cleanup_payload.count(bytes.fromhex("43F900FF0100")))
        self.assertIn(bytes.fromhex("B02900B2"), cleanup_payload)
        self.assertIn(bytes.fromhex("082900000010"), cleanup_payload)
        self.assertIn(bytes.fromhex("B02900DE"), cleanup_payload)
        self.assertIn(bytes.fromhex("422900DE"), cleanup_payload)
        self.assertIn(bytes.fromhex("08A9000000DF"), cleanup_payload)
        self.assertIn(bytes.fromhex("08A9000100DF"), cleanup_payload)
        for shared_status_address in (
            0xFFDFF2,
            0xFFDFF4,
            0xFFDFF6,
            0xFFDFF8,
            0xFFDFFA,
        ):
            self.assertNotIn(shared_status_address.to_bytes(4, "big"), cleanup_payload)

        targeted_payload = allocation_payload(targeted_guard)
        self.assertEqual(1, targeted_payload.count(bytes.fromhex("4EB90001A2CC")))
        self.assertEqual(1, targeted_payload.count(bytes.fromhex("4EB90001A304")))
        self.assertIn(
            bytes.fromhex(f"4EB9{release_existing_target_effect.address:08X}"),
            targeted_payload,
        )
        self.assertIn(
            bytes.fromhex(f"4EB9{cleanup_orphaned_aoe_state.address:08X}"),
            targeted_payload,
        )
        self.assertEqual(
            [88, 80, 68, 68],
            [
                word_branch_target(targeted_payload, offset)
                for offset in (6, 36, 48, 58)
            ],
        )
        self.assertIn(bytes.fromhex("0C2800040057"), targeted_payload)
        self.assertIn(bytes.fromhex("0C28000B0057"), targeted_payload)
        self.assertEqual(
            bytes.fromhex(f"4EF9{targeted_guard.address:08X}"),
            payloads[0x015868],
        )

        existing_effect_payload = allocation_payload(release_existing_target_effect)
        self.assertEqual(
            1, existing_effect_payload.count(bytes.fromhex("4EB90001A304"))
        )
        self.assertIn(bytes.fromhex("B22F0003"), existing_effect_payload)
        self.assertIn(
            bytes.fromhex(f"4EB9{cleanup_orphaned_aoe_state.address:08X}"),
            existing_effect_payload,
        )
        self.assertEqual(
            [56, 52],
            [
                word_branch_target(existing_effect_payload, offset)
                for offset in (4, 40)
            ],
        )
        self.assertIn(bytes.fromhex("422900B2"), existing_effect_payload)

        initial_payload = allocation_payload(attach_effect_to_selected_target)
        self.assertEqual(
            bytes.fromhex(
                "3F00424010280057"
                f"4EB9{release_existing_target_effect.address:08X}"
                "301F1368005700B24E75"
            ),
            initial_payload,
        )
        self.assertEqual(
            bytes.fromhex(f"4EB9{attach_effect_to_selected_target.address:08X}"),
            payloads[0x0158E0],
        )
        self.assertEqual(bytes.fromhex("4E714E71"), payloads[0x015A36])

        handoff_payload = allocation_payload(chain_aoe_to_next_target)
        self.assertEqual(
            bytes.fromhex(
                "3F004240102900DE"
                f"4EB9{release_existing_target_effect.address:08X}"
                "301F136900DE00B24E75"
            ),
            handoff_payload,
        )
        for offset in (0x004D14, 0x004D8A, 0x0052F4, 0x005470, 0x00563E):
            self.assertEqual(
                bytes.fromhex(f"4EB9{chain_aoe_to_next_target.address:08X}"),
                payloads[offset],
            )

        completion_payload = allocation_payload(finish_spell_effect_on_target)
        for action in (3, 5, 10):
            self.assertIn(bytes.fromhex(f"0C0000{action:02X}"), completion_payload)
        self.assertIn(bytes.fromhex("43F900FF0100"), completion_payload)
        self.assertEqual(1, completion_payload.count(bytes.fromhex("4EB90001A304")))
        for offset in (0x005008, 0x005178, 0x005348):
            self.assertEqual(
                bytes.fromhex(
                    f"4EB9{finish_spell_effect_on_target.address:08X}"
                    + "4E71" * 8
                ),
                payloads[offset],
            )

        deallocation_payload = allocation_payload(deallocator)
        self.assertEqual(bytes.fromhex("08A800000010"), deallocation_payload[:6])
        self.assertIn(bytes.fromhex("2F0922484240"), deallocation_payload)
        self.assertIn(
            bytes.fromhex(f"4EB9{release_existing_target_effect.address:08X}"),
            deallocation_payload,
        )
        self.assertTrue(deallocation_payload.endswith(bytes.fromhex("225F301F4E75")))
        self.assertEqual(
            bytes.fromhex(f"4EB9{deallocator.address:08X}"),
            payloads[0x01E524],
        )

    def test_party_invulnerability_rejects_negative_health_deltas(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["party-invulnerability-diagnostic"]
        )
        payloads = {edit.offset: edit.payload for edit in edits}
        self.assertEqual([20, 20], [item.size for item in allocations])
        cave = payloads[builder.CODE_CAVE_START]

        for allocation, displaced_save, continuation in zip(
            allocations,
            ("48E7FFC0", "48E7BFC0"),
            (0x00367C, 0x0037F4),
        ):
            start = allocation.address - builder.CODE_CAVE_START
            helper = cave[start : start + allocation.size]
            self.assertTrue(helper.startswith(bytes.fromhex("4A416B0E")))
            self.assertIn(bytes.fromhex(displaced_save), helper)
            self.assertIn(bytes.fromhex("4A68003E"), helper)
            self.assertIn(bytes.fromhex(f"4EF9{continuation:08X}"), helper)
            self.assertTrue(helper.endswith(bytes.fromhex("4E75")))

        for offset, allocation in zip(
            (0x003674, 0x0037EC), allocations
        ):
            self.assertEqual(
                bytes.fromhex(f"4EF9{allocation.address:08X}4E71"),
                payloads[offset],
            )

    def test_firearm_attachment_and_gas_vent_patches_compose(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog,
            ["firearm-attachment-slot-fix", "gas-vent-balance"],
        )
        gas_vent_edits = {
            edit.offset: edit
            for edit in edits
            if edit.patch_id == "gas-vent-balance"
        }
        attachment_ranges = [
            range(edit.offset, edit.offset + len(edit.payload))
            for edit in edits
            if edit.patch_id == "firearm-attachment-slot-fix"
        ]

        # The attachment fix deliberately leaves all three stock arithmetic
        # sites for the balance patch to replace after the TN-2 clamp.
        for offset in (0x0556DC, 0x0556EA, 0x0556FA):
            self.assertFalse(
                any(offset in edit_range for edit_range in attachment_ranges)
            )
            self.assertEqual(bytes.fromhex("4E71"), gas_vent_edits[offset].payload)

        allocation = next(
            item for item in allocations if item.patch_id == "gas-vent-balance"
        )
        hook = gas_vent_edits[0x0556A4].payload
        self.assertEqual(bytes.fromhex("4EB9"), hook[:2])
        self.assertEqual(allocation.address, int.from_bytes(hook[2:], "big"))
        self.assertEqual((), self.catalog["gas-vent-balance"].requires)

    def test_all_six_gas_vent_modifiers_are_independently_configurable(self) -> None:
        self.assertEqual((-2, -1, -1), gas_vent_balance.GAS_VENT_III_MODS)
        self.assertEqual((-1, -1, -1), gas_vent_balance.GAS_VENT_II_MODS)

        with (
            mock.patch.object(gas_vent_balance, "GAS_VENT_III_MODS", (0, -1, -2)),
            mock.patch.object(gas_vent_balance, "GAS_VENT_II_MODS", (-3, 0, -2)),
        ):
            edits, allocations = builder.selected_edits(
                self.catalog,
                ["gas-vent-balance"],
            )

        allocation = next(
            item for item in allocations if item.patch_id == "gas-vent-balance"
        )
        cave = next(edit for edit in edits if edit.patch_id == "code-cave")
        start = allocation.address - cave.offset
        helper = cave.payload[start : start + allocation.size]

        # Control flow stores third, first, then second for each Gas Vent.
        self.assertEqual(bytes.fromhex("5544"), helper[54:56])   # GV III third
        self.assertEqual(bytes.fromhex("4E71"), helper[60:62])   # GV III first
        self.assertEqual(bytes.fromhex("5344"), helper[66:68])   # GV III second
        self.assertEqual(bytes.fromhex("5544"), helper[98:100])  # GV II third
        self.assertEqual(bytes.fromhex("5744"), helper[104:106])  # GV II first
        self.assertEqual(bytes.fromhex("4E71"), helper[110:112])  # GV II second

    def test_zero_success_firearm_gate_preserves_control_flow(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog,
            ["firearm-zero-success-miss"],
        )
        allocation = next(
            item
            for item in allocations
            if item.patch_id == "firearm-zero-success-miss"
        )
        hook = next(
            edit
            for edit in edits
            if edit.patch_id == "firearm-zero-success-miss"
        )
        self.assertEqual(firearm_zero_success_miss.FIREARM_IMPACT_RESOLVER, hook.offset)
        self.assertEqual(bytes.fromhex("4EF9"), hook.payload[:2])
        self.assertEqual(allocation.address, int.from_bytes(hook.payload[2:], "big"))

        cave = next(edit for edit in edits if edit.patch_id == "code-cave")
        start = allocation.address - cave.offset
        gate = cave.payload[start : start + allocation.size]
        self.assertEqual(bytes.fromhex("423900FFF0CC"), gate[:6])
        self.assertEqual(bytes.fromhex("4A28009F"), gate[6:10])
        self.assertEqual(bytes.fromhex("6706"), gate[10:12])
        self.assertEqual(bytes.fromhex("4EF90005594E"), gate[12:18])
        self.assertEqual(bytes.fromhex("4E75"), gate[18:20])

    def test_preimage_guard_generator_uses_replacement_length(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rom_path = Path(temp_dir) / "fixture.bin"
            rom = bytes(range(32))
            rom_path.write_bytes(rom)
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "generate_preimage_guard.py"),
                    str(rom_path),
                    "0x04",
                    "AABB",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            guard = PreimageGuard.from_bytes(4, rom[4:6], len(rom))
            self.assertEqual(
                f"            source_genesis_sum={guard.genesis_sum},\n"
                "            source_crc32_influence="
                f"0x{guard.crc32_influence:08X},\n",
                result.stdout,
            )

    def test_address_is_numeric_and_defaults_to_rom_hex(self) -> None:
        address = Address(0x0E51D8)
        self.assertEqual(0x0E51D8, address)
        self.assertEqual("000E51D8", f"{address}")
        self.assertEqual("0E51D8", f"{address:06X}")
        self.assertEqual(b"\x00\x0E\x51\xD8", address.to_bytes(4, "big"))

    def test_patch_finalizer_can_only_rewrite_its_own_cave_allocation(self) -> None:
        class FinalizedPatch(PatchSpec):
            id = "finalized"
            description = "Finalizer fixture"
            finalize_priority = 10

            def __init__(self) -> None:
                self.address = 0

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                self.address = patch_builder.add_cave(b"0000")

            def finalize_patch(self, patch_builder: PatchBuilder) -> None:
                patch_builder.rewrite_cave(self.address, b"DONE")

        patch = FinalizedPatch()
        edits, _ = builder.selected_edits({patch.id: patch}, [patch.id])
        cave = next(edit.payload for edit in edits if edit.patch_id == "code-cave")
        self.assertEqual(b"DONE", cave[:4])

        root = PatchBuilder(
            0x100,
            0x10F,
            cave_preimage=PreimageGuard(0, 0),
        )
        owner = root.for_patch("owner")
        foreign = root.for_patch("foreign")
        address = owner.add_cave(b"0000")
        with self.assertRaisesRegex(ValueError, "owned by foreign"):
            foreign.rewrite_cave(address, b"NO")
        with self.assertRaisesRegex(ValueError, "owned by owner"):
            owner.rewrite_cave(address + 2, b"TOO")

    def test_patch_finalizers_run_after_builds_in_priority_order(self) -> None:
        events: list[str] = []

        class OrderedPatch(PatchSpec):
            description = "Finalizer ordering fixture"

            def __init__(self, patch_id: str, priority: int) -> None:
                self.id = patch_id
                self.finalize_priority = priority

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                events.append(f"build:{self.id}")
                patch_builder.add_cave(self.id.encode("ascii"))

            def finalize_patch(self, patch_builder: PatchBuilder) -> None:
                events.append(f"finalize:{self.id}")

        later = OrderedPatch("later", 20)
        earlier = OrderedPatch("earlier", 10)
        catalog = {patch.id: patch for patch in (later, earlier)}
        builder.selected_edits(catalog, [later.id, earlier.id])

        self.assertEqual(
            [
                "build:later",
                "build:earlier",
                "finalize:earlier",
                "finalize:later",
            ],
            events,
        )

    def test_manifests_are_valid_and_alphabetized_within_blocks(self) -> None:
        self.assertTrue(MANIFEST_PATHS)
        for path in MANIFEST_PATHS:
            with self.subTest(manifest=path.name):
                document = json.loads(path.read_text(encoding="utf-8"))
                manifest = builder.load_manifest(path, self.catalog)
                self.assertEqual(tuple(document["patches"]), manifest.patches)
                for block in manifest_patch_blocks(path):
                    self.assertEqual(sorted(block), block)

    def test_core_manifest_is_a_strict_subset_of_full(self) -> None:
        self.assertTrue(set(self.core) < set(self.full))

    def test_manifest_rejects_extra_fields_and_unknown_patches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            extra = Path(temp_dir) / "extra.json"
            unknown = Path(temp_dir) / "unknown.json"
            extra.write_text(
                json.dumps(
                    {
                        "name": "test",
                        "display_name": "Test",
                        "version": "1.0",
                        "patches": ["caster-item-slot-8-fix"],
                        "suffix": "unexpected",
                    }
                ),
                encoding="utf-8",
            )
            unknown.write_text(
                json.dumps(
                    {
                        "name": "test",
                        "display_name": "Test",
                        "version": "1.0",
                        "patches": ["not-a-patch"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(builder.PatchBuildError):
                builder.load_manifest(extra, self.catalog)
            with self.assertRaises(builder.PatchBuildError):
                builder.load_manifest(unknown, self.catalog)

    def test_manifest_rejects_an_unrenderable_display_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid = Path(temp_dir) / "invalid.json"
            invalid.write_text(
                json.dumps(
                    {
                        "name": "test",
                        "display_name": "x" * 37,
                        "version": "1.0",
                        "patches": ["title-screen-attribution"],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(builder.PatchBuildError, "36-character"):
                builder.load_manifest(invalid, self.catalog)

    def test_manifest_configures_the_title_screen_attribution_patch(self) -> None:
        manifest = builder.ReleaseManifest(
            "fixture", "Fixture Build", "9.9", ("title-screen-attribution",)
        )
        catalog = builder.configure_catalog_for_manifest(
            self.catalog, manifest
        )
        edits, allocations = builder.selected_edits(catalog, manifest.patches)
        cave_edit = next(
            edit for edit in edits if edit.offset == builder.CODE_CAVE_START
        )
        self.assertEqual("title-screen-attribution", allocations[0].patch_id)
        self.assertIn(manifest.title_attribution.encode("ascii"), cave_edit.payload)
        self.assertTrue(
            next(
                edit.payload
                for edit in edits
                if edit.offset == 0x001E44
            ).startswith(
            bytes.fromhex("4EF9") + allocations[1].address.to_bytes(4, "big"),
            )
        )
        self.assertEqual(
            bytes.fromhex("004A"),
            next(edit.payload for edit in edits if edit.offset == 0x002066),
        )

    def test_comma_separated_patch_parser_preserves_order(self) -> None:
        self.assertEqual(
            ("sorcery-tooltip", "muscle-replacement-quickness-fix"),
            builder.parse_patch_list(
                "sorcery-tooltip, muscle-replacement-quickness-fix"
            ),
        )
        with self.assertRaises(builder.PatchBuildError):
            builder.parse_patch_list("sorcery-tooltip,")

    def test_list_places_blank_categories_under_uncategorized(self) -> None:
        class UncategorizedPatch(PatchSpec):
            id = "uncategorized-example"
            description = "Example patch with no assigned category."

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                patch_builder.add_cave(b"fixture")

        catalog = dict(self.catalog)
        catalog[UncategorizedPatch.id] = UncategorizedPatch()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            builder.print_patch_list(catalog)
        rendered = output.getvalue()
        self.assertIn(
            "Uncategorized:\n\n"
            "    uncategorized-example\n"
            "        Example patch with no assigned category.",
            rendered,
        )
        self.assertLess(
            rendered.index("Disabled Patches:"),
            rendered.index("Uncategorized:"),
        )

    def test_list_generates_game_genie_codes_for_eligible_patches(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            builder.print_patch_list(self.catalog)
        rendered = output.getvalue()
        self.assertIn(
            "    melee-instant-death-fix\n"
            "        Fixed a melee defense underflow bug that caused instant death "
            "when attacked in melee\n"
            "        with Wired Reflexes or certain other cyberware installed.\n"
            "        Game Genie: T7RA-LT1R, J3RA-M7ST, AKRA-LY9W\n",
            rendered,
        )
        self.assertIn(
            "        Game Genie: FFSA-LTDC, KFSA-LJMT\n",
            rendered,
        )

    def test_list_omits_game_genie_for_ineligible_patches(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            builder.print_patch_list(self.catalog)
        sections = output.getvalue().split("\n    ")
        by_patch = {
            section.splitlines()[0]: section
            for section in sections
            if section and not section.endswith(":")
        }
        for patch_id in (
            "agira-power-focus-notebook-rank-4",
            "defense-pip-display-clamp",
            "garbled-contact-screen-fix",
        ):
            with self.subTest(patch_id=patch_id):
                self.assertNotIn("Game Genie:", by_patch[patch_id])

    def test_dependencies_and_conflicts_are_enforced(self) -> None:
        with self.assertRaisesRegex(
            builder.PatchBuildError,
            "requires defense-pip-display-clamp",
        ):
            builder.validate_selection(
                self.catalog, ["protection-talisman-resistance-dice"]
            )
        with self.assertRaisesRegex(builder.PatchBuildError, "appear earlier"):
            builder.validate_selection(
                self.catalog,
                [
                    "rockskin-and-talisman-defense-fix",
                    "protection-talisman-resistance-dice",
                    "defense-pip-display-clamp",
                ],
            )
        with self.assertRaisesRegex(builder.PatchBuildError, "conflict"):
            builder.validate_selection(
                self.catalog,
                [
                    "agira-power-focus-rank-3",
                    "agira-power-focus-notebook-rank-4",
                ],
            )

    def test_selected_patch_order_controls_allocation_order(self) -> None:
        first = builder.allocate_caves(
            self.catalog,
            [
                "defense-pip-display-clamp",
                "sorcery-tooltip",
                "muscle-replacement-quickness-fix",
            ],
        )
        second = builder.allocate_caves(
            self.catalog,
            [
                "defense-pip-display-clamp",
                "muscle-replacement-quickness-fix",
                "sorcery-tooltip",
            ],
        )
        self.assertEqual(builder.CODE_CAVE_START, first[0].address)
        self.assertEqual(builder.CODE_CAVE_START, second[0].address)
        self.assertEqual("sorcery-tooltip", first[1].patch_id)
        self.assertEqual("muscle-replacement-quickness-fix", second[1].patch_id)

    def test_overflow_is_rejected_without_a_source_rom(self) -> None:
        class HugePatch(PatchSpec):
            id = "huge"
            description = "Overflow fixture"

            def build_patch(self, patch_builder: PatchBuilder) -> None:
                patch_builder.add_cave(bytes.fromhex("FF" * 2945))

        huge = HugePatch()
        with self.assertRaisesRegex(builder.PatchBuildError, "need 2945 bytes"):
            builder.allocate_caves({"huge": huge}, ["huge"])

    def test_allocations_emit_one_ff_filled_orb_region_edit(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog,
            ["defense-pip-display-clamp", "muscle-replacement-quickness-fix"],
        )
        cave_edits = [
            edit for edit in edits if edit.offset == builder.CODE_CAVE_START
        ]
        self.assertEqual(1, len(cave_edits))
        cave_edit = cave_edits[0]
        self.assertEqual(builder.CODE_CAVE_PREIMAGE, cave_edit.preimage)
        self.assertEqual(2944, len(cave_edit.payload))
        used = (
            allocations[-1].address
            + allocations[-1].size
            - builder.CODE_CAVE_START
        )
        self.assertEqual(b"\xFF" * (2944 - used), cave_edit.payload[used:])

    def test_fixed_only_selection_preserves_the_orb_region(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["caster-item-slot-8-fix"]
        )
        self.assertEqual([], allocations)
        self.assertNotIn(builder.CODE_CAVE_START, [edit.offset for edit in edits])

    def test_hooks_use_dynamically_allocated_addresses(self) -> None:
        allocations = builder.allocate_caves(
            self.catalog,
            ["defense-pip-display-clamp", "muscle-replacement-quickness-fix"],
        )
        edits, _ = builder.selected_edits(
            self.catalog,
            ["defense-pip-display-clamp", "muscle-replacement-quickness-fix"],
        )
        hooks = [
            edit
            for edit in edits
            if edit.patch_id == "muscle-replacement-quickness-fix"
        ]
        helper_address = allocations[1].address
        adapter_address = allocations[2].address
        expected_helper_call = (
            bytes.fromhex("4EB9") + helper_address.to_bytes(4, "big")
        )
        expected_adapter_call = (
            bytes.fromhex("4EB9") + adapter_address.to_bytes(4, "big")
        )
        self.assertEqual(4, len(hooks))
        self.assertEqual(3, sum(edit.payload == expected_helper_call for edit in hooks))
        self.assertEqual(1, sum(edit.payload == expected_adapter_call for edit in hooks))

    def test_caster_item_slot_8_fix_updates_all_three_stock_scans(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["caster-item-slot-8-fix"]
        )
        patch_edits = {
            edit.offset: edit.payload
            for edit in edits
            if edit.patch_id == "caster-item-slot-8-fix"
        }
        self.assertEqual([], allocations)
        self.assertEqual(
            {
                0x01042C: bytes.fromhex("7E07"),
                0x0104F8: bytes.fromhex("7807"),
                0x055F08: bytes.fromhex("7E07"),
            },
            patch_edits,
        )

    def test_power_focus_rework_caves_only_the_focus_scan(self) -> None:
        edits, allocations = builder.selected_edits(
            self.catalog, ["caster-item-slot-8-fix", "power-focus-rework"]
        )
        rework_edits = [
            edit
            for edit in edits
            if edit.patch_id == "power-focus-rework"
        ]
        rework_allocations = [
            allocation
            for allocation in allocations
            if allocation.patch_id == "power-focus-rework"
        ]
        self.assertEqual(1, len(rework_allocations))
        allocation = rework_allocations[0]
        self.assertEqual(36, allocation.size)
        self.assertEqual([0x0104FA, 0x055F0A], sorted(
            edit.offset for edit in rework_edits
        ))
        hook = next(edit for edit in rework_edits if edit.offset == 0x0104FA)
        self.assertEqual(0x01050E - 0x0104FA, len(hook.payload))
        self.assertEqual(
            bytes.fromhex("4EB9")
            + allocation.address.to_bytes(4, "big")
            + bytes.fromhex("4E71" * 7),
            hook.payload,
        )
        retirement = next(edit for edit in rework_edits if edit.offset == 0x055F0A)
        self.assertEqual(bytes.fromhex("4E75"), retirement.payload)

        # Selecting the rework by itself still scans all eight slots; it does
        # not rely on caster-item-slot-8-fix to initialize D4.
        standalone_edits, standalone_allocations = builder.selected_edits(
            self.catalog, ["power-focus-rework"]
        )
        self.assertEqual(1, len(standalone_allocations))
        standalone_cave = next(
            edit for edit in standalone_edits if edit.patch_id == "code-cave"
        )
        self.assertEqual(bytes.fromhex("7807"), standalone_cave.payload[:2])

    def test_no_argument_command_builds_the_named_bps_without_a_rom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [sys.executable, str(BUILDER_PATH)],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            output = Path(temp_dir) / f"{self.full_manifest.output_stem}.bps"
            self.assertTrue(output.is_file())
            allocations = builder.allocate_caves(self.catalog, self.full)
            used = (
                allocations[-1].address
                + allocations[-1].size
                - builder.CODE_CAVE_START
            )
            total = builder.CODE_CAVE_END + 1 - builder.CODE_CAVE_START
            self.assertIn(
                f"Code cave: {used}/{total} bytes used "
                f"({total - used} bytes remaining)",
                result.stdout,
            )

    def test_core_manifest_controls_the_default_output_filename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER_PATH),
                    "--manifest",
                    str(ROOT / "manifest_core.json"),
                ],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(
                (Path(temp_dir) / f"{self.core_manifest.output_stem}.bps").is_file()
            )

    def test_output_rom_without_source_rom_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER_PATH),
                    "--output-rom",
                    str(Path(temp_dir) / "target.bin"),
                ],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("--output-rom requires --source-rom", result.stderr)

    def test_sparse_checksum_and_bps_generation_match_direct_calculation(self) -> None:
        source = bytearray(builder.SOURCE_ROM_SIZE)
        offset = 0x0200
        source[offset : offset + 4] = b"test"
        source = bytes(source)
        edit = Edit(
            offset=offset,
            preimage=PreimageGuard.from_bytes(offset, b"test", len(source)),
            payload=b"TEST",
            patch_id="fixture",
        )
        target = source[:offset] + edit.payload + source[offset + 4 :]
        source_crc = zlib.crc32(source) & 0xFFFFFFFF
        target_crc = zlib.crc32(target) & 0xFFFFFFFF

        self.assertEqual(
            target_crc,
            builder.target_crc32_from_edits([edit], source_crc),
        )
        self.assertEqual(
            builder.genesis_checksum(target),
            builder.derived_genesis_checksum(
                [edit], builder.genesis_checksum(source)
            ),
        )

        patch = builder.bps_patch_from_edits(
            [edit], b"checksum fixture", source_crc32=source_crc
        )
        source_crc, target_crc, patch_crc = struct.unpack_from(
            "<III", patch, len(patch) - 12
        )
        self.assertEqual(zlib.crc32(source) & 0xFFFFFFFF, source_crc)
        self.assertEqual(zlib.crc32(target) & 0xFFFFFFFF, target_crc)
        self.assertEqual(zlib.crc32(patch[:-4]) & 0xFFFFFFFF, patch_crc)
        self.assertEqual(target, builder.apply_our_bps(source, patch))

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_derived_checksums_match_the_real_full_target(self) -> None:
        source = PRIVATE_SOURCE_ROM.read_bytes()
        edits, _ = builder.build_edits(self.catalog, self.full)
        target = builder.apply_edits(source, edits)
        self.assertEqual(
            builder.target_crc32_from_edits(edits),
            zlib.crc32(target) & 0xFFFFFFFF,
        )
        self.assertEqual(
            builder.derived_genesis_checksum(edits[:-1]),
            builder.genesis_checksum(target),
        )
        self.assertEqual(
            builder.genesis_checksum(target),
            int.from_bytes(
                target[
                    builder.GENESIS_CHECKSUM_OFFSET :
                    builder.GENESIS_CHECKSUM_OFFSET + 2
                ],
                "big",
            ),
        )

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_rom_free_bps_reproduces_the_real_full_target(self) -> None:
        source = PRIVATE_SOURCE_ROM.read_bytes()
        edits, _ = builder.build_edits(self.catalog, self.full)
        target = builder.apply_edits(source, edits)
        patch = builder.bps_patch_from_edits(
            edits, self.full_manifest.bps_metadata
        )
        self.assertEqual(target, builder.apply_our_bps(source, patch))

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_source_rom_option_writes_default_bps_and_bin_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER_PATH),
                    "--source-rom",
                    str(PRIVATE_SOURCE_ROM),
                ],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(
                (Path(temp_dir) / "shadowrun-defragged-v1.0.bps").is_file()
            )
            self.assertTrue(
                (Path(temp_dir) / "shadowrun-defragged-v1.0.bin").is_file()
            )

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_premodified_source_rom_warns_and_builds_compatible_bps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            # Overwrite part of the header title: the global hashes no longer
            # match the canonical ROM, but every patch-site preimage still does.
            premodified = bytearray(PRIVATE_SOURCE_ROM.read_bytes())
            premodified[0x120:0x129] = b"test edit"
            source_path = Path(temp_dir) / "shadowrun_premodified.bin"
            source_path.write_bytes(premodified)
            bps_path = Path(temp_dir) / "premodified.bps"
            rom_path = Path(temp_dir) / "premodified-patched.bin"
            result = subprocess.run(
                [
                    sys.executable,
                    str(BUILDER_PATH),
                    "--source-rom",
                    str(source_path),
                    "--output-bps",
                    str(bps_path),
                    "--output-rom",
                    str(rom_path),
                ],
                cwd=temp_dir,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("WARNING: source ROM does not match", result.stderr)
            self.assertEqual(
                rom_path.read_bytes(),
                builder.apply_our_bps(
                    bytes(premodified), bps_path.read_bytes()
                ),
            )

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_noncanonical_rom_is_rejected_when_a_patch_preimage_differs(
        self,
    ) -> None:
        source = bytearray(PRIVATE_SOURCE_ROM.read_bytes())
        catalog = builder.load_patch_catalog()
        edits, _ = builder.build_edits(
            catalog, ["caster-item-slot-8-fix"]
        )
        patch_edit = next(
            edit
            for edit in edits
            if edit.offset != builder.GENESIS_CHECKSUM_OFFSET
        )
        source[patch_edit.offset] ^= 0xFF
        with self.assertRaisesRegex(builder.PatchBuildError, "expected"):
            builder.apply_edits(bytes(source), edits)

    @unittest.skipUnless(
        PRIVATE_SOURCE_ROM.is_file(),
        "private source ROM is intentionally absent from public clones",
    )
    def test_every_patch_applies_independently_with_requirements(self) -> None:
        source = PRIVATE_SOURCE_ROM.read_bytes()
        for patch_id, patch in self.catalog.items():
            selected = [*patch.requires, patch_id]
            with self.subTest(patch=patch_id):
                edits, _ = builder.build_edits(self.catalog, selected)
                target = builder.apply_edits(source, edits)
                bps = builder.bps_patch_from_edits(
                    edits, b"individual patch test"
                )
                self.assertEqual(target, builder.apply_our_bps(source, bps))


if __name__ == "__main__":
    unittest.main()
