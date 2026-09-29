#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

set -euo pipefail

RELEASE=false

# can specify -r flag to set release mode
while getopts ":r" opt; do
    case "$opt" in
        r) RELEASE=true ;;
        *) ;;
    esac
done

VERSION=$(cat library/discopop_library/global_data/version/VERSION)
#PACKAGE_NAME="discopop-${VERSION}-$(uname --hardware-platform)-$(uname --kernel-name).deb"
PACKAGE_NAME="discopop-${VERSION}-all-Linux.deb"

rm -vf packages/${PACKAGE_NAME}

# create a temporary copy of the code to build the package
rm -rf tmp_package_build_dir
mkdir -p tmp_package_build_dir
shopt -s dotglob nullglob
for item in *; do
    [ "$item" = "tmp_package_build_dir" ] && continue
    [ "$item" = "packages" ] && continue
    cp -a "$item" tmp_package_build_dir/
done
shopt -u dotglob nullglob

# modify folder structure to install DiscoPoP to /opt when installing the package
cd tmp_package_build_dir
mkdir opt
mkdir opt/DiscoPoP

# specify files to be included in the package
shopt -s dotglob nullglob
for item in *; do
    [ "$item" = "opt" ] && continue
    mv "$item" opt/DiscoPoP/
done
shopt -u dotglob nullglob
mv opt/DiscoPoP/DEBIAN/all_targets DEBIAN

sed -i "s|@RELEASE@|${RELEASE}|g" DEBIAN/postinst

# specify files to be removed from the package
find opt/DiscoPoP -path '*/__pycache__*' -delete
find opt/DiscoPoP -path '*/.pytest_cache*' -delete
find opt/DiscoPoP -path '*/.mypy_cache*' -delete
find opt/DiscoPoP -path '*/.idea*' -delete
find opt/DiscoPoP -path '*/.vscode*' -delete

# add the Version tag to DEBIAN/control.raw to create DEBIAN/control
echo "$(cat DEBIAN/control.raw)" > DEBIAN/control
echo "Version: $(cat opt/DiscoPoP/discopop_library/global_data/version/VERSION)" >> DEBIAN/control
echo "" >> DEBIAN/control

# delete build folder if exists
rm -rf opt/DiscoPoP/build
# delete packages folder if exists
rm -rf opt/DiscoPoP/packages
# delete venv folder if exists
rm -rf opt/DiscoPoP/venv
# delete docs folder if exists
rm -rf opt/DiscoPoP/docs

# delete only if release is true
if [ "$RELEASE" = "true" ]; then
    # delete test folder if exists
    rm -rf opt/DiscoPoP/test
fi

# cleanup
rm -rf opt/DiscoPoP/tmp_packages_build_dir

# create packages folder
cd ..
mkdir -p packages

# build package
dpkg-deb --build tmp_package_build_dir packages/${PACKAGE_NAME}
chmod 775 packages/${PACKAGE_NAME}

# cleanup
rm -rf tmp_package_build_dir
