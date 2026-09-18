#include <gtest/gtest.h>

#include <string>

#include "../../../../profiler/rtlib/hybrid_analysis/bb_deps.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

// The registry behind __dp_add_bb_deps. An instrumented module hands over one string covering the
// dependencies of the instructions whose profiling was omitted; the format is produced by
// DPInstrumentationOmission and looks like
//
//   <basic block id>=<dependency>,<dependency>/<basic block id>=<dependency>
//
// with a dependency of the form "<instruction id> NOM <type> <instruction id>|<variable>(<memory
// region>)". process_registered_bb_deps() merges the dependencies of every basic block that was
// actually reported into outPutDeps, keyed by the instruction id the dependency starts with.
class BasicBlockDepsTest : public ::testing::Test {
protected:
  __dp::ReportedBBSet reported_basic_blocks;
  __dp::stringDepMap collected_dependencies;

  void SetUp() override {
    __dp::release_registered_bb_deps();
    __dp::bbList = &reported_basic_blocks;
    __dp::outPutDeps = &collected_dependencies;
  }

  void TearDown() override {
    __dp::release_registered_bb_deps();
    __dp::bbList = nullptr;
    __dp::outPutDeps = nullptr;
  }

  // the registry keeps the pointer, not the characters, so everything registered here has to
  // outlive the call -- string literals do
  static void register_string(const char *const dependencies) {
    __dp::registered_bb_dep_strings().push_back(dependencies);
  }
};

TEST_F(BasicBlockDepsTest, testTheRegistryStartsEmpty) { EXPECT_TRUE(__dp::registered_bb_dep_strings().empty()); }

TEST_F(BasicBlockDepsTest, testTheRegistryIsTheSameContainerOnEveryCall) {
  __dp::registered_bb_dep_strings().push_back("0=1 NOM RAW 2|x(3)");

  ASSERT_EQ(__dp::registered_bb_dep_strings().size(), 1u);
  EXPECT_EQ(&__dp::registered_bb_dep_strings(), &__dp::registered_bb_dep_strings());
}

// release_registered_bb_deps() destroys the storage; the next access constructs it again, empty
TEST_F(BasicBlockDepsTest, testReleasingTheRegistryDropsWhatWasRegistered) {
  register_string("0=1 NOM RAW 2|x(3)");

  __dp::release_registered_bb_deps();

  EXPECT_TRUE(__dp::registered_bb_dep_strings().empty());
}

TEST_F(BasicBlockDepsTest, testReleasingTheRegistryTwiceIsHarmless) {
  register_string("0=1 NOM RAW 2|x(3)");

  __dp::release_registered_bb_deps();
  __dp::release_registered_bb_deps();

  EXPECT_TRUE(__dp::registered_bb_dep_strings().empty());
}

