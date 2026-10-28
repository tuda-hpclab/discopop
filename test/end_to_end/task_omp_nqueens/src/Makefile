all: clean prog

prog: nqueens.o
	$(CC) -o prog nqueens.o $(CFLAGS) -lm

nqueens.o:
	$(CC) -c -o nqueens.o nqueens.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name nqueens.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
