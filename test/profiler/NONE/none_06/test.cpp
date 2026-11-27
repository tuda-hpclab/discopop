#include <vector>

int main() {
  std::vector<unsigned> counts;
  unsigned total = 0;
  for (unsigned round = 0; round < 2000; round++) {
    counts.resize(round + 1);
    for (unsigned i = 0; i <= round; i++) {
      counts[i] += i;
    }
    total += counts[round];
  }
  return total == 0 ? 1 : 0;
}
