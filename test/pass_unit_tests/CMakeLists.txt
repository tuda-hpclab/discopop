# Unit tests for the DiscoPoP LLVM pass (profiler/DiscoPoP).
#
# These live in a separate binary from test/unit_tests: the pass tests have to link the LLVM
# libraries, and the runtime tests should not inherit that dependency.

include(FetchContent)

enable_testing()

# googletest may already have been declared by test/unit_tests. Re-declaring is a no-op in that
# case, which keeps this directory self-contained regardless of the order the tests are added in.
FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest
        GIT_TAG release-1.12.1)

set(gtest_force_shared_crt
        ON
        CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

get_target_property(gtest_main_includes gtest_main
        INTERFACE_INCLUDE_DIRECTORIES)
set_target_properties(gtest_main PROPERTIES INTERFACE_SYSTEM_INCLUDE_DIRECTORIES
        "${gtest_main_includes}")

add_executable(DiscoPoP_Pass_UT)
target_sources(
  DiscoPoP_Pass_UT
  PRIVATE
  tests.cpp
  utils/output/test_output.cpp
  )

target_include_directories(DiscoPoP_Pass_UT PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})

# DiscoPoP_PassObjects carries the pass objects plus the include directories and the
# DP_HYBRID_PROFILING / DP_BRANCH_TRACKING definitions the sources need in order to compile.
target_link_libraries(DiscoPoP_Pass_UT PRIVATE DiscoPoP_PassObjects)

# the pass objects reference the LLVM libraries, which the plugin normally gets from its host
# process (opt/clang). A standalone binary has to link them itself.
#
# Prefer libLLVM.so: the individual static components pull zstd::libzstd_shared into their link
# interface, and Debian/Ubuntu ship libzstd-dev without a CMake package, so that imported target
# does not exist and CMake fails at generate time.
if(TARGET LLVM)
    target_link_libraries(DiscoPoP_Pass_UT PRIVATE LLVM)
else()
    if(NOT TARGET zstd::libzstd_shared)
        find_library(DiscoPoP_ZSTD_LIBRARY NAMES zstd)
        if(DiscoPoP_ZSTD_LIBRARY)
            add_library(zstd::libzstd_shared UNKNOWN IMPORTED)
            set_target_properties(zstd::libzstd_shared PROPERTIES IMPORTED_LOCATION "${DiscoPoP_ZSTD_LIBRARY}")
        endif()
    endif()
    llvm_map_components_to_libnames(discopop_pass_ut_llvm_libs
      core
      support
      analysis
      passes
      asmparser
      irreader
      )
    target_link_libraries(DiscoPoP_Pass_UT PRIVATE ${discopop_pass_ut_llvm_libs})
endif()

target_link_libraries(DiscoPoP_Pass_UT PRIVATE gtest)
set_target_properties(DiscoPoP_Pass_UT PROPERTIES CXX_STANDARD 17)
set_target_properties(DiscoPoP_Pass_UT PROPERTIES ENABLE_EXPORTS 1)
