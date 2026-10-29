import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from preview import build_report, tree


def sha(content):
    return hashlib.sha256(content).hexdigest()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        write(self.root / "instructions.md", b"new instruction\n")
        self.skill = {
            "name": "sample", "source": "owner/repo", "commit": "a" * 40,
            "skillPath": "skills/sample/SKILL.md",
            "installUrl": "https://github.com/owner/repo/tree/" + "a" * 40 + "/skills/sample",
            "agents": ["claude-code", "codex"],
        }
        self.manifest = {"skills": [self.skill], "custom": []}
        self.baseline = {"version": 1, "skills": {"sample": {
            "source": self.skill["source"], "commit": self.skill["commit"],
            "skillPath": self.skill["skillPath"],
            "files": {"SKILL.md": sha(b"new skill\n"), "reference.md": sha(b"reference\n")},
        }}}
        self.save_baseline()
        self.environment = dict(os.environ)
        self.environment.pop("CLAUDE_CONFIG_DIR", None)
        self.environment.pop("CODEX_HOME", None)

    def save_baseline(self):
        (self.root / "skills-baseline.json").write_text(json.dumps(self.baseline))

    def report(self):
        from unittest.mock import patch
        with patch.dict(os.environ, self.environment, clear=True):
            return build_report(self.root, self.home, self.manifest, [self.home / ".claude/CLAUDE.md"])

    def test_real_instruction_and_skill_changes_are_reported_without_writes(self):
        write(self.home / ".claude/CLAUDE.md", b"old instruction\n")
        write(self.home / ".agents/skills/sample/SKILL.md", b"old skill\n")
        write(self.home / ".agents/skills/sample/extra.md", b"local extra\n")
        write(self.home / ".agents/skills/legacy/SKILL.md", b"keep me\n")
        write(self.home / ".claude/skills/synced/profile/SKILL.md", b"provider owned\n")
        write(self.home / ".codex/skills/.system/tool/SKILL.md", b"bundled\n")
        before = tree(self.home)
        report = self.report()
        self.assertEqual(tree(self.home), before)
        self.assertFalse(report["errors"])
        self.assertIn("-old instruction", report["instructions"][0]["diff"])
        self.assertIn("+new instruction", report["instructions"][0]["diff"])
        changes = {file["path"]: file["status"] for file in report["skills"][0]["files"]}
        self.assertEqual(changes, {"SKILL.md": "MODIFY", "extra.md": "REMOVE", "reference.md": "ADD"})
        self.assertIn(str(self.home / ".agents/skills/legacy"), report["preserved"])
        self.assertIn(str(self.home / ".claude/skills/synced"), report["preserved"])
        self.assertTrue(any(".codex/skills" in path for path in report["preserved"]))
        self.assertFalse((self.home / ".local").exists())

    def test_matching_payload_and_links_are_current(self):
        canonical = self.home / ".agents/skills/sample"
        write(canonical / "SKILL.md", b"new skill\n")
        write(canonical / "reference.md", b"reference\n")
        target = self.home / ".claude/skills/sample"
        target.parent.mkdir(parents=True)
        target.symlink_to(canonical)
        (self.home / ".claude/CLAUDE.md").symlink_to(self.root / "instructions.md")
        report = self.report()
        self.assertEqual(report["skills"][0]["status"], "CURRENT")
        self.assertEqual(report["skills"][0]["files"], [])
        self.assertEqual(report["instructions"][0]["status"], "CURRENT")

    def test_correct_contents_with_wrong_claude_link_report_link_change(self):
        write(self.home / ".agents/skills/sample/SKILL.md", b"new skill\n")
        write(self.home / ".agents/skills/sample/reference.md", b"reference\n")
        old_copy = self.home / ".claude/skills/sample"
        write(old_copy / "old.md", b"will be replaced\n")
        report = self.report()
        self.assertEqual(report["skills"][0]["status"], "LINK")
        link = report["skills"][0]["links"][0]
        self.assertEqual(link["status"], "REPLACE")
        self.assertEqual(link["replacedEntries"], ["old.md"])

    def test_unexpected_symlinks_are_not_followed_for_hashes(self):
        outside = Path(self.temporary.name) / "private.txt"
        outside.write_text("private content")
        canonical = self.home / ".agents/skills/sample"
        canonical.mkdir(parents=True)
        (canonical / "SKILL.md").symlink_to(outside)
        report = self.report()
        changes = {file["path"]: file["status"] for file in report["skills"][0]["files"]}
        self.assertEqual(changes["SKILL.md"], "MODIFY")
        self.assertEqual(outside.read_text(), "private content")

    def test_changed_pin_or_url_cannot_reuse_stale_file_hashes(self):
        self.skill["commit"] = "b" * 40
        self.assertIn("No file baseline", self.report()["errors"][0])
        self.skill["commit"] = "a" * 40
        self.skill["installUrl"] += "/wrong"
        self.assertIn("Install URL", self.report()["errors"][0])

    def test_known_line_ending_variant_is_not_a_false_modification(self):
        entry = self.baseline["skills"]["sample"]
        entry["files"] = {"SKILL.md": sha(b"new skill\r\n")}
        entry["equivalentHashes"] = {"SKILL.md": [sha(b"new skill\n")]}
        self.save_baseline()
        write(self.home / ".agents/skills/sample/SKILL.md", b"new skill\n")
        self.assertEqual(self.report()["skills"][0]["files"], [])

    def test_instruction_directory_is_reported_as_blocked(self):
        (self.home / ".claude/CLAUDE.md").mkdir(parents=True)
        report = self.report()
        self.assertEqual(report["instructions"][0]["status"], "BLOCKED")
        self.assertTrue(report["errors"])
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/install.py"), "--only", "instructions", "--apply"],
            env=dict(self.environment, HOME=str(self.home)), capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.home / ".codex").exists())

    def test_custom_markdown_diff_contains_both_versions(self):
        self.manifest = {"skills": [], "custom": [{"name": "voice", "path": "skills/voice", "agents": ["claude-code", "codex"]}]}
        write(self.root / "skills/voice/SKILL.md", b"new voice\n")
        write(self.home / ".agents/skills/voice/SKILL.md", b"old voice\n")
        diff = self.report()["skills"][0]["files"][0]["diff"]
        self.assertIn("-old voice", diff)
        self.assertIn("+new voice", diff)

    def test_actual_cli_dry_run_has_no_home_or_checkout_side_effects(self):
        # A fake npx fails loudly if a preview accidentally executes it.
        fake_bin = self.home / "bin"
        write(fake_bin / "npx", b"#!/bin/sh\nexit 99\n")
        (fake_bin / "npx").chmod(0o755)
        env = dict(self.environment, HOME=str(self.home), PATH=str(fake_bin))
        before_home = tree(self.home)
        before_checkout = tree(ROOT / "scripts")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), "--dry-run", "--json"], env=env, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertFalse(report["errors"])
        self.assertTrue(report["skills"])
        self.assertEqual(tree(self.home), before_home)
        self.assertEqual(tree(ROOT / "scripts"), before_checkout)

    def test_instruction_apply_still_backs_up_and_is_idempotent(self):
        target = self.home / ".claude/CLAUDE.md"
        write(target, b"original\n")
        env = dict(self.environment, HOME=str(self.home))
        command = [sys.executable, str(ROOT / "scripts/install.py"), "--only", "instructions", "--apply"]
        subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        backups = list((self.home / ".local/state/fleet/backups").iterdir())
        self.assertEqual((backups[0] / ".claude/CLAUDE.md").read_bytes(), b"original\n")
        self.assertEqual(target.resolve(), ROOT / "instructions.md")
        subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        self.assertEqual(len(list((self.home / ".local/state/fleet/backups").iterdir())), 1)

    def test_staged_preview_compares_new_content_without_touching_live_checkout(self):
        stable = self.home / "fleet"
        write(stable / "instructions.md", b"currently live\n")
        target = self.home / ".claude/CLAUDE.md"
        target.parent.mkdir()
        target.symlink_to(stable / "instructions.md")
        report = build_report(self.root, self.home, None, [target], target_checkout=stable)
        change = report["instructions"][0]
        self.assertEqual(change["status"], "MODIFY")
        self.assertEqual(change["target"], str(stable / "instructions.md"))
        self.assertIn("-currently live", change["diff"])
        self.assertIn("+new instruction", change["diff"])
        self.assertEqual((stable / "instructions.md").read_bytes(), b"currently live\n")

    def test_target_checkout_cli_is_preview_only_and_uses_permanent_paths(self):
        # Exercise a standalone checkout with private skills, not the developer's profile.
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ["install.py", "preview.py"]:
            shutil.copy2(ROOT / "scripts" / name, scripts / name)
        manifest = {"cli": {"version": "1.7.0"}, "skills": [], "custom": []}
        (self.root / "skills.json").write_text(json.dumps(manifest))
        local = {"custom": [{"name": "local-writing", "path": "private-skills/local-writing", "agents": ["claude-code", "codex"]}]}
        (self.root / "skills.local.json").write_text(json.dumps(local))
        write(self.root / "private-skills/local-writing/SKILL.md", b"private writing preference\n")
        stable = self.home / "future-fleet"
        env = dict(self.environment, HOME=str(self.home))
        command = [sys.executable, str(scripts / "install.py"), "--target-checkout", str(stable)]
        before = tree(self.root), tree(self.home)
        result = subprocess.run(command + ["--dry-run", "--json"], env=env, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report["checkout"], str(stable))
        self.assertTrue(all(x["target"] == str(stable / "instructions.md") for x in report["instructions"]))
        voice = next(x for x in report["skills"] if x["name"] == "local-writing")
        self.assertEqual(voice["source"], str(stable / "private-skills/local-writing"))
        self.assertIn("+private writing preference", voice["files"][0]["diff"])
        self.assertEqual(report["commands"][0][4], str(stable / "private-skills/local-writing"))
        self.assertEqual((tree(self.root), tree(self.home)), before)
        self.assertFalse(stable.exists())
        blocked = subprocess.run(command + ["--apply"], env=env, capture_output=True, text=True)
        self.assertNotEqual(blocked.returncode, 0)
        self.assertFalse((self.home / ".local").exists())
        self.assertFalse((self.home / ".claude").exists())

    def test_private_skills_are_optional_and_do_not_change_the_public_manifest(self):
        from install import load_manifest
        public = {"skills": [], "custom": []}
        path = self.root / "skills.json"
        path.write_text(json.dumps(public))
        self.assertEqual(load_manifest(self.root), public)
        local = {"custom": [{"name": "local-writing", "path": "private-skills/local-writing", "agents": ["claude-code"]}]}
        (self.root / "skills.local.json").write_text(json.dumps(local))
        manifest = load_manifest(self.root)
        report = build_report(self.root, self.home, manifest, [])
        self.assertIn("Missing custom skill", report["errors"][0])
        write(self.root / "private-skills/local-writing/SKILL.md", b"private preference\n")
        report = build_report(self.root, self.home, load_manifest(self.root), [])
        self.assertFalse(report["errors"])
        self.assertEqual(report["skills"][0]["name"], "local-writing")
        self.assertEqual(json.loads(path.read_text()), public)

    def test_private_skill_conflicts_and_paths_fail_before_applying(self):
        from install import load_manifest
        (self.root / "skills.json").write_text(json.dumps(self.manifest))
        local = {"name": "local-writing", "path": "private-skills/local-writing", "agents": ["codex"]}
        cases = [
            ({**local, "name": "sample"}, "unique"),
            ({**local, "path": "../outside"}, "inside the checkout"),
            ({**local, "path": str(self.home)}, "relative path"),
            ({**local, "agents": []}, "agents"),
            ({**local, "name": "../outside"}, "directory names"),
            ({**local, "installUrl": "https://example.com"}, "name, path, and agents only"),
        ]
        for entry, message in cases:
            with self.subTest(entry=entry):
                (self.root / "skills.local.json").write_text(json.dumps({"custom": [entry]}))
                with self.assertRaisesRegex(ValueError, message):
                    load_manifest(self.root)
        scripts = self.root / "scripts"
        scripts.mkdir()
        for name in ["install.py", "preview.py"]:
            shutil.copy2(ROOT / "scripts" / name, scripts / name)
        (self.root / "skills.local.json").write_text("{invalid json")
        result = subprocess.run(
            [sys.executable, str(scripts / "install.py"), "--apply"],
            env=dict(self.environment, HOME=str(self.home)), capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Cannot load skill selection", result.stderr)
        self.assertFalse((self.home / ".local").exists())

    def test_claude_only_package_copy_is_normalized_with_originals_preserved(self):
        from install import finalize_skills
        self.skill["agents"] = ["claude-code"]
        source = self.home / ".claude/skills/sample"
        canonical = self.home / ".agents/skills/sample"
        write(source / "SKILL.md", b"new skill\n")
        write(source / "reference.md", b"reference\n")
        write(canonical / "SKILL.md", b"previous version\n")
        saved = self.home / "backups"
        saved.mkdir()
        finalize_skills(self.manifest, self.home, saved, root=self.root)
        self.assertTrue(source.is_symlink())
        self.assertEqual(source.resolve(), canonical)
        self.assertEqual((canonical / "SKILL.md").read_bytes(), b"new skill\n")
        archived = saved / "layout-normalization/.agents/skills/sample/SKILL.md"
        self.assertEqual(archived.read_bytes(), b"previous version\n")
        finalize_skills(self.manifest, self.home, saved, root=self.root)
        self.assertEqual(self.report()["skills"][0]["status"], "CURRENT")

    def test_only_known_packaging_metadata_is_archived(self):
        from install import finalize_skills
        entry = self.baseline["skills"]["sample"]
        entry["omittedFiles"] = {".claude-plugin/plugin.json": sha(b"known metadata\n")}
        self.save_baseline()
        canonical = self.home / ".agents/skills/sample"
        metadata = canonical / ".claude-plugin/plugin.json"
        write(metadata, b"locally changed metadata\n")
        saved = self.home / "backups"
        saved.mkdir()
        with self.assertRaisesRegex(RuntimeError, "Unexpected contents"):
            finalize_skills(self.manifest, self.home, saved, root=self.root)
        self.assertEqual(metadata.read_bytes(), b"locally changed metadata\n")
        metadata.write_bytes(b"known metadata\n")
        write(canonical / "unrelated.txt", b"preserve this\n")
        finalize_skills(self.manifest, self.home, saved, root=self.root)
        self.assertFalse(metadata.exists())
        self.assertEqual((saved / "layout-normalization/.agents/skills/sample/.claude-plugin/plugin.json").read_bytes(), b"known metadata\n")
        self.assertEqual((canonical / "unrelated.txt").read_bytes(), b"preserve this\n")


if __name__ == "__main__":
    unittest.main()
