#include <gtest/gtest.h>

#include "../../../../profiler/rtlib/runtimeFunctionsGlobals.hpp"
#include "../../../../profiler/rtlib/runtimeFunctionsTypes.hpp"
#include "../../../../profiler/rtlib/runtimeFunctions.hpp"

using namespace __dp;

class AccessQueueIntegrationTest : public ::testing::Test {
    void SetUp() override{
        __dp::allDeps = new __dp::depMap();
        __dp::mainThread_AccessInfoBuffer = __dp::firstAccessQueueChunkBuffer.get_prepared_chunk(FIRST_ACCESS_QUEUE_SIZES);
        __dp::initParallelization();
    }

    void TearDown() override {
        if(!(finalizeParallelizationCalled)){
            finalizeParallelization();
        }
        delete __dp::allDeps;
    }
};

void printAllDeps(){
    std::cout << "allDeps:" << std::endl;
    for(auto pair : *allDeps){
        std::cout << "LID: " << pair.first << std::endl;
        for(auto dep: *(pair.second)){
            std::cout << "--> ";
            switch(dep.type){
                case(RAW):
                    std::cout << "RAW ";
                    break;
                case (WAR):
                    std::cout << "WAR ";
                    break;
                case (WAW):
                    std::cout << "WAW ";
                    break;
                case (INIT):
                    std::cout << "INIT ";
                    break;
            }

            std::cout << "depOn: " << dep.depOn << " var: " << dep.var << std::endl;
        }
    }
    std::cout << std::endl;

}


void read(std::int64_t addr, std::int64_t lid){
    AccessInfo& current = mainThread_AccessInfoBuffer->get_next_AccessInfo_buffer();
    current.addr = addr;
    current.isRead = true;
    current.lid = lid;
    current.skip = false;
    current.var = "dummy";
}

void write(std::int64_t addr, std::int64_t lid){
    AccessInfo& current = mainThread_AccessInfoBuffer->get_next_AccessInfo_buffer();
    current.addr = addr;
    current.isRead = false;
    current.lid = lid;
    current.skip = false;
    current.var = "dummy";
}

void clear(std::int64_t addr){
    AccessInfo& current = mainThread_AccessInfoBuffer->get_next_AccessInfo_buffer();
    current.addr = addr;
    current.isRead = true;
    current.lid = 1;
    current.skip = true;
    current.var = "dummy";

    AccessInfo& current_1 = mainThread_AccessInfoBuffer->get_next_AccessInfo_buffer();
    current_1.addr = addr;
    current_1.isRead = false;
    current_1.lid = 1;
    current_1.skip = true;
    current_1.var = "dummy";
}

void push(){
    firstAccessQueue.push(mainThread_AccessInfoBuffer);
    mainThread_AccessInfoBuffer = firstAccessQueueChunkBuffer.get_prepared_chunk(10);
}

void check_lid_deps(LID lid, int expected_INIT, int expected_RAW, int expected_WAR, int expected_WAW){
    bool lid_contained = false;
    auto got = allDeps->find (lid);
    if ( got != allDeps->end() ){
        lid_contained = true;
    }

    if(!lid_contained){
        printAllDeps();
    }

    ASSERT_TRUE(lid_contained);
    int expected_size = expected_INIT + expected_RAW + expected_WAR + expected_WAW;
    ASSERT_EQ(((*allDeps)[lid])->size(), expected_size);
    int count_INIT = 0, count_RAW = 0, count_WAR = 0, count_WAW = 0;
    for(Dep elem: *((*allDeps)[lid])){
        switch(elem.type){
            case(INIT):
                count_INIT++;
                break;
            case(RAW):
                count_RAW++;
                break;
            case(WAR):
                count_WAR++;
                break;
            case(WAW):
                count_WAW++;
                break;
        }
    }
    ASSERT_EQ(count_INIT, expected_INIT);
    ASSERT_EQ(count_RAW, expected_RAW);
    ASSERT_EQ(count_WAR, expected_WAR);
    ASSERT_EQ(count_WAW, expected_WAW);
}

void check_registered_lids(int expected_lids){
    ASSERT_EQ(allDeps->size(), expected_lids);
}


// test detected dependencies
TEST_F(AccessQueueIntegrationTest, testSetupAndTeardown) {
}

TEST_F(AccessQueueIntegrationTest, checkEnvironment) {
    read(42, 1337);
    push();
}

TEST_F(AccessQueueIntegrationTest, NoDep_1) {
    ASSERT_EQ(allDeps->size(), 0);
    finalizeParallelization();
    ASSERT_EQ(allDeps->size(), 0);
}