// process_registered_bb_deps() runs from __dp_finalize, where both globals are in place. It is
// reached without them when the runtime shuts down before it ever started up.
TEST_F(BasicBlockDepsTest, testNothingIsProcessedWithoutTheReportedBasicBlocks) {
  register_string("0=1 NOM RAW 2|x(3)");
  __dp::bbList = nullptr;

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

TEST_F(BasicBlockDepsTest, testNothingIsProcessedWithoutTheCollectedDependencies) {
  register_string("0=1 NOM RAW 2|x(3)");
  reported_basic_blocks.insert(0);
  __dp::outPutDeps = nullptr;

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

TEST_F(BasicBlockDepsTest, testADependencyOfAReportedBasicBlockIsCollected) {
  register_string("0=1 NOM RAW 2|x(3)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  ASSERT_EQ(collected_dependencies.count("1"), 1u);
  EXPECT_EQ(collected_dependencies["1"], __dp::stringDepMap::mapped_type{"RAW 2|x(3)"});
}

// the point of the whole registry: a basic block the target never executed contributes nothing
TEST_F(BasicBlockDepsTest, testABasicBlockThatWasNotReportedIsSkipped) {
  register_string("0=1 NOM RAW 2|x(3)");
  reported_basic_blocks.insert(7);

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

TEST_F(BasicBlockDepsTest, testTheDependenciesOfOneBasicBlockAreSplitOnCommas) {
  register_string("0=1 NOM RAW 2|x(3),4 NOM WAR 5|y(6)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  ASSERT_EQ(collected_dependencies.count("1"), 1u);
  EXPECT_EQ(collected_dependencies["1"], __dp::stringDepMap::mapped_type{"RAW 2|x(3)"});
  ASSERT_EQ(collected_dependencies.count("4"), 1u);
  EXPECT_EQ(collected_dependencies["4"], __dp::stringDepMap::mapped_type{"WAR 5|y(6)"});
}

TEST_F(BasicBlockDepsTest, testTheBasicBlocksAreSplitOnSlashes) {
  register_string("0=1 NOM RAW 2|x(3)/7=4 NOM WAW 5|y(6)");
  reported_basic_blocks.insert(7);

  __dp::process_registered_bb_deps();

  EXPECT_EQ(collected_dependencies.count("1"), 0u);
  ASSERT_EQ(collected_dependencies.count("4"), 1u);
  EXPECT_EQ(collected_dependencies["4"], __dp::stringDepMap::mapped_type{"WAW 5|y(6)"});
}

// an allocation is reported as an INIT dependency, which carries no source instruction
TEST_F(BasicBlockDepsTest, testAnInitDependencyIsCollectedAsWell) {
  register_string("0=1 NOM INIT *|x(3)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  ASSERT_EQ(collected_dependencies.count("1"), 1u);
  EXPECT_EQ(collected_dependencies["1"], __dp::stringDepMap::mapped_type{"INIT *|x(3)"});
}

// two instructions depending on the same one end up under the same key
TEST_F(BasicBlockDepsTest, testSeveralDependenciesOfOneInstructionAreKeptTogether) {
  register_string("0=1 NOM RAW 2|x(3),1 NOM WAR 4|x(3)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  ASSERT_EQ(collected_dependencies.count("1"), 1u);
  EXPECT_EQ(collected_dependencies["1"], (__dp::stringDepMap::mapped_type{"RAW 2|x(3)", "WAR 4|x(3)"}));
}

// every module registers its own string, and they are all merged into the same map
TEST_F(BasicBlockDepsTest, testEveryRegisteredStringIsProcessed) {
  register_string("0=1 NOM RAW 2|x(3)");
  register_string("0=4 NOM WAR 5|y(6)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_EQ(collected_dependencies.count("1"), 1u);
  EXPECT_EQ(collected_dependencies.count("4"), 1u);
}

// __dp_add_bb_deps rejects a null pointer, but the registry is public and the loop guards anyway
TEST_F(BasicBlockDepsTest, testANullStringIsSkipped) {
  register_string(nullptr);
  register_string("0=1 NOM RAW 2|x(3)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_EQ(collected_dependencies.count("1"), 1u);
}

TEST_F(BasicBlockDepsTest, testAnEmptyRegistryCollectsNothing) {
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

// an entry without the '=' separating the basic block id from its dependencies has nothing that
// could be looked up in the reported blocks
TEST_F(BasicBlockDepsTest, testAnEntryWithoutDependenciesContributesNothing) {
  register_string("0");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

// The two searches below used to be run without looking at whether they matched. An empty match
// reads back as an empty string, so an entry naming no instruction was collected under the empty
// key -- and outputDeps() writes out every key it finds, so that reached the results as a line
// beginning with " NOM ".
TEST_F(BasicBlockDepsTest, testAnEntryWithoutAnInstructionIdIsSkipped) {
  register_string("0=no numbers in here");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

TEST_F(BasicBlockDepsTest, testAnEntryWithoutADependencyTypeIsSkipped) {
  register_string("0=1 NOM something else entirely");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  EXPECT_TRUE(collected_dependencies.empty());
}

// and neither of them takes the readable entries of the same basic block down with it
TEST_F(BasicBlockDepsTest, testTheReadableEntriesOfTheSameBlockAreStillCollected) {
  register_string("0=no numbers in here,1 NOM something else entirely,2 NOM RAW 3|x(4)");
  reported_basic_blocks.insert(0);

  __dp::process_registered_bb_deps();

  ASSERT_EQ(collected_dependencies.size(), 1u);
  ASSERT_EQ(collected_dependencies.count("2"), 1u);
  EXPECT_EQ(collected_dependencies["2"], __dp::stringDepMap::mapped_type{"RAW 3|x(4)"});
}
