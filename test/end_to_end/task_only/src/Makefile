all: clean prog

prog: fib.o
	$(CC) -o prog fib.o $(CFLAGS) -lm

fib.o:
	$(CC) -c -o fib.o fib.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name fib.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
