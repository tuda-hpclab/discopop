#include <cstdlib>
#include <iostream>
#include <map>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  std::map<int, int> m;
  for (int i = 0; i < n; i++)
    m[i] = i;
  std::cout << m.size() << std::endl;
  return 0;
}
