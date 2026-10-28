all: clean prog

prog: waw.o
	$(CC) -o prog waw.o $(CFLAGS) -lm

waw.o:
	$(CC) -c -o waw.o waw.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name waw.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
