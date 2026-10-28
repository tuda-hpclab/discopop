all: clean prog

prog: sort.o
	$(CC) -o prog sort.o $(CFLAGS) -lm

sort.o:
	$(CC) -c -o sort.o sort.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name sort.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
