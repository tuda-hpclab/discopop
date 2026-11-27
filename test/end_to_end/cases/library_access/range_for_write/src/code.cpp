#include <cstdlib>
#include <iostream>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  std::vector<int> v(n);
  for (int &x : v)
    x = x * 2 + 1;
  std::cout << v.back() << std::endl;
  return 0;
}
