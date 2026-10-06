#include <gtest/gtest.h>

#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsTypes.hpp"

using namespace __dp;

// mergeDeps moves the dependencies a worker thread collected for one chunk (myMap) into allDeps. It
// used to clear myMap without freeing its sets, which leaked one set per dependency sink and chunk.
class MergeDepsTest : public ::testing::Test {
protected:
  void SetUp() override {
    allDeps = new depMap();
    myMap = new depMap();
  }

  void TearDown() override {
    for (auto &entry : *allDeps) {
      delete entry.second;
    }
    delete allDeps;
    for (auto &entry : *myMap) {
      delete entry.second;
    }
    delete myMap;
    allDeps = nullptr;
    myMap = nullptr;
  }

  static const char *var() {
    static const char name[] = "x";
    return name;
  }
};

TEST_F(MergeDepsTest, aNewSinkTakesOverTheThreadsSet) {
  auto *collected = new depSet();
  collected->insert(Dep(RAW, 11, var(), 0));
  (*myMap)[100] = collected;

  mergeDeps();

  ASSERT_EQ(allDeps->size(), 1);
  // the set itself is handed over, so nothing is copied or leaked
  EXPECT_EQ(allDeps->at(100), collected);
  EXPECT_EQ(allDeps->at(100)->size(), 1);
  EXPECT_TRUE(myMap->empty());
}

TEST_F(MergeDepsTest, aKnownSinkGetsTheUnionAndTheThreadsSetIsFreed) {
  auto *global = new depSet();
  global->insert(Dep(RAW, 11, var(), 0));
  (*allDeps)[100] = global;
  auto *collected = new depSet();
  collected->insert(Dep(RAW, 11, var(), 0));
  collected->insert(Dep(WAR, 12, var(), 0));
  (*myMap)[100] = collected;

  mergeDeps();

  EXPECT_EQ(allDeps->at(100), global);
  EXPECT_EQ(global->size(), 2);
  EXPECT_TRUE(myMap->empty());
}

TEST_F(MergeDepsTest, repeatedChunksAccumulateInAllDeps) {
  for (LID chunk = 0; chunk < 3; ++chunk) {
    auto *collected = new depSet();
    collected->insert(Dep(RAW, 20 + chunk, var(), 0));
    (*myMap)[100] = collected;
    auto *other = new depSet();
    other->insert(Dep(WAW, 30, var(), 0));
    (*myMap)[200 + chunk] = other;

    mergeDeps();
    EXPECT_TRUE(myMap->empty());
  }

  EXPECT_EQ(allDeps->at(100)->size(), 3);
  EXPECT_EQ(allDeps->size(), 4);
}
