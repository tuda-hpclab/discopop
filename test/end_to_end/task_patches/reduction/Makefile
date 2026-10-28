all: clean prog

prog: red.o
	$(CC) -o prog red.o $(CFLAGS) -lm

red.o:
	$(CC) -c -o red.o red.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name red.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
