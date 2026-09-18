#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/calltree/CallTreeNode.hpp"
#include "../../../../profiler/rtlib/calltree/CallTreeNodeType.hpp"
#include "../../../../profiler/rtlib/calltree/MetaDataQueueElement.hpp"

#include <cstdint>
#include <memory>
#include <string>

// A MetaDataQueueElement is the raw dependency that the runtime hands to processQueueElement: the
// two locations, the variable, and the call tree nodes both sides were recorded in.
class MetaDataQueueElementTest : public ::testing::Test {};

namespace {

std::shared_ptr<__dp::CallTreeNode> makeNode(__dp::CallTreeNodeType type, unsigned int id, unsigned int iteration) {
  return std::make_shared<__dp::CallTreeNode>(nullptr, nullptr, type, id, iteration);
}

// The runtime interns variable names, so every access to the same variable passes the same pointer.
// The second name holds the same text at a different address, which is what the comparison tests
// below need.
const char *const variable_name = "x";
char other_variable_name[] = {'x', '\0'};

} // namespace

TEST_F(MetaDataQueueElementTest, testTheConstructorKeepsTheFieldsAndSharesTheNodes) {
  auto sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);

  const auto element = __dp::MetaDataQueueElement(__dp::WAW, 100, 50, variable_name, 42, sink_node, source_node);

  ASSERT_EQ(element.type, __dp::WAW);
  ASSERT_EQ(element.sink, 100);
  ASSERT_EQ(element.source, 50);
  ASSERT_EQ(element.var, variable_name);
  ASSERT_EQ(element.AAvar, 42);

  // the element takes part in the ownership of both nodes instead of copying them, which is what
  // keeps the ancestry alive until processQueueElement has walked it
  ASSERT_EQ(element.sink_ctn, sink_node);
  ASSERT_EQ(element.source_ctn, source_node);
  ASSERT_EQ(sink_node.use_count(), 2);
  ASSERT_EQ(source_node.use_count(), 2);
}

TEST_F(MetaDataQueueElementTest, testEqualityLooksAtWhatTheNodesHoldNotAtWhichNodesTheyAre) {
  auto sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);

  // a second pair of nodes holding the same type, id and iteration, at different addresses
  auto other_sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto other_source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);

  const auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 0, sink_node, source_node);
  const auto same =
      __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 0, other_sink_node, other_source_node);

  ASSERT_TRUE(element == same);

  // the parent is not part of the comparison either, so two nodes stay equal even when they sit in
  // completely different places of the call tree
  auto parent = makeNode(__dp::CallTreeNodeType::Function, 9, 0);
  auto rooted_sink_node =
      std::make_shared<__dp::CallTreeNode>(parent, parent.get(), __dp::CallTreeNodeType::Iteration, 2, 7);
  const auto rooted =
      __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 0, rooted_sink_node, other_source_node);

  ASSERT_TRUE(element == rooted);
}

TEST_F(MetaDataQueueElementTest, testTheVariableIsComparedByAddressNotByText) {
  auto sink_node = makeNode(__dp::CallTreeNodeType::Function, 1, 0);
  auto source_node = makeNode(__dp::CallTreeNodeType::Function, 2, 0);

  const auto element = __dp::MetaDataQueueElement(__dp::RAW, 1, 2, variable_name, 0, sink_node, source_node);
  const auto same_text = __dp::MetaDataQueueElement(__dp::RAW, 1, 2, other_variable_name, 0, sink_node, source_node);

  ASSERT_STREQ(element.var, same_text.var);
  ASSERT_FALSE(element == same_text);
}

TEST_F(MetaDataQueueElementTest, testEveryOtherFieldTakesPartInTheComparison) {
  auto sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);

  const auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, sink_node, source_node);

  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::WAR, 100, 50, variable_name, 42, sink_node, source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 101, 50, variable_name, 42, sink_node, source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 51, variable_name, 42, sink_node, source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 43, sink_node, source_node));

  // and the three node properties, once for the sink and once for the source
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42,
                                                     makeNode(__dp::CallTreeNodeType::Loop, 2, 7), source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42,
                                                     makeNode(__dp::CallTreeNodeType::Iteration, 3, 7), source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42,
                                                     makeNode(__dp::CallTreeNodeType::Iteration, 2, 8), source_node));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, sink_node,
                                                     makeNode(__dp::CallTreeNodeType::Loop, 5, 0)));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, sink_node,
                                                     makeNode(__dp::CallTreeNodeType::Function, 6, 0)));
  ASSERT_FALSE(element == __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, sink_node,
                                                     makeNode(__dp::CallTreeNodeType::Iteration, 5, 1)));
}

TEST_F(MetaDataQueueElementTest, testTheHashFollowsTheComparison) {
  const auto hasher = std::hash<__dp::MetaDataQueueElement>{};

  auto sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);
  auto other_sink_node = makeNode(__dp::CallTreeNodeType::Iteration, 2, 7);
  auto other_source_node = makeNode(__dp::CallTreeNodeType::Function, 5, 0);

  const auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, sink_node, source_node);
  const auto same =
      __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 42, other_sink_node, other_source_node);

  // this is what makes MetaDataQueueElement usable as a key: equal elements have to hash equally
  // although they hold different nodes
  ASSERT_TRUE(element == same);
  ASSERT_EQ(hasher(element), hasher(same));

  const auto different =
      __dp::MetaDataQueueElement(__dp::RAW, 100, 50, variable_name, 43, other_sink_node, other_source_node);
  ASSERT_NE(hasher(element), hasher(different));
}
