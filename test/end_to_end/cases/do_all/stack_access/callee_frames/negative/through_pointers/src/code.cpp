#include <cstdio>
#include <vector>

// a value carried from one iteration to the next, written and read by two different callees through pointers:
// like a dependency through the stack memory of a callee, it has a callee's local as its variable name, but it is real
__attribute__((noinline)) static void store(int *target, const int value) { *target = value; }

__attribute__((noinline)) static int load(const int *source) { return *source; }

int main() {
  const int n = 100;
  std::vector<int> out(n);
  int carried = 0;
  for (int i = 0; i < n; i++) {
    const int previous = load(&carried);
    store(&carried, previous + i);
    out[i] = previous;
  }
  int sum = 0;
  for (int i = 0; i < n; i++) {
    sum += out[i];
  }
  std::printf("%d\n", sum);
  return 0;
}
