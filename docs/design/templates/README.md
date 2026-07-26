---
created: 26.07.2026 19:00
type: index
tags:
  - index
---
# Document templates

Fill-in starting points for each document class. Copy, don't edit in place.

| Template | For | Lands in |
|----------|-----|----------|
| [`adr.md`](adr.md) | A settled decision and its rationale | [`../adr/`](../adr/README.md) |
| [`proposal.md`](proposal.md) | An implementation plan or scope change | [`../proposals/draft/`](../proposals/README.md) |
| [`architecture.md`](architecture.md) | A section of the living system description | [`../architecture/`](../architecture/README.md) |

The front matter is not decoration: `nox -s docs` checks that every ADR and
proposal carries it with a valid `status`. Replace the `<placeholders>` — the
lint does not check prose, but a template committed unedited is obvious in
review.
