#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 200;
  std::vector<std::vector<int>> rows(n, std::vector<int>(16));
  for (int r = 0; r < n; r++)
    for (int c = 0; c < 16; c++)
      rows[r][c] = (r * 7 + c * 13) % 31;
  for (int r = 0; r < n; r++)
    std::sort(rows[r].begin(), rows[r].end(), [](int a, int b) { return a > b; });
  std::cout << rows[n - 1][0] << std::endl;
  return 0;
}
