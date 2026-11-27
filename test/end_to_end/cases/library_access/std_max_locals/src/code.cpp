#include <algorithm>
#include <cstdlib>
#include <iostream>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  std::vector<int> out(n);
  for (int i = 0; i < n; i++) {
    int a = i, b = n - i;
    out[i] = std::max(a, b);
  }
  std::cout << out.back() << std::endl;
  return 0;
}
