#include <cstdio>
#include <vector>

static int collect(const int seed) {
  std::vector<int> values;
  for (int k = 0; k < 40; k++) {
    values.push_back(seed + k);
  }
  int sum = 0;
  for (const int value : values) {
    sum += value;
  }
  return sum;
}

int main() {
  const int n = 100;
  std::vector<int> result(n);
  for (int i = 0; i < n; i++) {
    result[i] = collect(i);
  }
  std::printf("%d\n", result[n - 1]);
  return 0;
}
