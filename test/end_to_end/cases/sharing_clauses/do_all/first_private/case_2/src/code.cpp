#include <cstddef>
#include <vector>

using real = double;

__attribute__((noinline)) void helper_set(real* p, real v) { *p = v; }
__attribute__((noinline)) void helper_copy(real* dst, const real* src) { *dst = *src; }

__attribute__((noinline)) void run(const double* x, double* y, std::size_t n) {
  real t = 0;
  // DO-ALL firstprivate(t): t is never named in the loop except for its address
  for (std::size_t i = 0; i < n; ++i) {
    helper_set(&t, x[i]);
    helper_copy(&y[i], &t);
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
