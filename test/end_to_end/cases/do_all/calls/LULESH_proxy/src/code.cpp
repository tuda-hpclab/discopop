#include <stdio.h>
#include <stdlib.h>

class Domain {
private:
  double *arr_x;
  double *arr_y;
  double *arr_z;
  double *arr_fx;
  double *arr_fy;
  double *arr_fz;

public:
  void setPointers(double *arg_arr_x, double *arg_arr_y, double *arg_arr_z, double *arg_fx, double *arg_fy,
                   double *arg_fz) {
    arr_x = arg_arr_x;
    arr_y = arg_arr_y;
    arr_z = arg_arr_z;
    arr_fx = arg_fx;
    arr_fy = arg_fy;
    arr_fz = arg_fz;
  }

  double &x(int idx) { return arr_x[idx]; }

  double &y(int idx) { return arr_y[idx]; }

  double &z(int idx) { return arr_z[idx]; }

  double &fx(int idx) { return arr_fx[idx]; }

  double &fy(int idx) { return arr_fy[idx]; }

  double &fz(int idx) { return arr_fz[idx]; }
};

static inline void CollectDomainNodesToElemNodes(Domain domain, const short *elemToNode, double elemX[8],
                                                 double elemY[8], double elemZ[8]) {
  short nd0i = elemToNode[0];
  short nd1i = elemToNode[1];
  short nd2i = elemToNode[2];
  short nd3i = elemToNode[3];
  short nd4i = elemToNode[4];
  short nd5i = elemToNode[5];
  short nd6i = elemToNode[6];
  short nd7i = elemToNode[7];

  elemX[0] = domain.x(nd0i);
  elemX[1] = domain.x(nd1i);
  elemX[2] = domain.x(nd2i);
  elemX[3] = domain.x(nd3i);
  elemX[4] = domain.x(nd4i);
  elemX[5] = domain.x(nd5i);
  elemX[6] = domain.x(nd6i);
  elemX[7] = domain.x(nd7i);

  elemY[0] = domain.y(nd0i);
  elemY[1] = domain.y(nd1i);
  elemY[2] = domain.y(nd2i);
  elemY[3] = domain.y(nd3i);
  elemY[4] = domain.y(nd4i);
  elemY[5] = domain.y(nd5i);
  elemY[6] = domain.y(nd6i);
  elemY[7] = domain.y(nd7i);

  elemZ[0] = domain.z(nd0i);
  elemZ[1] = domain.z(nd1i);
  elemZ[2] = domain.z(nd2i);
  elemZ[3] = domain.z(nd3i);
  elemZ[4] = domain.z(nd4i);
  elemZ[5] = domain.z(nd5i);
  elemZ[6] = domain.z(nd6i);
  elemZ[7] = domain.z(nd7i);
}

