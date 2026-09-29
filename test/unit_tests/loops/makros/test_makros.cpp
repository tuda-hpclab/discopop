#include <gtest/gtest.h>

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
