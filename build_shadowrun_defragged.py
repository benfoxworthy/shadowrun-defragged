#!/usr/bin/env python3
"""Build Shadowrun Defragged BPS patches from authoritative Python modules.

No ROM is needed to generate a BPS file. Patch modules keep each replacement
beside its non-literal source checksum influences. Supplying the canonical
source ROM additionally validates every preimage and writes a local patched
ROM.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import pkgutil
import re
import struct
import sys
import textwrap
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from patch_framework import (
    CaveAllocation,
    Edit,
    PatchBuilder,
    PatchSpec,
    PreimageGuard,
    game_genie_codes_for_edits,
)


ROOT = Path(__file__).resolve().parent
PATCHES_PATH = ROOT / "patches"
DEFAULT_MANIFEST_PATH = ROOT / "manifest_full.json"

SOURCE_ROM_SIZE = 2_097_152
SOURCE_ROM_SHA1 = "A06A281D39E845BFF446A541B2FF48E1D93143C2"
SOURCE_ROM_CRC32 = 0xFBB92909
SOURCE_GENESIS_CHECKSUM = 0x6BAF
SOURCE_ROM_DESCRIPTION = "clean, headerless Shadowrun (USA) Genesis ROM"

CODE_CAVE_START = 0x0E51D8
CODE_CAVE_END = 0x0E5D57
SHARED_DICE_TEST = 0x00000DBA
CODE_CAVE_PREIMAGE = PreimageGuard(
    genesis_sum=25_241_521,
    crc32_influence=0x08781CE5,
)
GENESIS_CHECKSUM_OFFSET = 0x18E
GENESIS_CHECKSUM_START = 0x200

SAFE_NAME = re.compile(r"[a-z0-9][a-z0-9-]*\Z")
SAFE_VERSION = re.compile(r"[0-9][0-9A-Za-z.-]*\Z")
LIST_CATEGORY_ORDER = (
    "Attribution/Diagnostics",
    "Gameplay Bug Fixes",
    "UI/Display Bug Fixes",
    "Balance Improvements",
    "Tar Pit & Deck Storage Rework",
    "Deferred Improvements",
    "Disabled Patches",
)
UNCATEGORIZED_CATEGORY = "Uncategorized"


class PatchBuildError(RuntimeError):
    """The manifest, patch definitions, or optional source ROM were invalid."""


@dataclass(frozen=True)
class ReleaseManifest:
    """Small release descriptor loaded from a root manifest JSON file."""

    name: str
    display_name: str
    version: str
    patches: tuple[str, ...]

    @property
    def output_stem(self) -> str:
        return f"{self.name}-v{self.version}"

    @property
    def bps_metadata(self) -> bytes:
        return f"{self.name} v{self.version}".encode("utf-8")

    @property
    def title_attribution(self) -> str:
        """The release label rendered below the title-screen copyright."""

        return f"{self.display_name} v{self.version}"


def encode_bps_number(value: int) -> bytes:
    """Encode BPS's base-128 integer representation."""

    if value < 0:
        raise ValueError("BPS numbers must be non-negative")
    result = bytearray()
    while True:
        part = value & 0x7F
        value >>= 7
        if value == 0:
            result.append(part | 0x80)
            return bytes(result)
        result.append(part)
        value -= 1


def decode_bps_number(patch: bytes, position: int) -> tuple[int, int]:
    """Decode a BPS number for emitted-patch verification."""

    value = 0
    shift = 1
    while position < len(patch):
        part = patch[position]
        position += 1
        value += (part & 0x7F) * shift
        if part & 0x80:
            return value, position
        shift <<= 7
        value += shift
    raise PatchBuildError("truncated BPS number")


def genesis_checksum(rom: bytes) -> int:
    """Return the 16-bit Genesis header word sum from ROM offset 0x200."""

    if len(rom) % 2:
        raise PatchBuildError("Genesis ROM length must be even")
    return (
        sum(
            int.from_bytes(rom[index : index + 2], "big")
            for index in range(GENESIS_CHECKSUM_START, len(rom), 2)
        )
        & 0xFFFF
    )


