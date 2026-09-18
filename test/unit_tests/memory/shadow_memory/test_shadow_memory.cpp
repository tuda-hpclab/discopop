#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/memory/AbstractShadow.hpp"
#include "../../../../profiler/rtlib/memory/ShadowMemory.hpp"

#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>

// ShadowMemory is the AbstractShadow implementation backed by two Signatures, one for reads and one
// for writes. It is what initSingleThreadedExecution() builds when USE_PERFECT is off.
//
// Every test below uses slotSize=16 (two bytes per slot) and 8 slots. Signature hashes an address
// as ((addr >> 8) + addr) % numSlot, which collapses to addr % 8 for the small addresses used here.
class ShadowMemoryTest : public ::testing::Test {};

TEST_F(ShadowMemoryTest, testAnUntouchedShadowReportsZero) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  for (auto address = 0; address < 8; ++address) {
    ASSERT_EQ(shadow.testInRead(address), 0);
    ASSERT_EQ(shadow.testInWrite(address), 0);
  }
}

TEST_F(ShadowMemoryTest, testInsertReturnsThePreviousValueOfTheSlot) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  ASSERT_EQ(shadow.insertToRead(1, 1234), 0);
  ASSERT_EQ(shadow.testInRead(1), 1234);

  ASSERT_EQ(shadow.insertToRead(1, 4321), 1234);
  ASSERT_EQ(shadow.testInRead(1), 4321);

  ASSERT_EQ(shadow.insertToWrite(1, 555), 0);
  ASSERT_EQ(shadow.testInWrite(1), 555);

  ASSERT_EQ(shadow.insertToWrite(1, 666), 555);
  ASSERT_EQ(shadow.testInWrite(1), 666);
}

TEST_F(ShadowMemoryTest, testReadsAndWritesAreKeptApart) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  shadow.insertToRead(3, 111);

  ASSERT_EQ(shadow.testInRead(3), 111);
  ASSERT_EQ(shadow.testInWrite(3), 0);

  shadow.insertToWrite(3, 222);

  ASSERT_EQ(shadow.testInRead(3), 111);
  ASSERT_EQ(shadow.testInWrite(3), 222);

  shadow.removeFromWrite(3);

  ASSERT_EQ(shadow.testInRead(3), 111);
  ASSERT_EQ(shadow.testInWrite(3), 0);
}

TEST_F(ShadowMemoryTest, testUpdateOverwritesTheSlot) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  shadow.insertToRead(2, 100);
  shadow.updateInRead(2, 200);
  ASSERT_EQ(shadow.testInRead(2), 200);

  shadow.insertToWrite(2, 300);
  shadow.updateInWrite(2, 400);
  ASSERT_EQ(shadow.testInWrite(2), 400);

  // update also works on a slot that was never inserted into
  shadow.updateInRead(5, 500);
  ASSERT_EQ(shadow.testInRead(5), 500);
}

TEST_F(ShadowMemoryTest, testRemoveClearsTheSlot) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  shadow.insertToRead(4, 111);
  shadow.insertToWrite(4, 222);

  shadow.removeFromRead(4);
  ASSERT_EQ(shadow.testInRead(4), 0);
  ASSERT_EQ(shadow.testInWrite(4), 222);

  shadow.removeFromWrite(4);
  ASSERT_EQ(shadow.testInWrite(4), 0);

  // removing an untouched slot is a no-op
  shadow.removeFromRead(7);
  ASSERT_EQ(shadow.testInRead(7), 0);
}

TEST_F(ShadowMemoryTest, testAddressesSharingASlotAliasOntoEachOther) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  // 8 addresses per signature, so 1 and 9 land in the same slot. This is the whole point of a
  // signature: it trades exactness for a fixed amount of memory, and a shadow lookup can report a
  // value that was written for a different address.
  shadow.insertToWrite(1, 111);
  ASSERT_EQ(shadow.testInWrite(9), 111);

  shadow.insertToWrite(9, 999);
  ASSERT_EQ(shadow.testInWrite(1), 999);

  shadow.removeFromWrite(9);
  ASSERT_EQ(shadow.testInWrite(1), 0);
}

TEST_F(ShadowMemoryTest, testValuesAreTruncatedToTheSlotSize) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  // two bytes per slot, so everything above the lower 16 bits is dropped
  shadow.insertToWrite(0, 0x12345);
  ASSERT_EQ(shadow.testInWrite(0), 0x2345);

  auto wide_shadow = __dp::ShadowMemory{32, 8, 1};

  wide_shadow.insertToWrite(0, 0x12345);
  ASSERT_EQ(wide_shadow.testInWrite(0), 0x12345);
}

TEST_F(ShadowMemoryTest, testGetAddrsInRangeIsEmptyByDesign) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  shadow.insertToRead(1, 111);
  shadow.insertToWrite(2, 222);

  // a signature does not keep its addresses, so it cannot answer this question at all
  ASSERT_TRUE(shadow.getAddrsInRange(0, 1000).empty());
}

TEST_F(ShadowMemoryTest, testTheKeyValueAccessorsAreNotImplemented) {
  auto shadow = __dp::ShadowMemory{16, 8, 1};

  shadow.insertToRead(1, 111);
  shadow.insertToWrite(2, 222);

  try {
    shadow.getReadKVPairs();
    FAIL() << "getReadKVPairs() is expected to throw";
  } catch (const std::logic_error &error) {
    EXPECT_STREQ(error.what(), "NOT IMPLEMENTED!");
  }

  try {
    shadow.getWriteKVPairs();
    FAIL() << "getWriteKVPairs() is expected to throw";
  } catch (const std::logic_error &error) {
    EXPECT_STREQ(error.what(), "NOT IMPLEMENTED!");
  }
}

TEST_F(ShadowMemoryTest, testUseThroughTheAbstractInterface) {
  // this is how the runtime holds it: a base class pointer that has to delete the derived signatures
  std::unique_ptr<__dp::AbstractShadow> shadow = std::make_unique<__dp::ShadowMemory>(16, 8, 1);

  ASSERT_EQ(shadow->insertToWrite(6, 42), 0);
  ASSERT_EQ(shadow->testInWrite(6), 42);

  ASSERT_EQ(shadow->insertToRead(6, 43), 0);
  ASSERT_EQ(shadow->testInRead(6), 43);

  shadow->print();
}
