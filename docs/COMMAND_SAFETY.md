# Command Safety

Guidance for long-running coding sessions in this repo. This is documentation, not
an enforced gate yet. Enforcement (a secret scan and related checks) arrives in
WP0.2.

## Principles

- Prefer read-only exploration before mutating commands.
- Warn before destructive operations: file deletion, overwrites, `git push --force`,
  history rewrites, recursive removes.
- Do not run commands that exfiltrate repo contents or secrets to external services.
- Keep changes scoped to the active work package; do not rewrite unrelated files.

## Secrets

- Never commit credentials, API keys, tokens, or `.env` files. These are ignored via
  [`.gitignore`](../.gitignore).
- **Secret scanning is deferred to WP0.2** (`scripts/secret_scan.py`). It is
  documented here but intentionally **not implemented** in the bootstrap scaffold.

## Destructive-command checklist

Before running a destructive or irreversible command:

1. Confirm the target path is what you expect.
2. Confirm it is recoverable (committed, or backed up) — or stop.
3. Prefer the narrowest command that does the job.
