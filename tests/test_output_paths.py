"""Protect source ROMs and distinct outputs using synthetic CLI fixtures."""

from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_shadowrun_defragged as builder  # noqa: E402
from patch_framework import PatchBuilder, PatchSpec, PreimageGuard  # noqa: E402


class SyntheticPatch(PatchSpec):
    id = "synthetic-output-path-fixture"
    description = "Change two synthetic bytes to exercise the complete CLI."

    def build_patch(self, patch_builder: PatchBuilder) -> None:
        guard = PreimageGuard.from_bytes(0x200, bytes(2), builder.SOURCE_ROM_SIZE)
        patch_builder.replace(
            offset=0x200,
            source_genesis_sum=guard.genesis_sum,
            source_crc32_influence=guard.crc32_influence,
            payload=b"QA",
        )


class OutputPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.directory = Path(self.temporary_directory.name)
        self.source = self.directory / "source.gen"
        self.source_bytes = bytes(builder.SOURCE_ROM_SIZE)
        self.source.write_bytes(self.source_bytes)
        self.patch_output = self.directory / "result.bps"
        self.rom_output = self.directory / "result.bin"

    def run_main(self, *arguments: str) -> tuple[int, str]:
        patch = SyntheticPatch()
        manifest = builder.ReleaseManifest(
            "fixture", "Fixture", "1.0", (patch.id,)
        )
        stderr = io.StringIO()
        previous_directory = Path.cwd()
        try:
            os.chdir(self.directory)
            with (
                mock.patch.object(
                    builder, "load_patch_catalog", return_value={patch.id: patch}
                ),
                mock.patch.object(builder, "load_manifest", return_value=manifest),
                mock.patch.object(
                    sys, "argv",
                    [str(ROOT / "build_shadowrun_defragged.py"), *arguments],
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(stderr),
            ):
                try:
                    return builder.main(), stderr.getvalue()
                except SystemExit as error:
                    return error.code, stderr.getvalue()
        finally:
            os.chdir(previous_directory)

    def assert_source_is_protected(
        self, aliased_output: Path, output_option: str
    ) -> None:
        self.source.write_bytes(self.source_bytes)
        other_option, other_output = (
            ("--output-rom", self.rom_output)
            if output_option == "--output-bps"
            else ("--output-bps", self.patch_output)
        )
        other_output.unlink(missing_ok=True)
        status, stderr = self.run_main(
            "--source-rom", str(self.source),
            output_option, str(aliased_output),
            other_option, str(other_output),
        )
        self.assertNotEqual(0, status)
        self.assertIn(f"{output_option} must be different from --source-rom", stderr)
        self.assertEqual(self.source_bytes, self.source.read_bytes())
        self.assertFalse(other_output.exists())

    def create_symlink_or_skip(self, link_path: Path, target_path: Path) -> None:
        try:
            link_path.symlink_to(target_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlinks are unavailable in this environment: {error}")

    def create_hardlink_or_skip(self, link_path: Path, target_path: Path) -> None:
        try:
            os.link(target_path, link_path)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"hardlinks are unavailable in this environment: {error}")

    def test_outputs_cannot_equal_source(self) -> None:
        for option in ("--output-bps", "--output-rom"):
            with self.subTest(option=option):
                self.assert_source_is_protected(self.source, option)

    def test_relative_output_cannot_alias_source(self) -> None:
        self.assert_source_is_protected(Path("source.gen"), "--output-bps")

    def test_symlink_outputs_cannot_alias_source(self) -> None:
        alias = self.directory / "source-alias"
        self.create_symlink_or_skip(alias, self.source)
        for option in ("--output-bps", "--output-rom"):
            with self.subTest(option=option):
                self.assert_source_is_protected(alias, option)

    def test_hardlink_outputs_cannot_alias_source(self) -> None:
        alias = self.directory / "source-alias"
        self.create_hardlink_or_skip(alias, self.source)
        for option in ("--output-bps", "--output-rom"):
            with self.subTest(option=option):
                self.assert_source_is_protected(alias, option)

    def test_outputs_cannot_alias_each_other(self) -> None:
        existing = b"Keep this existing output intact."
        for alias_kind in ("same-path", "symlink", "hardlink"):
            with self.subTest(alias_kind=alias_kind):
                self.patch_output.write_bytes(existing)
                if alias_kind == "same-path":
                    rom_output = self.patch_output
                else:
                    rom_output = self.rom_output
                    if alias_kind == "symlink":
                        self.create_symlink_or_skip(rom_output, self.patch_output)
                    else:
                        self.create_hardlink_or_skip(rom_output, self.patch_output)
                try:
                    status, stderr = self.run_main(
                        "--source-rom", str(self.source),
                        "--output-bps", str(self.patch_output),
                        "--output-rom", str(rom_output),
                    )
                    self.assertNotEqual(0, status)
                    self.assertIn(
                        "--output-bps and --output-rom must be different files", stderr
                    )
                    self.assertEqual(existing, self.patch_output.read_bytes())
                    self.assertEqual(self.source_bytes, self.source.read_bytes())
                finally:
                    if rom_output != self.patch_output:
                        rom_output.unlink(missing_ok=True)

    def test_default_outputs_cannot_equal_source(self) -> None:
        for suffix, option in (("bps", "--output-bps"), ("bin", "--output-rom")):
            with self.subTest(suffix=suffix):
                source = self.directory / f"fixture-v1.0.{suffix}"
                source.write_bytes(self.source_bytes)
                status, stderr = self.run_main("--source-rom", str(source))
                self.assertNotEqual(0, status)
                self.assertIn(f"{option} must be different from --source-rom", stderr)
                self.assertEqual(self.source_bytes, source.read_bytes())
                other_suffix = "bin" if suffix == "bps" else "bps"
                self.assertFalse(
                    (self.directory / f"fixture-v1.0.{other_suffix}").exists()
                )
                source.unlink()

    def test_distinct_outputs_build_and_preserve_source(self) -> None:
        status, stderr = self.run_main(
            "--source-rom", str(self.source),
            "--output-bps", str(self.patch_output),
            "--output-rom", str(self.rom_output),
        )
        self.assertEqual(0, status, stderr)
        self.assertEqual(self.source_bytes, self.source.read_bytes())
        target = self.rom_output.read_bytes()
        self.assertEqual(b"QA", target[0x200:0x202])
        self.assertEqual(
            target,
            builder.apply_our_bps(self.source_bytes, self.patch_output.read_bytes()),
        )


if __name__ == "__main__":
    unittest.main()
