all: clean prog

prog: code.o
	$(CXX) -o prog code.o $(CXXFLAGS) -lm

code.o:
	$(CXX) -c -S -emit-llvm -o code.ll code.cpp $(CXXFLAGS) -lm
	rm -rf .discopop
	$(CXX) -c -o code.o code.cpp $(CXXFLAGS) -lm

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name code.cpp -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