def load_patch_catalog() -> dict[str, PatchSpec]:
    """Import every authoritative patch module and return it by patch ID."""

    catalog: dict[str, PatchSpec] = {}
    for module_info in pkgutil.iter_modules([str(PATCHES_PATH)]):
        if module_info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"patches.{module_info.name}")
        except Exception as error:
            raise PatchBuildError(
                f"cannot import patch module {module_info.name}: {error}"
            ) from error
        patch = getattr(module, "PATCH", None)
        if not isinstance(patch, PatchSpec):
            raise PatchBuildError(
                f"patches/{module_info.name}.py does not define PatchSpec PATCH"
            )
        patch_id = getattr(patch, "id", None)
        description = getattr(patch, "description", None)
        category = getattr(patch, "category", None)
        requires = getattr(patch, "requires", None)
        conflicts = getattr(patch, "conflicts", None)
        if not isinstance(patch_id, str) or not patch_id:
            raise PatchBuildError(
                f"patches/{module_info.name}.py has an invalid patch ID"
            )
        if not isinstance(description, str) or not description:
            raise PatchBuildError(f"patch {patch_id!r} has no description")
        if not isinstance(category, str):
            raise PatchBuildError(f"patch {patch_id!r} has an invalid category")
        if not isinstance(requires, tuple) or not all(
            isinstance(item, str) for item in requires
        ):
            raise PatchBuildError(f"patch {patch_id!r} has invalid requirements")
        if not isinstance(conflicts, tuple) or not all(
            isinstance(item, str) for item in conflicts
        ):
            raise PatchBuildError(f"patch {patch_id!r} has invalid conflicts")
        expected_module_name = patch_id.replace("-", "_")
        if module_info.name != expected_module_name:
            raise PatchBuildError(
                f"patch {patch_id!r} must be defined in {expected_module_name}.py"
            )
        if patch_id in catalog:
            raise PatchBuildError(f"duplicate patch ID: {patch_id}")
        catalog[patch_id] = patch
    if not catalog:
        raise PatchBuildError("no patch modules found")
    return catalog


