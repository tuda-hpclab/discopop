#include <stdio.h>
#include <stdlib.h>
int g_ok = 0;
int g_seen = 0;
int to_int(const char *token, int *ret) {
  char *endptr;
  if (token == NULL)
    return 0;
  *ret = (int)strtol(token, &endptr, 10);
  if ((endptr != token) && ((*endptr == ' ') || (*endptr == '\0')))
    return 1;
  else
    return 0;
}
void note(int v) { g_seen += v; }
int main() {
  const char *tokens[4] = {"12", "x", "7", "3 "};
  int s = 0;
  for (int i = 0; i < 4; ++i) {
    int v = 0;
    g_ok += to_int(tokens[i], &v);
    note(v);
    s += v;
  }
  printf("%d %d %d\n", s, g_ok, g_seen);
  return 0;
}
