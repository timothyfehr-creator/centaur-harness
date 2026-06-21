# Knowledge book schema (v1) — compact grounding catalog

Contract for the compact knowledge books agents cite. Books live under
`knowledge/country_books/` and `knowledge/institution_books/` (one YAML doc per book).
[`scripts/validate_agents.py`](../scripts/validate_agents.py) globs `knowledge/**/*.yaml`,
builds the **book-id index**, and resolves agent `knowledge` refs against it.

## Book shape

```yaml
schema_version: "1.0"
id: book-...
title: "..."
summary: >
  ...
```

| Field | Required | Type | Rule |
|---|---|---|---|
| `schema_version` | recommended | string | convention for consistency; **not** enforced — only `id` is required to build the index |
| `id` | yes | string | non-empty; the resolution key agents cite (the only field the index enforces) |
| `title` | recommended | string | human label |
| `summary` | recommended | string | compact grounding prose |

## Resolution-only (this is a catalog, not an encyclopedia)

WP5 checks **reference resolution**, not book content: an agent's `knowledge` ref must
resolve to a book `id`. The index is **fail-closed** — a book that is unreadable, not a
mapping, or missing its `id` makes the catalog untrustworthy and the gate refuses to report
clean (exit 2); an empty `knowledge/` dir likewise fails closed.

## Deferred

Encyclopedic country books, sourced `facts:` that cite claims, full doctrine libraries, and
SME-authored packs are out of scope. A book may later (WP6+) grow a `facts:` list citing
claims without breaking any existing agent reference. All shipped books are SYNTHETIC /
ILLUSTRATIVE — they carry no sourced real-world facts.
