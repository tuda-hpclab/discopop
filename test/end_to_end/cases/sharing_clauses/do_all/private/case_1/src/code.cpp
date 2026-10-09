#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;

  int y = 42;
  int z = 0;

  // DO-ALL shared(y) private(z)
  for (int i = 0; i < n; i++) {
    z = y + i;
    int x = z;
  }
}
