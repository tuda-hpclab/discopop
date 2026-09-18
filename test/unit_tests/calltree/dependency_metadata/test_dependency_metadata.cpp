#include <gtest/gtest.h>

#include <memory>
#include <string>

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

TEST_F(DependencyMetadataTest, testDefaultConstructionLeavesNoDependencies) {
  // the default constructor has no caller in the runtime. The six sets come up empty because they
  // are class types; the scalars next to them are left uninitialised, so nothing here reads them.
  const auto metadata = __dp::DependencyMetadata();

  EXPECT_TRUE(metadata.intra_call_dependencies.empty());
  EXPECT_TRUE(metadata.intra_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());
  EXPECT_TRUE(metadata.inter_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.sink_ancestors.empty());
  EXPECT_TRUE(metadata.source_ancestors.empty());
}

TEST_F(DependencyMetadataTest, testTheHashFollowsTheComparison) {
  const auto hasher = std::hash<__dp::DependencyMetadata>{};
  const auto element = makeElement(__dp::RAW, 10, 20);

  const auto metadata = __dp::DependencyMetadata(element, {1}, {2}, {3}, {4}, {5}, {6});
  const auto same = __dp::DependencyMetadata(element, {1}, {2}, {3}, {4}, {5}, {6});

  // this is what makes DependencyMetadata usable as a key of the result set the runtime collects
  // the dependencies in
  EXPECT_TRUE(metadata == same);
  EXPECT_EQ(hasher(metadata), hasher(same));

  EXPECT_NE(hasher(metadata), hasher(__dp::DependencyMetadata(element, {}, {2}, {3}, {4}, {5}, {6})));
  EXPECT_NE(hasher(metadata),
            hasher(__dp::DependencyMetadata(makeElement(__dp::WAR, 10, 20), {1}, {2}, {3}, {4}, {5}, {6})));
}

TEST_F(DependencyMetadataTest, testToStringWritesEveryBracket) {
  const auto element = makeElement(__dp::RAW, 3 * MAXLNO + 100, 4 * MAXLNO + 200);

  auto metadata = __dp::DependencyMetadata(element, {1}, {2}, {3}, {4}, {5}, {6});

  // the six brackets hold loop and function ids, not source locations, but they are written with
  // decodeLID all the same -- an id of 1 comes out as the line 1 of the file 0
  EXPECT_EQ(metadata.toString(),
            "RAW 3:100 4:200 x 0 IAC[0:1,] IAI[0:2,] IEC[0:3,] IEI[0:4,] SINK_ANC[0:5,] SOURCE_ANC[0:6,] ");
}

TEST_F(DependencyMetadataTest, testToStringNamesTheFourDependencyTypesItKnows) {
  const auto empty = std::string("* * x 0 IAC[] IAI[] IEC[] IEI[] SINK_ANC[] SOURCE_ANC[] ");

  auto raw = __dp::DependencyMetadata(makeElement(__dp::RAW, 0, 0), {}, {}, {}, {}, {}, {});
  auto war = __dp::DependencyMetadata(makeElement(__dp::WAR, 0, 0), {}, {}, {}, {}, {}, {});
  auto waw = __dp::DependencyMetadata(makeElement(__dp::WAW, 0, 0), {}, {}, {}, {}, {}, {});
  auto init = __dp::DependencyMetadata(makeElement(__dp::INIT, 0, 0), {}, {}, {}, {}, {}, {});

  EXPECT_EQ(raw.toString(), "RAW " + empty);
  EXPECT_EQ(war.toString(), "WAR " + empty);
  EXPECT_EQ(waw.toString(), "WAW " + empty);
  EXPECT_EQ(init.toString(), "INIT " + empty);

  // the inter-iteration types fall through the switch without a name. MetaDataQueueElement leaves
  // INIT unnamed as well, so the two do not agree on the set of types they can write.
  auto inter_iteration = __dp::DependencyMetadata(makeElement(__dp::RAW_II_0, 0, 0), {}, {}, {}, {}, {}, {});
  EXPECT_EQ(inter_iteration.toString(), empty);
}
