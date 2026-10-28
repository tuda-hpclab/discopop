all: clean prog

prog: strassen.o
	$(CC) -o prog strassen.o $(CFLAGS) -lm

strassen.o:
	$(CC) -c -o strassen.o strassen.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name strassen.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
