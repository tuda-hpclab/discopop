#include <stdio.h>
int g_v = 0;
void tick() { g_v += 2; }
int main() {
  int i = 0;
  do {
    tick();
    ++i;
  } while (i < 4);
  printf("%d\n", g_v);
  return 0;
}
