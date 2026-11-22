// A header-only "third-party library" below the project root, excluded by some of the tests.
inline double tp_sum(const double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) s += a[i];
  return s;
}
