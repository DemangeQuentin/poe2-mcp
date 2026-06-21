"""
Jewel Radius Calculator for Path of Exile 2

This module calculates which passive nodes fall within a jewel socket's radius.
Used for planning jewel placement and analyzing threshold jewel effects.

Jewel Radius Reference (from passivejewelradii.datc64):
- Small: 800 units
- Medium: 1000 units
- Large: 1075 units
- Very Large: 1500 units

Author: Claude (HivemindMinion)
Date: 2025-01-16
"""

import json
import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Configure logging
logger = logging.getLogger(__name__)


class JewelRadiusSize(Enum):
    """Jewel radius sizes and their unit values."""

    SMALL = 800
    MEDIUM = 1000
    LARGE = 1075
    VERY_LARGE = 1500

    @classmethod
    def from_name(cls, name: str) -> "JewelRadiusSize":
        """Get radius size from name string."""
        name_map = {
            "small": cls.SMALL,
            "medium": cls.MEDIUM,
            "large": cls.LARGE,
            "very large": cls.VERY_LARGE,
            "very_large": cls.VERY_LARGE,
            "verylarge": cls.VERY_LARGE,
        }
        return name_map.get(name.lower(), cls.MEDIUM)


@dataclass
class JewelSocket:
    """
    Represents a jewel socket node on the passive tree.

    Attributes:
        node_id: The psg_id of the socket node
        x: X coordinate on the passive tree
        y: Y coordinate on the passive tree
        name: Node name (typically "Jewel Socket")
        group_id: The group this socket belongs to
    """

    node_id: int
    x: float
    y: float
    name: str = "Jewel Socket"
    group_id: Optional[int] = None

    def __repr__(self) -> str:
        return f"JewelSocket(id={self.node_id}, x={self.x:.1f}, y={self.y:.1f})"


@dataclass
class AffectedNode:
    """
    Represents a passive node within a jewel's radius.

    Attributes:
        node_id: The psg_id of the affected node
        name: Node name
        distance: Distance from the jewel socket in tree units
        is_notable: Whether this is a notable passive
        is_keystone: Whether this is a keystone passive
        stats: List of stat descriptions on this node
        x: X coordinate
        y: Y coordinate
    """

    node_id: int
    name: str
    distance: float
    is_notable: bool = False
    is_keystone: bool = False
    stats: List[str] = field(default_factory=list)
    x: float = 0.0
    y: float = 0.0

    def __repr__(self) -> str:
        node_type = "Keystone" if self.is_keystone else ("Notable" if self.is_notable else "Small")
        return f"AffectedNode({self.name}, {node_type}, dist={self.distance:.1f})"


@dataclass
class RadiusAnalysis:
    """
    Results of analyzing nodes within a jewel socket's radius.

    Attributes:
        socket: The jewel socket being analyzed
        radius: The radius used for analysis
        radius_name: Human-readable radius name
        affected_nodes: List of all nodes within radius
        keystones: Count of keystone nodes
        notables: Count of notable nodes
        small_passives: Count of small passive nodes
        notable_names: List of notable node names
        keystone_names: List of keystone node names
    """

    socket: JewelSocket
    radius: float
    radius_name: str
    affected_nodes: List[AffectedNode]
    keystones: int = 0
    notables: int = 0
    small_passives: int = 0
    notable_names: List[str] = field(default_factory=list)
    keystone_names: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Calculate counts from affected nodes."""
        if self.affected_nodes and self.keystones == 0 and self.notables == 0:
            self._calculate_counts()

    def _calculate_counts(self) -> None:
        """Calculate node type counts from affected_nodes list."""
        self.keystones = sum(1 for n in self.affected_nodes if n.is_keystone)
        self.notables = sum(1 for n in self.affected_nodes if n.is_notable and not n.is_keystone)
        self.small_passives = len(self.affected_nodes) - self.keystones - self.notables

        self.keystone_names = [n.name for n in self.affected_nodes if n.is_keystone and n.name]
        self.notable_names = [
            n.name for n in self.affected_nodes if n.is_notable and not n.is_keystone and n.name
        ]


def euclidean_distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """
    Calculate Euclidean distance between two points.

    Args:
        x1: X coordinate of first point
        y1: Y coordinate of first point
        x2: X coordinate of second point
        y2: Y coordinate of second point

    Returns:
        Distance between the two points
    """
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)


def load_passive_tree(file_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load passive tree data from JSON file.

    Args:
        file_path: Path to JSON file. Defaults to data/psg_passive_nodes.json

    Returns:
        Dictionary of node_id -> node data
    """
    if file_path is None:
        # Default path relative to project root
        file_path = Path(__file__).parent.parent.parent / "data" / "psg_passive_nodes.json"

    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_jewel_sockets(tree_data: Dict[str, Any]) -> List[JewelSocket]:
    """
    Find all jewel socket nodes in the passive tree.

    Args:
        tree_data: Dictionary of node_id -> node data from psg_passive_nodes.json

    Returns:
        List of JewelSocket objects
    """
    sockets = []

    for node_id, node in tree_data.items():
        name = node.get("name", "")
        if name == "Jewel Socket":
            socket = JewelSocket(
                node_id=int(node_id),
                x=node.get("x", 0.0),
                y=node.get("y", 0.0),
                name=name,
                group_id=node.get("group_id"),
            )
            sockets.append(socket)

    # Sort by node_id for consistent ordering
    sockets.sort(key=lambda s: s.node_id)
    return sockets


