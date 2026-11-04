#include <complex>
#include <vector>
#define ADD(x, v) x += v
struct D {
    double &fx(int n);
};
template <typename T> void upd_tmpl(T *out, const T *in, const int *idx, int n) {
    for (int i = 0; i < n; i++) {
        out[idx[i]] += in[i];
    }
}
template <typename T> void upd_never(T *out, const T *in, int n) {
    for (int i = 0; i < n; i++) {
        out[i] += in[i];
    }
}
void upd_inst(double *d, float *f, const double *dd, const float *ff, const int *idx, int n) {
    upd_tmpl(d, dd, idx, n);
    upd_tmpl(f, ff, idx, n);
}
void upd_basic(double *a, double *b, int *h, const int *idx, double v, int n) {
    for (int i = 0; i < n; i++) {
        a[idx[i]] += v;
    }
}
void upd_incdec(int *h, int n) {
    for (int k = 0; k < n; k++) {
        h[k]++;
        ++h[k];
        h[k]--;
    }
}
void upd_ops(double *m, long *b, int n, double v, long w) {
    for (int k = 0; k < n; k++) {
        m[k] *= v;
        b[k] &= w;
        b[k] |= w;
        b[k] ^= w;
        m[k] -= v;
    }
}
void upd_prefix(double *p, int n) {
    for (int i = 0; i < n; i++) {
        p[i + 1] += p[i];
    }
}
void upd_value(int *h, int *y, const double *x, int n) {
    double s = 0;
    for (int k = 0; k < n; k++) {
        y[k] = h[k]++;
    }
    for (int i = 0; i < n; i++) s += x[i];
}
void upd_notalone(double *a, double *b, int n) {
    for (int k = 0; k < n; k++) {
        a[k] += 1; b[k] += 1;
    }
    for (int k = 0; k < n; k++) { a[k] += 1; }
}
void upd_multi(double *a, const double *v, int n) {
    for (int k = 0; k < n; k++) {
        a[k] +=
            v[k];
    }
}
void upd_macro(double *a, int n) {
    for (int k = 0; k < n; k++) {
        ADD(a[k], 1.0);
    }
}
void upd_vec(std::vector<double> &v, D &d, const double *x, int n, double f) {
    for (int k = 0; k < n; k++) {
        v[k] += x[k];
        d.fx(n) += f;
    }
}
void upd_complex(std::complex<double> &c, std::complex<double> z, int n) {
    for (int k = 0; k < n; k++) {
        c += z;
    }
}
void upd_none(double *a, int n) {
    for (int k = 0; k < n; k++) {
        a[k] = 1.0;
    }
}
