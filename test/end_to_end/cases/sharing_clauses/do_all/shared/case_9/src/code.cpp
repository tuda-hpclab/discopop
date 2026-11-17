#include <cstddef>
#include <mutex>
#include <vector>

__attribute__((noinline)) void guarded_copy(const double* x, double* y, std::size_t n) {
  std::mutex m;
  // DO-ALL shared(m, x, y, n)
  for (std::size_t i = 0; i < n; ++i) {
    m.lock();
    y[i] = x[i];
    m.unlock();
  }
}

int main() {
  std::vector<double> x(1000, 1.0);
  std::vector<double> y(1000, 0.0);
  guarded_copy(x.data(), y.data(), x.size());
  volatile double sink = y[3];
  (void)sink;
  return 0;
}
