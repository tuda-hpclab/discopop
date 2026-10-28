all: clean prog

prog: uts.o
	$(CC) -o prog uts.o $(CFLAGS) -lm

uts.o:
	$(CC) -c -o uts.o uts.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name uts.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
