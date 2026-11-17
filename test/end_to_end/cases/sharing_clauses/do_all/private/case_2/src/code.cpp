#include <cstddef>
#include <vector>

struct Acc {
  double s = 0;
  void reset() { s = 0; }
  void add(double v) { s += v; }
  double sum() const { return s; }
};

__attribute__((noinline)) void run(const double* x, double* y, std::size_t n) {
  Acc tmp;
  // DO-ALL private(tmp): the iterations reset it; the profile does not see the writes made inside the methods
  for (std::size_t i = 0; i < n; ++i) {
    tmp.reset();
    tmp.add(x[i]);
    tmp.add(1.0);
    y[i] = tmp.sum();
  }
}

int main() {
  std::vector<double> x(1000, 1.0);
  std::vector<double> y(1000, 0.0);
  run(x.data(), y.data(), x.size());
  volatile double sink = y[3];
  (void)sink;
  return 0;
}
