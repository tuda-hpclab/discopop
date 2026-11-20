#include <cstddef>
#include <vector>

__attribute__((noinline)) void integrate(const double* x, double* y, std::size_t n, double cc, double dd) {
  const double c = cc * 2.0;
  const double d = dd * 2.0;
  const double V = 3.0;
  // DO-ALL shared(x, y, n, c, d, V): c, d and V are const and never written
  for (std::size_t i = 0; i < n; ++i) {
    double v = x[i];
    double u = 0;
    for (unsigned s = 0; s < 4; ++s) {
      v += 1.0;
      if (v >= V) {
        v = c;
        u += d;
        break;
      }
    }
    y[i] = v + u;
  }
}

int main() {
  std::vector<double> x(1000, 1.0);
  std::vector<double> y(1000, 0.0);
  integrate(x.data(), y.data(), x.size(), 1.0, 2.0);
  volatile double sink = y[3];
  (void)sink;
  return 0;
}
