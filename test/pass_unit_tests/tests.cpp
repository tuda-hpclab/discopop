#include <gtest/gtest.h>

int main(int argc, char **argv) {
  ::testing::InitGoogleTest(&argc, argv);
  const auto tests_return_code = RUN_ALL_TESTS();

  return tests_return_code;
}
