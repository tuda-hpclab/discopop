all: clean prog

prog: sparselu.o
	$(CC) -o prog sparselu.o $(CFLAGS) -lm

sparselu.o:
	$(CC) -c -o sparselu.o sparselu.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name sparselu.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
