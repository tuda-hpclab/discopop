#include <stdio.h>

#define MAXC 4

typedef struct {
  int height;
  unsigned state;
  int numChildren;
} Node;

unsigned spawn(unsigned parent, int i) {
  unsigned h = parent * 2654435761u + (unsigned)i * 40503u + 12345u;
  return h ^ (h >> 13);
}

int numChildren(Node *n) {
  if (n->height >= 4) return 0;
  return (int)(n->state % (MAXC + 1));
}

unsigned long long parTreeSearch(int depth, Node *parent, int nChildren) {
  Node n[MAXC], *nodePtr;
  int i;
  unsigned long long subtreesize = 1, partialCount[MAXC];

  for (i = 0; i < nChildren; i++) {
    nodePtr = &n[i];
    nodePtr->height = parent->height + 1;
    nodePtr->state = spawn(parent->state, i);
    nodePtr->numChildren = numChildren(nodePtr);
    // omp-tasks/uts/uts.c:209 (task, firstprivate(i, nodePtr), shared(partialCount))
    partialCount[i] = parTreeSearch(depth + 1, nodePtr, nodePtr->numChildren);
  }
  // omp-tasks/uts/uts.c:213 (taskwait)
  for (i = 0; i < nChildren; i++) {
    subtreesize += partialCount[i];
  }
  return subtreesize;
}

int main() {
  Node root;
  root.height = 0;
  root.state = 7;
  root.numChildren = 3;
  printf("%llu\n", parTreeSearch(0, &root, root.numChildren));
  return 0;
}