TEST_F(AccessQueueIntegrationTest, R) {
    read(42, 1337);
    ASSERT_EQ(allDeps->size(), 0);
    finalizeParallelization();
    ASSERT_EQ(allDeps->size(), 0);
}

TEST_F(AccessQueueIntegrationTest, RP) {
    read(42, 1337);
    push();
    ASSERT_EQ(allDeps->size(), 0);
    finalizeParallelization();
    ASSERT_EQ(allDeps->size(), 0);
}

TEST_F(AccessQueueIntegrationTest, RPR) {
    read(42, 1337);
    push();
    read(42, 1337);

    ASSERT_EQ(allDeps->size(), 0);
    finalizeParallelization();
    ASSERT_EQ(allDeps->size(), 0);
}

TEST_F(AccessQueueIntegrationTest, W) {
    write(42, 1337);
    ASSERT_EQ(allDeps->size(), 0);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337,1,0,0,0);
}

TEST_F(AccessQueueIntegrationTest, WP) {
    write(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, WPW) {
    write(42, 1337);
    push();
    write(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 1);
}

TEST_F(AccessQueueIntegrationTest, RPW) {
    read(42, 1337);
    push();
    write(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, WPR) {
    write(42, 1337);
    push();
    read(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 1, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, RPRP) {
    read(42, 1337);
    push();
    read(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(0);
}

TEST_F(AccessQueueIntegrationTest, WPWP) {
    write(42, 1337);
    push();
    write(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 1);
}

TEST_F(AccessQueueIntegrationTest, RPWP) {
    read(42, 1337);
    push();
    write(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, WPRP) {
    write(42, 1337);
    push();
    read(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 1, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, PR) {
    push();
    read(42, 1337);
    finalizeParallelization();
    check_registered_lids(0);
}

TEST_F(AccessQueueIntegrationTest, PW) {
    push();
    write(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, PRP) {
    push();
    read(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(0);
}

TEST_F(AccessQueueIntegrationTest, PWP) {
    push();
    write(42, 1337);
    push();
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, PRW) {
    push();
    read(42, 1337);
    write(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 0, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, PWR) {
    push();
    write(42, 1337);
    read(42, 1337);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1337, 1, 1, 0, 0);
}

TEST_F(AccessQueueIntegrationTest, RPRPR) {
    read(42, 1337);
    push();
    read(42, 1338);
    push();
    read(42, 1339);
    finalizeParallelization();
    check_registered_lids(0);
}

TEST_F(AccessQueueIntegrationTest, WPWPW) {
    write(42, 1337);
    push();
    write(42, 1338);
    push();
    write(42, 1339);
    finalizeParallelization();
    check_registered_lids(3);
    check_lid_deps(1337, 1, 0, 0, 0);
    check_lid_deps(1338, 0, 0, 0, 1);
    check_lid_deps(1339, 0, 0, 0, 1);
}

TEST_F(AccessQueueIntegrationTest, RPPPPR) {
    read(42, 1337);
    push();
    push();
    push();
    push();
    read(42, 1338);
    finalizeParallelization();
    check_registered_lids(0);
}

TEST_F(AccessQueueIntegrationTest, WPPPPW) {
    write(42, 1337);
    push();
    push();
    push();
    push();
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337, 1, 0,0,0);
    check_lid_deps(1338, 0, 0,0,1);
}

TEST_F(AccessQueueIntegrationTest, RPPPPW) {
    read(42, 1337);
    push();
    push();
    push();
    push();
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(1);
    check_lid_deps(1338, 1, 0,0,0);
}

TEST_F(AccessQueueIntegrationTest, WPPPPR) {
    write(42, 1337);
    push();
    push();
    push();
    push();
    read(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337,1,0,0,0);
    check_lid_deps(1338,0,1,0,0);
}

TEST_F(AccessQueueIntegrationTest, WCW) {
    write(42, 1337);
    clear(42);
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337,1,0,0,0);
    check_lid_deps(1338,1,0,0,0);
}

TEST_F(AccessQueueIntegrationTest, WPCW) {
    write(42, 1337);
    push();
    clear(42);
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337,1,0,0,0);
    check_lid_deps(1338,1,0,0,0);
}

TEST_F(AccessQueueIntegrationTest, WCPW) {
    write(42, 1337);
    clear(42);
    push();
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337,1,0,0,0);
    check_lid_deps(1338,1,0,0,0);
}

TEST_F(AccessQueueIntegrationTest, WPCPW) {
    write(42, 1337);
    push();
    clear(42);
    push();
    write(42, 1338);
    finalizeParallelization();
    check_registered_lids(2);
    check_lid_deps(1337,1,0,0,0);
    check_lid_deps(1338,1,0,0,0);
}
