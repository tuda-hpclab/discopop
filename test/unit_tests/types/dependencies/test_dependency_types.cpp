#include <gtest/gtest.h>

#include <cstring>
#include <string>

#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"

using namespace __dp;

// The records the runtime passes between its stages: an AccessInfo is what a callback puts into
// the first access queue, and a Dep is what the analysis derives from two of them. Which Deps
// count as the same one is decided by DepHasher and eqDep, because they are the hash and the
// equality of depSet -- the set that decides what ends up in dynamic_dependencies.txt.
class DependencyTypesTest : public ::testing::Test {
protected:
  // the runtime identifies variables by the address of their name, not by its characters, so a
  // test that wants two distinct variables needs two distinct pointers
  static constexpr const char *first_variable = "a";
  static constexpr const char *second_variable = "b";
};

TEST_F(DependencyTypesTest, testADefaultAccessInfoDescribesNoAccess) {
  const AccessInfo access;

  EXPECT_FALSE(access.isRead);
  EXPECT_FALSE(access.skip);
  EXPECT_EQ(access.lid, 0);
  EXPECT_EQ(access.AAvar, 0);
  EXPECT_EQ(access.addr, 0);
  EXPECT_STREQ(access.var, "");
}

TEST_F(DependencyTypesTest, testAnAccessInfoKeepsWhatItWasGiven) {
  char variable[] = "x";

  const AccessInfo access(true, 42, variable, 7, 0x1000);

  EXPECT_TRUE(access.isRead);
  EXPECT_EQ(access.lid, 42);
  EXPECT_EQ(access.var, variable);
  EXPECT_EQ(access.AAvar, 7);
  EXPECT_EQ(access.addr, 0x1000);
}

// skip marks an access whose dependencies the pass already determined statically
TEST_F(DependencyTypesTest, testAnAccessInfoIsNotSkippedUnlessItIsSaidToBe) {
  char variable[] = "x";

  EXPECT_FALSE(AccessInfo(true, 42, variable, 7, 0x1000).skip);
  EXPECT_TRUE(AccessInfo(true, 42, variable, 7, 0x1000, true).skip);
}

TEST_F(DependencyTypesTest, testADependencyKeepsWhatItWasGiven) {
  const Dep dependency(RAW, 42, first_variable, 7);

  EXPECT_EQ(dependency.type, RAW);
  EXPECT_EQ(dependency.depOn, 42);
  EXPECT_EQ(dependency.var, first_variable);
  EXPECT_EQ(dependency.AAvar, 7);
}

TEST_F(DependencyTypesTest, testTwoIdenticalDependenciesAreEqual) {
  EXPECT_TRUE(eqDep{}(Dep(RAW, 42, first_variable, 7), Dep(RAW, 42, first_variable, 7)));
}

TEST_F(DependencyTypesTest, testDependenciesOfDifferentTypesDiffer) {
  EXPECT_FALSE(eqDep{}(Dep(RAW, 42, first_variable, 7), Dep(WAR, 42, first_variable, 7)));
}

TEST_F(DependencyTypesTest, testDependenciesOnDifferentLocationsDiffer) {
  EXPECT_FALSE(eqDep{}(Dep(RAW, 42, first_variable, 7), Dep(RAW, 43, first_variable, 7)));
}

TEST_F(DependencyTypesTest, testDependenciesOnDifferentVariablesDiffer) {
  EXPECT_FALSE(eqDep{}(Dep(RAW, 42, first_variable, 7), Dep(RAW, 42, second_variable, 7)));
}

// variables are told apart by the address of their name; equal characters at different addresses
// are two variables as far as the runtime is concerned
TEST_F(DependencyTypesTest, testVariablesAreComparedByAddressAndNotByName) {
  const std::string first = "same";
  const std::string second = "same";
  ASSERT_NE(first.c_str(), second.c_str());

  EXPECT_FALSE(eqDep{}(Dep(RAW, 42, first.c_str(), 7), Dep(RAW, 42, second.c_str(), 7)));
}

// the memory region is not part of the identity: two accesses to the same variable that were
// attributed to different allocations still merge into one dependency
TEST_F(DependencyTypesTest, testTheMemoryRegionDoesNotDistinguishDependencies) {
  EXPECT_TRUE(eqDep{}(Dep(RAW, 42, first_variable, 7), Dep(RAW, 42, first_variable, 8)));
}

TEST_F(DependencyTypesTest, testEqualDependenciesHashAlike) {
  EXPECT_EQ(DepHasher{}(Dep(RAW, 42, first_variable, 7)), DepHasher{}(Dep(RAW, 42, first_variable, 8)));
}

// the hash only reads the location and the type, so the variable may not change it -- otherwise
// two dependencies eqDep calls equal could land in different buckets
TEST_F(DependencyTypesTest, testTheVariableDoesNotChangeTheHash) {
  EXPECT_EQ(DepHasher{}(Dep(RAW, 42, first_variable, 7)), DepHasher{}(Dep(RAW, 42, second_variable, 7)));
}

TEST_F(DependencyTypesTest, testDependenciesOnDifferentLocationsHashDifferently) {
  EXPECT_NE(DepHasher{}(Dep(RAW, 42, first_variable, 7)), DepHasher{}(Dep(RAW, 43, first_variable, 7)));
}

TEST_F(DependencyTypesTest, testASetKeepsOneOfTwoIdenticalDependencies) {
  depSet dependencies;

  dependencies.insert(Dep(RAW, 42, first_variable, 7));
  dependencies.insert(Dep(RAW, 42, first_variable, 7));

  EXPECT_EQ(dependencies.size(), 1u);
}

TEST_F(DependencyTypesTest, testASetMergesDependenciesThatOnlyDifferInTheirMemoryRegion) {
  depSet dependencies;

  dependencies.insert(Dep(RAW, 42, first_variable, 7));
  dependencies.insert(Dep(RAW, 42, first_variable, 8));

  EXPECT_EQ(dependencies.size(), 1u);
}

TEST_F(DependencyTypesTest, testASetKeepsDependenciesOfDifferentTypesApart) {
  depSet dependencies;

  dependencies.insert(Dep(RAW, 42, first_variable, 7));
  dependencies.insert(Dep(WAR, 42, first_variable, 7));
  dependencies.insert(Dep(WAW, 42, first_variable, 7));

  EXPECT_EQ(dependencies.size(), 3u);
}

TEST_F(DependencyTypesTest, testASetKeepsDependenciesOnDifferentVariablesApart) {
  depSet dependencies;

  dependencies.insert(Dep(RAW, 42, first_variable, 7));
  dependencies.insert(Dep(RAW, 42, second_variable, 7));

  EXPECT_EQ(dependencies.size(), 2u);
}
