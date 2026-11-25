#include <cstdio>

static double fill(const int n) {
  double values[64];
  for (int i = 0; i < 64; i++) {
    values[i] = n * 0.5 + i;
  }
  double sum = 0.0;
  for (int i = 0; i < 64; i++) {
    sum += values[i];
  }
  return sum;
}

static double descend(const int depth) { return depth == 0 ? fill(depth) : fill(depth) + descend(depth - 1); }

struct Logger {
  int count = 0;
  ~Logger() { std::printf("%f\n", descend(count)); }
};

static Logger logger;

int main() {
  for (int i = 0; i < 1000; i++) {
    logger.count += 1;
  }
  return 0;
}
