all: clean prog

prog: main.o other.o
	$(CXX) -o prog main.o other.o $(CXXFLAGS)

main.o:
	$(CXX) -c -o main.o main.cpp $(CXXFLAGS)

other.o:
	$(CXX) -c -o other.o other.cpp $(CXXFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name main.cpp -not -name other.cpp -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
