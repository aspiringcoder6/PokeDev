"""Verify source/state isolation and dirty-working-tree preservation."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / "prepare.py"
spec = importlib.util.spec_from_file_location("fork_prepare", MODULE)
prep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prep)


class ForkPreparationTests(unittest.TestCase):
    def test_private_and_runtime_files_excluded_even_if_tracked(self):
        for path in (".env", ".env.remote", "adlc-flow/data/intake.sqlite3", "data/state.json",
                     "adlc-flow/frontend/.auth/session.json", "tmp/result.json",
                     "adlc-flow/runtime.sqlite3-wal", "sdk/id_rsa", "sdk/key.pem",
                     "agent-harness-server/src/server.py", "docs/report/example.docx",
                     "deploy/configure_remote.py", "adlc-flow/.venv/pyvenv.cfg"):
            with self.subTest(path=path):
                self.assertFalse(prep.include(path))

    def test_rejects_paths_outside_allowlist(self):
        for path in ("../escape.py", "/etc/passwd", "adlc-flow/../../env", "adlc-flow\\private.py"):
            self.assertFalse(prep.include(path))
        self.assertTrue(prep.include("adlc-flow/langflow/adlc/run_service.py"))
        self.assertTrue(prep.include("integration-sources/workloop/source-lock.json"))

    def test_brand_changes_leave_backend_contract_names_intact(self):
        raw = b'VAI_PLATFORM_URL vAIPlatform VAIPlatformLogo.svg'
        self.assertEqual(prep.rebrand("sdk/config.py", raw, "PokeDev"), raw)
        self.assertEqual(prep.rebrand("adlc-flow/frontend/src/view.tsx", raw, "PokeDev"),
                         b'VAI_PLATFORM_URL PokeDev PokeDevLogo.svg')

    def test_lockfile_root_name_tracks_package_name(self):
        raw = b'{"name":"langflow","packages":{"":{"name":"langflow"},"node_modules/pkg":{"name":"pkg"}}}'
        result = json.loads(prep.rebrand("adlc-flow/frontend/package-lock.json", raw, "PokeDev"))
        self.assertEqual(result["name"], "pokedev")
        self.assertEqual(result["packages"][""]["name"], "pokedev")
        self.assertEqual(result["packages"]["node_modules/pkg"]["name"], "pkg")

    def test_output_cannot_overwrite_or_nest_in_source(self):
        with tempfile.TemporaryDirectory(prefix="pokedev-fork-test-") as temporary:
            base = Path(temporary).resolve()
            source = base / "source"
            source.mkdir()
            occupied = base / "occupied"
            occupied.mkdir()
            (occupied / "keep.txt").write_text("keep")
            for destination in (source, source / "fork", base, occupied):
                with self.subTest(destination=destination), self.assertRaises(ValueError):
                    prep.validate_output(source, destination)
            self.assertEqual((occupied / "keep.txt").read_text(), "keep")

    def test_exports_current_changes_and_omits_deleted_or_private_source(self):
        with tempfile.TemporaryDirectory(prefix="pokedev-fork-test-") as temporary:
            base = Path(temporary).resolve()
            source, output = base / "source", base / "output"
            source.mkdir()
            fixture = {"Readme.md": "original", ".gitignore": "", "AGENTS.md": "desktop",
                       "adlc-flow/langflow/core.py": "original", "sdk/deleted.py": "old",
                       "adlc-flow/langflow/base/data/utils.py": "source module, not runtime state",
                       ".env": "not-a-real-secret", "adlc-flow/data/state.sqlite3": "private state",
                       "adlc-flow/frontend/src/assets/PokeDevLogo.svg": '<svg xmlns="http://www.w3.org/2000/svg"/>',
                       "deploy/fork/README.fork.md": "# PokeDev {{GITHUB_REPOSITORY}}",
                       "deploy/fork/env.example": "LANGFLOW_PORT=7862\n",
                       "deploy/fork/migration.md": "Migration required"}
            for relative, value in fixture.items():
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(value, encoding="utf-8")
            prep.git(source, "init", "--initial-branch=main")
            prep.git(source, "add", "--all")
            prep.git(source, "-c", "user.name=Fork Test", "-c", "user.email=fork-test@localhost", "commit", "-qm", "fixture")
            (source / "adlc-flow/langflow/core.py").write_text("modified")
            (source / "adlc-flow/langflow/new.py").write_text("untracked")
            (source / "sdk/deleted.py").unlink()
            status_before = prep.git(source, "status", "--porcelain=v1")
            preview = prep.prepare(source, output, "PokeDev", "example/PokeDev")
            self.assertFalse(preview["written"])
            self.assertFalse(output.exists())
            result = prep.prepare(source, output, "PokeDev", "example/PokeDev", write=True)
            self.assertTrue(result["written"])
            self.assertEqual((output / "adlc-flow/langflow/core.py").read_text(), "modified")
            self.assertEqual((output / "adlc-flow/langflow/new.py").read_text(), "untracked")
            self.assertFalse((output / "sdk/deleted.py").exists())
            self.assertFalse((output / ".env").exists())
            self.assertFalse((output / "adlc-flow/data").exists())
            self.assertEqual((output / "docs/upstream-readme.md").read_text(), "original")
            self.assertIn("Do not introduce new Workloop dependencies", (output / "AGENTS.md").read_text())
            self.assertEqual(prep.git(source, "status", "--porcelain=v1"), status_before)
            self.assertEqual(prep.git(output, "remote", "get-url", "origin").decode().strip(),
                             "https://github.com/example/PokeDev.git")
            self.assertEqual(prep.git(output, "branch", "--show-current").decode().strip(), "codex/pokedev-fork-prep")
            prep.git(output, "add", "--all")
            self.assertIn("adlc-flow/langflow/base/data/utils.py", prep.git(output, "ls-files").decode().splitlines())
            self.assertEqual(json.loads((output / "fork-baseline.json").read_text())["workloop_migration"], "required")
            with self.assertRaises(ValueError):
                prep.prepare(source, output, "PokeDev", "example/PokeDev", write=True)


if __name__ == "__main__":
    unittest.main()