static inline void CalcElemShapeFunctionDerivatives(double const x[], double const y[], double const z[], double b[][8],
                                                    double *const volume) {
  const double x0 = x[0];
  const double x1 = x[1];
  const double x2 = x[2];
  const double x3 = x[3];
  const double x4 = x[4];
  const double x5 = x[5];
  const double x6 = x[6];
  const double x7 = x[7];

  const double y0 = y[0];
  const double y1 = y[1];
  const double y2 = y[2];
  const double y3 = y[3];
  const double y4 = y[4];
  const double y5 = y[5];
  const double y6 = y[6];
  const double y7 = y[7];

  const double z0 = z[0];
  const double z1 = z[1];
  const double z2 = z[2];
  const double z3 = z[3];
  const double z4 = z[4];
  const double z5 = z[5];
  const double z6 = z[6];
  const double z7 = z[7];

  double fjxxi, fjxet, fjxze;
  double fjyxi, fjyet, fjyze;
  double fjzxi, fjzet, fjzze;
  double cjxxi, cjxet, cjxze;
  double cjyxi, cjyet, cjyze;
  double cjzxi, cjzet, cjzze;

  fjxxi = double(.125) * ((x6 - x0) + (x5 - x3) - (x7 - x1) - (x4 - x2));
  fjxet = double(.125) * ((x6 - x0) - (x5 - x3) + (x7 - x1) - (x4 - x2));
  fjxze = double(.125) * ((x6 - x0) + (x5 - x3) + (x7 - x1) + (x4 - x2));

  fjyxi = double(.125) * ((y6 - y0) + (y5 - y3) - (y7 - y1) - (y4 - y2));
  fjyet = double(.125) * ((y6 - y0) - (y5 - y3) + (y7 - y1) - (y4 - y2));
  fjyze = double(.125) * ((y6 - y0) + (y5 - y3) + (y7 - y1) + (y4 - y2));

  fjzxi = double(.125) * ((z6 - z0) + (z5 - z3) - (z7 - z1) - (z4 - z2));
  fjzet = double(.125) * ((z6 - z0) - (z5 - z3) + (z7 - z1) - (z4 - z2));
  fjzze = double(.125) * ((z6 - z0) + (z5 - z3) + (z7 - z1) + (z4 - z2));

  /* compute cofactors */
  cjxxi = (fjyet * fjzze) - (fjzet * fjyze);
  cjxet = -(fjyxi * fjzze) + (fjzxi * fjyze);
  cjxze = (fjyxi * fjzet) - (fjzxi * fjyet);

  cjyxi = -(fjxet * fjzze) + (fjzet * fjxze);
  cjyet = (fjxxi * fjzze) - (fjzxi * fjxze);
  cjyze = -(fjxxi * fjzet) + (fjzxi * fjxet);

  cjzxi = (fjxet * fjyze) - (fjyet * fjxze);
  cjzet = -(fjxxi * fjyze) + (fjyxi * fjxze);
  cjzze = (fjxxi * fjyet) - (fjyxi * fjxet);

  /* calculate partials :
     this need only be done for l = 0,1,2,3   since , by symmetry ,
     (6,7,4,5) = - (0,1,2,3) .
  */
  b[0][0] = -cjxxi - cjxet - cjxze;
  b[0][1] = cjxxi - cjxet - cjxze;
  b[0][2] = cjxxi + cjxet - cjxze;
  b[0][3] = -cjxxi + cjxet - cjxze;
  b[0][4] = -b[0][2];
  b[0][5] = -b[0][3];
  b[0][6] = -b[0][0];
  b[0][7] = -b[0][1];

  b[1][0] = -cjyxi - cjyet - cjyze;
  b[1][1] = cjyxi - cjyet - cjyze;
  b[1][2] = cjyxi + cjyet - cjyze;
  b[1][3] = -cjyxi + cjyet - cjyze;
  b[1][4] = -b[1][2];
  b[1][5] = -b[1][3];
  b[1][6] = -b[1][0];
  b[1][7] = -b[1][1];

  /* calculate jacobian determinant (volume) */
  *volume = double(8.) * (fjxet * cjxet + fjyet * cjyet + fjzet * cjzet);
}

static inline void SumElemFaceNormal(double *normalX0, double *normalY0, double *normalZ0, double *normalX1,
                                     double *normalY1, double *normalZ1, double *normalX2, double *normalY2,
                                     double *normalZ2, double *normalX3, double *normalY3, double *normalZ3,
                                     const double x0, const double y0, const double z0, const double x1,
                                     const double y1, const double z1, const double x2, const double y2,
                                     const double z2, const double x3, const double y3, const double z3) {
  double bisectX0 = double(0.5) * (x3 + x2 - x1 - x0);
  double bisectY0 = double(0.5) * (y3 + y2 - y1 - y0);
  double bisectZ0 = double(0.5) * (z3 + z2 - z1 - z0);
  double bisectX1 = double(0.5) * (x2 + x1 - x3 - x0);
  double bisectY1 = double(0.5) * (y2 + y1 - y3 - y0);
  double bisectZ1 = double(0.5) * (z2 + z1 - z3 - z0);
  double areaX = double(0.25) * (bisectY0 * bisectZ1 - bisectZ0 * bisectY1);
  double areaY = double(0.25) * (bisectZ0 * bisectX1 - bisectX0 * bisectZ1);
  double areaZ = double(0.25) * (bisectX0 * bisectY1 - bisectY0 * bisectX1);

  *normalX0 += areaX;
  *normalX1 += areaX;
  *normalX2 += areaX;
  *normalX3 += areaX;

  *normalY0 += areaY;
  *normalY1 += areaY;
  *normalY2 += areaY;
  *normalY3 += areaY;

  *normalZ0 += areaZ;
  *normalZ1 += areaZ;
  *normalZ2 += areaZ;
  *normalZ3 += areaZ;
}

