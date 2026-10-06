#include <stdio.h>
int g_a = 0;
int g_b = 0;
struct Dom { double t; double stop; int cyc; };
double get_time(Dom *d) { return d->t; }
void step_a(Dom *d) { g_a += 1; d->t += 1.0; }
void step_b(Dom *d) { g_b += g_a; d->cyc += 1; }
int main(int argc, char **argv) {
  Dom d = {0.0, 5.0, 0};
  int its = 100;
  int show = argc > 5;
  while ((get_time(&d) < d.stop) && (d.cyc < its)) {
    step_a(&d);
    step_b(&d);
    if (show) {
      printf("%d\n", d.cyc);
    }
  }
  printf("%d %d\n", g_a, g_b);
  return 0;
}
