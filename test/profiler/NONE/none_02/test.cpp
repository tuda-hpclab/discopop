#include <cstdlib>

int main(){
    int arr[200];

    for(int i = 0; i < 100; ++i){
        arr[2*i] = i;
        arr[2*i+1] = i + 1;
    }

    return 0;
}
