#include <cstddef>
#include <vector>

double g_scale = 2.0;

__attribute__((noinline)) void scale(const double* x, double* y, std::size_t n) {
  // DO-ALL shared(x, y, n, g_scale)
  for (std::size_t i = 0; i < n; ++i) {
    y[i] = x[i] * g_scale;
  }
}

int main() {
  std::vector<double> x(1000, 1.0);
  std::vector<double> y(1000, 0.0);
  scale(x.data(), y.data(), x.size());
  volatile double sink = y[3];
  (void)sink;
  return 0;
}
