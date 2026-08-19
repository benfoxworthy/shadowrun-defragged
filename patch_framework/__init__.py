"""Public API for defining and recording Shadowrun Defragged patches."""

from .patch_framework import (
    Address,
    CaveAllocation,
    Edit,
    GAME_GENIE_HARDWARE_LIMIT,
    PatchBuilder,
    PatchSpec,
    PreimageGuard,
    encode_game_genie_code,
    game_genie_codes_for_edits,
)

__all__ = [
    "Address",
    "CaveAllocation",
    "Edit",
    "GAME_GENIE_HARDWARE_LIMIT",
    "PatchBuilder",
    "PatchSpec",
    "PreimageGuard",
    "encode_game_genie_code",
    "game_genie_codes_for_edits",
]
