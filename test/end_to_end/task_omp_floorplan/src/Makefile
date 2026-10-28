all: clean prog

prog: floorplan.o
	$(CC) -o prog floorplan.o $(CFLAGS) -lm

floorplan.o:
	$(CC) -c -o floorplan.o floorplan.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name floorplan.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
