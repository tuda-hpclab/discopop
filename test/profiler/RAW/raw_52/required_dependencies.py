from typing import List

# The point of this case is *when* the accesses happen, not how involved they are: the constructor
# of a global object runs before main, its destructor after main has returned. The runtime is
# brought up from .init_array and shut down from .fini_array so that both are covered; before that,
# the destructor's accesses were discarded because profiling had already been finalized at the
# return of main.
required_dependencies_list: List[str] = [
    # the constructor, running before main
    "1:9 RAW 1:8|i",
    # main reads in line 25 what that constructor wrote in line 9
    "1:25 RAW 1:9|GEPRESULT_global_table",
    # the destructor, running after main returned
    "1:14 RAW 1:14|i",
    "1:15 RAW 1:9|this1",
    "1:15 WAR 1:15|this1",
]
