# Task loop v0.2 — Delivery B

These schemas add a live-provider loop boundary without modifying the frozen ADLC v0.1 execution contracts or the Delivery A v0.1 mock contracts.

- `task-loop-spec.schema.json`: full immutable objective, pinned 40-character Git commit, exact writable files, registered unittest checks, criterion-to-check mapping, and loop budgets.
- `task-loop-candidate.schema.json`: complete cumulative UTF-8 overlay relative to that commit, file modes, explicit deletions, candidate/parent IDs, and a content digest.
- `task-loop-verification.schema.json`: actual command evidence bound to the spec and candidate digests, including protected-test checksum, exit status, executed test count, timeout, and bounded output.

The initial scope is local trusted development: at most 64 writable paths, 16,384 characters per text file, and 64 KiB aggregate file content. Protected test files are subject to the same individual text bound. Binary files, arbitrary shell runners, and container security boundaries are outside this version. A detached Git worktree isolates file changes; verification runs in a second reconstructed worktree and does not inherit provider credentials.

The example commit of forty zeroes is a template placeholder. Run `scripts.prepare_adlc_task_loop_live` to create the fixture repository and replace it with an actual commit. Human approval remains required after every check passes.
