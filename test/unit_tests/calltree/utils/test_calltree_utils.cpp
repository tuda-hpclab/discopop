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
  auto sink_iteration = std::make_shared<__dp::CallTreeNode>(loop, loop.get(), __dp::CallTreeNodeType::Iteration, 2, 1);
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

TEST_F(CallTreeUtilsProcessQueueElementTest, testACommonIterationYieldsAnIntraIterationDependency) {
  // Root -> Function(1) -> Loop(2) -> Iteration(2,1) -> {Function(3) [sink], Function(4) [source]}
  // Both sides were recorded in the same pass through the loop body, in two different calls.
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto function = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 1, 0);
  auto loop = std::make_shared<__dp::CallTreeNode>(function, function.get(), __dp::CallTreeNodeType::Loop, 2, 0);
  auto iteration = std::make_shared<__dp::CallTreeNode>(loop, loop.get(), __dp::CallTreeNodeType::Iteration, 2, 1);
  auto sink_call =
      std::make_shared<__dp::CallTreeNode>(iteration, iteration.get(), __dp::CallTreeNodeType::Function, 3, 0);
  auto source_call =
      std::make_shared<__dp::CallTreeNode>(iteration, iteration.get(), __dp::CallTreeNodeType::Function, 4, 0);

  auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, "x", 0, sink_call, source_call);
  const auto metadata = __dp::processQueueElement(std::move(element));

  // the shared iteration node carries the id of its loop, which is what lands in the set
  EXPECT_EQ(metadata.intra_iteration_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.intra_iteration_dependencies.contains(2));

  EXPECT_EQ(metadata.intra_call_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.intra_call_dependencies.contains(1));

  // the two calls are disjoint but belong to different functions, so neither yields an inter
  // dependency
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());
  EXPECT_TRUE(metadata.inter_iteration_dependencies.empty());

  EXPECT_TRUE(metadata.sink_ancestors.contains(3));
  EXPECT_TRUE(metadata.source_ancestors.contains(4));
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testIterationsOfDifferentLoopsAreNotInterIterationDependent) {
  // Root -> Loop(2) -> Iteration(2,1) [sink]
  // Root -> Loop(3) -> Iteration(3,1) [source]
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto sink_loop = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Loop, 2, 0);
  auto source_loop = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Loop, 3, 0);
  auto sink_iteration =
      std::make_shared<__dp::CallTreeNode>(sink_loop, sink_loop.get(), __dp::CallTreeNodeType::Iteration, 2, 1);
  auto source_iteration =
      std::make_shared<__dp::CallTreeNode>(source_loop, source_loop.get(), __dp::CallTreeNodeType::Iteration, 3, 1);

  auto element = __dp::MetaDataQueueElement(__dp::WAW, 100, 50, "x", 0, sink_iteration, source_iteration);
  const auto metadata = __dp::processQueueElement(std::move(element));

  // both sides are iterations, but of loops that have nothing to do with each other
  EXPECT_TRUE(metadata.inter_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.intra_iteration_dependencies.empty());

  // the loops themselves are reported as ancestors although they are kept out of the
  // classification
  EXPECT_TRUE(metadata.sink_ancestors.contains(2));
  EXPECT_TRUE(metadata.source_ancestors.contains(3));
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testAMissingCallTreeNodeYieldsNothing) {
  // the runtime leaves the node out when it did not take one, and the walk has to cope with that
  // instead of dereferencing it
  auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, "x", 0, nullptr, nullptr);
  const auto metadata = __dp::processQueueElement(std::move(element));

  EXPECT_TRUE(metadata.intra_call_dependencies.empty());
  EXPECT_TRUE(metadata.intra_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());
  EXPECT_TRUE(metadata.inter_iteration_dependencies.empty());
  EXPECT_TRUE(metadata.sink_ancestors.empty());
  EXPECT_TRUE(metadata.source_ancestors.empty());

  // the fields that do not come from the call tree survive
  EXPECT_EQ(metadata.type, __dp::RAW);
  EXPECT_EQ(metadata.sink, 100);
  EXPECT_EQ(metadata.source, 50);
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testAWalkEndsAtAMissingParentJustAsItDoesAtTheRoot) {
  // a node whose ancestry is cut off instead of ending in a root node
  auto sink_call = std::make_shared<__dp::CallTreeNode>(nullptr, nullptr, __dp::CallTreeNodeType::Function, 1, 0);
  auto root = std::make_shared<__dp::CallTreeNode>();
  auto source_call = std::make_shared<__dp::CallTreeNode>(root, root.get(), __dp::CallTreeNodeType::Function, 1, 0);

  auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, "x", 0, sink_call, source_call);
  const auto metadata = __dp::processQueueElement(std::move(element));

  EXPECT_TRUE(metadata.sink_ancestors.contains(1));
  EXPECT_TRUE(metadata.source_ancestors.contains(1));

  // the two are disjoint calls of the same function, which is exactly the inter call case
  EXPECT_EQ(metadata.inter_call_dependencies.size(), 1u);
  EXPECT_TRUE(metadata.inter_call_dependencies.contains(1));
}

TEST_F(CallTreeUtilsProcessQueueElementTest, testARootOnBothSidesYieldsNothing) {
  auto root = std::make_shared<__dp::CallTreeNode>();

  auto element = __dp::MetaDataQueueElement(__dp::RAW, 100, 50, "x", 0, root, root);
  const auto metadata = __dp::processQueueElement(std::move(element));

  // the walk stops before it looks at the root itself, so a dependency recorded outside of any
  // function or loop is classified as nothing at all
  EXPECT_TRUE(metadata.sink_ancestors.empty());
  EXPECT_TRUE(metadata.source_ancestors.empty());
  EXPECT_TRUE(metadata.intra_call_dependencies.empty());
  EXPECT_TRUE(metadata.inter_call_dependencies.empty());
}
