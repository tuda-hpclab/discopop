// A header-only "third-party library" below the project root, but outside of the instrumentation scope src/.
inline double tp_sum(const double* a, int n) {
  double s = 0;
  for (int i = 0; i < n; ++i) s += a[i];
  return s;
}
