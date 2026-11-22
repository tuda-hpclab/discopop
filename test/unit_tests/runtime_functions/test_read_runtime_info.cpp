#include <gtest/gtest.h>

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <string>
#include <sys/stat.h>

#include "lid_utils.hpp"
#include "runtimeFunctions.hpp"
#include "runtimeFunctionsGlobals.hpp"

using namespace dp;

// The first thing __dp_init does: read dp.conf, if there is one next to the executable, and let
// it override the built-in defaults. Every setting is "<name> = <value>"; whatever the file does
// not mention keeps the value the runtime was compiled with.
//
// USE_PERFECT is deliberately left out of these tests. Whether its guard lets the setting be
// turned off is a question about the intended behaviour and is being looked at elsewhere; a test
// here would only freeze whichever answer the code gives today.
class ReadRuntimeInfoTest : public ::testing::Test {
protected:
  void SetUp() override {
    previous_debug = dp_debug;
    previous_sig_elem_bit = sig_elem_bit;
    previous_sig_num_elem = sig_num_elem;
    previous_sig_num_hash = sig_num_hash;
    previous_num_workers = num_workers;
    previous_use_perfect = use_perfect;
    previous_bb_report_cache_mb = bb_report_cache_mb;
    unsetenv("DP_BB_REPORT_CACHE_MB");

    configuration_path = dputil::GetExeDir() + "/dp.conf";

    // a dp.conf that is already there belongs to whoever put it next to the binary
    struct stat unused = {};
    if (::stat(configuration_path.c_str(), &unused) == 0) {
      GTEST_SKIP() << "a dp.conf is already present at " << configuration_path;
    }
  }

  void TearDown() override {
    if (!configuration_path.empty()) {
      std::remove(configuration_path.c_str());
    }

    dp_debug = previous_debug;
    sig_elem_bit = previous_sig_elem_bit;
    sig_num_elem = previous_sig_num_elem;
    sig_num_hash = previous_sig_num_hash;
    num_workers = previous_num_workers;
    use_perfect = previous_use_perfect;
    bb_report_cache_mb = previous_bb_report_cache_mb;
    unsetenv("DP_BB_REPORT_CACHE_MB");
  }

  void write_configuration(const std::string &contents) const {
    std::ofstream configuration(configuration_path);
    configuration << contents;
  }

private:
  std::string configuration_path;
  bool previous_debug = false;
  std::int32_t previous_sig_elem_bit = 0;
  std::int32_t previous_sig_num_elem = 0;
  std::int32_t previous_sig_num_hash = 0;
  std::int32_t previous_num_workers = 0;
  bool previous_use_perfect = true;
  std::int32_t previous_bb_report_cache_mb = 0;
};

// the allowance of the basic block report caches: dp.conf, overridden by the environment; 0 turns the caches off
TEST_F(ReadRuntimeInfoTest, testTheReportCacheAllowanceComesFromTheConfigurationOrTheEnvironment) {
  bb_report_cache_mb = kDefaultBbReportCacheMb;
  write_configuration("BB_REPORT_CACHE_MB = 0\n");
  ReadRuntimeInfo();
  EXPECT_EQ(bb_report_cache_mb, 0);

  write_configuration("BB_REPORT_CACHE_MB = 20\n");
  setenv("DP_BB_REPORT_CACHE_MB", "300", 1);
  ReadRuntimeInfo();
  EXPECT_EQ(bb_report_cache_mb, 300);

  setenv("DP_BB_REPORT_CACHE_MB", "lots", 1);  // ignored, with a warning
  ReadRuntimeInfo();
  EXPECT_EQ(bb_report_cache_mb, 20);
}

TEST_F(ReadRuntimeInfoTest, testWithoutAConfigurationTheDefaultsAreKept) {
  sig_elem_bit = 56;
  num_workers = 4;

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 56);
  EXPECT_EQ(num_workers, 4);
}

TEST_F(ReadRuntimeInfoTest, testEveryShadowMemoryParameterCanBeConfigured) {
  write_configuration("SIG_ELEM_BIT = 32\nSIG_NUM_ELEM = 1024\nSIG_NUM_HASH = 3\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 32);
  EXPECT_EQ(sig_num_elem, 1024);
  EXPECT_EQ(sig_num_hash, 3);
}

TEST_F(ReadRuntimeInfoTest, testTheNumberOfWorkersCanBeConfigured) {
  num_workers = 4;
  write_configuration("NUM_WORKERS = 8\n");

  ReadRuntimeInfo();

  EXPECT_EQ(num_workers, 8);
}

TEST_F(ReadRuntimeInfoTest, testSpacesAroundTheNameAndTheValueAreIgnored) {
  write_configuration("   SIG   _ELEM_BIT=32\nSIG_NUM_ELEM   =    1024   \n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 32);
  EXPECT_EQ(sig_num_elem, 1024);
}

TEST_F(ReadRuntimeInfoTest, testASettingThatIsNotMentionedKeepsItsValue) {
  sig_num_elem = 270000;
  write_configuration("SIG_ELEM_BIT = 32\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_num_elem, 270000);
}

TEST_F(ReadRuntimeInfoTest, testAnUnknownSettingIsIgnored) {
  sig_elem_bit = 56;
  write_configuration("NOT_A_SETTING = 1\nSIG_ELEM_BIT = 32\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 32);
}

// a line has to be exactly "<name>=<value>" to be taken apart
TEST_F(ReadRuntimeInfoTest, testLinesThatAreNotASettingAreSkipped) {
  sig_elem_bit = 56;
  write_configuration("\n# a comment\nSIG_ELEM_BIT\nSIG_ELEM_BIT=32=64\nSIG_ELEM_BIT = 32\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 32);
}

// only positive values are taken, so a setting that cannot be zero is not silently zeroed by a
// value that does not parse as a number
TEST_F(ReadRuntimeInfoTest, testAValueThatIsNotPositiveLeavesTheSettingAlone) {
  sig_elem_bit = 56;
  write_configuration("SIG_ELEM_BIT = 0\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 56);
}

TEST_F(ReadRuntimeInfoTest, testAValueThatIsNoNumberLeavesTheSettingAlone) {
  sig_elem_bit = 56;
  write_configuration("SIG_ELEM_BIT = wide\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 56);
}

TEST_F(ReadRuntimeInfoTest, testTheLastValueOfARepeatedSettingWins) {
  write_configuration("SIG_ELEM_BIT = 32\nSIG_ELEM_BIT = 48\n");

  ReadRuntimeInfo();

  EXPECT_EQ(sig_elem_bit, 48);
}
