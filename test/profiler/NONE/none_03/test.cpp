#include <cstdlib>

int main(){
    int x = 0;
    int y = 0;

    for(int i = 0; i < 100; ++i){
        x = i;
    }

    for(int i = 0; i < 100; ++i){
        y = i * 2;
    }

    (void)x;
    (void)y;
    return 0;
}
