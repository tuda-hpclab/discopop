#include <gtest/gtest.h>

#include <cstdlib>
#include <string>

#include "../../../profiler/rtlib/output_paths.hpp"

// Every result file the runtime writes goes through profiler_output_path(). __dp_init pins
// DOT_DISCOPOP_PROFILER down before any other code of an instrumented program runs, so by the time
// a callback wants to write something the directory is known; the function only has to join it
// with the file name.
class OutputPathsTest : public ::testing::Test {
protected:
  void SetUp() override {
    const char *const current = getenv(variable);
    had_directory = current != nullptr;
    if (had_directory) {
      previous_directory = current;
    }
  }

  void TearDown() override {
    if (had_directory) {
      setenv(variable, previous_directory.c_str(), 1);
    } else {
      unsetenv(variable);
    }
  }

  static constexpr const char *variable = "DOT_DISCOPOP_PROFILER";

private:
  bool had_directory = false;
  std::string previous_directory;
};

TEST_F(OutputPathsTest, testTheFileIsPlacedInTheProfilerDirectory) {
  setenv(variable, "/tmp/some_target/.discopop/profiler", 1);

  EXPECT_EQ(__dp::profiler_output_path("loop_meta.txt"), "/tmp/some_target/.discopop/profiler/loop_meta.txt");
}

// write_results() asks for statistics/profiling_time.txt, so the file may name a subdirectory
TEST_F(OutputPathsTest, testAFileInASubdirectoryKeepsItsSubdirectory) {
  setenv(variable, "/tmp/target/.discopop/profiler", 1);

  EXPECT_EQ(__dp::profiler_output_path("statistics/profiling_time.txt"),
            "/tmp/target/.discopop/profiler/statistics/profiling_time.txt");
}

TEST_F(OutputPathsTest, testARelativeDirectoryIsKeptRelative) {
  setenv(variable, ".discopop/profiler", 1);

  EXPECT_EQ(__dp::profiler_output_path("dynamic_dependencies.txt"), ".discopop/profiler/dynamic_dependencies.txt");
}

// An unset variable means __dp_init did not run. A build with asserts says so and stops; the
// shipped build has no assert and falls back to the directory __dp_init would have established,
// rather than constructing a std::string from a null pointer.
TEST_F(OutputPathsTest, testAnUnsetDirectoryFallsBackToTheDefaultOne) {
  unsetenv(variable);

#ifdef NDEBUG
  EXPECT_EQ(__dp::profiler_output_path("reduction.txt"), ".discopop/profiler/reduction.txt");
#else
  EXPECT_DEATH(__dp::profiler_output_path("reduction.txt"), "DOT_DISCOPOP_PROFILER is unset");
#endif
}

// An empty value is not the same as an unset one: it is a directory the runtime was given, and
// joining it produces an absolute path, which is what the callers then try to open.
TEST_F(OutputPathsTest, testAnEmptyDirectoryIsNotTreatedAsUnset) {
  setenv(variable, "", 1);

  EXPECT_EQ(__dp::profiler_output_path("reduction.txt"), "/reduction.txt");
}
