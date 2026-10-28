all: clean prog

prog: knapsack.o
	$(CC) -o prog knapsack.o $(CFLAGS) -lm

knapsack.o:
	$(CC) -c -o knapsack.o knapsack.c $(CFLAGS)

clean:
	rm -rf .discopop
	rm -rf src/.discopop
	find . -not -name knapsack.c -not -name Makefile -not -path **/FileMapping.txt -delete

veryclean: clean
	rm -f FileMapping.txt
