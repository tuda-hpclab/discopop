#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 200;
  std::vector<std::vector<int>> rows(n, std::vector<int>(16, 1));
  long total = 0;
  for (int r = 0; r < n; r++)
    std::for_each(rows[r].begin(), rows[r].end(), [&total](int x) { total += x; });
  std::cout << total << std::endl;
  return 0;
}
