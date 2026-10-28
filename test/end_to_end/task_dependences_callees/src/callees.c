#include <stdio.h>

// the callee writes through its pointer parameter and keeps locals
void set(int *p, int v) {
    int s = 0;
    for (int i = 0; i < 100000; i++)
        s += (v * i) % 7;
    *p = s;
}

// WRITES_SHARED: both tasks write d inside the same callee
int shared(int n) {
    int d = 0;
    set(&d, n);     // SHARED_FIRST
    set(&d, n + 1); // SHARED_SECOND
    return d;
}

// the callee has locals and a loop, but writes nothing the caller can see
int work(int v) {
    int s = 0;
    for (int i = 0; i < 100000; i++)
        s += (v * i) % 7;
    return s;
}

// locals of every kind: an array, a struct and a variable whose address is passed on
struct acc { int sum; int cnt; };
static void add(struct acc *a, int x) { a->sum += x; a->cnt++; }
int buffered(int v) {
    int buf[16];
    struct acc a = {0, 0};
    for (int i = 0; i < 16; i++)
        buf[i] = (v * i) % 5;
    for (int i = 0; i < 16; i++)
        add(&a, buf[i]);
    return a.sum + a.cnt;
}

// CONTROL: independent results
int control(int n) {
    int a = work(n);     // CONTROL_FIRST
    int b = work(n + 1); // CONTROL_SECOND
    return a + b;
}

// CONTROL_LOCALS: the callee keeps arrays, structs and pointers to its own locals
int control_locals(int n) {
    int a = buffered(n);     // LOCALS_FIRST
    int b = buffered(n + 1); // LOCALS_SECOND
    return a + b;
}

int main(int argc, char **argv) {
    printf("%d\n", shared(10));
    printf("%d\n", control(10));
    printf("%d\n", control_locals(10));
    return 0;
}
