#include <gtest/gtest.h>

#include "../../../../profiler/DiscoPoP/DiscoPoP.hpp"

// Tests for profiler/DiscoPoP/utils/output.cpp
//
// xmlEscape is the entry point of everything the pass writes into Data.xml. It needs no LLVM
// module and no output files, which makes it the smallest piece of the pass that can be tested
// in isolation.

class OutputTest : public ::testing::Test {
protected:
  // The constructor only initialises a counter and the destructor only closes a stream that was
  // never opened, so an instance can be created per test without touching the file system.
  DiscoPoP dp;
};

TEST_F(OutputTest, testXmlEscapeLeavesHarmlessTextUnchanged) {
  EXPECT_EQ(dp.xmlEscape(""), "");
  EXPECT_EQ(dp.xmlEscape("int"), "int");
  EXPECT_EQ(dp.xmlEscape("a b c 123 _-.:"), "a b c 123 _-.:");
}

TEST_F(OutputTest, testXmlEscapeReplacesEveryReservedCharacter) {
  EXPECT_EQ(dp.xmlEscape("\""), "&quot;");
  EXPECT_EQ(dp.xmlEscape("&"), "&amp;");
  EXPECT_EQ(dp.xmlEscape("<"), "&lt;");
  EXPECT_EQ(dp.xmlEscape(">"), "&gt;");

  // ' is legal in XML attribute values delimited by ", so it is deliberately not escaped
  EXPECT_EQ(dp.xmlEscape("'"), "'");
}

TEST_F(OutputTest, testXmlEscapeDoesNotEscapeItsOwnReplacements) {
  // Every replacement introduces a fresh '&'. If the scan resumed before it, "<" would turn into
  // "&amp;lt;" and the generated Data.xml would be wrong.
  EXPECT_EQ(dp.xmlEscape("<>"), "&lt;&gt;");
  EXPECT_EQ(dp.xmlEscape("&amp;"), "&amp;amp;");
}

TEST_F(OutputTest, testXmlEscapeHandlesTypeNamesAsTheyAppearInDataXml) {
  // The types the pass records for variables are the realistic input for this function
  EXPECT_EQ(dp.xmlEscape("std::vector<int>"), "std::vector&lt;int&gt;");
  EXPECT_EQ(dp.xmlEscape("std::map<int, std::vector<char *>>"), "std::map&lt;int, std::vector&lt;char *&gt;&gt;");
  EXPECT_EQ(dp.xmlEscape("int &"), "int &amp;");
}
