#include <gtest/gtest.h>

#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsTypes.hpp"

using namespace __dp;

// mergeDeps moves the dependencies a worker thread collected (myMap) into allDeps and empties myMap.
class MergeDepsTest : public ::testing::Test {
protected:
  void SetUp() override {
    allDeps = new depMap();
    myMap = new depMap();
  }

  void TearDown() override {
    delete allDeps;
    delete myMap;
    allDeps = nullptr;
    myMap = nullptr;
  }

  static const char *var() {
    static const char name[] = "x";
    return name;
  }
};

TEST_F(MergeDepsTest, aNewSinkTakesOverTheThreadsDependencies) {
  (*myMap)[100].insert(Dep(RAW, 11, var(), 0));

  mergeDeps();

  ASSERT_EQ(allDeps->size(), 1);
  EXPECT_EQ(allDeps->at(100).size(), 1);
  EXPECT_EQ(allDeps->at(100).count(Dep(RAW, 11, var(), 0)), 1);
  EXPECT_TRUE(myMap->empty());
}

TEST_F(MergeDepsTest, aKnownSinkGetsTheUnion) {
  (*allDeps)[100].insert(Dep(RAW, 11, var(), 0));
  (*myMap)[100].insert(Dep(RAW, 11, var(), 0));
  (*myMap)[100].insert(Dep(WAR, 12, var(), 0));

  mergeDeps();

  EXPECT_EQ(allDeps->at(100).size(), 2);
  EXPECT_TRUE(myMap->empty());
}

TEST_F(MergeDepsTest, repeatedMergesAccumulateInAllDeps) {
  for (LID round = 0; round < 3; ++round) {
    (*myMap)[100].insert(Dep(RAW, 20 + round, var(), 0));
    (*myMap)[200 + round].insert(Dep(WAW, 30, var(), 0));

    mergeDeps();
    EXPECT_TRUE(myMap->empty());
  }

  EXPECT_EQ(allDeps->at(100).size(), 3);
  EXPECT_EQ(allDeps->size(), 4);
}
