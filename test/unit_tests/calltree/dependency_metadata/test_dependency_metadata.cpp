#include <gtest/gtest.h>

#include <memory>

#include "../../../../profiler/rtlib/calltree/CallTreeNode.hpp"
#include "../../../../profiler/rtlib/calltree/DependencyMetadata.hpp"
#include "../../../../profiler/rtlib/calltree/MetaDataQueueElement.hpp"

class DependencyMetadataTest : public ::testing::Test {};

namespace {
__dp::MetaDataQueueElement makeElement(__dp::depType type, LID sink, LID source) {
  auto sink_ctn = std::make_shared<__dp::CallTreeNode>();
  auto source_ctn = std::make_shared<__dp::CallTreeNode>();
  return __dp::MetaDataQueueElement(type, sink, source, "x", 0, sink_ctn, source_ctn);
}
} // namespace

TEST_F(DependencyMetadataTest, testConstructorCopiesFieldsFromElement) {
  const auto element = makeElement(__dp::RAW, 100, 50);

  const auto metadata = __dp::DependencyMetadata(element, {1}, {2}, {3}, {4}, {5}, {6});

  EXPECT_EQ(metadata.type, __dp::RAW);
  EXPECT_EQ(metadata.sink, 100);
  EXPECT_EQ(metadata.source, 50);

  EXPECT_TRUE(metadata.intra_call_dependencies.contains(1));
  EXPECT_TRUE(metadata.intra_iteration_dependencies.contains(2));
  EXPECT_TRUE(metadata.inter_call_dependencies.contains(3));
  EXPECT_TRUE(metadata.inter_iteration_dependencies.contains(4));
  EXPECT_TRUE(metadata.sink_ancestors.contains(5));
  EXPECT_TRUE(metadata.source_ancestors.contains(6));
}

TEST_F(DependencyMetadataTest, testEqualityComparesAllFields) {
  const auto element = makeElement(__dp::WAR, 10, 20);

  const auto a = __dp::DependencyMetadata(element, {1}, {}, {}, {}, {}, {});
  const auto b = __dp::DependencyMetadata(element, {1}, {}, {}, {}, {}, {});
  const auto c = __dp::DependencyMetadata(element, {2}, {}, {}, {}, {}, {});

  EXPECT_TRUE(a == b);
  EXPECT_FALSE(a == c);
}

TEST_F(DependencyMetadataTest, testToStringContainsTypeAndDependencies) {
  const auto element = makeElement(__dp::WAW, 10, 20);

  auto metadata = __dp::DependencyMetadata(element, {7}, {}, {}, {}, {}, {});
  const auto text = metadata.toString();

  EXPECT_NE(text.find("WAW"), std::string::npos);
  // intra_call_dependencies entries are formatted via dputil::decodeLID (file:line)
  EXPECT_NE(text.find("IAC[" + dputil::decodeLID(7) + ",]"), std::string::npos);
}
