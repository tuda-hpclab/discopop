#include <stdio.h>

int f(int n) {
  int s = 0;
  for (int i = 0; i < n * 100; i++) s += i % 7;
  return s;
}

// a later statement reads what an earlier task wrote (RAW): it is not a task of the group, the group is joined first
int raw(int k, int n) {
  int a, b, c;
  a = f(k);      // RAW_WRITE
  b = f(n);      // RAW_OTHER
  c = f(a);      // RAW_READ
  return a + b + c;
}

// a later statement overwrites what an earlier task read (WAR, anti dependence)
int war(int k, int n) {
  int p = k, b, c, d;
  b = f(p);      // WAR_READ
  c = f(n);      // WAR_OTHER
  p = f(n + 1);  // WAR_WRITE
  d = f(n + 2);
  return b + c + p + d;
}

// two tasks write the same variable (WAW, output dependence)
int waw(int k, int n) {
  int d, b, c;
  d = f(k);      // WAW_FIRST
  d = f(n);      // WAW_SECOND
  b = f(n + 1);
  c = f(n + 2);
  return d + b + c;
}

// the iterations of the loop accumulate into sum
int reduction_loop(int n) {
  int sum = 0;
  for (int k = 0; k < 16; k++) {
    sum += f(n + k);  // REDUCTION_BODY
  }
  return sum;
}

// the value of the last iteration is needed after the loop
int last_value_loop(int n) {
  int last = 0, v, res[16];
  for (int k = 0; k < 16; k++) {
    v = f(n + k);  // LAST_BODY
    res[k] = v;
    last = v;
  }
  return last + res[3];
}

int main() {
  printf("%d\n", raw(40, 50) + war(40, 50) + waw(40, 50) + reduction_loop(3) + last_value_loop(4));
  return 0;
}
