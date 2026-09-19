#include <gtest/gtest.h>

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <sstream>
#include <string>
#include <unistd.h>
#include <vector>

#include "../../../profiler/rtlib/DPUtils.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

using namespace __dp;

namespace {

// A location id as the runtime builds it: the instruction id in the lower half, the call path
// state the access was observed in in the upper one.
std::int64_t located_at(const std::uint32_t instruction_id, const std::uint32_t callpath_state) {
  return static_cast<std::int64_t>(instruction_id) | (static_cast<std::int64_t>(callpath_state) << 32);
}

} // namespace

// The stages between the recorded accesses and dynamic_dependencies.txt. generateStringDepMap
// turns the dependencies the analysis collected into the text of the report, keyed by the
// instruction and the call path state they belong to, and outputDeps writes that text out.
class RuntimeFunctionsTest : public ::testing::Test {
protected:
  depMap collected_dependencies;
  stringDepMap rendered_dependencies;

  void SetUp() override {
    previous_all_deps = allDeps;
    previous_output_deps = outPutDeps;
    previous_out = out;

    allDeps = &collected_dependencies;
    outPutDeps = &rendered_dependencies;
    out = nullptr;
  }

  void TearDown() override {
    allDeps = previous_all_deps;
    outPutDeps = previous_output_deps;
    out = previous_out;

    if (!report_path.empty()) {
      std::remove(report_path.c_str());
    }
  }

  // outputDeps writes into the std::ofstream the runtime keeps in `out`, so reading its result
  // back means going through a file.
  std::string write_report() {
    char pattern[] = "/tmp/discopop_runtime_functions_test_XXXXXX";
    const int descriptor = ::mkstemp(pattern);
    EXPECT_NE(descriptor, -1);
    ::close(descriptor);
    report_path = pattern;

    std::ofstream report(report_path);
    out = &report;
    outputDeps();
    out = nullptr;
    report.close();

    std::ifstream written(report_path);
    std::stringstream contents;
    contents << written.rdbuf();
    return contents.str();
  }

  static std::vector<std::string> sorted_lines(const std::string &text) {
    std::vector<std::string> lines;
    std::istringstream stream(text);
    std::string line;
    while (std::getline(stream, line)) {
      lines.push_back(line);
    }
    std::sort(lines.begin(), lines.end());
    return lines;
  }

private:
  depMap *previous_all_deps = nullptr;
  stringDepMap *previous_output_deps = nullptr;
  std::ofstream *previous_out = nullptr;
  std::string report_path;
};

TEST_F(RuntimeFunctionsTest, testADependencyIsRenderedWithItsTypeLocationVariableAndMemoryRegion) {
  collected_dependencies[located_at(10, 2)].insert(Dep(RAW, located_at(7, 1), "x", 3));

  generateStringDepMap();

  ASSERT_EQ(rendered_dependencies.size(), 1u);
  ASSERT_EQ(rendered_dependencies.count("10@2"), 1u);
  EXPECT_EQ(rendered_dependencies["10@2"], (std::unordered_set<std::string>{"RAW 7@1|x(3)"}));
}

TEST_F(RuntimeFunctionsTest, testEveryDependencyTypeHasItsOwnName) {
  collected_dependencies[located_at(10, 0)].insert(Dep(RAW, located_at(1, 0), "x", 0));
  collected_dependencies[located_at(11, 0)].insert(Dep(WAR, located_at(2, 0), "x", 0));
  collected_dependencies[located_at(12, 0)].insert(Dep(WAW, located_at(3, 0), "x", 0));
  collected_dependencies[located_at(13, 0)].insert(Dep(INIT, located_at(4, 0), "x", 0));

  generateStringDepMap();

  EXPECT_EQ(rendered_dependencies["10@0"], (std::unordered_set<std::string>{"RAW 1@0|x(0)"}));
  EXPECT_EQ(rendered_dependencies["11@0"], (std::unordered_set<std::string>{"WAR 2@0|x(0)"}));
  EXPECT_EQ(rendered_dependencies["12@0"], (std::unordered_set<std::string>{"WAW 3@0|x(0)"}));
  EXPECT_EQ(rendered_dependencies["13@0"], (std::unordered_set<std::string>{"INIT 4@0|x(0)"}));
}

