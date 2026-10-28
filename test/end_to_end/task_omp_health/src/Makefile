all: clean prog

prog: health.o
	$(CC) -o prog health.o $(CFLAGS) -lm

health.o:
	$(CC) -c -o health.o health.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name health.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
