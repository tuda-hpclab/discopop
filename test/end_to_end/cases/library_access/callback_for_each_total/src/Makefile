all: clean prog

prog: code.o
	$(CXX) -o prog code.o $(CXXFLAGS)

code.o:
	$(CXX) -c -S -emit-llvm -o code.ll code.cpp $(CXXFLAGS)
	rm -rf .discopop
	$(CXX) -c -o code.o code.cpp $(CXXFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name code.cpp -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
