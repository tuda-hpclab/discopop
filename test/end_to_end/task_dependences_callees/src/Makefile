all: clean prog

prog: callees.o
	$(CC) -o prog callees.o $(CFLAGS) -lm

callees.o:
	$(CC) -c -o callees.o callees.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name callees.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
