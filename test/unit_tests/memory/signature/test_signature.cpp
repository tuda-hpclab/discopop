#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/Signature.hpp"

// slotSize=16 (2 bytes/slot), 4 slots -> hash(elem) = ((elem >> 8) + elem) % 4.
// elem 0 and elem 4 both hash to slot 0, elem 1 hashes to slot 1: used below to
// exercise the shared-slot ("conflict") semantics documented on Signature::insert.
class SignatureTest : public ::testing::Test {};

TEST_F(SignatureTest, testInsertOnEmptySlotReturnsZeroAndIsRetrievable) {
  __dp::Signature sig(16, 4);

  const auto old_value = sig.insert(0, 1234);

  EXPECT_EQ(old_value, 0);
  EXPECT_EQ(sig.membershipCheck(0), 1234);
}

TEST_F(SignatureTest, testInsertIntoSharedSlotReturnsPreviousValue) {
  __dp::Signature sig(16, 4);

  sig.insert(0, 1000);
  const auto old_value = sig.insert(4, 2000); // elem 4 shares elem 0's slot

  EXPECT_EQ(old_value, 1000);
  EXPECT_EQ(sig.membershipCheck(0), 2000);
  EXPECT_EQ(sig.membershipCheck(4), 2000);
}

TEST_F(SignatureTest, testDistinctSlotsDoNotInterfere) {
  __dp::Signature sig(16, 4);

  sig.insert(0, 1234);
  sig.insert(1, 555);

  EXPECT_EQ(sig.membershipCheck(0), 1234);
  EXPECT_EQ(sig.membershipCheck(1), 555);
}

TEST_F(SignatureTest, testUpdateOverwritesValueWithoutConflictReporting) {
  __dp::Signature sig(16, 4);

  sig.insert(0, 1000);
  sig.update(0, 3000);

  EXPECT_EQ(sig.membershipCheck(0), 3000);
}

TEST_F(SignatureTest, testRemoveClearsSlot) {
  __dp::Signature sig(16, 4);

  sig.insert(0, 1234);
  sig.remove(0);

  EXPECT_EQ(sig.membershipCheck(0), 0);
}

TEST_F(SignatureTest, testRemoveClearsSharedSlotForAllElementsMappingToIt) {
  __dp::Signature sig(16, 4);

  sig.insert(0, 1000);
  sig.insert(4, 2000); // overwrites the slot shared with elem 0

  sig.remove(0); // removal is slot-based, so this also clears elem 4's value

  EXPECT_EQ(sig.membershipCheck(0), 0);
  EXPECT_EQ(sig.membershipCheck(4), 0);
}

TEST_F(SignatureTest, testMembershipCheckOnUnusedSlotReturnsZero) {
  __dp::Signature sig(16, 4);

  EXPECT_EQ(sig.membershipCheck(2), 0);
}
