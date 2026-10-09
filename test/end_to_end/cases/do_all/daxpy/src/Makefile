all: clean prog

prog: daxpy.o
	$(CXX) -o prog daxpy.o $(CXXFLAGS)

daxpy.o:
	$(CXX) -c -o daxpy.o daxpy.cpp $(CXXFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name daxpy.cpp -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
