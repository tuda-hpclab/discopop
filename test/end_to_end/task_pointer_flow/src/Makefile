all: clean prog

prog: ptr.o
	$(CC) -o prog ptr.o $(CFLAGS) -lm

ptr.o:
	$(CC) -c -o ptr.o ptr.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name ptr.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
