all: clean prog

prog: last.o
	$(CC) -o prog last.o $(CFLAGS) -lm

last.o:
	$(CC) -c -o last.o last.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name last.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
