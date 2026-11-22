#include <cstddef>
#include <memory>
#include <vector>

struct Holder {
  std::vector<double> v;
  explicit Holder(std::size_t n) : v(n, 1.5) {}
  double get(std::size_t i) const { return v[i]; }
};

__attribute__((noinline)) void gather(std::shared_ptr<Holder> p, double* out, std::size_t n) {
  // DO-ALL shared(p, out, n): p is only read, through the const operator->
  for (std::size_t i = 0; i < n; ++i) {
    out[i] = p->get(i);
  }
}

int main() {
  auto holder = std::make_shared<Holder>(1000);
  std::vector<double> out(1000, 0.0);
  gather(holder, out.data(), out.size());
  volatile double sink = out[3];
  (void)sink;
  return 0;
}
