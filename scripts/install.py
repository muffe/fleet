#!/usr/bin/env python3
"""Compare or install this checkout's shared instructions and selected skills."""

import sys

# A preview must not create a __pycache__ directory in the checkout.
sys.dont_write_bytecode = True

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

from preview import build_report, expected_files, print_report, tree


ROOT = Path(__file__).resolve().parent.parent


def load_manifest(root):
    manifest = json.loads((root / "skills.json").read_text())
    local_path = root / "skills.local.json"
    if local_path.exists():
        local = json.loads(local_path.read_text())
        if not isinstance(local, dict) or set(local) != {"custom"} or not isinstance(local["custom"], list):
            raise ValueError("skills.local.json must contain a custom skill list")
        for skill in local["custom"]:
            if not isinstance(skill, dict) or set(skill) != {"name", "path", "agents"}:
                raise ValueError("Local skills require name, path, and agents only")
            name, path, agents = skill["name"], skill["path"], skill["agents"]
            if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name or "\\" in name:
                raise ValueError("Local skill names must be single directory names")
            if not isinstance(path, str) or not path or Path(path).is_absolute() or "\\" in path:
                raise ValueError(f"Local skill {name} needs a relative path inside the checkout")
            try:
                relative = (root / path).resolve().relative_to(root.resolve())
            except ValueError:
                raise ValueError(f"Local skill {name} must stay inside the checkout") from None
            if not relative.parts:
                raise ValueError(f"Local skill {name} must have its own directory")
            if not isinstance(agents, list) or not agents or any(agent not in ("claude-code", "codex") for agent in agents):
                raise ValueError(f"Local skill {name} needs claude-code and/or codex agents")
        manifest["custom"] = manifest.get("custom", []) + local["custom"]
    names = [skill["name"] for skill in manifest["skills"] + manifest["custom"]]
    if len(names) != len(set(names)):
        raise ValueError("Skill names must be unique across skills.json and skills.local.json")
    return manifest


def instruction_targets(home):
    return [
        Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or home / ".claude").expanduser() / "CLAUDE.md",
        Path(os.environ.get("CODEX_HOME", "").strip() or home / ".codex").expanduser() / "AGENTS.md",
    ]


def skill_commands(manifest, checkout=ROOT):
    cli = f"skills@{manifest['cli']['version']}"
    for skill in manifest["skills"] + manifest["custom"]:
        source = skill.get("installUrl") or str(checkout / skill["path"])
        yield [
            "npx", "--yes", cli, "add", source, "--global",
            "--agent", *skill["agents"], "--skill", skill["name"], "--yes",
        ]


def already_linked(path, source):
    return path.is_symlink() and path.resolve() == source


def backup(paths, home):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = home / ".local/state/fleet/backups" / stamp
    destination.mkdir(parents=True, mode=0o700, exist_ok=False)
    records = []
    for index, path in enumerate(dict.fromkeys(paths)):
        if not path.exists() and not path.is_symlink():
            continue
        try:
            relative = path.relative_to(home)
        except ValueError:
            relative = Path("external") / str(index) / path.name
        saved = destination / relative
        saved.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir() and not path.is_symlink():
            shutil.copytree(path, saved, symlinks=True)
        else:
            shutil.copy2(path, saved, follow_symlinks=False)
        records.append({"original": str(path), "backup": str(saved)})
    (destination / "manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    print(f"Backups: {destination}")
    return destination


def finalize_skills(manifest, home, saved, root=ROOT):
    """Normalize package-specific layouts to the payload shown in the preview."""
    baseline = json.loads((root / "skills-baseline.json").read_text())
    records_path = saved / "manifest.json"
    records = json.loads(records_path.read_text()) if records_path.exists() else []

    def archive(path):
        destination = saved / "layout-normalization" / path.relative_to(home)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(destination))
        records.append({"original": str(path), "backup": str(destination), "reason": "package layout normalization"})
        records_path.write_text(json.dumps(records, indent=2) + "\n")

    for skill in manifest["skills"] + manifest["custom"]:
        canonical = home / ".agents/skills" / skill["name"]
        if skill["agents"] == ["claude-code"]:
            source = instruction_targets(home)[0].parent / "skills" / skill["name"]
            # The CLI uses a direct copy when only Claude is selected.
            if source.is_dir() and not source.is_symlink() and source.resolve() != canonical.resolve():
                expected, _ = expected_files(root, skill, baseline)
                actual = tree(source)
                if actual.keys() != expected.keys() or any(actual[name].get("sha256") not in expected[name] for name in expected):
                    raise RuntimeError(f"Unexpected package payload at {source}; keeping it for inspection")
                if canonical.exists() or canonical.is_symlink():
                    archive(canonical)
                canonical.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(canonical))
                source.symlink_to(os.path.relpath(canonical, source.parent))
        entry = baseline["skills"].get(skill["name"], {})
        for relative, sha in entry.get("omittedFiles", {}).items():
            path = canonical / relative
            if not path.exists() and not path.is_symlink():
                continue
            if path.is_symlink() or not path.is_file() or tree(path.parent).get(path.name, {}).get("sha256") != sha:
                raise RuntimeError(f"Unexpected contents at {path}; not removing them")
            archive(path)
            try:
                path.parent.rmdir()
            except OSError:
                pass


