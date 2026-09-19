#include <gtest/gtest.h>

#include <cstdint>
#include <cstdio>
#include <fstream>
#include <string>
#include <sys/stat.h>

#include "../../../profiler/rtlib/DPUtils.hpp"
#include "../../../profiler/rtlib/runtimeFunctions.hpp"
#include "../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"

using namespace __dp;

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
    previous_debug = DP_DEBUG;
    previous_sig_elem_bit = SIG_ELEM_BIT;
    previous_sig_num_elem = SIG_NUM_ELEM;
    previous_sig_num_hash = SIG_NUM_HASH;
    previous_num_workers = NUM_WORKERS;
    previous_use_perfect = USE_PERFECT;

    configuration_path = dputil::get_exe_dir() + "/dp.conf";

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

    DP_DEBUG = previous_debug;
    SIG_ELEM_BIT = previous_sig_elem_bit;
    SIG_NUM_ELEM = previous_sig_num_elem;
    SIG_NUM_HASH = previous_sig_num_hash;
    NUM_WORKERS = previous_num_workers;
    USE_PERFECT = previous_use_perfect;
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
};

TEST_F(ReadRuntimeInfoTest, testWithoutAConfigurationTheDefaultsAreKept) {
  SIG_ELEM_BIT = 56;
  NUM_WORKERS = 4;

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 56);
  EXPECT_EQ(NUM_WORKERS, 4);
}

TEST_F(ReadRuntimeInfoTest, testEveryShadowMemoryParameterCanBeConfigured) {
  write_configuration("SIG_ELEM_BIT = 32\nSIG_NUM_ELEM = 1024\nSIG_NUM_HASH = 3\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 32);
  EXPECT_EQ(SIG_NUM_ELEM, 1024);
  EXPECT_EQ(SIG_NUM_HASH, 3);
}

TEST_F(ReadRuntimeInfoTest, testTheNumberOfWorkersCanBeConfigured) {
  NUM_WORKERS = 4;
  write_configuration("NUM_WORKERS = 8\n");

  readRuntimeInfo();

  EXPECT_EQ(NUM_WORKERS, 8);
}

TEST_F(ReadRuntimeInfoTest, testSpacesAroundTheNameAndTheValueAreIgnored) {
  write_configuration("   SIG   _ELEM_BIT=32\nSIG_NUM_ELEM   =    1024   \n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 32);
  EXPECT_EQ(SIG_NUM_ELEM, 1024);
}

TEST_F(ReadRuntimeInfoTest, testASettingThatIsNotMentionedKeepsItsValue) {
  SIG_NUM_ELEM = 270000;
  write_configuration("SIG_ELEM_BIT = 32\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_NUM_ELEM, 270000);
}

TEST_F(ReadRuntimeInfoTest, testAnUnknownSettingIsIgnored) {
  SIG_ELEM_BIT = 56;
  write_configuration("NOT_A_SETTING = 1\nSIG_ELEM_BIT = 32\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 32);
}

// a line has to be exactly "<name>=<value>" to be taken apart
TEST_F(ReadRuntimeInfoTest, testLinesThatAreNotASettingAreSkipped) {
  SIG_ELEM_BIT = 56;
  write_configuration("\n# a comment\nSIG_ELEM_BIT\nSIG_ELEM_BIT=32=64\nSIG_ELEM_BIT = 32\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 32);
}

// only positive values are taken, so a setting that cannot be zero is not silently zeroed by a
// value that does not parse as a number
TEST_F(ReadRuntimeInfoTest, testAValueThatIsNotPositiveLeavesTheSettingAlone) {
  SIG_ELEM_BIT = 56;
  write_configuration("SIG_ELEM_BIT = 0\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 56);
}

TEST_F(ReadRuntimeInfoTest, testAValueThatIsNoNumberLeavesTheSettingAlone) {
  SIG_ELEM_BIT = 56;
  write_configuration("SIG_ELEM_BIT = wide\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 56);
}

TEST_F(ReadRuntimeInfoTest, testTheLastValueOfARepeatedSettingWins) {
  write_configuration("SIG_ELEM_BIT = 32\nSIG_ELEM_BIT = 48\n");

  readRuntimeInfo();

  EXPECT_EQ(SIG_ELEM_BIT, 48);
}
