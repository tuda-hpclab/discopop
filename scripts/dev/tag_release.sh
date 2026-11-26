#!/usr/bin/env bash
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Usage: tag_release.sh <tag> <commit>
# Tags the commit of a published package (workflow "Release") and pushes the tag. A tag that exists already on the
# same commit is fine (a repeated run); on another commit, the published version came from elsewhere: the run
# fails, so the difference is noticed.
set -euo pipefail

tag="$1"
commit="$2"

existing="$(git ls-remote --tags origin "refs/tags/${tag}" | cut -f1)"
if [ -n "${existing}" ]; then
  target="$(git rev-parse "${existing}^{commit}" 2>/dev/null || true)"
  if [ -z "${target}" ]; then
    git fetch --quiet origin "refs/tags/${tag}:refs/tags/${tag}"
    target="$(git rev-parse "${tag}^{commit}")"
  fi
  if [ "${target}" = "$(git rev-parse "${commit}^{commit}")" ]; then
    echo "The tag ${tag} exists already on ${commit}."
    exit 0
  fi
  echo "::error title=Tag of the release::The tag ${tag} exists already on ${target}, not on ${commit}." >&2
  exit 1
fi

git tag "${tag}" "${commit}"
git push origin "refs/tags/${tag}"
echo "Tagged ${commit} as ${tag}."
