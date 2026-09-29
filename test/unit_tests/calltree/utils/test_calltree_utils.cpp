#include <gtest/gtest.h>

#include <memory>

#include "../../../../profiler/rtlib/calltree/CallTreeNode.hpp"
#include "../../../../profiler/rtlib/calltree/DependencyMetadata.hpp"
#include "../../../../profiler/rtlib/calltree/MetaDataQueueElement.hpp"
#include "../../../../profiler/rtlib/calltree/utils.hpp"

// processQueueElement() walks the call-tree ancestry of the sink/source nodes
// to classify a raw dependency as intra/inter call or iteration dependent.
class CallTreeUtilsProcessQueueElementTest : public ::testing::Test {};

TEST_F(CallTreeUtilsProcessQueueElementTest, testCommonIterationParentYieldsIntraCallAndInterIteration) {
  // Root -> Function(1) -> Loop(2) -> {Iteration(2,1) [sink], Iteration(2,2) [source]}
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto function = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 1, 0);
  auto loop = std::make_shared<__dp::CallTreeNode>(function, function.get(), __dp::CallTreeNodeType::Loop, 2, 0);
  auto sink_iteration =
      std::make_shared<__dp::CallTreeNode>(loop, loop.get(), __dp::CallTreeNodeType::Iteration, 2, 1);
  auto source_iteration =
      std::make_shared<__dp::CallTreeNode>(loop, loop.get(), __dp::CallTreeNodeType::Iteration, 2, 2);

  auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, "x", 0, sink_iteration, source_iteration);
  const auto metadata = __dp::processQueueElement(std::move(element));

  EXPECT_EQ(metadata.intra_call_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.intra_call_dependencies.contains(1));
  EXPECT_TRUE(metadata.intra_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());

  EXPECT_EQ(metadata.inter_iteration_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.inter_iteration_dependencies.contains(2));

  EXPECT_TRUE(metadata.sink_ancestors.contains(1));
  EXPECT_TRUE(metadata.sink_ancestors.contains(2));
  EXPECT_TRUE(metadata.source_ancestors.contains(1));
  EXPECT_TRUE(metadata.source_ancestors.contains(2));
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testTwoCallsToSameFunctionYieldInterCallDependency) {
  // Root -> Function(5) [sink call]
  // Root -> Function(5) [source call] (a second, independent call to the same function)
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto sink_call = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 5, 0);
  auto source_call = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 5, 0);

  auto element = __dp::MetaDataQueueElement(__dp::WAR, 200, 150, "y", 0, sink_call, source_call);
  const auto metadata = __dp::processQueueElement(std::move(element));

  EXPECT_TRUE(metadata.intra_call_dependencies.empty());
  EXPECT_EQ(metadata.inter_call_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.inter_call_dependencies.contains(5));
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testDisjointFunctionsYieldNoDependencies) {
  // Root -> Function(1) [sink]
  // Root -> Function(2) [source] (a wholly unrelated function)
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto sink_call = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 1, 0);
  auto source_call = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 2, 0);

  auto element = __dp::MetaDataQueueElement(__dp::RAW, 10, 20, "z", 0, sink_call, source_call);
  const auto metadata = __dp::processQueueElement(std::move(element));

  EXPECT_TRUE(metadata.intra_call_dependencies.empty());
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());
  EXPECT_TRUE(metadata.intra_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.inter_iteration_dependencies.empty());
}
