#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

# Script to help creating a new DiscoPoP Version.
#
# This script creates
# - a commit "Release of Version ${VERSION}" in release/v${VERSION} to update the
#   version files, and
# - a tag "v${VERSION}" pointing to the new commit.
# After that, it prints the steps that are required manually for finalizing the
# release creation.
#
# Usage:
#   scripts/dev/create-release.sh <version>
# where <version> is a valid version identifier, such as "1.2.0".

function error {
  echo "$*" > /dev/stderr
  exit 1
}

VERSION=$1
[ -z "$VERSION" ] && error "Usage: $0 <version>"

# Regular expression for a version number, copied from PEP440
VERSION_REGEX='^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?$'
echo "$VERSION" | grep -qEe "$VERSION_REGEX" || \
    error "\"$VERSION\" is not a valid version number."

cd "$(dirname "$0")/../.." || error "cd into source root failed."

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
[ "$CURRENT_BRANCH" != "master" ] && [ "$CURRENT_BRANCH" != "develop" ] && \
    error "You are not in master or develop branch."

[ -z "$(git status --short)" ] || error "Working tree is not clean."

git checkout -b "release/v${VERSION}" || error "Failed."
echo "${VERSION}" > VERSION
echo "__version__ = \"${VERSION}\"" > explorer/discopop_explorer/_version.py
echo "__version__ = \"${VERSION}\"" > discopop_profiler/_version.py
git add VERSION explorer/discopop_explorer/_version.py discopop_profiler/_version.py || \
    error "Failed."
git commit -m "Release of Version ${VERSION}" || error "Failed."
git tag -a -m "Version ${VERSION}" "v${VERSION}" || error "Failed."

cat << EOF


Created
 - a commit "Release of Version ${VERSION}" in release/v${VERSION} to update the
   version files, and
 - a tag "v${VERSION}" pointing to the new commit.

To finalize releasing, do the following five steps manually:
 1. git push --set-upstream origin release/v${VERSION}
 2. Create a Pull Request for the newly pushed branch release/v${VERSION}
 3. Merge the branch release/v${VERSION} into ${CURRENT_BRANCH} without altering the
    commit hash
 4. git push --tags
 The CI will then automatically publish the release to PyPI and create a Draft Release
 on GitHub
 5. Go to GitHub and remove the "Draft" flag of the new release
EOF
