// SPDX-License-Identifier: Apache-2.0
// CPU-only validation of the reconstructed source's listener contract.
#include "switchless_listener_contract.h"
#include <algorithm>
#include <cassert>
#include <cstdio>

static void valid(uint8_t gids[4][16], char roots[4][11]) {
  std::memset(gids, 0, 4 * 16);
  for (int i = 0; i < 4; ++i) {
    gids[i][10] = gids[i][11] = 0xff;
    gids[i][12] = 10; gids[i][13] = 100;
    gids[i][14] = uint8_t(224 + i / 2);
    gids[i][15] = uint8_t(1 + i % 2);
    std::memcpy(roots[i], i % 2 ? "pci0002:00" : "pci0000:00", 11);
  }
}

// Per-function layout: every PF on its own /24, two PFs per PCI root.
static void perFunction(uint8_t gids[4][16], char roots[4][11]) {
  valid(gids, roots);
  for (int i = 0; i < 4; ++i) { gids[i][14] = uint8_t(i); gids[i][15] = 1; }
}

int main() {
  // Device 2 must remain selected even when other devices sort before it.
  for (int selected = 0; selected < 4; ++selected) {
    for (int strict = 0; strict < 2; ++strict) {
      for (int extended = 0; extended < 2; ++extended) {
        const auto devices = switchlessListenerDevices(strict, extended, selected, 4);
        int published = 0;
        for (int i = devices.begin; i < devices.end; ++i) {
          assert(i >= 0 && i < 4);
          if (!strict && !extended) assert(i == selected);
          ++published;
        }
        assert(published == (strict || extended ? 4 : 1));
      }
    }
  }
  uint8_t gids[4][16], orderedGids[4][16];
  char roots[4][11], orderedRoots[4][11];
  valid(gids, roots);
  int order[] = {0, 1, 2, 3}, permutations = 0;
  do {
    for (int i = 0; i < 4; ++i) {
      std::memcpy(orderedGids[i], gids[order[i]], 16);
      std::memcpy(orderedRoots[i], roots[order[i]], 11);
    }
    assert(switchlessValidateListener(orderedGids, orderedRoots, 4, true) == nullptr);
    ++permutations;
  } while (std::next_permutation(order, order + 4));
  assert(permutations == 24);

  for (int count : {0, 1, 2, 3, 5}) {
    assert(switchlessValidateListener(gids, roots, count, true) != nullptr);
  }
  std::memcpy(orderedGids[0], gids[0], 16);
  std::memcpy(orderedGids[1], gids[2], 16);
  assert(switchlessValidateListener(orderedGids, roots, 2, false) == nullptr);
  std::memcpy(orderedGids[1], gids[1], 16);
  assert(switchlessValidateListener(orderedGids, roots, 2, false) != nullptr);

  std::memcpy(gids[3], gids[0], 16);
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][0] = 0x20;
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][12] = 224;
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][15] = 0;
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); gids[0][15] = 255;
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); std::memcpy(roots[1], roots[0], 11);
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); roots[0][0] = 0;
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); roots[0][10] = 'x';
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  valid(gids, roots); std::memcpy(roots[3], "pci0003:00", 11);
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  // Unrelated /24 cable networks can share the third octet. This caught
  // the original validator's implicit common /16 assumption.
  valid(gids, roots);
  for (int i = 0; i < 4; ++i) {
    gids[i][12] = uint8_t(i < 2 ? 10 : 172);
    gids[i][13] = uint8_t(i < 2 ? 33 : 16);
    gids[i][14] = 7;
  }
  assert(switchlessValidateListener(gids, roots, 4, true) == nullptr);
  for (int first : {0, 127, 224, 255}) {
    const auto saved = gids[0][12]; gids[0][12] = uint8_t(first);
    assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
    gids[0][12] = saved;
  }
  // Per-function /24 addressing (NVIDIA p0-to-p1 playbook style).
  perFunction(gids, roots);
  {
    int order2[] = {0, 1, 2, 3}, n = 0;
    do {
      for (int i = 0; i < 4; ++i) {
        std::memcpy(orderedGids[i], gids[order2[i]], 16);
        std::memcpy(orderedRoots[i], roots[order2[i]], 11);
      }
      assert(switchlessValidateListener(orderedGids, orderedRoots, 4, true) == nullptr);
      ++n;
    } while (std::next_permutation(order2, order2 + 4));
    assert(n == 24);
  }
  perFunction(gids, roots); gids[3][14] = gids[2][14];           // three subnets: refused
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  perFunction(gids, roots); std::memcpy(roots[1], roots[0], 11); // three PFs on one root
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  perFunction(gids, roots); std::memcpy(roots[3], "pci0003:00", 11); // third root
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  perFunction(gids, roots); std::memcpy(gids[3], gids[0], 16);    // duplicate GID
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  perFunction(gids, roots); gids[2][12] = 127;                     // loopback
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  // Per-cable layout with both PFs of one cable on the same root: refused.
  valid(gids, roots);
  std::memcpy(roots[0], "pci0000:00", 11); std::memcpy(roots[1], "pci0000:00", 11);
  std::memcpy(roots[2], "pci0002:00", 11); std::memcpy(roots[3], "pci0002:00", 11);
  assert(switchlessValidateListener(gids, roots, 4, true) != nullptr);
  // Two-PF mode with per-function addresses: two different /24s pass.
  perFunction(gids, roots);
  assert(switchlessValidateListener(gids, roots, 2, false) == nullptr);
  std::puts("listener contract: per-cable and per-function four-PF layouts (24 permutations each), two-PF and invalid cases passed");
}
