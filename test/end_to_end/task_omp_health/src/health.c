#include <stdio.h>
#include <stdlib.h>

struct Village {
  struct Village *forward, *next, *back;
  int level, inside, assess, waiting, realloc_, population;
};

static int sim_level = 3;

static struct Village *build(int level, int id) {
  struct Village *v = calloc(1, sizeof(struct Village)), *inext = NULL;
  v->level = level;
  v->population = 10 + id % 5;
  for (int i = 0; level > 1 && i < 2; i++) {
    struct Village *c = build(level - 1, id * 2 + i);
    c->next = inext;
    c->back = v;
    inext = c;
  }
  v->forward = inext;
  return v;
}

static void check_patients_inside(struct Village *v) { v->inside += v->population / 4; }
static void check_patients_assess(struct Village *v) {
  v->assess += v->inside / 2;
  if (v->back != NULL) v->back->realloc_ += v->assess % 2; /* moves patients to the upper level hospital */
}
static void check_patients_waiting(struct Village *v) { v->waiting += v->assess + 1; }
static void check_patients_realloc(struct Village *v) { v->realloc_ += v->waiting; }
static void check_patients_population(struct Village *v) { v->population += v->realloc_ % 3; }

/* omp-tasks/health/health.c, variant IF_CUTOFF (sim_village_par, task with if clause) */
void sim_village_if(struct Village *village) {
  struct Village *vlist;
  if (village == NULL) return;
  vlist = village->forward;
  while (vlist) {
    sim_village_if(vlist);  // task: health.c:418
    vlist = vlist->next;
  }
  check_patients_inside(village);
  check_patients_assess(village);
  check_patients_waiting(village);
  // taskwait: health.c:432
  check_patients_realloc(village);
  check_patients_population(village);
}

/* omp-tasks/health/health.c, variant MANUAL_CUTOFF (task in the first branch of the cutoff test) */
void sim_village_manual(struct Village *village) {
  struct Village *vlist;
  if (village == NULL) return;
  vlist = village->forward;
  while (vlist) {
    sim_village_manual(vlist);  // task: health.c:456
    vlist = vlist->next;
  }
  check_patients_inside(village);
  check_patients_assess(village);
  check_patients_waiting(village);
  // taskwait: health.c:481
  check_patients_realloc(village);
  check_patients_population(village);
}

/* omp-tasks/health/health.c, default variant */
void sim_village_plain(struct Village *village) {
  struct Village *vlist;
  if (village == NULL) return;
  vlist = village->forward;
  while (vlist) {
    sim_village_plain(vlist);  // task: health.c:504
    vlist = vlist->next;
  }
  check_patients_inside(village);
  check_patients_assess(village);
  check_patients_waiting(village);
  // taskwait: health.c:518
  check_patients_realloc(village);
  check_patients_population(village);
}

int main() {
  struct Village *top = build(sim_level, 1);
  for (int t = 0; t < 3; t++) {
    sim_village_if(top);
    sim_village_manual(top);
    sim_village_plain(top);
  }
  printf("%d %d\n", top->population, top->waiting);
  return 0;
}
