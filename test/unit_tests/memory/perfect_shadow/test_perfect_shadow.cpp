#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "../../../../profiler/rtlib/memory/PerfectShadow.hpp"

// Tests for old version (i.e., capturing functionality)

class PerfectShadowTest : public ::testing::Test {};

TEST_F(PerfectShadowTest, testConstructor) {
  const auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  ASSERT_NE(reads, nullptr);
  ASSERT_TRUE(reads->empty());

  const auto *writes = shadow.getSigWrite();
  ASSERT_NE(writes, nullptr);
  ASSERT_TRUE(writes->empty());
}

TEST_F(PerfectShadowTest, testGet) {
  auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadowTest, testInsert) {
  auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToRead(address, 1);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 1);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToRead(address, 14);
    ASSERT_EQ(old_val, 1);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 14);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToWrite(address, 4);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 4);
  }
}

TEST_F(PerfectShadowTest, testUpdate) {
  auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.insertToRead(address, 1);
    std::ignore = shadow.insertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.updateInRead(address, 14);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.updateInWrite(address, 27);
  }

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 27);
  }
}

TEST_F(PerfectShadowTest, testRemove) {
  auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.insertToRead(address, 1);
    std::ignore = shadow.insertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.removeFromRead(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.removeFromWrite(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadowTest, testAddressesInRange) {
  auto shadow = __dp::PerfectShadow{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses_read = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};
  const auto addresses_write = std::vector<std::int64_t>{4, 6, 8, 12, 16, 20, 48, 56, 1001, 1002, 1003, 1005};

  for (const auto address : addresses_read) {
    std::ignore = shadow.insertToRead(address, 1);
  }

  for (const auto address : addresses_write) {
    std::ignore = shadow.insertToWrite(address, 1);
  }

  const auto addresses_in_range_1 = shadow.getAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_1.size(), 2);
  ASSERT_TRUE(addresses_in_range_1.find(8) != addresses_in_range_1.end());
  ASSERT_TRUE(addresses_in_range_1.find(12) != addresses_in_range_1.end());

  const auto addresses_in_range_2 = shadow.getAddrsInRange(1000, 1004);
  ASSERT_EQ(addresses_in_range_2.size(), 5);
  ASSERT_TRUE(addresses_in_range_2.find(1000) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1001) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1002) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1003) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1004) != addresses_in_range_2.end());

  for (const auto address : addresses_read) {
    shadow.removeFromRead(address);
  }

  const auto addresses_in_range_3 = shadow.getAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_3.size(), 2);
  ASSERT_TRUE(addresses_in_range_3.find(8) != addresses_in_range_3.end());
  ASSERT_TRUE(addresses_in_range_3.find(12) != addresses_in_range_3.end());
}

// Tests for new version (i.e., reproducing functionality)

class PerfectShadow2Test : public ::testing::Test {};

TEST_F(PerfectShadow2Test, testConstructor) {
  const auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  ASSERT_NE(reads, nullptr);
  ASSERT_TRUE(reads->empty());

  const auto *writes = shadow.getSigWrite();
  ASSERT_NE(writes, nullptr);
  ASSERT_TRUE(writes->empty());
}

TEST_F(PerfectShadow2Test, testGet) {
  auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadow2Test, testInsert) {
  auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToRead(address, 1);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 1);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToRead(address, 14);
    ASSERT_EQ(old_val, 1);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.testInRead(address), 14);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.insertToWrite(address, 4);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 4);
  }
}

TEST_F(PerfectShadow2Test, testUpdate) {
  auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.insertToRead(address, 1);
    std::ignore = shadow.insertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.updateInRead(address, 14);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.updateInWrite(address, 27);
  }

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 27);
  }
}

TEST_F(PerfectShadow2Test, testRemove) {
  auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.insertToRead(address, 1);
    std::ignore = shadow.insertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.removeFromRead(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.removeFromWrite(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    const auto addr = iterator->first;
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadow2Test, testAddressesInRange) {
  auto shadow = __dp::PerfectShadow2{};

  const auto *reads = shadow.getSigRead();
  const auto *writes = shadow.getSigWrite();

  const auto addresses_read = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};
  const auto addresses_write = std::vector<std::int64_t>{4, 6, 8, 12, 16, 20, 48, 56, 1001, 1002, 1003, 1005};

  for (const auto address : addresses_read) {
    std::ignore = shadow.insertToRead(address, 1);
  }

  for (const auto address : addresses_write) {
    std::ignore = shadow.insertToWrite(address, 1);
  }

  const auto addresses_in_range_1 = shadow.getAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_1.size(), 2);
  ASSERT_TRUE(addresses_in_range_1.find(8) != addresses_in_range_1.end());
  ASSERT_TRUE(addresses_in_range_1.find(12) != addresses_in_range_1.end());

  const auto addresses_in_range_2 = shadow.getAddrsInRange(1000, 1004);
  ASSERT_EQ(addresses_in_range_2.size(), 5);
  ASSERT_TRUE(addresses_in_range_2.find(1000) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1001) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1002) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1003) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1004) != addresses_in_range_2.end());

  for (const auto address : addresses_read) {
    shadow.removeFromRead(address);
  }

  const auto addresses_in_range_3 = shadow.getAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_3.size(), 2);
  ASSERT_TRUE(addresses_in_range_3.find(8) != addresses_in_range_3.end());
  ASSERT_TRUE(addresses_in_range_3.find(12) != addresses_in_range_3.end());
}
