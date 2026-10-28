all: clean prog

prog: loop.o
	$(CC) -o prog loop.o $(CFLAGS) -lm

loop.o:
	$(CC) -c -o loop.o loop.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name loop.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
