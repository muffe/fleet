"""Read-only comparisons for the Fleet installer. No package or network calls."""

from collections import Counter
import difflib
import hashlib
import json
import os
from pathlib import Path
import socket


def exists(path):
    return path.exists() or path.is_symlink()


def kind(path):
    if path.is_symlink():
        return "symlink"
    if path.is_dir():
        return "directory"
    return "file" if path.exists() else "missing"


def tree(path):
    """Hash regular files, recording nested symlinks without following them."""
    result = {}
    if not path.is_dir():
        return result
    def on_error(error):
        raise error

    for parent, directories, files in os.walk(path, followlinks=False, onerror=on_error):
        for name in directories[:] + files:
            child = Path(parent) / name
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                result[relative] = {"link": os.readlink(child)}
                if name in directories:
                    directories.remove(name)
            elif child.is_file():
                result[relative] = {"sha256": hashlib.sha256(child.read_bytes()).hexdigest()}
    return result


def text_diff(current, desired, before, after):
    return "\n".join(difflib.unified_diff(
        current.decode("utf-8", errors="replace").splitlines(),
        desired.decode("utf-8", errors="replace").splitlines(),
        fromfile=before, tofile=after, lineterm="",
    ))


def link_change(path, source):
    current_kind = kind(path)
    same = path.is_symlink() and path.resolve() == source.resolve()
    # The canonical skill location may already be reached through a parent link.
    same = same or (path.is_dir() and path.resolve() == source.resolve())
    status = "CURRENT" if same else "ADD" if current_kind == "missing" else "REPLACE"
    return {
        "path": str(path), "target": str(source), "status": status,
        "currentKind": current_kind,
        "currentTarget": os.readlink(path) if path.is_symlink() else None,
        "replacedEntries": sorted(tree(path)) if current_kind == "directory" and not same else [],
    }


def instruction_change(path, source, link_target=None):
    change = link_change(path, link_target or source)
    if change["currentKind"] == "directory":
        change["status"] = "BLOCKED"
        change["error"] = "Expected an instruction file, but found a directory."
        return change
    current = path.read_bytes() if path.is_file() else b""
    desired = source.read_bytes()
    change["contentChanged"] = current != desired
    if change["contentChanged"] and change["status"] == "CURRENT":
        change["status"] = "MODIFY"
    change["diff"] = text_diff(current, desired, str(path), str(link_target or source))
    return change


def expected_files(root, skill, baseline):
    if "path" in skill:
        source = root / skill["path"]
        if not (source / "SKILL.md").is_file():
            raise ValueError(f"Missing custom skill: {source}")
        entries = tree(source)
        if any("link" in value for value in entries.values()):
            raise ValueError(f"Custom skill contains symlinks: {source}")
        return {name: [value["sha256"]] for name, value in entries.items()}, source
    entry = baseline.get("skills", {}).get(skill["name"])
    identity = ("source", "commit", "skillPath")
    if not entry or any(entry.get(key) != skill.get(key) for key in identity):
        raise ValueError(f"No file baseline for {skill['name']} at its selected revision. Capture hashes before applying.")
    folder = str(Path(skill["skillPath"]).parent).replace("\\", "/")
    url = f"https://github.com/{skill['source']}/tree/{skill['commit']}"
    if folder != ".":
        url += "/" + folder
    if skill["installUrl"] != url:
        raise ValueError(f"Install URL does not match the captured source/revision for {skill['name']}")
    alternatives = entry.get("equivalentHashes", {})
    return {name: [sha, *alternatives.get(name, [])] for name, sha in entry["files"].items()}, None


def skill_change(root, home, claude_directory, skill, baseline, target_checkout=None):
    path = home / ".agents/skills" / skill["name"]
    expected, custom_source = expected_files(root, skill, baseline)
    current = tree(path)
    changes = []
    for relative in sorted(expected.keys() | current.keys()):
        actual = current.get(relative)
        wanted = expected.get(relative)
        status = "ADD" if actual is None else "REMOVE" if wanted is None else "CURRENT"
        if actual is not None and wanted is not None and actual.get("sha256") not in wanted:
            status = "MODIFY"
        if status != "CURRENT":
            file = {"path": relative, "status": status}
            if custom_source and relative in expected and (custom_source / relative).suffix == ".md":
                old_path = path / relative
                # Never follow an unexpected file or directory symlink for a diff.
                has_link = path.is_symlink() or any(
                    (path / Path(*Path(relative).parts[:i])).is_symlink()
                    for i in range(1, len(Path(relative).parts) + 1)
                )
                old = old_path.read_bytes() if old_path.is_file() and not has_link else b""
                destination = (target_checkout or root) / skill["path"] / relative
                file["diff"] = text_diff(old, (custom_source / relative).read_bytes(), str(old_path), str(destination))
            changes.append(file)
    links = []
    if "claude-code" in skill["agents"]:
        links.append(link_change(claude_directory / "skills" / skill["name"], path))
    status = "ADD" if not exists(path) else "MODIFY" if changes or not path.is_dir() else "CURRENT"
    if status == "CURRENT" and any(link["status"] != "CURRENT" for link in links):
        status = "LINK"
    return {
        "name": skill["name"], "path": str(path), "status": status,
        "currentKind": kind(path), "currentTarget": os.readlink(path) if path.is_symlink() else None,
        "files": changes, "expectedFileCount": len(expected),
        "source": skill.get("installUrl", str((target_checkout or root) / skill["path"]) if custom_source else ""),
        "links": links,
    }


