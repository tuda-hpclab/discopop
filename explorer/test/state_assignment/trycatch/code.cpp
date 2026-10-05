#include <stdio.h>
#include <stdexcept>
// a throw inside a loop, caught in the loop body: the landing pads, the destructor cleanup of
// the Guard and the catch handler are cut from the TaskGraph (__cut_exception_unwind_paths)
int g_sum = 0;
int g_caught = 0;
struct Guard {
  ~Guard() { g_sum += 1; }
};
void work(int i) {
  Guard g;
  if (i == 3) {
    throw std::runtime_error("three");
  }
  g_sum += i;
}
int main() {
  for (int i = 0; i < 5; ++i) {
    try {
      work(i);
    } catch (const std::exception &e) {
      g_caught += 1;
    }
  }
  printf("%d %d\n", g_sum, g_caught);
  return 0;
}
