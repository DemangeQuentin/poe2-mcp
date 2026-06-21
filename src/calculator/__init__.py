"""
Calculator modules for Path of Exile 2 build optimization.

This package provides calculation tools including:
- TinyMT32 PRNG for Timeless Jewel seed calculations
- Jewel radius calculator for determining affected nodes
- Timeless seed mapper for Undying Hate transformations
"""

from .tinymt32 import TinyMT32, create_timeless_rng, generate_poe_seed
from .jewel_radius import (
    JewelRadiusSize,
    JewelSocket,
    AffectedNode,
    RadiusAnalysis,
    euclidean_distance,
    load_passive_tree,
    get_jewel_sockets,
    get_nodes_in_radius,
    analyze_socket_radius,
    analyze_all_sockets,
    find_best_socket_for_notables,
)
from .timeless_seed_mapper import (
    TimelessSeedMapper,
    TransformedNode,
    SeedAnalysis,
    analyze_undying_hate,
    ABYSS_LEADERS,
)

__all__ = [
    # TinyMT32 PRNG
    "TinyMT32",
    "create_timeless_rng",
    "generate_poe_seed",
    # Jewel radius
    "JewelRadiusSize",
    "JewelSocket",
    "AffectedNode",
    "RadiusAnalysis",
    "euclidean_distance",
    "load_passive_tree",
    "get_jewel_sockets",
    "get_nodes_in_radius",
    "analyze_socket_radius",
    "analyze_all_sockets",
    "find_best_socket_for_notables",
    # Timeless seed mapper
    "TimelessSeedMapper",
    "TransformedNode",
    "SeedAnalysis",
    "analyze_undying_hate",
    "ABYSS_LEADERS",
]
