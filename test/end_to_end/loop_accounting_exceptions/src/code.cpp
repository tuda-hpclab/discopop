#include <cstdio>

int g[16];

void thrower(int i) {
  g[i] = i;
  if (i % 2) throw i;
}

// Every odd iteration throws; the exception is caught inside the loop, in the function of the loop.
int withexc() {
  int s = 0;
  for (int i = 0; i < 6; i++) {  // LOOP:withexc
    try {
      thrower(i);
      s += i;
    } catch (int) {
      s--;
    }
  }
  return s;
}

int caller() {
  int t = 0;
  for (int k = 0; k < 3; k++) {  // LOOP:caller
    t += withexc();
  }
  return t;
}

int main() {
  printf("%d\n", caller());
  return 0;
}
