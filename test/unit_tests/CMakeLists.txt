include(FetchContent)

enable_testing()

FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest
        GIT_TAG release-1.12.1)

# google test
set(gtest_force_shared_crt
        ON
        CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

get_target_property(gtest_main_includes gtest_main
        INTERFACE_INCLUDE_DIRECTORIES)
set_target_properties(gtest_main PROPERTIES INTERFACE_SYSTEM_INCLUDE_DIRECTORIES
        "${gtest_main_includes}")

add_executable(DiscoPoP_UT)
target_sources(
  DiscoPoP_UT
  PRIVATE
  tests.cpp
  loops/loop_counter/test_loop_counter.cpp
  loops/loop_info/test_loop_info.cpp
  loops/loop_manager/test_loop_manager.cpp
  loops/loop_record/test_loop_record.cpp
  loops/loop_table/test_loop_table.cpp
  loops/loop_table_entry/test_loop_table_entry.cpp
  loops/makros/test_makros.cpp
  loops/var_counter/test_var_counter.cpp
  loops/var_info/test_var_info.cpp
  memory/memory_manager/test_memory_manager.cpp
  memory/memory_region_tree/test_memory_region_tree.cpp
  memory/mrtnode/test_mrtnode.cpp
  memory/perfect_shadow/test_perfect_shadow.cpp
  memory/scope/test_scope.cpp
  memory/signature/test_signature.cpp
  calltree/call_tree/test_call_tree.cpp
  calltree/call_tree_node/test_call_tree_node.cpp
  calltree/metadata_queue/test_metadata_queue.cpp
  calltree/dependency_metadata/test_dependency_metadata.cpp
  calltree/utils/test_calltree_utils.cpp
  access_queues/test_first_access_queue_chunk.cpp
  access_queues/test_first_access_queue_chunk_buffer.cpp
  access_queues/test_second_access_queue_element.cpp
  access_queues/test_second_access_queue.cpp
  access_queues/test_first_access_queue.cpp
  access_queues/test_integration.cpp
  functions/function_manager/test_function_manager.cpp
  static_callstate_transitions/call_state/test_call_state.cpp
  static_callstate_transitions/call_state_graph/test_call_state_graph.cpp
  static_callstate_transitions/utils/test_call_state_transitions_utils.cpp

  )

target_include_directories(DiscoPoP_UT PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(DiscoPoP_UT PRIVATE DiscoPoP_RT)
target_link_libraries(DiscoPoP_UT PRIVATE gtest)
set_target_properties(DiscoPoP_UT PROPERTIES CXX_STANDARD 20)
set_target_properties(DiscoPoP_UT PROPERTIES ENABLE_EXPORTS 1)
