#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// Ground truth for the get_side_effects tests: every function documents the
// effects it has outside of itself (see DESIGN_get_side_effects.md, section 5).

int g_counter = 0;
int g_sink = 0;
int g_unused = 0;
int g_seq = 0;
int g_chain = 0;
int g_pointer_target = 0;
const int g_table[4] = {1, 2, 3, 4};

struct Pair {
  int first;
  int second;
};

// no effects
int pure_add(int a, int b) { return a + b; }

// reads g_counter
int read_global() { return g_counter; }

// writes g_counter (read later in main)
void write_global(int v) { g_counter = v; }

// writes g_sink, which is never read again
void write_only_global(int v) { g_sink = v; }

// writes the pointee of p
void write_through_param(int *p, int n) {
  for (int i = 0; i < n; ++i) {
    p[i] = i;
  }
}

// no own effects; writes the pointee of q through write_through_param. The effect is named as at
// the access: parameter p, with via [write_through_param]; the caller's buf goes to outside_names
void wrapper(int *q, int n) { write_through_param(q, n); }

// no effects: the written buffer is its own
int local_buffer() {
  int local[8];
  write_through_param(local, 8);
  return local[7];
}

// reads and writes g_seq; called repeatedly
int next_value() { return ++g_seq; }

// no effects: v is its own copy, even though its address is passed on
void bump(int *x) { *x += 1; }
int address_taken(int v) {
  bump(&v);
  return v;
}

// no effects: both pass the address of a local, which may reuse the same stack slot
int sibling_a() {
  int a = 1;
  bump(&a);
  return a;
}
int sibling_b() {
  int b = 2;
  bump(&b);
  return b;
}

// writes the pointee of p, but inside a library function that is not profiled
void clear(int *p, int n) { memset(p, 0, sizeof(int) * n); }

// writes a member of the pointee of s
void set_member(Pair *s) { s->second = 7; }

// no effects: the local shadows the global g_counter
int shadow() {
  int g_counter = 5;
  g_counter += 1;
  return g_counter;
}

// reads and writes its function-static counter (persistent state)
int count_calls() {
  static int calls = 0;
  calls += 1;
  return calls;
}

// reads the constant-initialized g_table, which is never written at runtime
int read_const_table(int i) { return g_table[i % 4]; }

// writes g_unused, but is never called
void never_called() { g_unused = 42; }

// recursion deeper than the inlining limit; writes g_counter at the bottom
int recurse(int n) {
  if (n == 0) {
    g_counter += 1;
    return 0;
  }
  return 1 + recurse(n - 1);
}

// a call chain deeper than the inlining limit; only chain7 writes g_chain
void chain7() { g_chain += 7; }
void chain6() { chain7(); }
void chain5() { chain6(); }
void chain4() { chain5(); }
void chain3() { chain4(); }
void chain2() { chain3(); }
void chain1() { chain2(); }

// only ever called through a function pointer (no static call site anywhere); writes g_pointer_target
void pointer_target() { g_pointer_target += 1; }
void call_via_pointer(void (*f)()) { f(); }

// file I/O
void log_value(int v) { printf("%d\n", v); }

int main(int argc, const char *argv[]) {
  int n = 16;
  int *buf = (int *)malloc(n * sizeof(int));
  int sum = pure_add(1, 2);
  write_global(sum);
  sum += read_global();
  write_only_global(sum);
  write_through_param(buf, n);
  wrapper(buf, n);
  sum += buf[3];
  sum += local_buffer();
  sum += next_value();
  for (int i = 0; i < 4; ++i) {
    sum += next_value();
  }
  sum += address_taken(sum);
  sum += sibling_a();
  sum += sibling_b();
  clear(buf, n);
  sum += buf[5];
  Pair pair = {1, 2};
  set_member(&pair);
  sum += pair.second;
  sum += shadow();
  sum += count_calls();
  sum += count_calls();
  sum += read_const_table(sum);
  sum += recurse(10);
  sum += g_counter;
  chain1();
  sum += g_chain;
  call_via_pointer(pointer_target);
  sum += g_pointer_target;
  if (argc > 100) {
    never_called();
  }
  log_value(sum);
  free(buf);
  return 0;
}
