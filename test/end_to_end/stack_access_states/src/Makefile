all: clean prog

prog:
	$(CXX) -g -O0 code.cpp -o prog

clean:
	rm -rf .discopop
	rm -f prog

veryclean: clean
	rm -f FileMapping.txt