def build_report(root, home, manifest, targets, target_checkout=None):
    report = {
        "machine": socket.gethostname(), "home": str(home), "checkout": str(target_checkout or root),
        "instructions": [], "skills": [], "preserved": [], "errors": [],
    }
    for target in targets:
        try:
            destination = (target_checkout or root) / "instructions.md"
            change = instruction_change(target, root / "instructions.md", destination)
            report["instructions"].append(change)
            if "error" in change:
                report["errors"].append(f"{target}: {change['error']}")
        except OSError as error:
            report["errors"].append(f"Cannot inspect {target}: {error}")
    if manifest is not None:
        baseline = json.loads((root / "skills-baseline.json").read_text())
        claude_directory = Path(os.environ.get("CLAUDE_CONFIG_DIR", "").strip() or home / ".claude").expanduser()
        selected = {skill["name"] for skill in manifest["skills"] + manifest["custom"]}
        for skill in manifest["skills"] + manifest["custom"]:
            try:
                report["skills"].append(skill_change(root, home, claude_directory, skill, baseline, target_checkout))
            except (OSError, ValueError) as error:
                report["errors"].append(f"Cannot inspect {skill['name']}: {error}")
        for directory in [home / ".agents/skills", claude_directory / "skills"]:
            if directory.is_dir():
                report["preserved"].extend(str(p) for p in sorted(directory.iterdir()) if p.name not in selected)
        codex_directory = Path(os.environ.get("CODEX_HOME", "").strip() or home / ".codex").expanduser()
        if exists(codex_directory / "skills"):
            report["preserved"].append(str(codex_directory / "skills") + " (existing provider skills and aliases)")
        report["sideEffects"] = [
            f"The package CLI reinstalls all {len(selected)} selected skills, including CURRENT payloads; it does not skip them.",
            f"The package CLI updates installation metadata in {home / '.agents/.skill-lock.json'}.",
            "npx may download the pinned CLI and populate its cache; upstream skill sources may be downloaded.",
            "Extra files inside selected skill directories are replaced; unrelated skill directories are preserved.",
            "If a Claude symlink cannot be created, the package CLI may fall back to a copy.",
        ]
    else:
        report["sideEffects"] = []
    report["sideEffects"].append(f"Apply saves affected existing files under {home / '.local/state/fleet/backups/<timestamp>'}.")
    report["summary"] = {
        "instructions": dict(Counter(x["status"] for x in report["instructions"])),
        "skills": dict(Counter(x["status"] for x in report["skills"])),
        "skillFiles": dict(Counter(f["status"] for x in report["skills"] for f in x["files"])),
    }
    return report


def print_link(change, indent=""):
    print(f"{indent}{change['status']} {change['path']} -> {change['target']}")
    if change["status"] != "CURRENT" and change["currentKind"] != "missing":
        old = f" -> {change['currentTarget']}" if change["currentTarget"] else ""
        print(f"{indent}  replaces {change['currentKind']}{old}")
    for entry in change["replacedEntries"]:
        print(f"{indent}  REMOVE old directory entry: {entry}")


def print_report(report, dry_run=True):
    print(f"Fleet preview on {report['machine']} ({report['home']})")
    for change in report["instructions"]:
        print()
        print_link(change)
        if change.get("diff"):
            print(change["diff"])
        elif change.get("contentChanged"):
            print("  Content differs only in line endings or final newline.")
        elif change["status"] != "CURRENT" and "error" not in change:
            print("  Same text; the file/link will be replaced with the shared link.")
    if report["skills"]:
        print("\nSkills (file comparisons against the captured pinned baseline):")
    for skill in report["skills"]:
        counts = Counter(file["status"] for file in skill["files"])
        details = ", ".join(f"{count} {status.lower()}" for status, count in counts.items())
        print(f"\n{skill['status']} {skill['name']} ({details or str(skill['expectedFileCount']) + ' matching files'})")
        print(f"  {skill['path']}\n  Source: {skill['source']}")
        if skill["currentKind"] == "symlink":
            print(f"  Replaces canonical symlink -> {skill['currentTarget']}")
        elif skill["currentKind"] == "file":
            print("  The canonical skill path is currently a file; the package replaces it with a directory.")
        for file in skill["files"]:
            print(f"  {file['status']} {file['path']}")
            if file.get("diff"):
                print(file["diff"])
        for link in skill["links"]:
            if link["status"] != "CURRENT":
                print_link(link, "  ")
    if report["preserved"]:
        print("\nPreserved outside the selected skills:")
        for path in report["preserved"]:
            print(f"  KEEP {path}")
    print("\nSummary:")
    for area, counts in report["summary"].items():
        print(f"  {area}: " + (", ".join(f"{n} {status.lower()}" for status, n in counts.items()) or "none"))
    print("\nOther apply effects:")
    for effect in report["sideEffects"]:
        print(f"  {effect}")
    for error in report["errors"]:
        print(f"\nBLOCKED: {error}")
    if dry_run:
        print("\nDry run: no files changed, no backups created, no packages run or downloaded.")
        print("Add --apply to perform this plan on this machine.")
    else:
        print("\nApplying the plan above after local backups.")