def get_nodes_in_radius(
    tree_data: Dict[str, Any], socket_id: int, radius: float = 1500.0, exclude_socket: bool = True
) -> List[AffectedNode]:
    """
    Get all passive nodes within a specified radius of a jewel socket.

    Args:
        tree_data: Dictionary of node_id -> node data
        socket_id: The psg_id of the jewel socket
        radius: Radius in tree units (default: 1500 for Very Large)
        exclude_socket: Whether to exclude the socket itself from results

    Returns:
        List of AffectedNode objects sorted by distance

    Raises:
        ValueError: If socket_id is not found in tree_data
    """
    socket_key = str(socket_id)
    if socket_key not in tree_data:
        raise ValueError(f"Socket ID {socket_id} not found in passive tree data")

    socket_node = tree_data[socket_key]
    socket_x = socket_node.get("x", 0.0)
    socket_y = socket_node.get("y", 0.0)

    affected = []

    for node_id, node in tree_data.items():
        # Skip if same as socket
        if exclude_socket and node_id == socket_key:
            continue

        # Skip nodes without coordinates
        x = node.get("x")
        y = node.get("y")
        if x is None or y is None:
            continue

        # Skip ascendancy nodes (they're in separate tree space)
        if node.get("is_ascendancy", False):
            continue

        # Calculate distance
        dist = euclidean_distance(socket_x, socket_y, x, y)

        if dist <= radius:
            affected_node = AffectedNode(
                node_id=int(node_id),
                name=node.get("name", ""),
                distance=dist,
                is_notable=node.get("is_notable", False),
                is_keystone=node.get("is_keystone", False),
                stats=node.get("stats", []),
                x=x,
                y=y,
            )
            affected.append(affected_node)

    # Sort by distance
    affected.sort(key=lambda n: n.distance)
    return affected


def analyze_socket_radius(
    socket_id: int, radius: float = 1500.0, tree_data: Optional[Dict[str, Any]] = None
) -> RadiusAnalysis:
    """
    Analyze all nodes within a jewel socket's radius.

    Args:
        socket_id: The psg_id of the jewel socket
        radius: Radius in tree units (default: 1500 for Very Large)
        tree_data: Optional pre-loaded tree data. Loads from file if not provided.

    Returns:
        RadiusAnalysis with socket info, affected nodes, and counts
    """
    if tree_data is None:
        tree_data = load_passive_tree()

    socket_key = str(socket_id)
    if socket_key not in tree_data:
        raise ValueError(f"Socket ID {socket_id} not found in passive tree data")

    socket_node = tree_data[socket_key]
    socket = JewelSocket(
        node_id=socket_id,
        x=socket_node.get("x", 0.0),
        y=socket_node.get("y", 0.0),
        name=socket_node.get("name", "Jewel Socket"),
        group_id=socket_node.get("group_id"),
    )

    affected_nodes = get_nodes_in_radius(tree_data, socket_id, radius)

    # Determine radius name
    radius_name = "Custom"
    for size in JewelRadiusSize:
        if abs(radius - size.value) < 1:
            radius_name = size.name.replace("_", " ").title()
            break

    return RadiusAnalysis(
        socket=socket, radius=radius, radius_name=radius_name, affected_nodes=affected_nodes
    )


def analyze_all_sockets(
    radius: float = 1500.0, tree_data: Optional[Dict[str, Any]] = None
) -> List[RadiusAnalysis]:
    """
    Analyze all jewel sockets in the passive tree.

    Args:
        radius: Radius in tree units (default: 1500 for Very Large)
        tree_data: Optional pre-loaded tree data

    Returns:
        List of RadiusAnalysis for each socket
    """
    if tree_data is None:
        tree_data = load_passive_tree()

    sockets = get_jewel_sockets(tree_data)
    analyses = []

    for socket in sockets:
        analysis = analyze_socket_radius(socket.node_id, radius, tree_data)
        analyses.append(analysis)

    return analyses


def find_best_socket_for_notables(
    target_notables: List[str], radius: float = 1500.0, tree_data: Optional[Dict[str, Any]] = None
) -> Optional[Tuple[JewelSocket, List[str]]]:
    """
    Find the jewel socket that covers the most target notables.

    Args:
        target_notables: List of notable names to search for
        radius: Radius in tree units
        tree_data: Optional pre-loaded tree data

    Returns:
        Tuple of (best socket, list of matched notable names) or None if no matches
    """
    if tree_data is None:
        tree_data = load_passive_tree()

    target_set = {n.lower() for n in target_notables}
    best_socket = None
    best_matches = []

    for analysis in analyze_all_sockets(radius, tree_data):
        matches = [
            n.name for n in analysis.affected_nodes if n.name and n.name.lower() in target_set
        ]
        if len(matches) > len(best_matches):
            best_matches = matches
            best_socket = analysis.socket

    if best_socket:
        return (best_socket, best_matches)
    return None


# For direct script execution
if __name__ == "__main__":
    # Quick test
    tree_data = load_passive_tree()
    print(f"Loaded {len(tree_data)} passive nodes")

    sockets = get_jewel_sockets(tree_data)
    print(f"Found {len(sockets)} jewel sockets")

    # Test first socket with Very Large radius
    if sockets:
        analysis = analyze_socket_radius(sockets[0].node_id, tree_data=tree_data)
        print(f"\nSocket {analysis.socket.node_id}:")
        print(f"  Nodes in radius: {len(analysis.affected_nodes)}")
        print(f"  Keystones: {analysis.keystones}")
        print(f"  Notables: {analysis.notables}")
        print(f"  Small passives: {analysis.small_passives}")
