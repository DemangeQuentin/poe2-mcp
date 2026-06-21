"""
TinyMT32 Pseudo Random Number Generator - Path of Exile Modified Version

This module implements the TinyMT32 PRNG as used by Path of Exile for Timeless Jewel
seed calculations. PoE uses a MODIFIED version of TinyMT32 (RFC 8682) with:
- Different internal state size (5 elements instead of 4)
- Modified next_state function
- Different parameter usage for mat1, mat2, and tmat

The standard TinyMT32 parameters are:
- mat1 = 0x8f7011ee
- mat2 = 0xfc78ff1f
- tmat = 0x3793fdff

Reference: https://github.com/majorregal/TimelessEmulator
RFC 8682: https://datatracker.ietf.org/doc/html/rfc8682

Author: HivemindMinion
"""

from typing import List, Tuple


class TinyMT32:
    """
    Path of Exile's modified TinyMT32 pseudo random number generator.

    This implementation matches the game's PRNG used for Timeless Jewel calculations.
    The seed is composed of [passive_node_graph_id, jewel_seed] as two uint32 values.

    Key differences from standard TinyMT32 (RFC 8682):
    - 5-element state array (index 0 is a counter, 1-4 are the actual state)
    - Different initialization constants
    - Modified state transition logic
    - Parameters used as XOR masks rather than matrix elements

    Example usage:
        >>> rng = TinyMT32.from_poe_seed(node_id=12345, jewel_seed=1000)
        >>> value = rng.generate_uint32()
        >>> roll = rng.generate_range(0, 100)  # Roll 0-99
    """

    # PoE-specific initialization constants (differ from RFC 8682)
    INITIAL_STATE_0 = 0x40336050
    INITIAL_STATE_1 = 0xCFA3723C
    INITIAL_STATE_2 = 0x3CAC5F6F
    INITIAL_STATE_3 = 0x3793FDFF

    # Standard TinyMT32 parameters (RFC 8682)
    MAT1 = 0x8F7011EE
    MAT2 = 0xFC78FF1F
    TMAT = 0x3793FDFF

    # Mask for 31-bit operations
    MASK = 0x7FFFFFFF

    def __init__(self, seeds: List[int]):
        """
        Initialize the PRNG with a list of seed values.

        For PoE Timeless Jewel calculations, seeds should be:
        [passive_skill_graph_id, timeless_jewel_seed]

        Args:
            seeds: List of uint32 seed values to initialize the state
        """
        self._state = [0] * 5
        self._initialize(seeds)

    @classmethod
    def from_poe_seed(cls, node_id: int, jewel_seed: int) -> "TinyMT32":
        """
        Create a TinyMT32 instance using PoE's seed format.

        This is the standard way to seed the PRNG for Timeless Jewel calculations.
        The node_id is the passive skill's graph identifier, and jewel_seed is
        the Timeless Jewel's seed value.

        Note: For Elegant Hubris, the displayed seed (100-160000) must be divided
        by 20 to get the actual seed value (5-8000).

        Args:
            node_id: Passive skill graph identifier (uint32)
            jewel_seed: Timeless Jewel seed value (uint32)

        Returns:
            Initialized TinyMT32 instance
        """
        return cls([node_id & 0xFFFFFFFF, jewel_seed & 0xFFFFFFFF])

    @staticmethod
    def _manipulate_alpha(value: int) -> int:
        """
        Alpha manipulation function used during initialization.

        This is part of the state mixing process, using the constant 0x19660D
        which is derived from the LCG multiplier used in some MT implementations.

        Formula: ((value ^ (value >> 27)) * 0x19660D) & 0xFFFFFFFF
        """
        value = value & 0xFFFFFFFF
        return ((value ^ (value >> 27)) * 0x19660D) & 0xFFFFFFFF

    @staticmethod
    def _manipulate_bravo(value: int) -> int:
        """
        Bravo manipulation function used during initialization.

        Similar to alpha but with constant 0x5D588B65, which is related to
        the period-improvement constant in Mersenne Twister variants.

        Formula: ((value ^ (value >> 27)) * 0x5D588B65) & 0xFFFFFFFF
        """
        value = value & 0xFFFFFFFF
        return ((value ^ (value >> 27)) * 0x5D588B65) & 0xFFFFFFFF

    def _initialize(self, seeds: List[int]) -> None:
        """
        Initialize the internal state with seed values.

        The initialization process has four phases:
        1. Set initial state constants
        2. Mix in seed values using ManipulateAlpha
        3. Additional mixing rounds with ManipulateAlpha (5 rounds)
        4. Final mixing rounds with ManipulateBravo (4 rounds)
        5. Warm-up by calling next_state 8 times

        This ensures good distribution even with similar seed values.
        """
        # Phase 1: Initialize state with constants
        # state[0] is a counter, state[1-4] hold the actual PRNG state
        self._state = [
            0,
            self.INITIAL_STATE_0,
            self.INITIAL_STATE_1,
            self.INITIAL_STATE_2,
            self.INITIAL_STATE_3,
        ]

        index = 1

        # Phase 2: Mix in seed values
        for i, seed in enumerate(seeds):
            seed = seed & 0xFFFFFFFF

            # XOR three state positions and apply alpha manipulation
            round_state = self._manipulate_alpha(
                self._state[(index % 4) + 1]
                ^ self._state[((index + 1) % 4) + 1]
                ^ self._state[(((index + 4) - 1) % 4) + 1]
            )

            self._state[((index + 1) % 4) + 1] = (
                self._state[((index + 1) % 4) + 1] + round_state
            ) & 0xFFFFFFFF

            round_state = (round_state + seed + index) & 0xFFFFFFFF

            self._state[(((index + 1) + 1) % 4) + 1] = (
                self._state[(((index + 1) + 1) % 4) + 1] + round_state
            ) & 0xFFFFFFFF
            self._state[(index % 4) + 1] = round_state

            index = (index + 1) % 4

        # Phase 3: Additional alpha mixing (5 rounds)
        for i in range(5):
            round_state = self._manipulate_alpha(
                self._state[(index % 4) + 1]
                ^ self._state[((index + 1) % 4) + 1]
                ^ self._state[(((index + 4) - 1) % 4) + 1]
            )

            self._state[((index + 1) % 4) + 1] = (
                self._state[((index + 1) % 4) + 1] + round_state
            ) & 0xFFFFFFFF

            round_state = (round_state + index) & 0xFFFFFFFF

            self._state[(((index + 1) + 1) % 4) + 1] = (
                self._state[(((index + 1) + 1) % 4) + 1] + round_state
            ) & 0xFFFFFFFF
            self._state[(index % 4) + 1] = round_state

            index = (index + 1) % 4

        # Phase 4: Bravo mixing with XOR operations (4 rounds)
        for i in range(4):
            round_state = self._manipulate_bravo(
                (
                    self._state[(index % 4) + 1]
                    + self._state[((index + 1) % 4) + 1]
                    + self._state[(((index + 4) - 1) % 4) + 1]
                )
                & 0xFFFFFFFF
            )

            self._state[((index + 1) % 4) + 1] ^= round_state

            round_state = (round_state - index) & 0xFFFFFFFF

            self._state[(((index + 1) + 1) % 4) + 1] ^= round_state
            self._state[(index % 4) + 1] = round_state

            index = (index + 1) % 4

        # Phase 5: Warm-up with 8 state transitions
        for _ in range(8):
            self.next_state()

    def next_state(self) -> None:
        """
        Advance the internal state by one step.

        This is the core state transition function, modified from RFC 8682.
        The algorithm performs bit manipulations and conditionally XORs with
        MAT1 and MAT2 based on the least significant bit of the result.

        State transition logic:
        1. Compute intermediate values a and b from current state
        2. Apply left shift to a, right shift and XOR to b
        3. Shift state values left (1->2->3->4)
        4. Conditionally XOR with MAT1/MAT2 based on b's LSB
        5. Increment the counter
        """
        # Extract current state values
        a = self._state[4]
        # Mask state[1] to 31 bits, XOR with state[2] and state[3]
        b = ((self._state[1] & self.MASK) ^ self._state[2]) ^ self._state[3]

        # Apply shifts and XOR
        a = (a ^ (a << 1)) & 0xFFFFFFFF
        b = (b ^ (b >> 1) ^ a) & 0xFFFFFFFF

        # Shift state values
        self._state[1] = self._state[2]
        self._state[2] = self._state[3]
        self._state[3] = (a ^ (b << 10)) & 0xFFFFFFFF
        self._state[4] = b

        # Conditional XOR with MAT1 and MAT2 based on LSB of b
        # This is PoE's modification - they use a clever bit trick:
        # -1 (signed) = 0xFFFFFFFF, so -(b & 1) gives either 0 or 0xFFFFFFFF
        if b & 1:
            self._state[2] ^= self.MAT1
            self._state[3] ^= self.MAT2

        # Increment counter
        self._state[0] = (self._state[0] + 1) & 0xFFFFFFFF

    def _temper(self) -> int:
        """
        Apply the tempering transformation to produce output.

        Tempering improves the statistical properties of the output by
        mixing multiple state values together with conditional XOR.

        Returns:
            Tempered uint32 value
        """
        a = self._state[4]
        b = (self._state[1] + (self._state[3] >> 8)) & 0xFFFFFFFF

        a ^= b

        # Conditional XOR with TMAT based on LSB of b
        if b & 1:
            a ^= self.TMAT

        return a & 0xFFFFFFFF

    def generate_uint32(self) -> int:
        """
        Generate the next random uint32 value.

        This advances the state and returns a tempered 32-bit value.

        Returns:
            Random uint32 in range [0, 2^32 - 1]
        """
        self.next_state()
        return self._temper()

    def generate_float(self) -> float:
        """
        Generate a random float in the range [0, 1).

        Returns:
            Random float in range [0.0, 1.0)
        """
        return self.generate_uint32() / 0x100000000

    def generate_range(self, exclusive_max: int) -> int:
        """
        Generate a random value in range [0, exclusive_max).

        This uses rejection sampling to ensure uniform distribution
        across the requested range, avoiding modulo bias.

        This matches PoE's Generate(uint exclusiveMaximumValue) method.

        Args:
            exclusive_max: Upper bound (exclusive)

        Returns:
            Random value in range [0, exclusive_max - 1]
        """
        if exclusive_max <= 0:
            return 0
        if exclusive_max == 1:
            return 0

        max_value = exclusive_max - 1
        round_state = 0
        value = 0

        # Rejection sampling loop
        while True:
            # Build up bits until round_state >= max_value
            while True:
                value = (self.generate_uint32() | (2 * ((value << 31) & 0xFFFFFFFF))) & 0xFFFFFFFF
                round_state = (0xFFFFFFFF | (2 * ((round_state << 31) & 0xFFFFFFFF))) & 0xFFFFFFFF
                if round_state >= max_value:
                    break

            # Check if we need to reject this sample
            if not (
                (value // exclusive_max >= round_state)
                and (round_state % exclusive_max != max_value)
            ):
                break

        return value % exclusive_max

    def generate_range_inclusive(self, min_value: int, max_value: int) -> int:
        """
        Generate a random value in range [min_value, max_value].

        This matches PoE's Generate(uint minimumValue, uint maximumValue) method.

        Args:
            min_value: Lower bound (inclusive)
            max_value: Upper bound (inclusive)

        Returns:
            Random value in range [min_value, max_value]
        """
        # Handle the signed/unsigned conversion PoE does
        a = (min_value + 0x80000000) & 0xFFFFFFFF
        b = (max_value + 0x80000000) & 0xFFFFFFFF

        if min_value >= 0x80000000:
            a = (min_value + 0x80000000) & 0xFFFFFFFF

        if max_value >= 0x80000000:
            b = (max_value + 0x80000000) & 0xFFFFFFFF

        roll = self.generate_range(((b - a) & 0xFFFFFFFF) + 1)

        return (roll + a + 0x80000000) & 0xFFFFFFFF

    def get_state(self) -> Tuple[int, int, int, int, int]:
        """
        Get the current internal state for debugging/testing.

        Returns:
            Tuple of (counter, state1, state2, state3, state4)
        """
        return tuple(self._state)

    def __repr__(self) -> str:
        return f"TinyMT32(state={self._state})"


def generate_poe_seed(node_id: int, jewel_seed: int) -> List[int]:
    """
    Generate the seed array for PoE's Timeless Jewel PRNG.

    In Path of Exile, the PRNG seed for Timeless Jewel calculations is composed
    of two uint32 values: the passive skill's graph identifier and the jewel's seed.

    Note for Elegant Hubris:
    - Displayed seed range: 100 - 160,000
    - Actual seed range: 5 - 8,000 (displayed / 20)

    Args:
        node_id: Passive skill graph identifier
        jewel_seed: Timeless Jewel seed value

    Returns:
        List of [node_id, jewel_seed] as uint32 values
    """
    return [node_id & 0xFFFFFFFF, jewel_seed & 0xFFFFFFFF]


def create_timeless_rng(node_id: int, jewel_seed: int) -> TinyMT32:
    """
    Convenience function to create a TinyMT32 instance for Timeless Jewel calculations.

    This is the standard entry point for calculating Timeless Jewel modifications.

    Example:
        >>> rng = create_timeless_rng(node_id=12345, jewel_seed=1000)
        >>> replacement_roll = rng.generate_range(100)  # Roll 0-99

    Args:
        node_id: Passive skill graph identifier
        jewel_seed: Timeless Jewel seed value

    Returns:
        Initialized TinyMT32 instance
    """
    return TinyMT32.from_poe_seed(node_id, jewel_seed)


# Test vectors for validation
# These can be used to verify the implementation matches PoE's behavior
TEST_VECTORS = [
    # (node_id, jewel_seed, expected_first_values)
    # TODO: Add verified test vectors from in-game testing
]


if __name__ == "__main__":
    # Basic demonstration
    print("TinyMT32 PRNG - Path of Exile Modified Version")
    print("=" * 50)

    # Create RNG with sample seed
    rng = TinyMT32.from_poe_seed(node_id=12345, jewel_seed=1000)

    print(f"\nInitial state: {rng.get_state()}")
    print("\nFirst 10 random uint32 values:")
    for i in range(10):
        value = rng.generate_uint32()
        print(f"  {i+1}: {value:>10} (0x{value:08X})")

    # Reset and show range generation
    rng2 = TinyMT32.from_poe_seed(node_id=12345, jewel_seed=1000)
    print("\nFirst 10 values in range [0, 100):")
    for i in range(10):
        value = rng2.generate_range(100)
        print(f"  {i+1}: {value}")
