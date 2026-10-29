---
name: fleet
description: Orchestrate shared instructions and skills across the machines configured locally for this repository through T3 Code. Use for fleet-wide dry runs, configuration status, or explicitly requested syncs.
---

# Fleet through T3 Code

The user operates this repository centrally. A fleet request defaults to every machine in the local, ignored `machines.json`. Use T3 linked environments to run the per-machine engine concurrently and return one combined result here. The user need not run commands separately on each device.

Machine identities and deployment records stay local. If `machines.json` is absent, use `machines.example.json` as the schema and discover the current and linked environments through T3. Ask for any unresolved machine selection or destination before dispatching; do not use example placeholders as real IDs. Save the confirmed configuration locally and keep it out of Git. The configured `repository` identifies the source to fetch, including when the user maintains a fork.

## Dry run

1. Read `machines.json`. Identify one published source commit and record it for this run. Disclose any uncommitted configuration edits excluded from that commit. Leave unrelated working files alone.
2. Discover T3's linked environments and current environment. Match the configured IDs. Report unreachable machines; continue with reachable ones. If a named machine is not linked, use T3's linking tool with its name.
3. Start one asynchronous `delegate_task` on each reachable remote environment, using a project from that environment and the inherited provider/model. Follow T3's capability discovery requirement. Launch all remote tasks before waiting, then run the current machine's comparison if it is configured. Children do their own work without delegating.
4. Give every worker the same exact source commit, its configured final checkout path, and a dry-run-only brief. Fetch an immutable source archive into temporary data staging using existing repository authentication; keep the child bound to its T3 workspace. Do not pull, reset, checkout, or edit an existing configuration checkout: its instruction file may already be live through symlinks. Do not change global configuration or run the skills package. Report authentication/approval failures without inventing credentials or alternate transport settings.
5. Prepare any private skills as described below, then from the staged source run `python3 scripts/install.py --dry-run --json --target-checkout <configured final checkout>`. Expand `~` on the worker machine. The target option predicts permanent instruction links, not links into a temporary directory. Record the source commit, private payload hashes, machine identity, completion status, and full JSON report. Temporary source staging and report files are the only permitted writes for this preview.
6. Each worker uses code to print one JSON export envelope to its command output: `machine`, `environmentId`, `sourceCommit`, `status`, `reportSha256`, and `reportGzipBase64` (UTF-8 JSON compressed with gzip and base64 encoded). Its final reply is a short receipt, not a manually copied payload. Once completed, the coordinator uses T3 thread activity to find the export command item and reads its raw output, paginating if truncated. Decode and verify SHA-256 before accepting it; large encoded strings copied through an assistant reply can be corrupted. For a blocked worker, retain the error and any available report. Save decoded envelopes under ignored `.fleet/runs/<run>/`; never commit reports because current profile diffs may contain private text.
7. Follow each delegated task's returned continuation instructions; no polling running tasks. On completion, collect results and publish one combined, machine-labelled report here. Keep offline, blocked, and completed states distinct. Check the commit matches across all completed workers before presenting them as one run. Include instruction diffs, skill file/link changes, preserved entries, and installer side effects. Once normalized machine envelopes are saved, `python3 scripts/fleet_report.py .fleet/runs/<run>` writes a combined HTML report and per-machine text files; use T3 HTML preview/render to display the combined report here. State that no configuration was applied.

## Private skills

The installer merges the public `skills.json` with an optional, ignored `skills.local.json` containing additional custom skills. The selected private source directories stay ignored too. Private payloads cannot be fetched from the public archive.

For a fleet preview or apply, read the coordinating checkout's local manifest and capture the hashes of every selected private file. Use T3 to transfer a temporary copy of that manifest and its source directories to each worker's staged source, preserving their relative paths. Keep the copy identical across machines and verify its hashes. Never put private contents in Git, published artifacts, or final replies. If an authorized transfer is unavailable, mark the private portion blocked rather than silently omitting it. Existing unselected skills remain preserved.

Review changes to the private manifest and payload alongside the public commit. Applying uses that same reviewed combination. In a persistent checkout or snapshot, back up existing private files and check for local drift before replacing them. Record their per-file hashes in the local deployment receipt. Do not overwrite a differing client-only manifest or private source without resolving the conflict.

## Apply

An explicit sync/apply request authorizes deployment to its named machines (all configured machines by default). Preview alone does not authorize applying. Use the reviewed public and private payloads and preserve local edits. Leave T3 settings, credentials, unrelated skills, and provider-managed files under their existing ownership.

Respect each configured `deploymentMode`. A `git` machine uses its existing checkout. A `snapshot` machine uses versioned files at its configured path; it does not need a Git repository or T3 project registration. Do not use project clone/create/settings tools for snapshot deployment. Fetch the immutable source archive using existing repository authentication when needed and stage it as data. The public snapshot payload consists of `instructions.md`, `skills.json`, `skills-baseline.json`, `scripts/install.py`, `scripts/preview.py`, and any custom skill paths selected in `skills.json`. Deploy the reviewed private manifest and sources separately through T3.

Before updating a snapshot, check its `.fleet-source.json` owner/revision and recorded file hashes. Preserve local drift as a conflict. Back up the previous owned files before installing the staged payload, then record the new source commit and per-file hashes. An absent or empty destination can receive a first snapshot; do not overwrite an unrelated nonempty directory. Updating an instruction source already linked globally is itself an apply action.

Run `scripts/install.py --apply` from the stable configured directory. The installer retains backups, normalizes Claude-only copies into the reviewed shared layout, archives only hash-verified packaging files excluded from the baseline, and verifies skills before linking instructions. Verify both global instruction links and their SHA-256, every selected public/private skill payload and link, and preserved unrelated skills. Report per-machine receipts and partial failures honestly. Save logs and complete receipts under ignored `.fleet/applies/` and any rollout summary under ignored `.fleet/rollout.json`. Keep machine IDs, local paths, source inventories, and report diffs out of commits.

## Worker cleanup

Clean up each worker after collecting and verifying its complete result, including failed or superseded attempts. Completion alone leaves a remote thread open in T3.

- Retain the parent task ID and remote environment/thread IDs returned at launch. After saving the result, call `task_cancel` with the task ID to release any remaining delegated activity; completed results are preserved. Do not interrupt a child by thread ID.
- Archive that worker's remote thread with `t3_thread_organize`, then verify `archived: true` and no active run. Keep this coordinator thread and unrelated user threads open. Archiving preserves the conversation history.
- Do this promptly after each phase, not only at the end of a long session. Refreshed links can lose permission to manage workers created by an earlier connection.
- If an offline machine or link-ownership gate prevents cleanup, record the exact remaining worker IDs under ignored `.fleet/` and report the blocker. An older connection's threads may need local archiving or a Full-access link. Do not change link permissions, bypass the restriction, or create another worker just to perform cleanup.
