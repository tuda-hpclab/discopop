all: clean prog

prog: dep.o
	$(CC) -o prog dep.o $(CFLAGS) -lm

dep.o:
	$(CC) -c -o dep.o dep.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name dep.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
