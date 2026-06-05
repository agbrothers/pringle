---
name: release
description: Draft and publish a Pringle GitHub release. Identifies the previous tag and commit, reviews all commits and closed issues since then, and produces a concise high-level changelog organized by category. Use when the user asks to cut a release, tag a version, or generate release notes.
---

# Cut a Pringle Release

## 1. Find the previous tag and its commit

```bash
git tag --sort=-creatordate | head -5          # most recent tags
git rev-list -n 1 <previous-tag>               # commit hash for that tag
```

Note the commit hash — this is the base for all comparisons below.

## 2. Gather the raw material (run in parallel)

```bash
git log <base-commit>..HEAD --oneline          # all commits since the last tag
gh issue list --state closed --limit 100       # recently closed issues
```

If the closed-issue list is long, filter to the relevant window:

```bash
gh issue list --state closed --limit 100 --json number,title,labels,closedAt \
  | python3 -c "
import json, sys
from datetime import datetime, timezone
issues = json.load(sys.stdin)
# tag date can be found with: git show <base-commit> --no-patch --format='%ci'
cutoff = datetime.fromisoformat('<tag-date>').replace(tzinfo=timezone.utc)
for i in issues:
    closed = datetime.fromisoformat(i['closedAt'].replace('Z','+00:00'))
    if closed >= cutoff:
        labels = [l['name'] for l in i['labels']]
        print(i['number'], i['title'], labels)
"
```

## 3. Write the changelog

Organize changes under these headings (omit any that have no entries):

| Section | What goes here |
|---|---|
| **Editor** | Keyboard shortcuts, text editing behavior, cell navigation |
| **UI & Visual Polish** | Theme changes, layout tweaks, new widgets, visual fixes |
| **Rendering** | New render modes, colormap/shader features, geometry changes |
| **Namespace & Expressions** | New names in the eval namespace, evaluation behavior changes |
| **Performance** | PERF issues with before/after numbers |
| **Bug Fixes** | BUG issues; minor fixes that don't fit above |

**Style rules:**
- One bullet per logical change. Lead with a bold label (`**BUG-071**`, `**Cmd+L**`, `**`camera` object**`).
- High-level only — no implementation details, no file paths.
- Group related fixes together rather than listing them individually when they share a theme.
- Bugs that are invisible to users (test fixes, internal refactors) can be omitted.

## 4. Sync the version in pyproject.toml

Before publishing, confirm that `pyproject.toml` matches the new tag (strip the leading `v`):

```bash
grep '^version' pyproject.toml        # e.g. version = "0.1.0"
```

If it doesn't match, update it and commit **before** creating the tag/release:

```bash
# sed in-place replacement (macOS-safe)
sed -i '' 's/^version = ".*"/version = "X.Y.Z"/' pyproject.toml

git add pyproject.toml
git commit -m "Bump version to X.Y.Z"
```

PyPI rejects uploads whose filename (which embeds the package version) already exists — even if the content changed. The tag must point to a commit that has the correct version, or the publish workflow will fail with a 400.

## 5. Publish the release

Write the notes to a temp file to avoid shell-quoting issues with backticks:

```bash
# Write to temp file
cat > /tmp/release-notes.md << 'NOTES'
## vX.Y.Z

### Section
- ...
NOTES

gh release create vX.Y.Z --title "vX.Y.Z" --notes-file /tmp/release-notes.md
```

`gh release create` creates the git tag and the GitHub release in one step. If the tag already exists locally, pass `--target <commit>` to pin it.

## 6. Confirm

The command prints the release URL. Share it with the user.
