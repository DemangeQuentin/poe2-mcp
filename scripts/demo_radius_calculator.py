#!/usr/bin/env python
"""
Demo: Jewel Radius Calculator

Demonstrates the jewel radius calculator by analyzing all jewel sockets
in the PoE2 passive tree with "Very Large" radius (1500 units).

This shows which notables and keystones each socket can affect,
useful for planning Undying Hate and similar threshold jewels.

Usage:
    python scripts/demo_radius_calculator.py
    python scripts/demo_radius_calculator.py --radius 1000  # Medium radius
    python scripts/demo_radius_calculator.py --socket 2491  # Specific socket

Author: Claude (HivemindMinion)
Date: 2025-01-16
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.calculator.jewel_radius import (
    JewelRadiusSize,
    analyze_all_sockets,
    analyze_socket_radius,
    get_jewel_sockets,
    load_passive_tree,
)


def format_analysis(analysis) -> str:
    """Format a RadiusAnalysis for display."""
    lines = []

    # Header
    lines.append(
        f"Jewel Socket {analysis.socket.node_id} at ({analysis.socket.x:.1f}, {analysis.socket.y:.1f})"
    )
    lines.append(f"  Nodes in radius ({analysis.radius:.0f}): {len(analysis.affected_nodes)}")
    lines.append(f"  - Keystones: {analysis.keystones}")
    lines.append(f"  - Notables: {analysis.notables}")
    lines.append(f"  - Small passives: {analysis.small_passives}")

    # Keystone names (if any)
    if analysis.keystone_names:
        lines.append(f"  Keystone names: {analysis.keystone_names}")

    # Notable names
    if analysis.notable_names:
        lines.append(f"  Notable names: {analysis.notable_names}")
    else:
        lines.append("  Notable names: []")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze jewel socket radius coverage on PoE2 passive tree"
    )
    parser.add_argument(
        "--radius",
        type=float,
        default=1500.0,
        help="Radius in tree units (default: 1500 for Very Large)",
    )
    parser.add_argument(
        "--size",
        choices=["small", "medium", "large", "very_large"],
        help="Use predefined radius size instead of --radius",
    )
    parser.add_argument("--socket", type=int, help="Analyze only this specific socket ID")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show only summary statistics, not full notable lists",
    )

    args = parser.parse_args()

    # Determine radius
    if args.size:
        radius = JewelRadiusSize.from_name(args.size).value
    else:
        radius = args.radius

    # Load tree data once
    print("Loading passive tree data...")
    tree_data = load_passive_tree()
    print(f"Loaded {len(tree_data)} passive nodes")

    # Find sockets
    sockets = get_jewel_sockets(tree_data)
    print(f"Found {len(sockets)} jewel sockets\n")

    # Analyze
    if args.socket:
        # Single socket analysis
        if args.socket not in [s.node_id for s in sockets]:
            print(f"Error: Socket ID {args.socket} not found")
            print(f"Available sockets: {[s.node_id for s in sockets]}")
            return 1

        analysis = analyze_socket_radius(args.socket, radius, tree_data)
        print(format_analysis(analysis))
    else:
        # All sockets
        print(f"Analyzing all sockets with radius {radius} ({get_radius_name(radius)})...")
        print("=" * 70)

        analyses = analyze_all_sockets(radius, tree_data)

        for analysis in analyses:
            print()
            if args.summary:
                print(
                    f"Socket {analysis.socket.node_id}: "
                    f"{len(analysis.affected_nodes)} nodes "
                    f"({analysis.keystones}K/{analysis.notables}N/{analysis.small_passives}S)"
                )
            else:
                print(format_analysis(analysis))

        # Summary
        print()
        print("=" * 70)
        print("SUMMARY:")
        total_nodes = sum(len(a.affected_nodes) for a in analyses)
        total_notables = sum(a.notables for a in analyses)
        total_keystones = sum(a.keystones for a in analyses)
        print(f"  Total sockets analyzed: {len(analyses)}")
        print(f"  Average nodes per socket: {total_nodes / len(analyses):.1f}")
        print(f"  Average notables per socket: {total_notables / len(analyses):.1f}")
        print(f"  Total unique keystones in range: {total_keystones}")

        # Best sockets for notable coverage
        best = max(analyses, key=lambda a: a.notables)
        print(f"\n  Best socket for notables: {best.socket.node_id} ({best.notables} notables)")

    return 0


def get_radius_name(radius: float) -> str:
    """Get human-readable name for a radius value."""
    for size in JewelRadiusSize:
        if abs(radius - size.value) < 1:
            return size.name.replace("_", " ").title()
    return "Custom"


if __name__ == "__main__":
    sys.exit(main())
