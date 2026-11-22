#include <gtest/gtest.h>

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

#include "memory/PerfectShadow.hpp"

// Tests for old version (i.e., capturing functionality)

class PerfectShadowTest : public ::testing::Test {};

TEST_F(PerfectShadowTest, testConstructor) {
  const auto shadow = dp::PerfectShadow{};

  const auto *reads = shadow.GetSigRead();
  ASSERT_NE(reads, nullptr);
  ASSERT_TRUE(reads->empty());

  const auto *writes = shadow.GetSigWrite();
  ASSERT_NE(writes, nullptr);
  ASSERT_TRUE(writes->empty());
}

// The runtime picks between PerfectShadow and ShadowMemory at startup and hands both the same
// three shadow memory parameters. A perfect shadow records every address, so it ignores them --
// but it has to accept them, or the two are no longer interchangeable.
TEST_F(PerfectShadowTest, testConstructorWithTheShadowMemoryParameters) {
  auto shadow = dp::PerfectShadow{56, 270000, 2};

  ASSERT_NE(shadow.GetSigRead(), nullptr);
  ASSERT_TRUE(shadow.GetSigRead()->empty());
  ASSERT_NE(shadow.GetSigWrite(), nullptr);
  ASSERT_TRUE(shadow.GetSigWrite()->empty());

  shadow.UpdateInWrite(1000, 7);
  EXPECT_EQ(shadow.TestInWrite(1000), 7);
}

TEST_F(PerfectShadowTest, testGet) {
  auto shadow = dp::PerfectShadow{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadowTest, testInsert) {
  auto shadow = dp::PerfectShadow{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToRead(address, 1);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 1);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToRead(address, 14);
    ASSERT_EQ(old_val, 1);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 14);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToWrite(address, 4);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 4);
  }
}

TEST_F(PerfectShadowTest, testUpdate) {
  auto shadow = dp::PerfectShadow{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.InsertToRead(address, 1);
    std::ignore = shadow.InsertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.UpdateInRead(address, 14);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.UpdateInWrite(address, 27);
  }

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 27);
  }
}

TEST_F(PerfectShadowTest, testRemove) {
  auto shadow = dp::PerfectShadow{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.InsertToRead(address, 1);
    std::ignore = shadow.InsertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.RemoveFromRead(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.RemoveFromWrite(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadowTest, testAddressesInRange) {
  auto shadow = dp::PerfectShadow{};

  const auto addresses_read = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};
  const auto addresses_write = std::vector<std::int64_t>{4, 6, 8, 12, 16, 20, 48, 56, 1001, 1002, 1003, 1005};

  for (const auto address : addresses_read) {
    std::ignore = shadow.InsertToRead(address, 1);
  }

  for (const auto address : addresses_write) {
    std::ignore = shadow.InsertToWrite(address, 1);
  }

  const auto addresses_in_range_1 = shadow.GetAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_1.size(), 2);
  ASSERT_TRUE(addresses_in_range_1.find(8) != addresses_in_range_1.end());
  ASSERT_TRUE(addresses_in_range_1.find(12) != addresses_in_range_1.end());

  const auto addresses_in_range_2 = shadow.GetAddrsInRange(1000, 1004);
  ASSERT_EQ(addresses_in_range_2.size(), 5);
  ASSERT_TRUE(addresses_in_range_2.find(1000) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1001) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1002) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1003) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1004) != addresses_in_range_2.end());

  for (const auto address : addresses_read) {
    shadow.RemoveFromRead(address);
  }

  const auto addresses_in_range_3 = shadow.GetAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_3.size(), 2);
  ASSERT_TRUE(addresses_in_range_3.find(8) != addresses_in_range_3.end());
  ASSERT_TRUE(addresses_in_range_3.find(12) != addresses_in_range_3.end());
}

// Tests for new version (i.e., reproducing functionality)

class PerfectShadow2Test : public ::testing::Test {};

TEST_F(PerfectShadow2Test, testConstructor) {
  const auto shadow = dp::PerfectShadow2{};

  const auto *reads = shadow.GetSigRead();
  ASSERT_NE(reads, nullptr);
  ASSERT_TRUE(reads->empty());

  const auto *writes = shadow.GetSigWrite();
  ASSERT_NE(writes, nullptr);
  ASSERT_TRUE(writes->empty());
}

