#include <vector>

struct Domain;
double helper(double x);
void setup_domain(Domain* d);

// a loop in a function reached only after
// - a call to a function defined in a system header (std::vector), which is not instrumented
// - a call to a function of another translation unit
double work(double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) {
    a[i] = i;
    s += a[i];
  }
  return s;
}

double driver(double* a, int n) {
  std::vector<double> v(n, 1.0);
  double s = v[0];
  s += helper(1.0);
  s += work(a, n);
  return s;
}

int main() {
  int n = 20;
  double* a = new double[n];
  setup_domain(nullptr);
  double s = driver(a, n);
  delete[] a;
  return s > 0 ? 0 : 1;
}
