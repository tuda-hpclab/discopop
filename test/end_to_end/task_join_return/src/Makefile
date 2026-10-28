all: clean prog

prog: ret.o
	$(CC) -o prog ret.o $(CFLAGS) -lm

ret.o:
	$(CC) -c -o ret.o ret.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name ret.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