TEST_F(PerfectShadow2Test, testGet) {
  auto shadow = dp::PerfectShadow2{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInWrite(address), 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadow2Test, testInsert) {
  auto shadow = dp::PerfectShadow2{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToRead(address, 1);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 1);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToRead(address, 14);
    ASSERT_EQ(old_val, 1);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_TRUE(writes->empty());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    ASSERT_EQ(shadow.TestInRead(address), 14);
  }

  for (const auto address : addresses) {
    const auto old_val = shadow.InsertToWrite(address, 4);
    ASSERT_EQ(old_val, 0);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 4);
  }
}

TEST_F(PerfectShadow2Test, testUpdate) {
  auto shadow = dp::PerfectShadow2{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.InsertToRead(address, 1);
    std::ignore = shadow.InsertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.UpdateInRead(address, 14);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.UpdateInWrite(address, 27);
  }

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 14);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 27);
  }
}

TEST_F(PerfectShadow2Test, testRemove) {
  auto shadow = dp::PerfectShadow2{};

  const auto *reads = shadow.GetSigRead();
  const auto *writes = shadow.GetSigWrite();

  const auto addresses = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};

  for (const auto address : addresses) {
    std::ignore = shadow.InsertToRead(address, 1);
    std::ignore = shadow.InsertToWrite(address, 12);
  }

  for (const auto address : addresses) {
    shadow.RemoveFromRead(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 12);
  }

  for (const auto address : addresses) {
    shadow.RemoveFromWrite(address);
  }

  ASSERT_EQ(reads->size(), addresses.size());
  ASSERT_EQ(writes->size(), addresses.size());

  for (const auto address : addresses) {
    const auto iterator = reads->find(address);
    ASSERT_NE(iterator, reads->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }

  for (const auto address : addresses) {
    const auto iterator = writes->find(address);
    ASSERT_NE(iterator, writes->end());

    ASSERT_EQ(iterator->first, address);
    const auto val = iterator->second;

    ASSERT_EQ(val, 0);
  }
}

TEST_F(PerfectShadow2Test, testAddressesInRange) {
  auto shadow = dp::PerfectShadow2{};

  const auto addresses_read = std::vector<std::int64_t>{0, 4, 5, 12, 16, 20, 24, 28, 1000, 1004, 1008};
  const auto addresses_write = std::vector<std::int64_t>{4, 6, 8, 12, 16, 20, 48, 56, 1001, 1002, 1003, 1005};

  for (const auto address : addresses_read) {
    std::ignore = shadow.InsertToRead(address, 1);
  }

  for (const auto address : addresses_write) {
    std::ignore = shadow.InsertToWrite(address, 1);
  }

  const auto addresses_in_range_1 = shadow.GetAddrsInRange(7, 14);
  ASSERT_EQ(addresses_in_range_1.size(), 2);
  ASSERT_TRUE(addresses_in_range_1.find(8) != addresses_in_range_1.end());
  ASSERT_TRUE(addresses_in_range_1.find(12) != addresses_in_range_1.end());

  const auto addresses_in_range_2 = shadow.GetAddrsInRange(1000, 1004);
  ASSERT_EQ(addresses_in_range_2.size(), 5);
  ASSERT_TRUE(addresses_in_range_2.find(1000) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1001) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1002) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1003) != addresses_in_range_2.end());
  ASSERT_TRUE(addresses_in_range_2.find(1004) != addresses_in_range_2.end());

  for (const auto address : addresses_read) {
    shadow.RemoveFromRead(address);
  }

  const auto addresses_in_range_3 = shadow.GetAddrsInRange(7, 14);
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

using kv_pairs = std::vector<std::pair<std::int64_t, SigElement>>;

kv_pairs sorted(kv_pairs pairs) {
  std::sort(pairs.begin(), pairs.end());
  return pairs;
}

} // namespace

TEST_F(PerfectShadowTest, testKeyValuePairs) {
  auto shadow = dp::PerfectShadow{};

  ASSERT_TRUE(shadow.GetReadKvPairs().empty());
  ASSERT_TRUE(shadow.GetWriteKvPairs().empty());

  shadow.InsertToRead(4, 100);
  shadow.InsertToRead(8, 200);
  shadow.InsertToWrite(4, 300);

  ASSERT_EQ(sorted(shadow.GetReadKvPairs()), (kv_pairs{{4, 100}, {8, 200}}));
  ASSERT_EQ(sorted(shadow.GetWriteKvPairs()), (kv_pairs{{4, 300}}));

  // remove zeroes the value instead of dropping the key, so the pair stays in the listing
  shadow.RemoveFromRead(8);
  ASSERT_EQ(sorted(shadow.GetReadKvPairs()), (kv_pairs{{4, 100}, {8, 0}}));
}

