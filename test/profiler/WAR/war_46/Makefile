all: compile execute

compile:
	discopop_cxx -O1 -c -o instrumented.ll -S -emit-llvm test.cpp
	rm -rf .discopop
	discopop_cxx test.cpp -o instrumented.exe

execute:
	./instrumented.exe

clean:
	rm -rf .discopop
	rm -f instrumented.exe
	rm -f instrumented.ll
