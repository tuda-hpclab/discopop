#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/loop/LoopTable.hpp"
#include "../../../../profiler/rtlib/loop/Makros.hpp"

// Tests for old version (i.e., capturing functionality)

class MakrosTest : public ::testing::Test {};

TEST_F(MakrosTest, testGetLoopId) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0010LL;
  const auto expected_lid_2 = 0b1111'0010LL;
  const auto expected_lid_3 = 0b0000'0010LL;
  const auto expected_lid_4 = 0b0000'1111LL;
  const auto expected_lid_5 = 0b1111'0010LL;
  const auto expected_lid_6 = 0b0000'1111LL;
  const auto expected_lid_7 = 0b1111'1111LL;
  const auto expected_lid_8 = 0b1111'1111LL;

  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_1), expected_lid_1);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_2), expected_lid_2);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_3), expected_lid_3);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_4), expected_lid_4);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_5), expected_lid_5);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_6), expected_lid_6);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_7), expected_lid_7);
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testGetLoopIteration0) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'1111LL;
  const auto expected_lid_2 = 0b0000'1111LL;
  const auto expected_lid_3 = 0b0000'1111LL;
  const auto expected_lid_4 = 0b0000'1111LL;
  const auto expected_lid_5 = 0b0111'1111LL;
  const auto expected_lid_6 = 0b0111'1111LL;
  const auto expected_lid_7 = 0b0111'1111LL;
  const auto expected_lid_8 = 0b0111'1111LL;

  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_1), expected_lid_1);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_2), expected_lid_2);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_3), expected_lid_3);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_4), expected_lid_4);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_5), expected_lid_5);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_6), expected_lid_6);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_7), expected_lid_7);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testGetLoopIteration1) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'1100LL;
  const auto expected_lid_2 = 0b0000'1100LL;
  const auto expected_lid_3 = 0b0000'1100LL;
  const auto expected_lid_4 = 0b0000'1111LL;
  const auto expected_lid_5 = 0b0111'1100LL;
  const auto expected_lid_6 = 0b0111'1111LL;
  const auto expected_lid_7 = 0b0111'1111LL;
  const auto expected_lid_8 = 0b0111'1111LL;

  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_1), expected_lid_1);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_2), expected_lid_2);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_3), expected_lid_3);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_4), expected_lid_4);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_5), expected_lid_5);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_6), expected_lid_6);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_7), expected_lid_7);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testGetLoopIteration2) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'1001LL;
  const auto expected_lid_2 = 0b0000'1001LL;
  const auto expected_lid_3 = 0b0000'1001LL;
  const auto expected_lid_4 = 0b0000'1111LL;
  const auto expected_lid_5 = 0b0111'1001LL;
  const auto expected_lid_6 = 0b0111'1111LL;
  const auto expected_lid_7 = 0b0111'1111LL;
  const auto expected_lid_8 = 0b0111'1111LL;

  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_1), expected_lid_1);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_2), expected_lid_2);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_3), expected_lid_3);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_4), expected_lid_4);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_5), expected_lid_5);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_6), expected_lid_6);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_7), expected_lid_7);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testValidity0) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0001LL;
  const auto expected_lid_2 = 0b0000'0001LL;
  const auto expected_lid_3 = 0b0000'0001LL;
  const auto expected_lid_4 = 0b0000'0001LL;
  const auto expected_lid_5 = 0b0000'0001LL;
  const auto expected_lid_6 = 0b0000'0001LL;
  const auto expected_lid_7 = 0b0000'0001LL;
  const auto expected_lid_8 = 0b0000'0001LL;

  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_1), expected_lid_1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_2), expected_lid_2);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_3), expected_lid_3);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_4), expected_lid_4);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_5), expected_lid_5);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_6), expected_lid_6);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_7), expected_lid_7);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testValidity1) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0001LL;
  const auto expected_lid_2 = 0b0000'0001LL;
  const auto expected_lid_3 = 0b0000'0001LL;
  const auto expected_lid_4 = 0b0000'0001LL;
  const auto expected_lid_5 = 0b0000'0001LL;
  const auto expected_lid_6 = 0b0000'0001LL;
  const auto expected_lid_7 = 0b0000'0001LL;
  const auto expected_lid_8 = 0b0000'0001LL;

  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_1), expected_lid_1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_2), expected_lid_2);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_3), expected_lid_3);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_4), expected_lid_4);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_5), expected_lid_5);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_6), expected_lid_6);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_7), expected_lid_7);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid_8), expected_lid_8);
}

