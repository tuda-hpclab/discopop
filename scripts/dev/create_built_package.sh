# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

VERSION=$(cat library/discopop_library/global_data/version/VERSION)

PACKAGE_NAME="discopop-${VERSION}-$(dpkg --print-architecture)-$(uname --kernel-name).deb"

rm -vf packages/${PACKAGE_NAME}


# create a temporary copy of the code to build the package
##rm -rf tmp_package_build_dir
##mkdir -p tmp_package_build_dir
##cd tmp_package_build_dir
##cmake .. -DIS_DEB_INSTALL="TRUE" -DDP_PTHREAD_COMPATIBILITY_MODE=0 -DDP_NUM_WORKERS=8 -DDP_RTLIB_VERBOSE=0 -DDP_MEMORY_REGION_DEALIASING=0 -DDP_BRANCH_TRACKING=0 -DDP_CALLSTACK_PROFILING=0 -DDP_STACK_ACCESS_DETECTION=0 -DDP_CALLSTACK_PROFILING_ENABLE_CUTOFF=1 -DDP_INTERNAL_TIMER=0 -DDP_HYBRID_PROFILING=1 -DDP_HYBRID_PROFILING_CUTOFF=0 -DDP_HYBRID_PROFILING_CUTOFF_IGNORE_PROBABILITY=1 -DDP_PROFILING_SAMPLING_PROBABILITY=0 -DDP_CALLTREE_PROFILING=1 -DDP_CALLTREE_PROFILING_METADATA_CUTOFF=5 -DDP_CALLTREE_PROFILING_METADATA_CUTOFF_IGNORE_PROBABILITY=1
##echo "Building..."
##make -j 4
##cd ..

# cp -r * tmp_package_build_dir


# modify folder structure to install DiscoPoP to /opt when installing the package
rm -rf tmp_package_dir
mkdir -p tmp_package_dir
cd tmp_package_dir

mkdir opt
mkdir opt/DiscoPoP
mkdir opt/DiscoPoP/build
mkdir opt/DiscoPoP/build/libi
mkdir opt/DiscoPoP/build/rtlib
mkdir opt/DiscoPoP/build/scripts
cp -r ../DEBIAN/prebuilt DEBIAN
cp ../library/discopop_library/global_data/version/VERSION opt/DiscoPoP

# specify files to be included in the package
#mv * opt/DiscoPoP
cp ../build/libi/LLVMDiscoPoP.so opt/DiscoPoP/build/libi
cp ../build/rtlib/libDiscoPoP_RT.a opt/DiscoPoP/build/rtlib
cp ../build/scripts/CC_wrapper.sh opt/DiscoPoP/build/scripts
cp ../build/scripts/CXX_wrapper.sh opt/DiscoPoP/build/scripts
cp ../build/scripts/CMAKE_wrapper.sh opt/DiscoPoP/build/scripts
cp ../build/scripts/dp-fmap opt/DiscoPoP/build/scripts
cp -r ../example opt/DiscoPoP

# specify files to be removed from the package
#find opt/DiscoPoP -path */__pycache__* -delete
#find opt/DiscoPoP -path */.pytest_cache* -delete
#find opt/DiscoPoP -path */.mypy_cache* -delete
#find opt/DiscoPoP -path */.idea* -delete
#find opt/DiscoPoP -path */.vscode* -delete

# add the Version tag to DEBIAN/control.raw to create DEBIAN/control
echo "$(cat DEBIAN/control.raw)" > DEBIAN/control
echo "Version: $(cat ../library/discopop_library/global_data/version/VERSION)" >> DEBIAN/control
echo "Architecture: $(dpkg --print-architecture)" >> DEBIAN/control
echo "" >> DEBIAN/control

# create packages folder
cd ..
mkdir -p packages
# build package
dpkg-deb --build tmp_package_dir packages/${PACKAGE_NAME}
chmod 775 packages/${PACKAGE_NAME}

# cleanup
#rm -rf tmp_package_build_dir
rm -rf tmp_package_dir

echo "Hint: this package can not be used during development if python packages have been modified!"
echo "---> Reason: Python modules will be loaded from Pypi."
