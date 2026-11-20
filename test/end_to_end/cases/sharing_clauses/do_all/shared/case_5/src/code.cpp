#include <cstddef>
#include <vector>

struct Scaler {
  double factor = 0.5;
  __attribute__((noinline)) void apply(const int* in, double* out, std::size_t n) {
    // DO-ALL shared(in, out, n); the member factor is reached through this
    for (std::size_t i = 0; i < n; ++i) {
      out[i] = in[i] * factor;
    }
  }
};

int main() {
  std::vector<int> in(1000, 2);
  std::vector<double> out(1000, 0.0);
  Scaler scaler;
  scaler.apply(in.data(), out.data(), in.size());
  volatile double sink = out[3];
  (void)sink;
  return 0;
}