TEST_F(MakrosTest, testValidity2) {
  const auto lid_1 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_2 = 0b1111'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'0000LL;
  const auto lid_3 = 0b0000'0010'1000'1111'1000'1100'1000'1001'0000'0000'0000'0000'0000'0000'0000'1111LL;
  const auto lid_4 = 0b0000'1111'1000'1111'1000'1111'1000'1111'0000'1111'0000'1111'0000'1111'0000'1111LL;
  const auto lid_5 = 0b1111'0010'1111'1111'1111'1100'1111'1001'1111'0000'1111'0000'1111'0000'1111'0000LL;
  const auto lid_6 = 0b0000'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;
  const auto lid_7 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'0000LL;
  const auto lid_8 = 0b1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111'1111LL;

  const auto expected_lid_1 = 0b0000'0001LL;
  const auto expected_lid_2 = 0b0000'0001LL;
  const auto expected_lid_3 = 0b0000'0001LL;
  const auto expected_lid_4 = 0b0000'0001LL;
  const auto expected_lid_5 = 0b0000'0001LL;
  const auto expected_lid_6 = 0b0000'0001LL;
  const auto expected_lid_7 = 0b0000'0001LL;
  const auto expected_lid_8 = 0b0000'0001LL;

  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_1), expected_lid_1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_2), expected_lid_2);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_3), expected_lid_3);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_4), expected_lid_4);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_5), expected_lid_5);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_6), expected_lid_6);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_7), expected_lid_7);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid_8), expected_lid_8);
}

// The macros above read what LoopTable::update_lid writes. Neither side has a caller in the
// runtime at the moment, so this is the only place where the two halves of the encoding meet.
TEST_F(MakrosTest, testRoundTripWithUpdateLid) {
  __dp::LoopTable lt;

  lt.push(__dp::LoopTableEntry{1, 42, 0, 0});
  for (auto i = 0; i < 5; ++i) {
    lt.increment_top_count();
  }
  lt.push(__dp::LoopTableEntry{1, 43, 0, 0});
  for (auto i = 0; i < 3; ++i) {
    lt.increment_top_count();
  }
  lt.push(__dp::LoopTableEntry{1, 44, 0, 0});
  lt.increment_top_count();

  const LID lid = lt.update_lid(0x1234);

  // the loop id comes from the outermost entry, the iteration counts from the top downwards
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid), 42);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid), 1);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_1(lid), 3);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_2(lid), 5);

  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid), 1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_1(lid), 1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid), 1);

  // the lid itself lives in the lower 32 bits and is left alone
  ASSERT_EQ(lid & 0xFFFFFFFF, 0x1234);
}

TEST_F(MakrosTest, testRoundTripWithUpdateLidSingleLoop) {
  __dp::LoopTable lt;
  lt.push(__dp::LoopTableEntry{1, 7, 0, 0});
  lt.increment_top_count();
  lt.increment_top_count();

  const LID lid = lt.update_lid(0x1234);

  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid), 7);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid), 2);

  // only one entry on the stack, so the two outer iteration counts are marked invalid
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid), 1);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_1(lid), 0);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid), 0);
}

TEST_F(MakrosTest, testRoundTripWithUpdateLidWithoutLoop) {
  __dp::LoopTable lt;

  const LID lid = lt.update_lid(0x1234);

  // update_lid writes 0xFF as the "no loop active" marker
  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid), 0xFF);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_0(lid), 0);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_1(lid), 0);
  ASSERT_EQ(checkLIDMetadata_getLoopIterationValidity_2(lid), 0);
}

TEST_F(MakrosTest, testRoundTripWithUpdateLidTruncates) {
  __dp::LoopTable lt;

  // update_lid keeps 8 bits of the loop id and 7 of the iteration count on purpose: the metadata
  // only has to tell iterations apart, not name them
  lt.push(__dp::LoopTableEntry{1, 0x1F2, 0, 0});
  for (auto i = 0; i < 130; ++i) {
    lt.increment_top_count();
  }

  const LID lid = lt.update_lid(0x1234);

  ASSERT_EQ(unpackLIDMetadata_getLoopID(lid), 0xF2);
  ASSERT_EQ(unpackLIDMetadata_getLoopIteration_0(lid), 130 & 0x7F);
}
