#!/usr/bin/env python3
"""Render collected T3 fleet dry-run results as one local HTML report."""

import sys
sys.dont_write_bytecode = True

import argparse
from contextlib import redirect_stdout
import html
import io
import json
from pathlib import Path

from preview import print_report


def escape(value):
    return html.escape(str(value))


def diff_html(value):
    lines = []
    for line in value.splitlines():
        style = "plus" if line.startswith("+") else "minus" if line.startswith("-") else ""
        lines.append(f'<span class="{style}">{escape(line)}</span>')
    return '<pre class="diff">' + "\n".join(lines) + "</pre>"


def machine_card(name, envelope, revision):
    status = envelope.get("status", "running")
    report = envelope.get("report")
    error = envelope.get("error", "")
    if envelope.get("sourceCommit", revision) != revision:
        status, error = "blocked", "This result used a different source revision."
        report = None
    header = f'<h2>{escape(name)} <small>{escape(status)}</small></h2>'
    if not report:
        return f'<article>{header}<p>{escape(error or "Report has not arrived yet.")}</p></article>'
    counts = report["summary"]["skills"]
    total = sum(counts.values()) or 1
    bars = "".join(f'<span class="{escape(key.lower())}" style="width:{value / total * 100:.2f}%" title="{escape(key)}: {value}">{value}</span>' for key, value in counts.items())
    legend = " · ".join(f"{value} {escape(key.lower())}" for key, value in counts.items())
    body = f'<p>{escape(report["machine"])} · {escape(report["home"])}</p><div class="bar" role="img" aria-label="{legend}">{bars}</div><p class="legend">{legend}</p>'
    if error or report["errors"]:
        body += '<p class="minus">' + escape(error or "; ".join(report["errors"])) + '</p>'
    body += '<details><summary>Instruction changes</summary>'
    for change in report["instructions"]:
        body += f'<h3>{escape(change["status"])} {escape(change["path"])}</h3><p>Target: <code>{escape(change["target"])}</code></p>'
        if change.get("currentTarget"):
            body += f'<p>Previous link: <code>{escape(change["currentTarget"])}</code></p>'
        body += diff_html(change.get("diff", "")) if change.get("diff") else '<p>No text changes.</p>'
    body += '</details><details><summary>Skill file and link changes</summary>'
    for skill in report["skills"]:
        body += f'<details><summary>{escape(skill["status"])} {escape(skill["name"])} · {len(skill["files"])} file changes</summary><p>Source: <code>{escape(skill["source"])}</code></p>'
        for file in skill["files"]:
            body += f'<p><b>{escape(file["status"])}</b> <code>{escape(file["path"])}</code></p>'
            if file.get("diff"):
                body += diff_html(file["diff"])
        for link in skill["links"]:
            body += f'<p>{escape(link["status"])} <code>{escape(link["path"])}</code> → <code>{escape(link["target"])}</code></p>'
            for entry in link["replacedEntries"]:
                body += f'<p>Remove previous directory entry: <code>{escape(entry)}</code></p>'
        body += '</details>'
    body += '</details><details><summary>Preserved paths and other apply effects</summary><ul>'
    body += "".join(f'<li>KEEP <code>{escape(path)}</code></li>' for path in report["preserved"])
    body += '</ul><ul>' + "".join(f'<li>{escape(effect)}</li>' for effect in report["sideEffects"]) + '</ul></details>'
    return f'<article>{header}{body}</article>'


def render(state, envelopes):
    revision = state["sourceCommit"]
    cards = "".join(machine_card(name, envelopes.get(name, state["machines"][name]), revision) for name in state["machines"])
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Fleet dry run</title><style>
*{box-sizing:border-box}:root{font-family:var(--font-sans,system-ui,sans-serif);color:var(--foreground,CanvasText)}body{margin:0;font-size:14px;line-height:1.55}main{max-width:1480px;margin:0}h2{margin:0;font-size:21px}h3{font-size:13px;overflow-wrap:anywhere}p{margin:8px 0 16px}small{font-size:12px;font-weight:500;background:var(--secondary,ButtonFace);padding:4px 9px;border-radius:var(--radius,10px)}article{background:var(--card,Canvas);border:1px solid var(--border,GrayText);border-radius:var(--radius,10px);padding:16px;min-width:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:16px}code{font-family:var(--font-mono,monospace);font-size:11px;overflow-wrap:anywhere}.bar{display:flex;height:28px;border-radius:5px;overflow:hidden;background:var(--muted,ButtonFace)}.bar span{min-width:18px;text-align:center;font-size:12px;line-height:28px}.add{background:color-mix(in srgb,var(--success,green) 45%,var(--card,Canvas))}.modify,.replace{background:color-mix(in srgb,var(--warning,orange) 50%,var(--card,Canvas))}.current{background:var(--muted,ButtonFace)}.link{background:color-mix(in srgb,var(--info,blue) 40%,var(--card,Canvas))}.legend{font-size:12px;color:var(--muted-foreground,GrayText)}.diff{white-space:pre-wrap;overflow-wrap:anywhere;font:11px/1.55 var(--font-mono,monospace);background:var(--code-background,ButtonFace);padding:10px;border-radius:var(--radius,6px)}.plus{color:var(--success,green)}.minus{color:var(--destructive,crimson)}details{border-top:1px solid var(--border,GrayText);margin-top:12px;padding-top:12px}summary{cursor:pointer;font-weight:600}li{margin:6px 0}ul{padding-left:20px}.note{color:var(--muted-foreground,GrayText)}@media(max-width:650px){.grid{grid-template-columns:1fr}}
</style><main><p class="note">One source revision · ''' + escape(revision) + '''<br>No configuration applied. Expand each machine’s changes below. Skill bars compare added, modified, current, and link-only payloads; CURRENT skills are still reinstalled on apply.</p><div class="grid">''' + cards + '</div></main></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    state = json.loads((args.run / "run.json").read_text())
    envelopes = {}
    for name in state["machines"]:
        path = args.run / f"{name}.json"
        if path.is_file():
            envelopes[name] = json.loads(path.read_text())
            if envelopes[name].get("report"):
                output = io.StringIO()
                with redirect_stdout(output):
                    print_report(envelopes[name]["report"])
                (args.run / f"{name}.txt").write_text(output.getvalue())
    destination = args.run / "report.html"
    destination.write_text(render(state, envelopes))
    print(destination.resolve())


if __name__ == "__main__":
    main()
