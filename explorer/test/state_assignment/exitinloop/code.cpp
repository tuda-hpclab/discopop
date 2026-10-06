#include <stdio.h>
#include <stdlib.h>
// the shape of LULESH's ApplyMaterialPropertiesForElems: exit() inside a loop body, followed by
// another loop whose body calls a function, and a return inside a loop
double g_v[8] = {1, 2, 3, 4, 5, 6, 7, 8};
double g_e[8];
int g_found = -1;
void eval(int i) { g_e[i] = g_v[i] * 2.0; }
void apply(double eosvmin) {
  for (int i = 0; i < 8; ++i) {
    if (g_v[i] < eosvmin) {
      exit(1);
    }
  }
  for (int i = 0; i < 8; ++i) {
    eval(i);
  }
}
int find(double value) {
  for (int i = 0; i < 8; ++i) {
    if (g_e[i] == value) {
      return i;
    }
  }
  return -1;
}
int main() {
  for (int t = 0; t < 3; ++t) {
    apply(0.5);
    g_found = find(4.0);
  }
  printf("%d %f\n", g_found, g_e[3]);
  return 0;
}
