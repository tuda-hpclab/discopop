#include <gtest/gtest.h>

#include <cstdint>
#include <unordered_set>

#include "../../../profiler/rtlib/memory/PerfectShadow.hpp"
#include "../../../profiler/rtlib/memory/ShadowMemory.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

using namespace __dp;

// What __dp_init sets up and __dp_finalize tears down again when the runtime profiles without
// worker threads: one shadow memory for the whole program instead of one per worker, and the
// per-thread dependency map the callbacks fill. Finalizing has to merge that map into the global
// one, because nothing else does it in this configuration.
class SingleThreadedExecutionTest : public ::testing::Test {
protected:
  depMap collected_dependencies;

  void SetUp() override {
    previous_all_deps = allDeps;
    previous_shadow = singleThreadedExecutionSMem;
    previous_map = myMap;
    previous_use_perfect = USE_PERFECT;
    previous_sig_elem_bit = SIG_ELEM_BIT;
    previous_sig_num_elem = SIG_NUM_ELEM;
    previous_sig_num_hash = SIG_NUM_HASH;

    allDeps = &collected_dependencies;
    singleThreadedExecutionSMem = nullptr;
    myMap = nullptr;
  }

  void TearDown() override {
    delete singleThreadedExecutionSMem;
    singleThreadedExecutionSMem = previous_shadow;
    delete myMap;
    myMap = previous_map;

    allDeps = previous_all_deps;
    USE_PERFECT = previous_use_perfect;
    SIG_ELEM_BIT = previous_sig_elem_bit;
    SIG_NUM_ELEM = previous_sig_num_elem;
    SIG_NUM_HASH = previous_sig_num_hash;
  }

private:
  depMap *previous_all_deps = nullptr;
  AbstractShadow *previous_shadow = nullptr;
  depMap *previous_map = nullptr;
  bool previous_use_perfect = true;
  std::int32_t previous_sig_elem_bit = 0;
  std::int32_t previous_sig_num_elem = 0;
  std::int32_t previous_sig_num_hash = 0;
};

TEST_F(SingleThreadedExecutionTest, testInitializingCreatesTheShadowMemoryAndTheDependencyMap) {
  initSingleThreadedExecution();

  EXPECT_NE(singleThreadedExecutionSMem, nullptr);
  EXPECT_NE(myMap, nullptr);
}

TEST_F(SingleThreadedExecutionTest, testTheNewDependencyMapIsEmpty) {
  initSingleThreadedExecution();

  EXPECT_TRUE(myMap->empty());
}

TEST_F(SingleThreadedExecutionTest, testTheNewShadowMemoryKnowsNoAccess) {
  initSingleThreadedExecution();

  EXPECT_EQ(singleThreadedExecutionSMem->testInRead(0x1000), 0);
  EXPECT_EQ(singleThreadedExecutionSMem->testInWrite(0x1000), 0);
}

// Which of the two shadow memories was created is told apart by what they can do rather than by
// their type: the runtime library is built without RTTI, so a dynamic_cast across it is not an
// option. A perfect shadow keeps every address and can enumerate them again; a signature keeps
// none and reports an empty range.
TEST_F(SingleThreadedExecutionTest, testThePerfectShadowIsUsedByDefault) {
  USE_PERFECT = true;
  initSingleThreadedExecution();

  singleThreadedExecutionSMem->insertToWrite(0x1000, 1);

  EXPECT_EQ(singleThreadedExecutionSMem->getAddrsInRange(0x0, 0x2000), (std::unordered_set<ADDR>{0x1000}));
}

// the signature based alternative, sized from the three shadow memory parameters
TEST_F(SingleThreadedExecutionTest, testTheSignatureShadowIsUsedWhenThePerfectOneIsTurnedOff) {
  USE_PERFECT = false;
  SIG_ELEM_BIT = 56;
  SIG_NUM_ELEM = 1024;
  SIG_NUM_HASH = 2;
  initSingleThreadedExecution();

  singleThreadedExecutionSMem->insertToWrite(0x1000, 1);

  EXPECT_EQ(singleThreadedExecutionSMem->testInWrite(0x1000), 1);
  EXPECT_TRUE(singleThreadedExecutionSMem->getAddrsInRange(0x0, 0x2000).empty());
}

TEST_F(SingleThreadedExecutionTest, testFinalizingReleasesTheShadowMemoryAndTheDependencyMap) {
  initSingleThreadedExecution();

  finalizeSingleThreadedExecution();

  EXPECT_EQ(singleThreadedExecutionSMem, nullptr);
  EXPECT_EQ(myMap, nullptr);
}

// nothing else merges the per-thread map in this configuration, so what the callbacks recorded
// would never reach the report if finalizing skipped it
TEST_F(SingleThreadedExecutionTest, testFinalizingMergesWhatWasRecordedIntoTheGlobalDependencies) {
  initSingleThreadedExecution();
  (*myMap)[42].insert(Dep(RAW, 7, "x", 3));

  finalizeSingleThreadedExecution();

  ASSERT_EQ(collected_dependencies.count(42), 1u);
  EXPECT_EQ(collected_dependencies[42].size(), 1u);
}

TEST_F(SingleThreadedExecutionTest, testFinalizingKeepsTheDependenciesThatWereAlreadyGlobal) {
  collected_dependencies[42].insert(Dep(WAR, 8, "y", 4));
  initSingleThreadedExecution();
  (*myMap)[42].insert(Dep(RAW, 7, "x", 3));

  finalizeSingleThreadedExecution();

  EXPECT_EQ(collected_dependencies[42].size(), 2u);
}

TEST_F(SingleThreadedExecutionTest, testFinalizingWithoutRecordedDependenciesChangesNothing) {
  initSingleThreadedExecution();

  finalizeSingleThreadedExecution();

  EXPECT_TRUE(collected_dependencies.empty());
}
