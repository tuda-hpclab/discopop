#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

int main(int argc, char *argv[]) {
  int n = argc > 1 ? std::atoi(argv[1]) : 1000;
  const char *words[] = {"alpha", "beta", "a rather long word beyond the small string buffer", "delta"};
  std::vector<std::size_t> lengths(n);
  for (int i = 0; i < n; i++) {
    std::string word(words[i % 4]);
    lengths[i] = word.size();
  }
  std::cout << lengths[n - 1] << std::endl;
  return 0;
}
