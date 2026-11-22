#include <cstdio>

#include "../third_party/lib.h"

int main() {
  static double a[1000];
  for (int i = 0; i < 1000; ++i) a[i] = i * 0.5;
  double t = 0;
  for (int i = 0; i < 1000; ++i) t += a[i] * 2;
  std::printf("%f %f\n", t, tp_sum(a, 1000));
  return 0;
}
