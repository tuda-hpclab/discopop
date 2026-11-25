#include <gtest/gtest.h>

#include <set>
#include <unordered_map>
#include <vector>

#include "memory/StackFrames.hpp"

using dp::StackFrames;

namespace {

// a frame [hi - size, hi), as the allocas of a function report it (stack frames grow downwards)
void EnterFrame(StackFrames &frames, ADDR hi, ADDR size) {
  frames.Push();
  frames.Register(hi - size, hi);
}

bool IsStackKey(ADDR key) { return (key & StackFrames::kStackKeyBit) != 0; }

// releases its buffer, which the runtime's instance never does
struct Frames : StackFrames {
  ~Frames() { Release(); }
};

} // namespace

TEST(StackFramesTest, AddressesWithoutFramesAreKeptAsTheyAre) {
  Frames frames;
  EXPECT_EQ(frames.Key(0x1000), 0x1000);

  frames.Push(); // a function without allocas
  EXPECT_EQ(frames.Key(0x1000), 0x1000);
}

TEST(StackFramesTest, MemoryOutsideTheLiveFramesKeepsItsAddress) {
  Frames frames;
  EnterFrame(frames, 0x8000, 0x100);
  EXPECT_EQ(frames.Key(0x1000), 0x1000); // heap
  EXPECT_EQ(frames.Key(0x8000), 0x8000); // just above the frame
  EXPECT_EQ(frames.Key(0x7eff), 0x7eff); // just below the frame
  EXPECT_TRUE(IsStackKey(frames.Key(0x7f00)));
  EXPECT_TRUE(IsStackKey(frames.Key(0x7fff)));
}

TEST(StackFramesTest, TheSameAddressInTwoFrameInstancesHasTwoKeys) {
  // two callees of the same function, one after the other, occupy the same stack memory
  Frames frames;
  EnterFrame(frames, 0x8000, 0x100); // caller
  EnterFrame(frames, 0x7f00, 0x40);  // first callee
  const ADDR first = frames.Key(0x7ef0);
  frames.Pop();
  EnterFrame(frames, 0x7f00, 0x40); // second callee
  const ADDR second = frames.Key(0x7ef0);
  frames.Pop();

  EXPECT_TRUE(IsStackKey(first));
  EXPECT_TRUE(IsStackKey(second));
  EXPECT_NE(first, second);
}

TEST(StackFramesTest, AnAddressKeepsItsKeyForTheLifetimeOfItsFrame) {
  Frames frames;
  EnterFrame(frames, 0x8000, 0x100);
  const ADDR before = frames.Key(0x7f80);

  EnterFrame(frames, 0x7f00, 0x40); // a callee accesses the caller's variable through a pointer
  EXPECT_EQ(frames.Key(0x7f80), before);
  frames.Pop();

  frames.Register(0x7e00, 0x7f00); // a variable size alloca extends the frame downwards
  EXPECT_EQ(frames.Key(0x7f80), before);
  EXPECT_TRUE(IsStackKey(frames.Key(0x7e10)));
  EXPECT_NE(frames.Key(0x7e10), before);
}

TEST(StackFramesTest, DifferentAddressesOfAFrameHaveDifferentKeys) {
  Frames frames;
  EnterFrame(frames, 0x8000, 0x100);
  EXPECT_NE(frames.Key(0x7f00), frames.Key(0x7f01));
  EXPECT_NE(frames.Key(0x7f00), frames.Key(0x7fff));
}

TEST(StackFramesTest, PoppingMoreFramesThanWerePushedIsIgnored) {
  Frames frames;
  frames.Pop();
  EXPECT_EQ(frames.Depth(), 0U);
  EnterFrame(frames, 0x8000, 0x100);
  frames.Pop();
  frames.Pop();
  EXPECT_EQ(frames.Depth(), 0U);
  EXPECT_EQ(frames.Key(0x7f80), 0x7f80);
}

