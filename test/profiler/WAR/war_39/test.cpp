#include <cstdlib>

int main(){
    int arr[101];
    for(int i = 0; i < 101; i++){
        arr[i] = 0;
    }
    for(int i = 0; i < 99; ++i){
        int z = arr[99-(i+1)];
        arr[99-i] = i+2;
    }

    return 0;
}
