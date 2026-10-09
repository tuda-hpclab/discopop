#include <stdio.h>
#include <stdlib.h>

int main(int argc, const char *argv[]) {
  static int n = 50000;
  int z = 123.456;


  for (int i = 0; i < n; i++) {
    int a = z + i;
    z = a + i;
    int x = z;
  }
}