def link_instructions(source, targets):
    for target in targets:
        if already_linked(target, source):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".fleet-", dir=target.parent) as temporary:
            link = Path(temporary) / "instructions"
            link.symlink_to(source)
            os.replace(link, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Compare local files without changing anything (default)")
    mode.add_argument("--apply", action="store_true", help="Install after making local backups")
    parser.add_argument("--only", choices=["all", "instructions", "skills"], default="all")
    parser.add_argument("--json", action="store_true", help="Print the dry-run report as JSON")
    parser.add_argument("--commands", action="store_true", help="Also print the exact skills install commands")
    parser.add_argument("--target-checkout", type=Path, help="Dry run only: plan permanent links while comparing a temporary source snapshot")
    args = parser.parse_args()
    if args.json and args.apply:
        parser.error("--json is available for dry runs only")
    if args.target_checkout and args.apply:
        parser.error("--target-checkout is available for dry runs only")
    home = Path.home()
    try:
        manifest = load_manifest(ROOT)
    except (OSError, ValueError) as error:
        parser.error(f"Cannot load skill selection: {error}")
    source = ROOT / "instructions.md"
    targets = instruction_targets(home) if args.only != "skills" else []
    if targets and not source.is_file():
        parser.error(f"Missing shared instructions: {source}")
    destination = args.target_checkout.expanduser().absolute() if args.target_checkout else ROOT
    commands = list(skill_commands(manifest, destination)) if args.only != "instructions" else []
    report = build_report(ROOT, home, manifest if commands else None, targets, target_checkout=destination)
    if args.json:
        report["commands"] = commands
        print(json.dumps(report, indent=2))
    else:
        print_report(report, dry_run=not args.apply or bool(report["errors"]))
        if args.commands:
            print("\nInstall commands:")
            for command in commands:
                print(shlex.join(command))
    if report["errors"]:
        if args.apply:
            parser.error("Cannot apply: resolve the blocked comparisons above first")
        return 1
    if not args.apply:
        return 0
    if commands:
        version = subprocess.check_output(["node", "-p", "process.versions.node"], text=True).strip()
        minimum = manifest["cli"]["minimumNodeVersion"]
        if tuple(map(int, version.split("."))) < tuple(map(int, minimum.split("."))):
            parser.error(f"Skills requires Node {minimum} or newer; found {version}")
        if not shutil.which("npx"):
            parser.error("npx is required to run the skills package")
        for skill in manifest["custom"]:
            if not (ROOT / skill["path"] / "SKILL.md").is_file():
                parser.error(f"Missing custom skill: {skill['path']}")
    changed = [target for target in targets if not already_linked(target, source)]
    saved_paths = list(changed)
    if commands:
        saved_paths.append(home / ".agents/.skill-lock.json")
        for skill in manifest["skills"] + manifest["custom"]:
            saved_paths.append(home / ".agents/skills" / skill["name"])
            for agent in skill["agents"]:
                directory = instruction_targets(home)[0 if agent == "claude-code" else 1].parent / "skills"
                saved_paths.append(directory / skill["name"])
    saved = backup(saved_paths, home) if saved_paths else None
    # A failed skill install leaves the existing instruction files in place.
    for command in commands:
        subprocess.run(command, check=True)
    if commands:
        finalize_skills(manifest, home, saved)
        verification = build_report(ROOT, home, manifest, [])
        mismatches = [skill["name"] for skill in verification["skills"] if skill["status"] != "CURRENT"]
        if verification["errors"] or mismatches:
            raise RuntimeError(f"Skill verification failed: {verification['errors'] or mismatches}; backups retained at {saved}")
    link_instructions(source, targets)
    print("Installation complete on this machine.")


if __name__ == "__main__":
    raise SystemExit(main())
