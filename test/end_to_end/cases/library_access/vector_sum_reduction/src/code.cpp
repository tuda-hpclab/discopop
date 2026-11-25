#include <cstdlib>
#include <iostream>
#include <numeric>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  std::vector<int> v(n);
  std::iota(v.begin(), v.end(), 0);
  long sum = 0;
  for (size_t i = 0; i < v.size(); i++)
    sum += v[i];
  std::cout << sum << std::endl;
  return 0;
}
