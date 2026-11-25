# libstdc++ is project code here (DP_PROJECT_INCLUDE_DIRS): its instantiations, e.g. std::vector<unsigned>::resize,
# are instrumented, and the profiler's runtime uses the same ones. The pass compares the resolved paths, e.g.
# /usr/include/c++/13 for /usr/lib/gcc/x86_64-linux-gnu/13/../../../../include/c++/13.
STD_INCLUDE_DIR := /usr/include/c++

all: compile execute

compile:
	test -d "$(STD_INCLUDE_DIR)"
	DP_PROJECT_INCLUDE_DIRS="$(STD_INCLUDE_DIR)" discopop_cxx test.cpp -o instrumented.exe

execute:
	./instrumented.exe

clean:
	rm -rf .discopop
	rm -f instrumented.exe
