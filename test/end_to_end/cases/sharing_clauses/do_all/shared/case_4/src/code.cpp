#include <cstddef>
#include <vector>

__attribute__((noinline)) void fill(double* out, std::size_t m) {
  const std::size_t n = m - 1;
  // DO-ALL shared(out, n): n is only read by the loop header
  for (std::size_t i = 0; i < n; ++i) {
    out[i] = static_cast<double>(i);
  }
}

int main() {
  std::vector<double> out(1000, 0.0);
  fill(out.data(), out.size());
  volatile double sink = out[3];
  (void)sink;
  return 0;
}
