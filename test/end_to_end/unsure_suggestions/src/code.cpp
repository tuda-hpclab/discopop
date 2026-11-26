#include <cstdio>
#include <vector>

static unsigned state = 12345u;

static unsigned next_random() {
  state = state * 1103515245u + 12345u;
  return state >> 8;
}

int main() {
  const int n = 200;
  std::vector<int> requests;
  std::vector<unsigned> drawn(n);
  std::vector<int> doubled(n);
  // APPEND: the order of the requests changes in a parallel loop
  for (int i = 0; i < n; i++) {
    if (i % 3 == 0) {
      requests.push_back(i);
    }
  }
  // RANDOM: each iteration advances the generator
  for (int i = 0; i < n; i++) {
    drawn[i] = next_random() % 100;
  }
  // INDEPENDENT: a do-all loop
  for (int i = 0; i < n; i++) {
    doubled[i] = 2 * i;
  }
  long sum = 0;
  for (int i = 0; i < n; i++) {
    sum += static_cast<long>(drawn[i]) + doubled[i];
  }
  std::printf("%zu %ld\n", requests.size(), sum);
  return 0;
}
