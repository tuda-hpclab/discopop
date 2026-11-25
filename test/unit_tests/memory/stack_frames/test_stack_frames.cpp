#include <gtest/gtest.h>

#include <set>
#include <unordered_map>
#include <vector>

#include "memory/StackFrames.hpp"

using dp::StackFrames;

namespace {

// a frame [hi - size, hi), as the allocas of a function report it (stack frames grow downwards)
void EnterFrame(StackFrames& frames, ADDR hi, ADDR size) {
  frames.Push();
  frames.Register(hi - size, hi);
}

bool IsStackKey(ADDR key) { return (key & StackFrames::kStackKeyBit) != 0; }

}  // namespace

TEST(StackFramesTest, AddressesWithoutFramesAreKeptAsTheyAre) {
  StackFrames frames;
  EXPECT_EQ(frames.Key(0x1000), 0x1000);

  frames.Push();  // a function without allocas
  EXPECT_EQ(frames.Key(0x1000), 0x1000);
}

TEST(StackFramesTest, MemoryOutsideTheLiveFramesKeepsItsAddress) {
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);
  EXPECT_EQ(frames.Key(0x1000), 0x1000);  // heap
  EXPECT_EQ(frames.Key(0x8000), 0x8000);  // just above the frame
  EXPECT_EQ(frames.Key(0x7eff), 0x7eff);  // just below the frame
  EXPECT_TRUE(IsStackKey(frames.Key(0x7f00)));
  EXPECT_TRUE(IsStackKey(frames.Key(0x7fff)));
}

TEST(StackFramesTest, TheSameAddressInTwoFrameInstancesHasTwoKeys) {
  // two callees of the same function, one after the other, occupy the same stack memory
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);  // caller
  EnterFrame(frames, 0x7f00, 0x40);   // first callee
  const ADDR first = frames.Key(0x7ef0);
  frames.Pop();
  EnterFrame(frames, 0x7f00, 0x40);  // second callee
  const ADDR second = frames.Key(0x7ef0);
  frames.Pop();

  EXPECT_TRUE(IsStackKey(first));
  EXPECT_TRUE(IsStackKey(second));
  EXPECT_NE(first, second);
}

TEST(StackFramesTest, AnAddressKeepsItsKeyForTheLifetimeOfItsFrame) {
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);
  const ADDR before = frames.Key(0x7f80);

  EnterFrame(frames, 0x7f00, 0x40);  // a callee accesses the caller's variable through a pointer
  EXPECT_EQ(frames.Key(0x7f80), before);
  frames.Pop();

  frames.Register(0x7e00, 0x7f00);  // a variable size alloca extends the frame downwards
  EXPECT_EQ(frames.Key(0x7f80), before);
  EXPECT_TRUE(IsStackKey(frames.Key(0x7e10)));
  EXPECT_NE(frames.Key(0x7e10), before);
}

TEST(StackFramesTest, DifferentAddressesOfAFrameHaveDifferentKeys) {
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);
  EXPECT_NE(frames.Key(0x7f00), frames.Key(0x7f01));
  EXPECT_NE(frames.Key(0x7f00), frames.Key(0x7fff));
}

TEST(StackFramesTest, PoppingMoreFramesThanWerePushedIsIgnored) {
  StackFrames frames;
  frames.Pop();
  EXPECT_EQ(frames.Depth(), 0U);
  EnterFrame(frames, 0x8000, 0x100);
  frames.Pop();
  frames.Pop();
  EXPECT_EQ(frames.Depth(), 0U);
  EXPECT_EQ(frames.Key(0x7f80), 0x7f80);
}

TEST(StackFramesTest, AFrameTooLargeForAKeyKeepsItsAddresses) {
  StackFrames frames;
  const ADDR hi = ADDR{1} << 40;
  EnterFrame(frames, hi, StackFrames::kMaxOffset + 2);
  EXPECT_TRUE(IsStackKey(frames.Key(hi - 1)));
  EXPECT_EQ(frames.Key(hi - StackFrames::kMaxOffset - 2), hi - StackFrames::kMaxOffset - 2);
}

TEST(StackFramesTest, TheSameVariableOfConsecutiveFramesDiffersInTheLowBits) {
  // the shadow maps choose their bucket by the low bits of a key: the same variable of many frame instances must not
  // share them, or every lookup probes along all of them
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);
  std::set<ADDR> low_bits;
  for (int call = 0; call < 1000; call++) {
    EnterFrame(frames, 0x7f00, 0x40);
    low_bits.insert(frames.Key(0x7ef0) & 0xFFF);
    frames.Pop();
  }
  EXPECT_GT(low_bits.size(), 900U);
}

TEST(StackFramesTest, TheKeysOfEndedFramesAreErased) {
  StackFrames frames;
  EnterFrame(frames, 0x8000, 0x100);  // stays live
  std::unordered_map<ADDR, int> shadow;
  const ADDR outer = frames.Key(0x7f80);
  shadow[outer] = 1;
  shadow[0x1000] = 2;  // heap

  EnterFrame(frames, 0x7f00, 0x40);  // ends before the snapshot
  const ADDR ended = frames.Key(0x7ef0);
  shadow[ended] = 3;
  frames.Pop();

  EnterFrame(frames, 0x7f00, 0x40);  // live at the snapshot
  const ADDR inner = frames.Key(0x7ef0);
  shadow[inner] = 4;

  std::vector<std::uint64_t> live;
  frames.LiveIds(live);
  ASSERT_EQ(live.size(), 2U);
  EXPECT_LT(live[0], live[1]);

  EXPECT_EQ(StackFrames::EraseKeysOfEndedFrames(shadow, live), 1U);
  EXPECT_EQ(shadow.count(ended), 0U);
  EXPECT_EQ(shadow.count(outer), 1U);
  EXPECT_EQ(shadow.count(inner), 1U);
  EXPECT_EQ(shadow.count(0x1000), 1U);
}
