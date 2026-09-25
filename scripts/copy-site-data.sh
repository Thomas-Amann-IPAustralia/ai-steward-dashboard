#!/usr/bin/env bash
# Copy the pipeline's output into the built site, next to index.html.
#
# The dashboard fetches these files at runtime; they are not bundled. Only
# what the pages read is shipped: the archived analyses and diffs are, the
# archived snapshots (13 of the 14 MB) and the pipeline's working state are
# not.
#
#     scripts/copy-site-data.sh build
set -euo pipefail

out="${1:?usage: scripts/copy-site-data.sh BUILD_DIR}"
mkdir -p "$out"/{analysis,snapshots,diffs,logs,news,transparency/diffs}

cp hashes.json policy_sets.json "$out"/
for f in health.json history.json; do
  if [ -f "$f" ]; then cp "$f" "$out"/; fi
done

for d in analysis snapshots diffs; do
  if [ -d "$d" ]; then cp -r "$d"/. "$out/$d"/; fi
done

# The feed and its monthly archive ship; state.json (validators and seen ids)
# is the pipeline's working memory, not something to serve.
if [ -d news ]; then cp -r news/. "$out"/news/; fi
rm -f "$out"/news/state.json

# The statements' current text stays in the repository; the page needs their
# state, the events and the latest diff of each.
for f in statements.json events.json; do
  if [ -f "transparency/$f" ]; then cp "transparency/$f" "$out"/transparency/; fi
done
if [ -d transparency/diffs ]; then cp -r transparency/diffs/. "$out"/transparency/diffs/; fi

find logs -maxdepth 1 \( -name '*_analysis.json' -o -name '*_diff.txt' \) -exec cp {} "$out"/logs/ \;
du -sh "$out"
