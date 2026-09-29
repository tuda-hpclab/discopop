#include <stdio.h>
#include <stdlib.h>
#include <cmath>


double dist ( int nd, double r1[], double r2[], double dr[] )

//****************************************************************************80
//
//  Purpose:
//
//    DIST computes the displacement (and its norm) between two particles.
//
//  Licensing:
//
//    This code is distributed under the GNU LGPL license.
//
//  Modified:
//
//    21 November 2007
//
//  Author:
//
//    Original FORTRAN90 version by Bill Magro.
//    C++ version by John Burkardt.
//
//  Parameters:
//
//    Input, int ND, the number of spatial dimensions.
//
//    Input, double R1[ND], R2[ND], the positions of the particles.
//
//    Output, double DR[ND], the displacement vector.
//
//    Output, double D, the Euclidean norm of the displacement.
//
{
  double d;
  int i;

  d = 0.0;
  for ( i = 0; i < nd; i++ )
  {
    dr[i] = r1[i] - r2[i];
    d = d + dr[i] * dr[i];
  }
  d = sqrt ( d );

  return d;
}



int main(int argc, const char *argv[]) {
  int nd = 10;
  double r1[10];
  double r2[10];
  double dr[10];
  for(int i = 0; i < 10; ++i){
    r1[i]=i*10/3;
    r2[i]=i*17/2;
    dr[i]=(i*(12+2)-51)/3;
  }
  dist(nd, r1, r2, dr);
}