TEST_F(PerfectShadowTest, testMoveConstructor) {
  auto shadow = dp::PerfectShadow{};
  shadow.InsertToRead(4, 100);
  shadow.InsertToWrite(8, 200);

  const auto *reads_before = shadow.GetSigRead();
  const auto *writes_before = shadow.GetSigWrite();

  auto moved = dp::PerfectShadow{std::move(shadow)};

  // the maps are handed over, not copied
  ASSERT_EQ(moved.GetSigRead(), reads_before);
  ASSERT_EQ(moved.GetSigWrite(), writes_before);
  ASSERT_EQ(moved.TestInRead(4), 100);
  ASSERT_EQ(moved.TestInWrite(8), 200);

  // and the moved-from shadow keeps none of them, which is what makes its destructor safe
  ASSERT_EQ(shadow.GetSigRead(), nullptr);
  ASSERT_EQ(shadow.GetSigWrite(), nullptr);
}

TEST_F(PerfectShadowTest, testMoveAssignment) {
  auto source = dp::PerfectShadow{};
  source.InsertToRead(4, 100);

  auto target = dp::PerfectShadow{};
  target.InsertToRead(9, 999);

  const auto *source_reads = source.GetSigRead();
  const auto *target_reads = target.GetSigRead();

  target = std::move(source);

  ASSERT_EQ(target.GetSigRead(), source_reads);
  ASSERT_EQ(target.TestInRead(4), 100);

  // assignment swaps rather than releases, so the maps the target held live on in the source and
  // are freed when it goes out of scope
  ASSERT_EQ(source.GetSigRead(), target_reads);
}

TEST_F(PerfectShadowTest, testPrint) {
  auto shadow = dp::PerfectShadow{};
  shadow.InsertToRead(4, 100);

  const CoutCapture capture{};
  shadow.Print();

  ASSERT_EQ(capture.str(), "Hello from PerfectShadow\n");
}

TEST_F(PerfectShadow2Test, testKeyValuePairs) {
  auto shadow = dp::PerfectShadow2{};

  ASSERT_TRUE(shadow.GetReadKvPairs().empty());
  ASSERT_TRUE(shadow.GetWriteKvPairs().empty());

  shadow.InsertToRead(4, 100);
  shadow.InsertToRead(8, 200);
  shadow.InsertToWrite(4, 300);

  ASSERT_EQ(sorted(shadow.GetReadKvPairs()), (kv_pairs{{4, 100}, {8, 200}}));
  ASSERT_EQ(sorted(shadow.GetWriteKvPairs()), (kv_pairs{{4, 300}}));

  shadow.RemoveFromRead(8);
  ASSERT_EQ(sorted(shadow.GetReadKvPairs()), (kv_pairs{{4, 100}, {8, 0}}));
}

TEST_F(PerfectShadow2Test, testPrint) {
  auto shadow = dp::PerfectShadow2{};
  shadow.InsertToRead(4, 100);
  shadow.InsertToWrite(4, 200);

  const CoutCapture capture{};
  shadow.Print();

  const auto output = capture.str();
  ASSERT_NE(output.find("ADDR"), std::string::npos);

  // the table lists one line per read, and takes the write of the same address from the write cache
  ASSERT_NE(output.find("| 4\t| 100\t| 200\t|"), std::string::npos) << output;
}

TEST_F(PerfectShadow2Test, testSummarize) {
  auto shadow = dp::PerfectShadow2{};
  ASSERT_TRUE(shadow.Summarize().empty());

  // 8: read, written, read again; 16: only read; 24: only written; 32: only asked for, as a first queue worker does
  shadow.InsertToRead(8, 1);
  shadow.InsertToWrite(8, 2);
  shadow.InsertToRead(8, 3);
  shadow.InsertToRead(16, 4);
  shadow.InsertToRead(16, 5);
  shadow.InsertToWrite(24, 6);
  shadow.TestInWrite(32);

  auto summary = shadow.Summarize();
  std::sort(summary.begin(), summary.end(), [](const auto &lhs, const auto &rhs) { return lhs.addr < rhs.addr; });

  ASSERT_EQ(summary.size(), 4);
  const std::int64_t expected[4][3] = {{8, 3, 2}, {16, 5, 0}, {24, 0, 6}, {32, 0, 0}};
  for (std::size_t i = 0; i < 4; ++i) {
    ASSERT_EQ(summary[i].addr, expected[i][0]);
    ASSERT_EQ(summary[i].last_read, expected[i][1]);
    ASSERT_EQ(summary[i].last_write, expected[i][2]);
  }
}