TEST(StackFramesTest, AFrameTooLargeForAKeyKeepsItsAddresses) {
  Frames frames;
  const ADDR hi = ADDR{1} << 40;
  EnterFrame(frames, hi, StackFrames::kMaxOffset + 2);
  EXPECT_TRUE(IsStackKey(frames.Key(hi - 1)));
  EXPECT_EQ(frames.Key(hi - StackFrames::kMaxOffset - 2), hi - StackFrames::kMaxOffset - 2);
}

TEST(StackFramesTest, TheSameVariableOfConsecutiveFramesDiffersInTheLowBits) {
  // the shadow maps choose their bucket by the low bits of a key: the same variable of many frame instances must not
  // share them, or every lookup probes along all of them
  Frames frames;
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
  Frames frames;
  EnterFrame(frames, 0x8000, 0x100); // stays live
  std::unordered_map<ADDR, int> shadow;
  const ADDR outer = frames.Key(0x7f80);
  shadow[outer] = 1;
  shadow[0x1000] = 2; // heap

  EnterFrame(frames, 0x7f00, 0x40); // ends before the snapshot
  const ADDR ended = frames.Key(0x7ef0);
  shadow[ended] = 3;
  frames.Pop();

  EnterFrame(frames, 0x7f00, 0x40); // live at the snapshot
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

TEST(StackFramesTest, DeepCallChainsKeepTheirKeys) {
  // more frames than the initial capacity: the outer frames stay found after the buffer grew
  Frames frames;
  constexpr int kDepth = 1000;
  std::vector<ADDR> keys;
  for (int depth = 0; depth < kDepth; ++depth) {
    const ADDR hi = 0x7fff0000 - depth * 0x100;
    EnterFrame(frames, hi, 0x40);
    keys.push_back(frames.Key(hi - 8));
  }
  EXPECT_EQ(frames.Depth(), static_cast<std::size_t>(kDepth));
  for (int depth = 0; depth < kDepth; ++depth) {
    EXPECT_EQ(frames.Key(0x7fff0000 - depth * 0x100 - 8), keys[depth]);
  }
  EXPECT_EQ(std::set<ADDR>(keys.begin(), keys.end()).size(), keys.size());
  for (int depth = 0; depth < kDepth; ++depth) {
    frames.Pop();
  }
  EXPECT_EQ(frames.Depth(), 0u);
}

// Library code (DP_LIBRARY_DIRS) has no frames: its accesses are attributed to the last call of the innermost frame of
// project code, see StackFrames::LibraryAccessAttribution. probe stands for the frame of the callback, below all
// frames.
TEST(StackFramesTest, LibraryAccessesAreAttributedToTheCallOfTheInnermostFrame) {
  Frames frames;
  constexpr ADDR kProbe = 0x1000;
  EnterFrame(frames, 0x8000, 0x100);
  frames.SetCallInstruction(17);

  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, kProbe), 17);  // heap below the stack
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7f80, kProbe), 17); // the caller's own variables
  EXPECT_EQ(frames.LibraryAccessAttribution(0x9000, kProbe), 17); // above the frames

  frames.SetCallInstruction(23); // the next call of the same frame
  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, kProbe), 23);
}

TEST(StackFramesTest, LibraryAccessesWithoutAProjectCallAreDropped) {
  Frames frames;
  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, 0x1000), 0); // no frame: e.g. static initialization

  EnterFrame(frames, 0x8000, 0x100);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, 0x1000), 0); // no call yet
}

// the locals of library frames lie between the callback and the memory of the project frames; dead after the call,
// they must not depend on the locals of the library call before, which used the same addresses
TEST(StackFramesTest, LibraryAccessesToStackBelowTheProjectFramesAreDropped) {
  Frames frames;
  constexpr ADDR kProbe = 0x7000;
  EnterFrame(frames, 0x8000, 0x100);
  frames.SetCallInstruction(17);

  EXPECT_EQ(frames.LibraryAccessAttribution(0x7000, kProbe), 0);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7eff, kProbe), 0);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7f00, kProbe), 17); // the lowest alloca of the project frame
  EXPECT_EQ(frames.LibraryAccessAttribution(0x6fff, kProbe), 17); // below the callback: not on this stack
}