static inline void CalcElemNodeNormals(double pfx[8], double pfy[8], double pfz[8], const double x[8],
                                       const double y[8], const double z[8]) {
  for (int i = 0; i < 8; ++i) {
    pfx[i] = double(0.0);
    pfy[i] = double(0.0);
    pfz[i] = double(0.0);
  }
  /* evaluate face one: nodes 0, 1, 2, 3 */
  SumElemFaceNormal(&pfx[0], &pfy[0], &pfz[0], &pfx[1], &pfy[1], &pfz[1], &pfx[2], &pfy[2], &pfz[2], &pfx[3], &pfy[3],
                    &pfz[3], x[0], y[0], z[0], x[1], y[1], z[1], x[2], y[2], z[2], x[3], y[3], z[3]);
  /* evaluate face two: nodes 0, 4, 5, 1 */
  SumElemFaceNormal(&pfx[0], &pfy[0], &pfz[0], &pfx[4], &pfy[4], &pfz[4], &pfx[5], &pfy[5], &pfz[5], &pfx[1], &pfy[1],
                    &pfz[1], x[0], y[0], z[0], x[4], y[4], z[4], x[5], y[5], z[5], x[1], y[1], z[1]);
  /* evaluate face three: nodes 1, 5, 6, 2 */
  SumElemFaceNormal(&pfx[1], &pfy[1], &pfz[1], &pfx[5], &pfy[5], &pfz[5], &pfx[6], &pfy[6], &pfz[6], &pfx[2], &pfy[2],
                    &pfz[2], x[1], y[1], z[1], x[5], y[5], z[5], x[6], y[6], z[6], x[2], y[2], z[2]);
  /* evaluate face four: nodes 2, 6, 7, 3 */
  SumElemFaceNormal(&pfx[2], &pfy[2], &pfz[2], &pfx[6], &pfy[6], &pfz[6], &pfx[7], &pfy[7], &pfz[7], &pfx[3], &pfy[3],
                    &pfz[3], x[2], y[2], z[2], x[6], y[6], z[6], x[7], y[7], z[7], x[3], y[3], z[3]);
  /* evaluate face five: nodes 3, 7, 4, 0 */
  SumElemFaceNormal(&pfx[3], &pfy[3], &pfz[3], &pfx[7], &pfy[7], &pfz[7], &pfx[4], &pfy[4], &pfz[4], &pfx[0], &pfy[0],
                    &pfz[0], x[3], y[3], z[3], x[7], y[7], z[7], x[4], y[4], z[4], x[0], y[0], z[0]);
  /* evaluate face six: nodes 4, 7, 6, 5 */
  SumElemFaceNormal(&pfx[4], &pfy[4], &pfz[4], &pfx[7], &pfy[7], &pfz[7], &pfx[6], &pfy[6], &pfz[6], &pfx[5], &pfy[5],
                    &pfz[5], x[4], y[4], z[4], x[7], y[7], z[7], x[6], y[6], z[6], x[5], y[5], z[5]);
}

static inline void SumElemStressesToNodeForces(const double B[][8], const double stress_xx, const double stress_yy,
                                               const double stress_zz, double fx[], double fy[], double fz[]) {
  for (int i = 0; i < 8; i++) {
    fx[i] = -(stress_xx * B[0][i]);
    fy[i] = -(stress_yy * B[1][i]);
    fz[i] = -(stress_zz * B[2][i]);
  }
}

int main(int argc, const char *argv[]) {
  static int n = 1000;
  double *x = (double *)malloc(n * sizeof(double));
  double *y = (double *)malloc(n * sizeof(double));
  double *z = (double *)malloc(n * sizeof(double));
  double *fx = (double *)malloc(n * sizeof(double));
  double *fy = (double *)malloc(n * sizeof(double));
  double *fz = (double *)malloc(n * sizeof(double));
  double *volumes = (double *)malloc(n * sizeof(double));
  Domain domain;
  domain.setPointers(x, y, z, fx, fy, fz);
  double fx_local[8];
  double fy_local[8];
  double fz_local[8];

  double sigxx = 0.42, sigyy = 1.42, sigzz = 2.42;

  // DOALL
  for (int k = 0; k < n; ++k) {
    double B[3][8]; // shape function derivatives
    double x_local[8];
    double y_local[8];
    double z_local[8];

    short elemToNode[8] = {4, 3, 2, 1, 5, 6, 7, 0};

    // get nodal coordinates from global arrays and copy into local arrays.
    CollectDomainNodesToElemNodes(domain, elemToNode, x_local, y_local, z_local);

    // Volume calculation involves extra work for numerical consistency
    CalcElemShapeFunctionDerivatives(x_local, y_local, z_local, B, &volumes[k]);

    CalcElemNodeNormals(B[0], B[1], B[2], x_local, y_local, z_local);

    SumElemStressesToNodeForces(B, sigxx, sigyy, sigzz, fx_local, fy_local, fz_local);

    // copy nodal force contributions to global force arrray.
    for (int lnode = 0; lnode < 8; ++lnode) {
      int gnode = elemToNode[lnode];
      domain.fx(gnode) += fx_local[lnode];
      domain.fy(gnode) += fy_local[lnode];
      domain.fz(gnode) += fz_local[lnode];
    }
  }
  free(x);
  free(y);
  free(z);
  free(volumes);
  return 0;
}
