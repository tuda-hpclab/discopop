#include <algorithm>
#include <cstdio>
#include <vector>

int main() {
  const int n = 100;
  std::vector<int> previous(16, 1);
  std::vector<int> current(16);
  for (int i = 0; i < n; i++) {
    std::copy(previous.begin(), previous.end(), current.begin());
    for (int k = 0; k < 16; k++) {
      previous[k] = current[k] + i;
    }
  }
  std::printf("%d\n", previous[15]);
  return 0;
}