TEST(StackFramesTest, AVariableSizedAllocaOfTheProjectFrameIsNotLibraryStack) {
  Frames frames;
  constexpr ADDR kProbe = 0x7000;
  EnterFrame(frames, 0x8000, 0x100);
  frames.Register(0x7c00, 0x7d00); // alloca() / VLA, reported later, below the static allocas
  frames.SetCallInstruction(17);

  EXPECT_EQ(frames.LibraryAccessAttribution(0x7c80, kProbe), 17);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7bff, kProbe), 0);
}

// a callback from the library into project code (e.g. a comparator) pushes a frame with calls of its own; when it
// returns, the library code continues within the call of the frame below
TEST(StackFramesTest, ACallbackIntoProjectCodeHasItsOwnAttribution) {
  Frames frames;
  constexpr ADDR kProbe = 0x1000;
  EnterFrame(frames, 0x8000, 0x100);
  frames.SetCallInstruction(17);    // e.g. std::sort
  EnterFrame(frames, 0x7c00, 0x40); // the comparator, called by the library
  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, kProbe), 0);
  frames.SetCallInstruction(31); // the comparator calls into the library itself
  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, kProbe), 31);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7f80, kProbe), 31); // the outer project frame's memory
  frames.Pop();

  EXPECT_EQ(frames.LibraryAccessAttribution(0x200, kProbe), 17);
}

TEST(StackFramesTest, AFrameWithoutAllocasBoundsTheLibraryStackByTheOuterFrames) {
  Frames frames;
  constexpr ADDR kProbe = 0x7000;
  EnterFrame(frames, 0x8000, 0x100);
  frames.Push(); // a project function without allocas, below
  frames.SetCallInstruction(41);

  EXPECT_EQ(frames.LibraryAccessAttribution(0x7e00, kProbe), 0);
  EXPECT_EQ(frames.LibraryAccessAttribution(0x7f80, kProbe), 41);
}

// library accesses to a variable of project code are reported under its name, see StackFrames::VariableAt
TEST(StackFramesTest, TheVariablesOfTheLiveFramesAreFoundByAddress) {
  Frames frames;
  frames.Push();
  frames.Register(0x7ff0, 0x8000, "outer");
  frames.Register(0x7fe0, 0x7ff0, "it");
  frames.Push();
  frames.Register(0x7f00, 0x7f08, "inner");

  EXPECT_STREQ(frames.VariableAt(0x7ff8), "outer");
  EXPECT_STREQ(frames.VariableAt(0x7fe8), "it");
  EXPECT_STREQ(frames.VariableAt(0x7f04), "inner");
  EXPECT_EQ(frames.VariableAt(0x7f08), nullptr); // a gap between the variables
  EXPECT_EQ(frames.VariableAt(0x1000), nullptr); // heap

  frames.Pop();
  EXPECT_EQ(frames.VariableAt(0x7f04), nullptr); // the variables of an ended frame are gone
  frames.Push();
  frames.Register(0x7f00, 0x7f08, "next");
  EXPECT_STREQ(frames.VariableAt(0x7f04), "next");
  EXPECT_STREQ(frames.VariableAt(0x7fe8), "it");
}

TEST(StackFramesTest, ManyVariablesAreKept) {
  // more variables than the initial capacity
  Frames frames;
  frames.Push();
  static const char *const kName = "v";
  for (ADDR i = 0; i < 1000; ++i) {
    frames.Register(0x100000 - 8 * (i + 1), 0x100000 - 8 * i, kName);
  }
  EXPECT_EQ(frames.VariableAt(0x100000 - 8 * 999), kName);
}

// a variable sized alloca in a loop is registered again in every iteration: it replaces its entry
TEST(StackFramesTest, AVariableRegisteredAgainReplacesItsEntry) {
  Frames frames;
  frames.Push();
  frames.Register(0x7ff0, 0x8000, "static");
  for (int i = 0; i < 100; ++i) {
    frames.Register(0x7f00, 0x7f00 + 8 * (i % 4 + 1), i % 2 == 0 ? "even" : "odd");
  }
  EXPECT_STREQ(frames.VariableAt(0x7f00), "odd");
  EXPECT_STREQ(frames.VariableAt(0x7ff8), "static");
}
