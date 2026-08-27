#!/usr/bin/env bash
# Upload the glider _grid_adjusted.nc set to a GitHub release, one deployment at a time.
#
# These files are 42 MB to 940 MB each. GitHub blocks any file over 100 MB in the
# repository tree, so they cannot be committed -- but release assets allow up to
# 2 GB each, which every file clears with room to spare. Hence a release rather
# than `git add`.
#
# One `gh release upload` call per deployment, sequentially: a single 10.68 GB push
# would be one long transfer with nothing to show for itself if it died halfway,
# whereas a per-file loop leaves each completed asset on the server. Re-running skips
# whatever already landed, so an interrupted run resumes rather than restarts.
#
#   bash data/upload_glider_adjusted.sh [tag]

set -uo pipefail

TAG="${1:-glider-adjusted-v1}"
REPO="oceanhackweek/ohw26_proj_BarkleyScope"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/glider_adjusted"

# Assets already on the release. Compared by name so a resumed run does not re-send
# a 900 MB file that is already up there.
mapfile -t DONE < <(gh release view "$TAG" --repo "$REPO" --json assets \
                      --jq '.assets[].name' 2>/dev/null)

have() { local f="$1"; for d in "${DONE[@]:-}"; do [[ "$d" == "$f" ]] && return 0; done; return 1; }

mapfile -t FILES < <(find "$ROOT" -name '*_grid_adjusted.nc' | sort)
total=${#FILES[@]}
ok=0; skipped=0; failed=0; i=0

echo "$total file(s) to upload to $TAG"
for path in "${FILES[@]}"; do
  i=$((i + 1))
  name="$(basename "$path")"
  size="$(du -h "$path" | cut -f1)"

  if have "$name"; then
    echo "[$i/$total] skip   $name (already uploaded)"
    skipped=$((skipped + 1))
    continue
  fi

  echo "[$i/$total] upload $name ($size)"
  if gh release upload "$TAG" "$path" --repo "$REPO" --clobber; then
    ok=$((ok + 1))
  else
    echo "[$i/$total] FAILED $name -- re-run to retry"
    failed=$((failed + 1))
  fi
done

# The manifest is small but is the thing that explains the rest, so it rides along.
[[ -f "$ROOT/manifest.json" ]] && \
  gh release upload "$TAG" "$ROOT/manifest.json" --repo "$REPO" --clobber

echo
echo "uploaded $ok, skipped $skipped, failed $failed, of $total"
[[ $failed -eq 0 ]]
