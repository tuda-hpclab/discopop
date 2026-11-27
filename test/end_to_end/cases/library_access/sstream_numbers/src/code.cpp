#include <cstdlib>
#include <iostream>
#include <sstream>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  std::vector<int> values(n, 3);
  std::ostringstream out;
  for (const int &value : values)
    out << value << ' ';
  std::cout << out.str().size() << std::endl;
  return 0;
}
