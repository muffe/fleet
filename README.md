# Fleet

Fleet is built around [T3 Code](https://github.com/pingdotgg/t3code): one thread coordinates shared agent instructions and skills across your linked computers. T3 Code provides access to each machine and runs concurrent workers for previews, reviewed updates, and verification, bringing their results back into the same thread.

Claude Code and Codex read one shared instruction file, while a pinned skill manifest records which upstream versions to install. Each machine keeps a local copy so the installed configuration works offline.

This is a personal configuration repository with a reusable installer. The checked-in instructions and skill selection reflect the owner's preferences. Review and adapt them before applying anything to your own machine.

T3 Code is the core of the multi-machine workflow. The Python installer is its per-machine engine and can also be run directly on a single computer. Syncs happen on request; there is no background sync service.

## How it works

Each machine keeps a local copy of the configuration so it works offline. Both agents' global instruction files point to that copy:

```text
~/.claude/CLAUDE.md  -> <local fleet directory>/instructions.md
~/.codex/AGENTS.md   -> <local fleet directory>/instructions.md
```

Skills are installed through the `skills` npm package into `~/.agents/skills`, with links for Claude Code. The installer compares actual files and links against the selected versions before changing them, then creates local backups when applying.

The shared files are:

| File | Purpose |
| --- | --- |
| [`instructions.md`](instructions.md) | Common global instructions for Claude Code and Codex. |
| [`skills.json`](skills.json) | Selected skills, upstream commit pins, target agents, and package CLI version. |
| [`skills-baseline.json`](skills-baseline.json) | Expected upstream file hashes for offline comparisons and post-install verification. |
| [`machines.example.json`](machines.example.json) | Template for the machines coordinated through T3 Code. |
| [`scripts/install.py`](scripts/install.py) | Per-machine dry run and installer. |
| [`scripts/fleet_report.py`](scripts/fleet_report.py) | Combines collected machine results into local HTML and text reports. |

The public manifest currently selects 43 upstream skills. Their contents stay in their original repositories; this repository records their revisions and expected hashes. Additional private skills can be selected locally without publishing their contents.

## Try it on one machine

Requirements: Python 3, Git, and Node.js 22.20.0 or newer with `npx`. The installer pins `skills` to version 1.7.0. Applying downloads packages and skill sources; a dry run uses local files only. T3 Code is optional for single-machine use.

The paths and symlinks are designed for Linux and macOS. Native Windows support has not been verified.

Clone the repository to a directory you intend to keep:

```sh
git clone https://github.com/muffe/fleet.git ~/.config/fleet
cd ~/.config/fleet
python3 scripts/install.py --dry-run
```

Before applying, read `instructions.md` and the selected skills in `skills.json`. If you want to maintain your own configuration, fork the repository and clone your fork instead.

The dry run shows:

- Instruction text diffs and the files or links that would be replaced.
- Added, modified, and removed files within each selected skill, plus Claude link changes.
- Text diffs for local custom Markdown skills. Upstream comparisons use pinned file hashes.
- Unrelated and provider-managed skills that will be preserved.
- Backup locations and the package, cache, and metadata changes an apply can make.

Running the installer without flags is also a dry run. It does not change configuration, create backups or bytecode caches, run the package CLI, or access the network. A missing or stale upstream baseline blocks the comparison rather than guessing.

To inspect only part of the configuration or save a report:

```sh
python3 scripts/install.py --dry-run --only instructions
python3 scripts/install.py --dry-run --only skills
python3 scripts/install.py --dry-run --commands
python3 scripts/install.py --dry-run --json > fleet-dry-run.json
```

Reports may include existing private instruction text. Keep them local; `fleet-dry-run.*` files are ignored by Git.

Once you have reviewed the plan:

```sh
python3 scripts/install.py --apply
```

The installer backs up affected instructions, selected skill folders, agent links, and the skills lock under `~/.local/state/fleet/backups/`. It installs the selected skills, verifies their payloads, then links the global instructions. `CLAUDE_CONFIG_DIR` and `CODEX_HOME` override the respective instruction locations. Keep the local fleet directory in place while the links are active.

`--only instructions` and `--only skills` also work with `--apply`. Reapplying instruction links is idempotent. `CURRENT` means the content matches; applying still reinstalls selected skills and updates package metadata. If a skill install fails, earlier skill installations may already have completed, but the installer stops before replacing instruction links. Backups remain available.

Unrelated skills, account-synced Claude skills, and Codex's bundled `.system` skills are preserved. Claude-specific workflows remain marked for Claude installation; discovery in a shared directory does not make them portable to Codex.

## Add private skills

Private skills are optional. Create an ignored `skills.local.json` beside `skills.json` to select additional local directories:

```json
{
  "custom": [
    {
      "name": "my-writing",
      "path": "private-skills/my-writing",
      "agents": ["claude-code", "codex"]
    }
  ]
}
```

Put the skill's `SKILL.md` and any reference files in the selected directory. Paths must stay inside the checkout, and skill names must be unique across the public and local manifests. Local entries contain only `name`, `path`, and `agents`.

The installer includes these skills in the same preview, backup, install, and verification flow. Their expected hashes come from the local source files. A missing selected directory blocks the preview. Without `skills.local.json`, the public checkout works on its own.

Both `skills.local.json` and `private-skills/` are ignored. Private skills need a separate local backup or private transfer between machines; cloning this repository does not recover them. Any private writing profile belongs with these local skills.

## Use it across machines with T3 Code

T3 Code's linked environments let a coordinating agent access your other computers. Fleet's [project skill](.agents/skills/fleet/SKILL.md) describes how to dispatch concurrent workers, collect their results, apply an approved revision, and archive the workers afterward. This orchestration runs through an agent in T3 Code, rather than a standalone fleet command.

In the checkout you use to coordinate your fleet:

```sh
cp machines.example.json machines.json
```

Edit the local `machines.json`:

1. Set `repository` to the repository you maintain, such as your fork.
2. Add or remove machine entries to match your fleet.
3. Replace every `environmentId` placeholder with the actual ID discovered through T3 Code.
4. Set `checkout` to the stable configuration directory on each machine. `~` expands on that machine.
5. Choose `git` for an existing checkout or `snapshot` for a directory of deployed configuration files.

`machines.json` is ignored by Git. Machine IDs, local paths, and deployment records stay on the coordinating machine.

Ask **"dry run fleet"** in a T3 Code thread opened in this repository. The agent uses one exact published commit for all configured machines, starts remote workers concurrently, and gathers one combined report. Offline or blocked machines are reported separately.

Preview sources are staged in temporary directories. Existing live checkouts are left in place because updating a file already linked as global instructions would itself change active configuration. The dry-run-only `--target-checkout <path>` option predicts the eventual permanent instruction links while comparing a staged source.

For private skills, the coordinator transfers the local manifest and source files through T3 into each worker's temporary staging directory. It records their hashes so the reviewed private payload is identical across machines. Private files stay outside Git. If transfer is unavailable, the private portion is reported as blocked rather than silently skipped.

After reviewing the report, ask to apply that revision and private payload to the fleet or to named machines. Snapshot deployments copy the installer and configuration into the stable target directory, recording ownership and file hashes in `.fleet-source.json`. They require no Git checkout or T3 project registration. Existing private sources are backed up, and local drift is reported as a conflict rather than overwritten.

The coordinator saves reports under `.fleet/runs/`, apply receipts under `.fleet/applies/`, and optional rollout summaries in `.fleet/rollout.json`. After collecting results, it stops delegated activity and archives each worker thread, preserving history. Any permission or connectivity blocker is reported.

## Maintain the configuration

Edit the shared source, review a dry run, commit and push, then explicitly apply the reviewed revision. Each machine keeps its installed configuration until it receives an update. Changes to ignored private skills need their own reviewed transfer and backup.

For instructions, edit `instructions.md`. For upstream skills, update the selected names or commit pins in `skills.json` and capture the corresponding file hashes in `skills-baseline.json`. Keep both files consistent: the installer rejects stale baselines and verifies installed files against them. Normal applies use the pinned revisions rather than silently upgrading to upstream HEAD.

When applying upstream changes to a checkout whose instructions are already linked globally, stage and review them separately first. Pulling directly into that live checkout immediately changes the linked instructions.

## Keep local data private

The public configuration contains shared instructions, the upstream skill selection, file hashes, scripts, tests, and a machine template. Actual machine mappings, source inventories, rollout records, private skills and writing samples, reports, backups, and credentials belong outside version control.

Local fleet state lives under ignored `.fleet/`. The root `machines.json`, legacy `rollout.json` and `sources/` paths, private skill locations, `.env` files, editor swap files, and dry-run output are also ignored. Review staged changes before pushing: ignore rules do not remove files already committed to Git history.

This repository does not copy provider credentials, account settings, or T3 Code settings between machines.

## Run the checks

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

The tests cover file comparisons, stale baselines, private skill selection and validation, symlink replacement, custom text diffs, preserved skills, read-only CLI behavior, instruction backup/idempotence, staged previews, and combined reports.
