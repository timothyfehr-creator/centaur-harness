# Command Safety

Guidance for long-running coding sessions in this repo. The secret scan below is
enforced in CI; the command-safety practices are conventions for contributors and
agents.

## Principles

- Prefer read-only exploration before mutating commands.
- Warn before destructive operations: file deletion, overwrites, `git push --force`,
  history rewrites, recursive removes.
- Do not run commands that exfiltrate repo contents or secrets to external services.
- Keep changes scoped to the active work package; do not rewrite unrelated files.

## Secrets

- Never commit credentials, API keys, tokens, or `.env`/key files. These are ignored
  via [`.gitignore`](../.gitignore).
- **Secret scanning is implemented** in
  [`scripts/secret_scan.py`](../scripts/secret_scan.py) and runs in CI. By default it
  scans tracked files (`git ls-files`); pass paths to scan specific files/dirs:

  ```bash
  python scripts/secret_scan.py            # scan tracked repo files
  python scripts/secret_scan.py PATH ...   # scan specific files/dirs
  ```

- It matches a curated set of high-precision patterns (AWS / GitHub / Google / Slack
  / Stripe / Anthropic / OpenAI keys, PEM private-key headers) plus one precise
  generic keyword/value rule. Matched values are masked in output.
- It is a **minimum gate, not a guarantee** — it will miss obfuscated or novel
  secrets. A clean scan means "no obvious secret", not "provably secret-free".
- To exempt a deliberately non-secret line (a documented example or a fixture),
  append the marker `pragma: allowlist secret` to that line.

## Destructive-command checklist

Before running a destructive or irreversible command:

1. Confirm the target path is what you expect.
2. Confirm it is recoverable (committed, or backed up) — or stop.
3. Prefer the narrowest command that does the job.
