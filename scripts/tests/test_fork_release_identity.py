"""Keep fork releases bound to the personal repository during migration."""

from pathlib import Path
import importlib.util
import unittest

ROOT = Path(__file__).resolve().parents[2]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


ARTIFACT = module("fork_artifact_info", "release-artifact-info.py")
DIGEST = module("fork_release_digest", "release-source-digest.py")


def manifest(owner):
    return (
        "let package = Package(targets: [\n"
        "  .binaryTarget(\n"
        '    name: "libvlc",\n'
        f'    url: "https://github.com/{owner}/SwiftVLC/releases/download/v1.1.0-beta.14-tonyflix.1/libvlc.xcframework.zip",\n'
        '    checksum: "' + "a" * 64 + '"\n'
        "  )\n])\n"
    )


class ForkReleaseIdentityTests(unittest.TestCase):
    def test_personal_release_asset_is_accepted(self):
        parsed = ARTIFACT.parse_manifest(
            manifest("tonyredondo"), "v1.1.0-beta.14-tonyflix.1"
        )
        self.assertEqual(parsed["tag"], "v1.1.0-beta.14-tonyflix.1")

    def test_upstream_asset_cannot_be_resolved_as_our_release(self):
        with self.assertRaises(SystemExit):
            ARTIFACT.parse_manifest(manifest("harflabs"), None)

    def test_foreign_repository_is_rejected(self):
        with self.assertRaises(SystemExit):
            ARTIFACT.parse_manifest(manifest("unrelated-owner"), None)

    def test_package_owner_migration_preserves_native_source_identity(self):
        self.assertEqual(
            DIGEST.normalized_package_manifest(manifest("harflabs").encode()),
            DIGEST.normalized_package_manifest(manifest("tonyredondo").encode()),
        )

    def test_showcase_owner_migration_preserves_native_source_identity(self):
        old = (
            ROOT / "Showcase/SwiftVLCShowcase.xcodeproj/project.pbxproj"
        ).read_bytes()
        old = old.replace(b"tonyredondo/SwiftVLC", b"harflabs/SwiftVLC")
        new = old.replace(b"harflabs/SwiftVLC", b"tonyredondo/SwiftVLC")
        self.assertEqual(
            DIGEST.normalized_showcase_project(old),
            DIGEST.normalized_showcase_project(new),
        )

    def test_foreign_package_is_not_an_allowed_metadata_migration(self):
        with self.assertRaises(SystemExit):
            DIGEST.normalized_package_manifest(manifest("unrelated-owner").encode())


if __name__ == "__main__":
    unittest.main()
