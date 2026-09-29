/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#define _GNU_SOURCE

// temporary rtlib
#include <stdio.h>
#include "time.h"
#include <stdbool.h>
#include <sys/time.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>


// temporary data structures
unsigned long* time_flag = NULL;
long double* time_a = NULL;
long double* time_b = NULL;

struct timeval start1, end1;

extern inline void __hotspot_detection_init(){
    // prepare environment variables
    char const * tmp = getenv("DOT_DISCOPOP");
    if(tmp == NULL){
        // DOT_DISCOPOP needs to be initialized
        setenv("DOT_DISCOPOP", ".discopop", 1);
    }

    FILE *filePointer;
    int bufferLength = 255;
    char buffer[bufferLength]; /* not ISO 90 compatible */
    char cntChar[bufferLength];

    char envbuffer[255] = "";
    strcpy(envbuffer, getenv("DOT_DISCOPOP"));
    char buffer1[255] = "";
    strcat(buffer1, strcat(envbuffer, "/hotspot_detection/private/cs_id.txt"));
    filePointer = fopen(buffer1, "r");
    int cs_num = 1;  // offset by one to account for cs_ids starting with 1
    while (fgets(buffer, bufferLength, filePointer))
    {
        cs_num++;
    }
    fclose(filePointer);
    printf("cs_num: %d\n", cs_num-1);  // -1 to correct offset in display

    // dynamically allocate global arrays
    time_flag = (unsigned long *) malloc(sizeof(long) * cs_num);
    time_a = (long double *) malloc(sizeof(long double)*cs_num);
    time_b = (long double *) malloc(sizeof(long double)*cs_num);


    for(int i = 0; i < cs_num; i++){
        time_flag[i] = 0;
        time_a[i] = 0;
        time_b[i] = 0;
    }

}

/*
We use different runtime function for loops and functions to support potential
differences in the implemented function in the future.
*/

extern inline void __hotspot_detection_function_start(const long int id)
{
    if (time_flag[id] == 0)
    {
        gettimeofday(&start1, NULL);
        time_a[id] = start1.tv_sec + 1e-6 * start1.tv_usec;
        // time_a[id] = clock();
    }
    time_flag[id]++;
    return;
}

extern inline void __hotspot_detection_loop_entry(const long int id)
{
    if (time_flag[id] == 0)
    {
        gettimeofday(&start1, NULL);
        time_a[id] = start1.tv_sec + 1e-6 * start1.tv_usec;
        // time_a[id] = clock();
    }
    time_flag[id]++;
    return;
}

extern inline void __hotspot_detection_loop_body_start(const long int id)
{
 /*   if (time_flag[id] == 0)
    {
        gettimeofday(&start1, NULL);
        time_a[id] = start1.tv_sec + 1e-6 * start1.tv_usec;
        // time_a[id] = clock();
    }
    //time_flag[id]++;
    return;
*/
}

extern inline void __hotspot_detection_function_end(const long int id)
{
    time_flag[id]--;
    if (time_flag[id] == 0)
    {
        gettimeofday(&end1, NULL);
        time_b[id] = time_b[id] + (end1.tv_sec + 1e-6 * end1.tv_usec) - time_a[id];
        // time_b[id] = time_b[id] + clock() - time_a[id];
    }
    return;
}

extern inline void __hotspot_detection_loop_end(const long int id)
{
    time_flag[id]--;
    if (time_flag[id] == 0)
    {
        gettimeofday(&end1, NULL);
        time_b[id] = time_b[id] + (end1.tv_sec + 1e-6 * end1.tv_usec) - time_a[id];
        // time_b[id] = time_b[id] + clock() - time_a[id];
    }
    return;
}

void __hotspot_detection_printOut()
{
    FILE *filePointer;
    int bufferLength = 255;
    char buffer[bufferLength]; /* not ISO 90 compatible */
    char cntChar[bufferLength];
    char buffer1[255] = "";
    char envbuffer[255] = "";
    strcpy(envbuffer, getenv("DOT_DISCOPOP"));
    strcat(buffer1, strcat(envbuffer, "/hotspot_detection/private/cs_id.txt"));
    filePointer = fopen(buffer1, "r");
    int num = 0;
    while (fgets(buffer, bufferLength, filePointer))
    {
        num++;
    }
    // printf("%d", num);
    // printf("%s", buffer);
    fclose(filePointer);
    FILE *fptr;

    // determine filename for result storage
    char buffer2[255] = "";
    char envbuffer2[255] = "";
    strcpy(envbuffer2, getenv("DOT_DISCOPOP"));
    strcat(buffer2, strcat(envbuffer2, "/hotspot_detection/private/hotspot_result_"));

    const char* result_base_name = buffer2;
    const char* result_file_ending = ".txt";
    char unused_file_name[255] = "";
    int counter = 0;
    char* s_counter;

    while(true){
        // create file name
        if (asprintf(&s_counter, "%d", counter) == -1) {
            perror("asprintf");
        } else {
            // assemble the next filename to be checked
            strcat(strcat(strcpy(unused_file_name, result_base_name), s_counter), result_file_ending);
        }
        // check if file name already exists
        if(access(unused_file_name, F_OK) == 0){
            // file exists. increment counter.
            counter++;
        }
        else{
            // file does not exist yet. Use the identified filename to output the results.
            break;
        }
    }
    free(s_counter);

    fptr = fopen(unused_file_name, "w");
    // fprintf(fptr,"RUNTIME:\n");
    for (int i = 1; i <= num; i++)
    {
        // if (time_b[i] > 0){
        fprintf(fptr, "%d", i);

        // fprintf(fptr, " %Lf", (time_b[i])/ (long double)(CLOCKS_PER_SEC) );
        fprintf(fptr, " %Lf", time_b[i]);

        fprintf(fptr, "\n");
        //}
    }
    fclose(fptr);
    return;
}