def load_manifest(
    path: Path, catalog: Mapping[str, PatchSpec]
) -> ReleaseManifest:
    """Load and validate a compact JSON release manifest."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PatchBuildError(f"cannot read manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise PatchBuildError(f"manifest {path} must contain a JSON object")
    unexpected = set(document) - {"name", "display_name", "version", "patches"}
    missing = {"name", "display_name", "version", "patches"} - set(document)
    if missing:
        raise PatchBuildError(
            f"manifest {path} is missing: {', '.join(sorted(missing))}"
        )
    if unexpected:
        raise PatchBuildError(
            f"manifest {path} has unexpected fields: "
            f"{', '.join(sorted(unexpected))}"
        )

    name = document["name"]
    display_name = document["display_name"]
    version = document["version"]
    patches = document["patches"]
    if not isinstance(name, str) or not SAFE_NAME.fullmatch(name):
        raise PatchBuildError(
            f"manifest name must use lowercase letters, digits, and hyphens: {name!r}"
        )
    if not isinstance(version, str) or not SAFE_VERSION.fullmatch(version):
        raise PatchBuildError(f"invalid manifest version: {version!r}")
    if (
        not isinstance(display_name, str)
        or not display_name
        or not display_name.isascii()
        or not display_name.isprintable()
    ):
        raise PatchBuildError(
            "manifest display_name must be a nonempty printable ASCII string"
        )
    title_attribution = f"{display_name} v{version}"
    if len(title_attribution) > 36:
        raise PatchBuildError(
            "manifest display_name and version exceed the 36-character "
            "title-screen attribution limit"
        )
    if not isinstance(patches, list) or not all(
        isinstance(patch_id, str) for patch_id in patches
    ):
        raise PatchBuildError("manifest patches must be a JSON string array")
    if not patches:
        raise PatchBuildError(f"manifest {path} selects no patches")
    if len(patches) != len(set(patches)):
        raise PatchBuildError(f"manifest {path} contains a duplicate patch ID")
    validate_selection(catalog, patches)
    return ReleaseManifest(name, display_name, version, tuple(patches))


def configure_catalog_for_manifest(
    catalog: Mapping[str, PatchSpec], manifest: ReleaseManifest
) -> dict[str, PatchSpec]:
    """Bind manifest-supplied inputs to the selectable release patches."""

    configured = dict(catalog)
    attribution_patch = configured.get("title-screen-attribution")
    if (
        attribution_patch is not None
        and "title-screen-attribution" in manifest.patches
    ):
        configure = getattr(attribution_patch, "with_display_text", None)
        if not callable(configure):
            raise PatchBuildError(
                "title-screen-attribution does not accept a display-name input"
            )
        configured["title-screen-attribution"] = configure(manifest.title_attribution)
    return configured


def parse_patch_list(value: str) -> tuple[str, ...]:
    """Parse the comma-separated value accepted by ``--patches``."""

    patches = tuple(part.strip() for part in value.split(","))
    if not patches or any(not patch_id for patch_id in patches):
        raise PatchBuildError(
            "--patches must be a comma-separated list of nonempty patch IDs"
        )
    if len(patches) != len(set(patches)):
        raise PatchBuildError("--patches contains a duplicate patch ID")
    return patches


def validate_selection(
    catalog: Mapping[str, PatchSpec], selected: Iterable[str]
) -> None:
    """Reject unknown patches, missing requirements, and conflicts."""

    selected_list = list(selected)
    selected_set = set(selected_list)
    selected_positions = {
        patch_id: index for index, patch_id in enumerate(selected_list)
    }
    unknown = selected_set - catalog.keys()
    if unknown:
        raise PatchBuildError(
            "unknown patch ID(s): " + ", ".join(sorted(unknown))
        )
    for patch_id in selected_list:
        patch = catalog[patch_id]
        missing = set(patch.requires) - selected_set
        if missing:
            raise PatchBuildError(
                f"patch {patch_id} requires {sorted(missing)[0]}"
            )
        late_requirements = {
            requirement
            for requirement in patch.requires
            if selected_positions[requirement] > selected_positions[patch_id]
        }
        if late_requirements:
            raise PatchBuildError(
                f"patch {patch_id} requires {sorted(late_requirements)[0]} "
                "to appear earlier"
            )
        conflicts = set(patch.conflicts) & selected_set
        if conflicts:
            raise PatchBuildError(
                f"patches conflict: {patch_id} and {sorted(conflicts)[0]}"
            )


def _build_selected_plan(
    catalog: Mapping[str, PatchSpec], selected: Iterable[str]
) -> PatchBuilder:
    """Execute selected patch definitions into one validated recording."""

    selected_list = list(selected)
    validate_selection(catalog, selected_list)
    builder = PatchBuilder(
        CODE_CAVE_START,
        CODE_CAVE_END,
        cave_preimage=CODE_CAVE_PREIMAGE,
    )
    for patch_id in selected_list:
        patch = catalog[patch_id]
        operation_count = len(builder.edits) + len(builder.allocations)
        try:
            patch.build_patch(builder.for_patch(patch_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise PatchBuildError(f"{patch_id}: {error}") from error
        if len(builder.edits) + len(builder.allocations) == operation_count:
            raise PatchBuildError(f"patch {patch_id} records no edits")
    for patch_id in sorted(
        selected_list, key=lambda item: catalog[item].finalize_priority
    ):
        patch = catalog[patch_id]
        try:
            patch.finalize_patch(builder.for_patch(patch_id))
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise PatchBuildError(f"{patch_id} finalizer: {error}") from error
    validate_edits(builder.edits)
    validate_cave_dice_callers(builder.edits, builder.allocations)
    return builder


def allocate_caves(
    catalog: Mapping[str, PatchSpec], selected: Iterable[str]
) -> list[CaveAllocation]:
    """Execute selected patches and return their dynamic cave layout."""

    builder = _build_selected_plan(catalog, selected)
    return builder.allocations


def selected_edits(
    catalog: Mapping[str, PatchSpec], selected: Iterable[str]
) -> tuple[list[Edit], list[CaveAllocation]]:
    """Execute selected patch definitions and return their recorded edits."""

    builder = _build_selected_plan(catalog, selected)
    return builder.edits, builder.allocations


def validate_edits(edits: Iterable[Edit]) -> None:
    """Reject length changes, out-of-ROM writes, and overlapping edits."""

    ranges: list[tuple[int, int, str]] = []
    for edit in edits:
        edit_name = f"{edit.patch_id}@{edit.offset:#08x}"
        end = edit.offset + len(edit.payload)
        if edit.offset < 0 or end > SOURCE_ROM_SIZE:
            raise PatchBuildError(f"{edit_name} lies outside the ROM")
        for old_start, old_end, old_id in ranges:
            if edit.offset < old_end and old_start < end:
                raise PatchBuildError(
                    f"{edit_name} overlaps {old_id}"
                )
        ranges.append((edit.offset, end, edit_name))


def validate_cave_dice_callers(
    edits: Iterable[Edit], allocations: Iterable[CaveAllocation]
) -> None:
    """Reject cave calls whose dynamic return addresses break dice diagnostics."""

    allocation_list = list(allocations)
    if not allocation_list:
        return
    cave = next(edit for edit in edits if edit.patch_id == "code-cave")
    forbidden_calls = (
        bytes.fromhex("4EB8") + SHARED_DICE_TEST.to_bytes(2, "big"),
        bytes.fromhex("4EB9") + SHARED_DICE_TEST.to_bytes(4, "big"),
    )
    for allocation in allocation_list:
        start = allocation.address - cave.offset
        payload = cave.payload[start : start + allocation.size]
        if any(call in payload for call in forbidden_calls):
            raise PatchBuildError(
                f"{allocation.patch_id} cave calls the shared dice test with JSR; "
                "tail-jump with JMP to preserve the original diagnostic caller"
            )


def derived_genesis_checksum(
    edits: Iterable[Edit],
    source_checksum: int = SOURCE_GENESIS_CHECKSUM,
) -> int:
    """Derive the target header checksum from sparse known byte changes."""

    checksum = source_checksum
    for edit in edits:
        replacement_sum = 0
        for index, new in enumerate(edit.payload):
            absolute_offset = edit.offset + index
            if absolute_offset < GENESIS_CHECKSUM_START:
                continue
            weight = 0x100 if absolute_offset % 2 == 0 else 1
            replacement_sum += new * weight
        if edit.offset >= GENESIS_CHECKSUM_START:
            checksum += replacement_sum - edit.preimage.genesis_sum
    return checksum & 0xFFFF


def build_edits(
    catalog: Mapping[str, PatchSpec],
    selected: Iterable[str],
    *,
    source_checksum: int = SOURCE_GENESIS_CHECKSUM,
    source_header_checksum: int | None = None,
) -> tuple[list[Edit], list[CaveAllocation]]:
    """Return selected edits plus the derived Genesis-header checksum edit."""

    edits, allocations = selected_edits(catalog, selected)
    new_checksum = derived_genesis_checksum(edits, source_checksum)
    if source_header_checksum is None:
        source_header_checksum = source_checksum
    edits.append(
        Edit(
            patch_id="builder",
            offset=GENESIS_CHECKSUM_OFFSET,
            preimage=PreimageGuard.from_bytes(
                GENESIS_CHECKSUM_OFFSET,
                source_header_checksum.to_bytes(2, "big"),
                SOURCE_ROM_SIZE,
            ),
            payload=new_checksum.to_bytes(2, "big"),
        )
    )
    validate_edits(edits)
    return edits, allocations


def target_crc32_from_edits(
    edits: Iterable[Edit],
    source_crc32: int = SOURCE_ROM_CRC32,
) -> int:
    """Derive target CRC-32 from source CRC and sparse byte substitutions.

    CRC-32 is affine over equal-length byte strings. The tracked preimage
    influences combine with the replacement-byte influence, so no source ROM
    bytes are needed.
    """

    replacement = bytearray(SOURCE_ROM_SIZE)
    source_influence = 0
    for edit in edits:
        end = edit.offset + len(edit.payload)
        replacement[edit.offset:end] = edit.payload
        source_influence ^= edit.preimage.crc32_influence
    zero_crc = zlib.crc32(bytes(SOURCE_ROM_SIZE)) & 0xFFFFFFFF
    replacement_influence = (zlib.crc32(replacement) & 0xFFFFFFFF) ^ zero_crc
    return source_crc32 ^ source_influence ^ replacement_influence


def bps_patch_from_edits(
    edits: Iterable[Edit],
    metadata: bytes,
    source_crc32: int = SOURCE_ROM_CRC32,
) -> bytes:
    """Emit a complete BPS1 patch without reading the source ROM."""

    sorted_edits = sorted(edits, key=lambda edit: edit.offset)
    validate_edits(sorted_edits)
    patch = bytearray(b"BPS1")
    patch.extend(encode_bps_number(SOURCE_ROM_SIZE))
    patch.extend(encode_bps_number(SOURCE_ROM_SIZE))
    patch.extend(encode_bps_number(len(metadata)))
    patch.extend(metadata)

    cursor = 0
    for edit in sorted_edits:
        unchanged_length = edit.offset - cursor
        if unchanged_length:
            patch.extend(encode_bps_number((unchanged_length - 1) << 2))
        patch.extend(
            encode_bps_number(((len(edit.payload) - 1) << 2) | 1)
        )
        patch.extend(edit.payload)
        cursor = edit.offset + len(edit.payload)
    if cursor < SOURCE_ROM_SIZE:
        patch.extend(
            encode_bps_number(((SOURCE_ROM_SIZE - cursor - 1) << 2))
        )

    target_crc = target_crc32_from_edits(sorted_edits, source_crc32)
    patch.extend(struct.pack("<I", source_crc32))
    patch.extend(struct.pack("<I", target_crc))
    patch.extend(struct.pack("<I", zlib.crc32(patch) & 0xFFFFFFFF))
    return bytes(patch)


def apply_edits(source: bytes, edits: Iterable[Edit]) -> bytes:
    """Validate the optional source ROM and apply resolved edits."""

    if len(source) != SOURCE_ROM_SIZE:
        raise PatchBuildError(
            f"source ROM must be {SOURCE_ROM_SIZE} bytes; "
            f"received {len(source)} bytes"
        )

    target = bytearray(source)
    for edit in edits:
        end = edit.offset + len(edit.payload)
        actual = bytes(target[edit.offset:end])
        actual_influence = PreimageGuard.from_bytes(
            edit.offset, actual, SOURCE_ROM_SIZE
        ).crc32_influence
        if actual_influence != edit.preimage.crc32_influence:
            raise PatchBuildError(
                f"{edit.patch_id}@{edit.offset:#08x} expected source CRC-32 "
                f"influence 0x{edit.preimage.crc32_influence:08X}, "
                f"found 0x{actual_influence:08X}"
            )
        target[edit.offset:end] = edit.payload
    return bytes(target)


def apply_our_bps(source: bytes, patch: bytes) -> bytes:
    """Apply the restricted BPS command subset emitted by this builder."""

    if patch[:4] != b"BPS1" or len(patch) < 16:
        raise PatchBuildError("not a BPS1 patch")
    patch_crc = struct.unpack_from("<I", patch, len(patch) - 4)[0]
    if patch_crc != zlib.crc32(patch[:-4]) & 0xFFFFFFFF:
        raise PatchBuildError("BPS patch checksum mismatch")

    position = 4
    source_size, position = decode_bps_number(patch, position)
    target_size, position = decode_bps_number(patch, position)
    metadata_size, position = decode_bps_number(patch, position)
    position += metadata_size
    if source_size != len(source):
        raise PatchBuildError("BPS source size mismatch")

    target = bytearray()
    command_end = len(patch) - 12
    while position < command_end:
        command, position = decode_bps_number(patch, position)
        length, action = (command >> 2) + 1, command & 3
        if action == 0:
            target.extend(source[len(target) : len(target) + length])
        elif action == 1:
            target.extend(patch[position : position + length])
            position += length
        else:
            raise PatchBuildError("unexpected copy command in generated BPS")

    if len(target) != target_size:
        raise PatchBuildError("BPS target size mismatch")
    source_crc, target_crc = struct.unpack_from("<II", patch, command_end)
    if source_crc != zlib.crc32(source) & 0xFFFFFFFF:
        raise PatchBuildError("BPS source checksum mismatch")
    if target_crc != zlib.crc32(target) & 0xFFFFFFFF:
        raise PatchBuildError("BPS target checksum mismatch")
    return bytes(target)


def print_patch_list(catalog: Mapping[str, PatchSpec]) -> None:
    """Print patches by fixed category, then uncategorized patches."""

    known_categories = set(LIST_CATEGORY_ORDER)
    unexpected = {
        patch.category
        for patch in catalog.values()
        if patch.category and patch.category not in known_categories
    }
    if unexpected:
        raise PatchBuildError(
            "patch modules use unknown list categories: "
            + ", ".join(sorted(unexpected))
        )

    for category in (*LIST_CATEGORY_ORDER, ""):
        patches = sorted(
            (
                patch
                for patch in catalog.values()
                if patch.category == category
            ),
            key=lambda patch: patch.id,
        )
        if not patches:
            continue
        print(f"{category or UNCATEGORIZED_CATEGORY}:")
        print()
        for patch in patches:
            game_genie_codes: tuple[str, ...] | None = None
            if not patch.requires:
                edits, allocations = selected_edits(catalog, [patch.id])
                if not allocations:
                    game_genie_codes = game_genie_codes_for_edits(edits)
            print(f"    {patch.id}")
            print(
                textwrap.fill(
                    patch.description,
                    width=92,
                    initial_indent="        ",
                    subsequent_indent="        ",
                )
            )
            if game_genie_codes is not None:
                print(f"        Game Genie: {', '.join(game_genie_codes)}")
            if patch.requires:
                print(f"        Dependent On: {', '.join(patch.requires)}")
            if patch.conflicts:
                print(f"        Conflicts With: {', '.join(patch.conflicts)}")
            print()


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the intentionally small public command-line interface."""

    parser = argparse.ArgumentParser(
        description=(
            "Build a Shadowrun Defragged BPS patch. With no arguments, "
            "builds manifest_full.json, outputting to the default filename "
            "<name>-v<version>.bps from that manifest."
        ),
        epilog=(
            "Examples:\n"
            "  python build_shadowrun_defragged.py\n"
            "  python build_shadowrun_defragged.py --manifest manifest_core.json\n"
            "  python build_shadowrun_defragged.py --patches "
            "\"caster-item-slot-8-fix, firearm-attachment-slot-fix\"\n"
            "  python build_shadowrun_defragged.py "
            "--source-rom \"Shadowrun (USA).gen\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument(
        "--manifest",
        type=Path,
        help="Compact JSON manifest; defaults to manifest_full.json",
    )
    selection.add_argument(
        "--patches",
        metavar='"PATCH-A, PATCH-B"',
        help="Comma-separated ordered patch IDs; exclusive with --manifest",
    )
    parser.add_argument(
        "--source-rom",
        type=Path,
        help=(
            "Optional headerless ROM; validates every patch preimage and "
            "writes a patched .bin file"
        ),
    )
    parser.add_argument(
        "--output-bps",
        type=Path,
        help="Optional BPS output path or filename",
    )
    parser.add_argument(
        "--output-rom",
        type=Path,
        help="Optional patched-ROM output path; requires --source-rom",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_patches",
        help="List every available patch and exit",
    )
    return parser


def main() -> int:
    parser = create_argument_parser()
    args = parser.parse_args()
    if args.output_rom is not None and args.source_rom is None:
        parser.error("--output-rom requires --source-rom")

    catalog = load_patch_catalog()
    if args.list_patches:
        print_patch_list(catalog)
        return 0

    if args.manifest is not None:
        manifest_path = args.manifest
    else:
        manifest_path = DEFAULT_MANIFEST_PATH
    base_manifest = load_manifest(manifest_path, catalog)

    if args.patches is not None:
        try:
            selected = parse_patch_list(args.patches)
            validate_selection(catalog, selected)
        except PatchBuildError as error:
            parser.error(str(error))
        manifest = ReleaseManifest(
            name=f"{base_manifest.name}-custom",
            display_name=base_manifest.display_name,
            version=base_manifest.version,
            patches=selected,
        )
    else:
        manifest = base_manifest

    catalog = configure_catalog_for_manifest(catalog, manifest)

    source: bytes | None = None
    source_crc32 = SOURCE_ROM_CRC32
    source_checksum = SOURCE_GENESIS_CHECKSUM
    source_header_checksum = SOURCE_GENESIS_CHECKSUM
    if args.source_rom is not None:
        source = args.source_rom.read_bytes()
        if len(source) != SOURCE_ROM_SIZE:
            raise PatchBuildError(
                f"source ROM must be {SOURCE_ROM_SIZE} bytes; "
                f"received {len(source)} bytes"
            )
        actual_sha1 = hashlib.sha1(source).hexdigest().upper()
        source_crc32 = zlib.crc32(source) & 0xFFFFFFFF
        if (
            actual_sha1 != SOURCE_ROM_SHA1
            or source_crc32 != SOURCE_ROM_CRC32
        ):
            print(
                "WARNING: source ROM does not match the canonical "
                f"{SOURCE_ROM_DESCRIPTION} "
                f"(expected SHA-1 {SOURCE_ROM_SHA1}, CRC-32 "
                f"{SOURCE_ROM_CRC32:08X}; received SHA-1 {actual_sha1}, "
                f"CRC-32 {source_crc32:08X}). Proceeding only if every "
                "selected patch preimage matches.",
                file=sys.stderr,
            )
        source_checksum = genesis_checksum(source)
        source_header_checksum = int.from_bytes(
            source[
                GENESIS_CHECKSUM_OFFSET : GENESIS_CHECKSUM_OFFSET + 2
            ],
            "big",
        )

    edits, allocations = build_edits(
        catalog,
        manifest.patches,
        source_checksum=source_checksum,
        source_header_checksum=source_header_checksum,
    )
    patch = bps_patch_from_edits(
        edits,
        manifest.bps_metadata,
        source_crc32=source_crc32,
    )
    patch_path = args.output_bps or Path(f"{manifest.output_stem}.bps")
    rom_path = args.output_rom
    if args.source_rom is not None and rom_path is None:
        rom_path = Path(f"{manifest.output_stem}.bin")
    if rom_path is not None and patch_path.resolve() == rom_path.resolve():
        parser.error("--output-bps and --output-rom must be different files")

    target: bytes | None = None
    if source is not None:
        target = apply_edits(source, edits)
        if target != apply_our_bps(source, patch):
            raise PatchBuildError("generated BPS does not reproduce patched ROM")
        expected_crc = target_crc32_from_edits(edits, source_crc32)
        if zlib.crc32(target) & 0xFFFFFFFF != expected_crc:
            raise PatchBuildError("derived target CRC does not match patched ROM")
        if genesis_checksum(target) != int.from_bytes(
            target[GENESIS_CHECKSUM_OFFSET : GENESIS_CHECKSUM_OFFSET + 2],
            "big",
        ):
            raise PatchBuildError("derived Genesis checksum does not match target")

    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_bytes(patch)
    if rom_path is not None and target is not None:
        rom_path.parent.mkdir(parents=True, exist_ok=True)
        rom_path.write_bytes(target)

    used = (
        allocations[-1].address + allocations[-1].size - CODE_CAVE_START
        if allocations
        else 0
    )
    available = CODE_CAVE_END + 1 - CODE_CAVE_START
    print(f"Built {manifest.name} v{manifest.version}")
    print(f"Patches: {len(manifest.patches)}")
    print(
        f"Code cave: {used}/{available} bytes used "
        f"({available - used} bytes remaining)"
    )
    print(f"Wrote BPS: {patch_path}")
    print(f"BPS SHA-256: {hashlib.sha256(patch).hexdigest().upper()}")
    if rom_path is not None and target is not None:
        print(f"Wrote ROM: {rom_path}")
        print(f"Target SHA-1: {hashlib.sha1(target).hexdigest().upper()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, PatchBuildError) as error:
        raise SystemExit(f"error: {error}")
