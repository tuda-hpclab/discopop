// The constructor of a global object runs before main, its destructor after main has returned.
// Both are ordinary user code and have to be profiled, which requires the runtime to be up before
// the first and still alive after the last of them -- see profiler/rtlib/injected_functions/dp_init.cpp.
struct Table {
    int values[4];

    Table() {
        for (int i = 0; i < 4; ++i) {
            values[i] = i;
        }
    }

    ~Table() {
        for (int i = 0; i < 4; ++i) {
            values[i] = values[i] + 1;
        }
    }
};

Table global_table;

int main() {
    int total = 0;
    for (int i = 0; i < 4; ++i) {
        total += global_table.values[i];
    }
    return total == 6 ? 0 : 1;
}
