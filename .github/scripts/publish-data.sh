#!/usr/bin/env bash
# Commit and push published/data to the `data` branch.
#
# Shared by collect.yml and election-night.yml, which both write the branch and
# must apply the same staleness guard. Run from the `published` checkout with
# OURS set to the commit the collector ran on.
#
# Exit status: 0 published or nothing to publish (including a skipped stale run),
# 1 the push failed after retries.
set -euo pipefail
: "${OURS:?OURS must be the collector commit sha}"

# Refuse to overwrite data written by newer code.
#
# This is not hypothetical. A workflow_dispatch run created at 15:30 on
# f181451 finished at 16:20 — after two fixes had landed and after a
# later scheduled run had published correct figures — and its old-code
# output replaced them. Hamilton vanished from outside spending again,
# the $214,014.88 double-count came back, and every committee was once
# more labelled as both supporting and opposing the same candidate.
#
# Timestamps cannot catch this: the stale run generated its payload at
# 16:20, genuinely later than the good one. What separates them is the
# commit, so the commit is what gets compared. The concurrency group
# serialises runs but says nothing about which code version they carry.
PREVIOUS=""
if [ -f collector-sha.txt ]; then
  PREVIOUS="$(tr -d '[:space:]' < collector-sha.txt)"
fi
if [ -n "$PREVIOUS" ] && [ "$PREVIOUS" != "$OURS" ]; then
  # Ours is an ancestor of what is already published, so that came from
  # later code and this run is stale.
  if git -C "${GITHUB_WORKSPACE:-..}" merge-base --is-ancestor "$OURS" "$PREVIOUS" 2>/dev/null; then
    echo "::warning::Skipping publish. This run is on $OURS; the data branch"
    echo "::warning::was written by $PREVIOUS, which is newer. Nothing overwritten."
    exit 0
  fi
fi
printf '%s\n' "$OURS" > collector-sha.txt

git add -A data collector-sha.txt
if git diff --cached --quiet; then
  echo "Nothing changed; not committing."
  exit 0
fi
git commit -q -m "Data update $(date -u +%Y-%m-%dT%H:%MZ)"

# HEAD:data is explicit: pushing the bare name `data` depends on a local branch
# of that name resolving, which is what broke before.
#
# On election night two workflows write this branch — the 20-minute collector
# and the results loop — so a rejected push is expected rather than exotic. The
# only file both write is results.json, and both versions were collected moments
# apart, so on a conflict ours (the one being replayed, `-X theirs` in rebase
# terms) wins. A rebase that still cannot complete is aborted rather than left
# half-applied, which is what `|| true` used to do.
for attempt in 1 2 3 4; do
  if git push -q origin HEAD:data; then
    echo "Published $(git rev-parse --short HEAD)."
    exit 0
  fi
  echo "Push failed (attempt $attempt); rebasing onto the current data branch."
  sleep $((2 ** attempt))
  if git fetch -q --depth=1 origin data; then
    # Replay only our one commit. The fetch is shallow, so FETCH_HEAD and HEAD
    # share no visible history and a plain `rebase FETCH_HEAD` would try to
    # replay the old tip as well.
    git rebase -q -X theirs --onto FETCH_HEAD HEAD~1 || git rebase --abort || true
  fi
done
echo "Push failed after 4 attempts." >&2
exit 1
