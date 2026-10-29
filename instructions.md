# Global instructions

## Writing

- Do not use em dashes in UI copy, documentation, comments, commit messages, or chat responses. Rephrase with commas, colons, or parentheses. Use an en dash for empty table values.
- Before drafting GitHub text in my name, including PR descriptions, issue comments, and reviews, invoke the `user-voice` skill. If it is unavailable, report that rather than claiming to have used it.
- Do not add AI attribution to commit messages or PR bodies, including co-author trailers or generated-by notices.

## Tooling

- Follow the repository's package manager. Otherwise, prefer Bun and bunx for JavaScript and TypeScript tooling, unless the tool requires another runner.

## Implementation

- Ask for clarification when missing information materially affects correctness, scope, or an action that is difficult to reverse. Otherwise, proceed with a reasonable assumption and state it when it affects the result.
- Solve the requested problem with the simplest design that fits. Avoid speculative features, configuration, and abstractions.
- Keep changes focused on the request and match the repository's style. Remove code made unused by your changes; leave unrelated cleanup alone unless requested.
- For multi-step work, give a brief plan with observable success criteria. Verify the changed behavior using appropriate checks; add a regression test when it provides a useful, reproducible check for a bug fix.

## Interface design

- Use Apple's Human Interface Guidelines as a design reference: prefer familiar interactions, clear hierarchy, and meaningful user control.
- Cut taglines, redundant helper text, and secondary labels. Fix unclear layouts before adding explanatory copy.
