all: compile execute

compile:
	discopop_cxx test.cpp -o instrumented.exe

execute:
	./instrumented.exe

clean:
	rm -rf .discopop
	rm -f instrumented.exe
