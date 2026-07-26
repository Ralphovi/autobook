#!/usr/bin/env python3
"""Lint the design documentation.

Run by `nox -s docs`, which `nox -s gate` includes. Checks four things that
review reliably misses and that would otherwise rot silently:

1. Every ADR and proposal carries the front matter its template defines, with a
   status drawn from the allowed set.
2. ADR filenames are `NNNN-slug.md`, numbers are unique, and every ADR is listed
   in the ADR README index.
3. Relative Markdown links resolve to a file that exists.
4. No Obsidian-style `[[wikilinks]]` — they render as literal text on GitHub.

Deliberately NOT checked: prose style, heading structure, line length. Those are
review's job; this is for the mechanical failures review is bad at.

Exit code 0 clean, 1 on any finding.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent
REPO = DOCS.parent

ADR_DIR = DOCS / "design" / "adr"
PROPOSAL_DIRS = [
    DOCS / "design" / "proposals" / "draft",
    DOCS / "design" / "proposals" / "accepted",
]
TEMPLATE_DIR = DOCS / "design" / "templates"

ADR_STATUSES = {"Proposed", "Accepted", "Superseded"}
PROPOSAL_STATUSES = {"draft", "accepted", "implemented", "withdrawn"}

ADR_NAME = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
MD_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")

FENCED_BLOCK = re.compile(r"^(?P<fence>```+|~~~+).*?^(?P=fence)", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"(?P<ticks>`+)(?:(?!(?P=ticks)).)*(?P=ticks)", re.DOTALL)

findings: list[str] = []


def report(path: Path, message: str) -> None:
    findings.append(f"{path.relative_to(REPO)}: {message}")


def front_matter(text: str) -> dict[str, str] | None:
    """Parse the leading YAML block as flat key: value pairs.

    Deliberately not a YAML parser: the templates use a flat shape plus a `tags`
    list, and depending on PyYAML would make the docs gate need a virtualenv.
    """
    match = FRONT_MATTER.match(text)
    if match is None:
        return None
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("-"):
            continue
        key, _, value = line.partition(":")
        if _:
            fields[key.strip()] = value.split("#")[0].strip()
    return fields


def check_front_matter(path: Path, text: str, kind: str, statuses: set[str]) -> None:
    fields = front_matter(text)
    if fields is None:
        report(path, "missing YAML front matter (see docs/design/templates/)")
        return
    if fields.get("type") != kind:
        report(path, f"front matter `type:` should be `{kind}`, found {fields.get('type')!r}")
    status = fields.get("status", "")
    # "Superseded by ADR-0007" is a legal ADR status; compare on the first word.
    head = status.split()[0] if status else ""
    if head not in statuses:
        report(
            path,
            f"front matter `status:` {status!r} is not one of {sorted(statuses)}",
        )


def strip_code(text: str) -> str:
    """Blank out fenced blocks and inline code spans, preserving line numbers.

    Link-shaped text inside code is documentation ABOUT the syntax, not a link:
    the design doc's YAML and Python samples are full of brackets and parens, and
    the docs README quotes the wikilink syntax in order to ban it. Checking those
    produces noise that trains people to ignore the gate.
    """
    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    return INLINE_CODE.sub(blank, FENCED_BLOCK.sub(blank, text))


def check_links(path: Path, text: str) -> None:
    text = strip_code(text)
    for wikilink in WIKILINK.findall(text):
        report(path, f"Obsidian wikilink [[{wikilink}]] does not render on GitHub")
    for target in MD_LINK.findall(text):
        target = target.split()[0]  # strip an optional "title"
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (path.parent / target.split("#")[0]).resolve()
        if not resolved.exists():
            report(path, f"link target does not exist: {target}")


def main() -> int:
    if not ADR_DIR.is_dir():
        print(f"lint_docs: no ADR directory at {ADR_DIR}", file=sys.stderr)
        return 1

    seen: dict[str, Path] = {}
    for adr in sorted(ADR_DIR.glob("*.md")):
        if adr.name == "README.md":
            continue
        match = ADR_NAME.match(adr.name)
        if match is None:
            report(adr, "filename must be NNNN-lowercase-slug.md")
            continue
        number = match.group(1)
        if number in seen:
            report(adr, f"duplicate ADR number {number} (also {seen[number].name})")
        seen[number] = adr
        text = adr.read_text(encoding="utf-8")
        check_front_matter(adr, text, "adr", ADR_STATUSES)
        check_links(adr, text)

    index = ADR_DIR / "README.md"
    if index.is_file():
        index_text = index.read_text(encoding="utf-8")
        for number, adr in sorted(seen.items()):
            if adr.name not in index_text:
                report(index, f"ADR {number} is not listed in the index")
        check_links(index, index_text)
    else:
        report(ADR_DIR, "missing README.md index")

    for directory in PROPOSAL_DIRS:
        for proposal in sorted(directory.glob("*.md")):
            if proposal.name == "README.md":
                continue
            text = proposal.read_text(encoding="utf-8")
            check_front_matter(proposal, text, "proposal", PROPOSAL_STATUSES)
            check_links(proposal, text)

    # Every other doc still gets its links checked; templates are placeholders.
    for doc in sorted(DOCS.rglob("*.md")):
        if TEMPLATE_DIR in doc.parents or ADR_DIR in doc.parents:
            continue
        if any(d in doc.parents for d in PROPOSAL_DIRS):
            continue
        check_links(doc, doc.read_text(encoding="utf-8"))

    for doc in (REPO / "README.md", REPO / "CONTRIBUTING.md", REPO / "AGENTS.md",
                REPO / "SECURITY.md", REPO / "CLAUDE.md"):
        if doc.is_file():
            check_links(doc, doc.read_text(encoding="utf-8"))

    if findings:
        for finding in findings:
            print(f"::error::{finding}", file=sys.stderr)
        print(f"\nlint_docs: {len(findings)} finding(s)", file=sys.stderr)
        return 1

    print(f"lint_docs: OK ({len(seen)} ADR(s) checked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
