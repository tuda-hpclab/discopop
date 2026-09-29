#include <cstdlib>

int main(){
    int a[100];
    int b[100];

    for(int i = 0; i < 100; ++i){
        a[i] = i;
    }

    for(int i = 0; i < 100; ++i){
        b[i] = i * 2;
    }

    return 0;
}
