#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
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

// The runtime picks between PerfectShadow and ShadowMemory at startup and hands both the same
// three shadow memory parameters. A perfect shadow records every address, so it ignores them --
// but it has to accept them, or the two are no longer interchangeable.
TEST_F(PerfectShadowTest, testConstructorWithTheShadowMemoryParameters) {
  auto shadow = __dp::PerfectShadow{56, 270000, 2};

  ASSERT_NE(shadow.getSigRead(), nullptr);
  ASSERT_TRUE(shadow.getSigRead()->empty());
  ASSERT_NE(shadow.getSigWrite(), nullptr);
  ASSERT_TRUE(shadow.getSigWrite()->empty());

  shadow.updateInWrite(1000, 7);
  EXPECT_EQ(shadow.testInWrite(1000), 7);
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

namespace {

// print() writes to std::cout, so the tests below redirect it and put the old buffer back.
class CoutCapture {
public:
  CoutCapture() : previous(std::cout.rdbuf(buffer.rdbuf())) {}
  ~CoutCapture() { std::cout.rdbuf(previous); }

  CoutCapture(const CoutCapture &) = delete;
  CoutCapture &operator=(const CoutCapture &) = delete;

  std::string str() const { return buffer.str(); }

private:
  std::ostringstream buffer;
  std::streambuf *previous;
};

using kv_pairs = std::vector<std::pair<std::int64_t, sigElement>>;

kv_pairs sorted(kv_pairs pairs) {
  std::sort(pairs.begin(), pairs.end());
  return pairs;
}

} // namespace

TEST_F(PerfectShadowTest, testKeyValuePairs) {
  auto shadow = __dp::PerfectShadow{};

  ASSERT_TRUE(shadow.getReadKVPairs().empty());
  ASSERT_TRUE(shadow.getWriteKVPairs().empty());

  shadow.insertToRead(4, 100);
  shadow.insertToRead(8, 200);
  shadow.insertToWrite(4, 300);

  ASSERT_EQ(sorted(shadow.getReadKVPairs()), (kv_pairs{{4, 100}, {8, 200}}));
  ASSERT_EQ(sorted(shadow.getWriteKVPairs()), (kv_pairs{{4, 300}}));

  // remove zeroes the value instead of dropping the key, so the pair stays in the listing
  shadow.removeFromRead(8);
  ASSERT_EQ(sorted(shadow.getReadKVPairs()), (kv_pairs{{4, 100}, {8, 0}}));
}

TEST_F(PerfectShadowTest, testMoveConstructor) {
  auto shadow = __dp::PerfectShadow{};
  shadow.insertToRead(4, 100);
  shadow.insertToWrite(8, 200);

  const auto *reads_before = shadow.getSigRead();
  const auto *writes_before = shadow.getSigWrite();

  auto moved = __dp::PerfectShadow{std::move(shadow)};

  // the maps are handed over, not copied
  ASSERT_EQ(moved.getSigRead(), reads_before);
  ASSERT_EQ(moved.getSigWrite(), writes_before);
  ASSERT_EQ(moved.testInRead(4), 100);
  ASSERT_EQ(moved.testInWrite(8), 200);

  // and the moved-from shadow keeps none of them, which is what makes its destructor safe
  ASSERT_EQ(shadow.getSigRead(), nullptr);
  ASSERT_EQ(shadow.getSigWrite(), nullptr);
}

TEST_F(PerfectShadowTest, testMoveAssignment) {
  auto source = __dp::PerfectShadow{};
  source.insertToRead(4, 100);

  auto target = __dp::PerfectShadow{};
  target.insertToRead(9, 999);

  const auto *source_reads = source.getSigRead();
  const auto *target_reads = target.getSigRead();

  target = std::move(source);

  ASSERT_EQ(target.getSigRead(), source_reads);
  ASSERT_EQ(target.testInRead(4), 100);

  // assignment swaps rather than releases, so the maps the target held live on in the source and
  // are freed when it goes out of scope
  ASSERT_EQ(source.getSigRead(), target_reads);
}

TEST_F(PerfectShadowTest, testPrint) {
  auto shadow = __dp::PerfectShadow{};
  shadow.insertToRead(4, 100);

  const CoutCapture capture{};
  shadow.print();

  ASSERT_EQ(capture.str(), "Hello from PerfectShadow\n");
}

TEST_F(PerfectShadow2Test, testKeyValuePairs) {
  auto shadow = __dp::PerfectShadow2{};

  ASSERT_TRUE(shadow.getReadKVPairs().empty());
  ASSERT_TRUE(shadow.getWriteKVPairs().empty());

  shadow.insertToRead(4, 100);
  shadow.insertToRead(8, 200);
  shadow.insertToWrite(4, 300);

  ASSERT_EQ(sorted(shadow.getReadKVPairs()), (kv_pairs{{4, 100}, {8, 200}}));
  ASSERT_EQ(sorted(shadow.getWriteKVPairs()), (kv_pairs{{4, 300}}));

  shadow.removeFromRead(8);
  ASSERT_EQ(sorted(shadow.getReadKVPairs()), (kv_pairs{{4, 100}, {8, 0}}));
}

TEST_F(PerfectShadow2Test, testPrint) {
  auto shadow = __dp::PerfectShadow2{};
  shadow.insertToRead(4, 100);
  shadow.insertToWrite(4, 200);

  const CoutCapture capture{};
  shadow.print();

  const auto output = capture.str();
  ASSERT_NE(output.find("ADDR"), std::string::npos);

  // the table lists one line per read, and takes the write of the same address from the write cache
  ASSERT_NE(output.find("| 4\t| 100\t| 200\t|"), std::string::npos) << output;
}
