#include <gtest/gtest.h>
#include <sys/wait.h>
#include <unistd.h>

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <map>
#include <set>
#include <string>
#include <vector>

#include "DPUtils.hpp"

// Tests for dputil::GetFileId (profiler/share/lib/DPUtils.cpp) with several compiler processes, as in a parallel build
// (make -j): all of them register the files they see in the one FileMapping.txt of the build, and a file must get
// exactly one id, an id exactly one file. Without the lock around rereading and appending, the processes below handed
// out ids twice in every run.

namespace {

namespace fs = std::filesystem;

constexpr int kProcesses = 8;
constexpr int kOwnFiles = 200;
constexpr int kSharedFiles = 50;

class FileMappingTest : public ::testing::Test {
 protected:
  void SetUp() override {
    char dir_template[] = "/tmp/dp_file_mapping_XXXXXX";
    const char* dir = mkdtemp(dir_template);
    ASSERT_NE(dir, nullptr);
    root_ = fs::canonical(dir);
    fs::create_directories(root_ / ".discopop");
    saved_root_ = Getenv("DP_PROJECT_ROOT_DIR");
    saved_mapping_path_ = FileMappingPath();
    setenv("DP_PROJECT_ROOT_DIR", root_.c_str(), 1);
  }

  void TearDown() override {
    if (saved_root_.empty()) {
      unsetenv("DP_PROJECT_ROOT_DIR");
    } else {
      setenv("DP_PROJECT_ROOT_DIR", saved_root_.c_str(), 1);
    }
    FileMappingPath() = saved_mapping_path_;
    fs::remove_all(root_);
  }

  static std::string Getenv(const char* name) {
    const char* value = std::getenv(name);
    return value == nullptr ? "" : value;
  }

  std::string Source(const std::string& name) const { return (root_ / "src" / name).string(); }

  // one compiler process: its own files and the shared ones (e.g. headers), each starting with another shared file
  void RegisterAsProcess(int process) const {
    FileMappingPath() = (root_ / ".discopop" / "FileMapping.txt").string();
    for (int file = 0; file < kOwnFiles; ++file) {
      dputil::GetFileId("", Source("p" + std::to_string(process) + "_" + std::to_string(file) + ".cpp"));
      const int shared = (process * 7 + file) % kSharedFiles;
      dputil::GetFileId("", Source("shared" + std::to_string(shared) + ".hpp"));
    }
  }

  fs::path root_;
  std::string saved_root_;
  std::string saved_mapping_path_;
};

TEST_F(FileMappingTest, ParallelProcessesGiveEveryFileExactlyOneId) {
  // the children start together when the pipe is closed
  int start[2];
  ASSERT_EQ(pipe(start), 0);
  std::vector<pid_t> children;
  for (int process = 0; process < kProcesses; ++process) {
    const pid_t pid = fork();
    ASSERT_NE(pid, -1);
    if (pid == 0) {
      close(start[1]);
      char byte;
      while (read(start[0], &byte, 1) > 0) {
      }
      RegisterAsProcess(process);
      _exit(0);
    }
    children.push_back(pid);
  }
  close(start[0]);
  close(start[1]);
  for (const pid_t pid : children) {
    int status = 0;
    ASSERT_EQ(waitpid(pid, &status, 0), pid);
    ASSERT_TRUE(WIFEXITED(status) && WEXITSTATUS(status) == 0) << "a registering process failed";
  }

  std::ifstream mapping(root_ / ".discopop" / "FileMapping.txt");
  ASSERT_TRUE(mapping.is_open());
  std::map<int, std::set<std::string>> files_of_id;
  std::map<std::string, std::set<int>> ids_of_file;
  std::string line;
  int lines = 0;
  while (std::getline(mapping, line)) {
    const std::size_t tab = line.find('\t');
    ASSERT_NE(tab, std::string::npos) << line;
    const int id = std::stoi(line.substr(0, tab));
    const std::string file = line.substr(tab + 1);
    files_of_id[id].insert(file);
    ids_of_file[file].insert(id);
    ++lines;
  }

  int ids_twice = 0;
  for (const auto& [id, files] : files_of_id) {
    ids_twice += files.size() > 1 ? 1 : 0;
  }
  int files_twice = 0;
  for (const auto& [file, ids] : ids_of_file) {
    files_twice += ids.size() > 1 ? 1 : 0;
  }
  EXPECT_EQ(ids_twice, 0) << "ids given to more than one file";
  EXPECT_EQ(files_twice, 0) << "files with more than one id";
  EXPECT_EQ(static_cast<int>(ids_of_file.size()), kProcesses * kOwnFiles + kSharedFiles);
  EXPECT_EQ(lines, kProcesses * kOwnFiles + kSharedFiles) << "a file is listed more than once";
  // the ids are 1..N
  EXPECT_EQ(files_of_id.begin()->first, 1);
  EXPECT_EQ(files_of_id.rbegin()->first, static_cast<int>(files_of_id.size()));
}

}  // namespace
