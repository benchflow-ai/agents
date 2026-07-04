# Runbook: purge the 82 MB opencode binary from `benchflow-ai/agents` history

**Status:** ready to run — **do NOT run without coordinating** (see §Blast radius).

PR #49 removes the binary from `HEAD` (new checkouts stop growing). This runbook
shrinks the `.git` history so *existing* clones and shallow fetches stop
carrying the 82 MB blob. `.git` today is **~90 MB**; after this it drops to
**~6–8 MB**. There is exactly **1 distinct blob** across **3 commits**.

## Blast radius (why this needs coordination)

A history rewrite **changes every commit SHA from the first commit that touched
the blob onward**. Consequences:

- **Every open PR** on the repo must be rebased or reopened (their base SHAs
  vanish). Merge #49 (and anything else in flight) **before** running this.
- **Every collaborator and CI cache** must re-clone (`git pull` will diverge).
- Any tag/branch/release pinned to an old SHA breaks.

Schedule a short freeze, announce it, then run the steps below.

## Steps (maintainer, on a fresh mirror clone)

```bash
# 0. Merge #49 and any other open PRs first. Announce the freeze.

# 1. Tooling
pipx install git-filter-repo        # or: brew install git-filter-repo

# 2. Fresh MIRROR clone (filter-repo refuses to run on a normal working clone)
git clone --mirror git@github.com:benchflow-ai/agents.git agents-mirror
cd agents-mirror

# 3. Strip the blob from ALL history
git filter-repo --invert-paths \
  --path acp/mini-swe-code/src/minisweagent/run/opencode/bin/opencode

# 4. Sanity-check the shrink (expect ~6–8MB, blob gone)
du -sh .              # was ~90MB
git rev-list --objects --all | grep opencode/bin/opencode && echo "STILL PRESENT (stop)" || echo "purged ✓"

# 5. Force-push the rewritten history (DESTRUCTIVE)
git push --force --mirror
```

## After the push

- Tell everyone to **re-clone** (not `git pull`).
- Reopen/rebase any PRs that were still open.
- The gitignore from #49 keeps it out going forward, so this is a one-time pass.

## If you'd rather not rewrite history

Leave it. #49 already stops the bleeding for new work; the 82 MB is a fixed
one-time cost on a full clone that GitHub serves compressed, and the lazy
`bench init` path only clones when an agent is actually resolved. The rewrite
is a nice-to-have, not a correctness fix.
