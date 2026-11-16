#include <gtest/gtest.h>

#include "DPUtils.hpp"

#include <unistd.h>

#include <filesystem>
#include <fstream>
#include <string>

// Tests for dputil::FindDotDiscopop / DiscoverDotDiscopop (profiler/share/lib/DPUtils.cpp): which .discopop directory a
// compilation without DOT_DISCOPOP uses. scripts/dp_environment.sh implements the same rule
// (test/end_to_end/dot_discopop_discovery tests both through a build).

namespace {

namespace fs = std::filesystem;

class DotDiscopopTest : public ::testing::Test {
 protected:
  void SetUp() override {
    char dir_template[] = "/tmp/dp_dot_discopop_XXXXXX";
    const char* dir = mkdtemp(dir_template);
    ASSERT_NE(dir, nullptr);
    // canonical: /tmp may be a symbolic link, and the functions resolve them
    root_ = fs::canonical(dir);
  }
  void TearDown() override { fs::remove_all(root_); }

  fs::path Make(const std::string& relative) {
    const fs::path path = root_ / relative;
    fs::create_directories(path);
    return path;
  }

  fs::path root_;
};

TEST_F(DotDiscopopTest, FindsTheDirectoryInTheStartDirectoryItself) {
  Make("project/.discopop/project");
  EXPECT_EQ(dputil::FindDotDiscopop((root_ / "project").string()), (root_ / "project/.discopop").string());
}

TEST_F(DotDiscopopTest, FindsTheDirectoryFromABuildDirectoryBelowTheProject) {
  Make("project/.discopop/project");
  const fs::path build = Make("project/build/sub/dir");
  EXPECT_EQ(dputil::FindDotDiscopop(build.string()), (root_ / "project/.discopop").string());
}

TEST_F(DotDiscopopTest, FindsNothingWithoutADirectory) {
  const fs::path build = Make("project/build");
  // an ancestor of the temporary directory may have one: only the result below the temporary directory counts
  const std::string found = dputil::FindDotDiscopop(build.string());
  EXPECT_TRUE(found.empty() || found.rfind(root_.string(), 0) != 0) << found;
}

TEST_F(DotDiscopopTest, AFileNamedLikeTheDirectoryIsNotOne) {
  Make("project");
  std::ofstream((root_ / "project/.discopop").string()).put('x');
  const std::string found = dputil::FindDotDiscopop((root_ / "project").string());
  EXPECT_TRUE(found.empty() || found.rfind(root_.string(), 0) != 0) << found;
}

TEST_F(DotDiscopopTest, TheNearestDirectoryWins) {
  Make("project/.discopop/project");
  Make("project/build/.discopop/project");
  EXPECT_EQ(dputil::FindDotDiscopop((root_ / "project/build").string()), (root_ / "project/build/.discopop").string());
}

TEST_F(DotDiscopopTest, ALeftoverWithoutProjectIsStillTheNearestButTheOneWithTheProjectIsReported) {
  Make("project/.discopop/project");
  Make("project/build/.discopop/profiler");
  std::string shadowed;
  EXPECT_EQ(dputil::FindDotDiscopop((root_ / "project/build").string(), &shadowed),
            (root_ / "project/build/.discopop").string());
  EXPECT_EQ(shadowed, (root_ / "project/.discopop").string());
}

TEST_F(DotDiscopopTest, ALeftoverWithoutAnyOtherIsNotReported) {
  Make("project/build/.discopop/profiler");
  std::string shadowed;
  EXPECT_EQ(dputil::FindDotDiscopop((root_ / "project/build").string(), &shadowed),
            (root_ / "project/build/.discopop").string());
  EXPECT_TRUE(shadowed.empty());
}

TEST_F(DotDiscopopTest, SymbolicLinksAreResolved) {
  Make("project/.discopop/project");
  Make("elsewhere");
  fs::create_directory_symlink(root_ / "project", root_ / "elsewhere/link");
  EXPECT_EQ(dputil::FindDotDiscopop((root_ / "elsewhere/link").string()), (root_ / "project/.discopop").string());
}

TEST_F(DotDiscopopTest, ABuildOutsideOfTheProjectFindsItFromTheSourceFile) {
  Make("project/.discopop/project");
  Make("project/src");
  const fs::path build = Make("elsewhere/build");
  const fs::path previous = fs::current_path();
  fs::current_path(build);
  const std::string found = dputil::DiscoverDotDiscopop((root_ / "project/src/a.cpp").string());
  fs::current_path(previous);
  EXPECT_EQ(found, (root_ / "project/.discopop").string());
}

TEST_F(DotDiscopopTest, TheCurrentDirectoryComesBeforeTheSourceFile) {
  Make("project/.discopop/project");
  Make("other/.discopop/project");
  Make("other/src");
  const fs::path previous = fs::current_path();
  fs::current_path(root_ / "project");
  const std::string found = dputil::DiscoverDotDiscopop((root_ / "other/src/a.cpp").string());
  fs::current_path(previous);
  EXPECT_EQ(found, (root_ / "project/.discopop").string());
}

}  // namespace