// LID 0 carries no source location, so there is nothing to attribute a dependency to
TEST_F(RuntimeFunctionsTest, testDependenciesWithoutALocationAreDropped) {
  collected_dependencies[0].insert(Dep(RAW, located_at(7, 1), "x", 3));

  generateStringDepMap();

  EXPECT_TRUE(rendered_dependencies.empty());
}

TEST_F(RuntimeFunctionsTest, testAllDependenciesOfOneLocationAreRenderedTogether) {
  collected_dependencies[located_at(10, 2)].insert(Dep(RAW, located_at(7, 1), "x", 3));
  collected_dependencies[located_at(10, 2)].insert(Dep(WAR, located_at(8, 1), "y", 4));

  generateStringDepMap();

  ASSERT_EQ(rendered_dependencies.size(), 1u);
  EXPECT_EQ(rendered_dependencies["10@2"], (std::unordered_set<std::string>{"RAW 7@1|x(3)", "WAR 8@1|y(4)"}));
}

// The same instruction is reached in several call path states, and those are separate keys: the
// pattern detection tells the calls apart by them.
TEST_F(RuntimeFunctionsTest, testTheSameInstructionInAnotherCallPathStateIsItsOwnEntry) {
  collected_dependencies[located_at(10, 1)].insert(Dep(RAW, located_at(7, 1), "x", 3));
  collected_dependencies[located_at(10, 2)].insert(Dep(RAW, located_at(7, 2), "x", 3));

  generateStringDepMap();

  EXPECT_EQ(rendered_dependencies.size(), 2u);
  EXPECT_EQ(rendered_dependencies["10@1"], (std::unordered_set<std::string>{"RAW 7@1|x(3)"}));
  EXPECT_EQ(rendered_dependencies["10@2"], (std::unordered_set<std::string>{"RAW 7@2|x(3)"}));
}

// process_registered_bb_deps() fills the same map from the statically determined dependencies
// before generateStringDepMap() runs, so an entry that is already there is extended
TEST_F(RuntimeFunctionsTest, testDependenciesAreAddedToWhatIsAlreadyReportedForALocation) {
  rendered_dependencies["10@2"].insert("WAR 8@1|y(4)");
  collected_dependencies[located_at(10, 2)].insert(Dep(RAW, located_at(7, 1), "x", 3));

  generateStringDepMap();

  EXPECT_EQ(rendered_dependencies["10@2"], (std::unordered_set<std::string>{"RAW 7@1|x(3)", "WAR 8@1|y(4)"}));
}

TEST_F(RuntimeFunctionsTest, testRenderingWithoutCollectedDependenciesReportsNothing) {
  generateStringDepMap();

  EXPECT_TRUE(rendered_dependencies.empty());
}

TEST_F(RuntimeFunctionsTest, testAReportedLocationCarriesItsDependencies) {
  rendered_dependencies["10@2"] = {"RAW 7@1|x(3)"};

  EXPECT_EQ(write_report(), "10@2 NOM  RAW 7@1|x(3)\n");
}

TEST_F(RuntimeFunctionsTest, testALocationWithoutDependenciesIsStillReported) {
  rendered_dependencies["10@2"] = {};

  EXPECT_EQ(write_report(), "10@2 NOM \n");
}

TEST_F(RuntimeFunctionsTest, testEveryReportedLocationGetsItsOwnLine) {
  rendered_dependencies["10@2"] = {"RAW 7@1|x(3)"};
  rendered_dependencies["11@2"] = {"WAR 8@1|y(4)"};

  EXPECT_EQ(sorted_lines(write_report()),
            (std::vector<std::string>{"10@2 NOM  RAW 7@1|x(3)", "11@2 NOM  WAR 8@1|y(4)"}));
}

TEST_F(RuntimeFunctionsTest, testAnEmptyReportIsEmpty) { EXPECT_EQ(write_report(), ""); }

// Without DP_MEMORY_REGION_DEALIASING the runtime does not ask the memory manager which
// allocation an address belongs to, and the variable name stands for itself.
TEST_F(RuntimeFunctionsTest, testTheMemoryRegionIdOfAnAddressIsTheFallbackByDefault) {
#if DP_MEMORY_REGION_DEALIASING
  GTEST_SKIP() << "the dealiasing build asks the memory manager instead";
#else
  EXPECT_EQ(getMemoryRegionIdFromAddr("x", 0x1000), "x");
#endif
}
