from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent

SCHEMA_PATH = ROOT / "canonical_graph_ir.schema.json"
ONTOLOGY_PATH = ROOT / "ontology.json"

DAG_EDGE_TYPES = {
    "EXTRACTED_FROM",
    "GENERATED_BY",
    "SUPERSEDES",
    "INVALIDATES",
    "DERIVES_FROM",
}


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(value, dict):
        raise TypeError(
            f"Expected JSON object: {path}"
        )

    return value


def ontology_values(
    ontology: dict[str, Any],
    section: str,
) -> set[str]:
    result: set[str] = set()

    for values in ontology[section].values():
        result.update(values)

    return result


def find_cycle(
    adjacency: dict[str, list[str]],
) -> list[str] | None:
    unseen = 0
    active = 1
    complete = 2

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = active
        stack.append(node)

        for target in adjacency.get(node, []):
            target_state = state.get(
                target,
                unseen,
            )

            if target_state == unseen:
                cycle = visit(target)

                if cycle is not None:
                    return cycle

            elif target_state == active:
                index = stack.index(target)

                return stack[index:] + [target]

        stack.pop()
        state[node] = complete
        return None

    all_nodes = set(adjacency)

    for targets in adjacency.values():
        all_nodes.update(targets)

    for node in sorted(all_nodes):
        if state.get(node, unseen) != unseen:
            continue

        cycle = visit(node)

        if cycle is not None:
            return cycle

    return None


def validate_graph(
    graph: dict[str, Any],
    schema: dict[str, Any],
    ontology: dict[str, Any],
) -> list[str]:
    errors: list[str] = []

    validator = Draft202012Validator(
        schema
    )

    for error in sorted(
        validator.iter_errors(graph),
        key=lambda item: list(item.path),
    ):
        location = ".".join(
            str(part)
            for part in error.path
        )

        errors.append(
            f"SCHEMA location={location or '<root>'} "
            f"message={error.message}"
        )

    valid_node_types = ontology_values(
        ontology,
        "node_types",
    )

    valid_edge_types = ontology_values(
        ontology,
        "edge_types",
    )

    node_ids: set[str] = set()
    edge_ids: set[str] = set()

    for node in graph.get("nodes", []):
        node_id = node["node_id"]

        if node_id in node_ids:
            errors.append(
                f"DUPLICATE_NODE_ID={node_id}"
            )

        node_ids.add(node_id)

        if node["node_type"] not in valid_node_types:
            errors.append(
                "UNKNOWN_NODE_TYPE "
                f"node_id={node_id} "
                f"node_type={node['node_type']}"
            )

    dag_adjacency: dict[str, list[str]] = (
        defaultdict(list)
    )

    for edge in graph.get("edges", []):
        edge_id = edge["edge_id"]

        if edge_id in edge_ids:
            errors.append(
                f"DUPLICATE_EDGE_ID={edge_id}"
            )

        edge_ids.add(edge_id)

        if edge["edge_type"] not in valid_edge_types:
            errors.append(
                "UNKNOWN_EDGE_TYPE "
                f"edge_id={edge_id} "
                f"edge_type={edge['edge_type']}"
            )

        source = edge["source_node_id"]
        target = edge["target_node_id"]

        if source not in node_ids:
            errors.append(
                "MISSING_SOURCE_NODE "
                f"edge_id={edge_id} "
                f"source={source}"
            )

        if target not in node_ids:
            errors.append(
                "MISSING_TARGET_NODE "
                f"edge_id={edge_id} "
                f"target={target}"
            )

        if edge["edge_type"] in DAG_EDGE_TYPES:
            dag_adjacency[source].append(target)

    cycle = find_cycle(dag_adjacency)

    if cycle is not None:
        errors.append(
            "DAG_CYCLE="
            + " -> ".join(cycle)
        )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "graph_path",
        type=Path,
    )

    args = parser.parse_args()

    graph = load_json(args.graph_path)
    schema = load_json(SCHEMA_PATH)
    ontology = load_json(ONTOLOGY_PATH)

    errors = validate_graph(
        graph,
        schema,
        ontology,
    )

    print(
        f"GRAPH_NODES={len(graph.get('nodes', []))}"
    )
    print(
        f"GRAPH_EDGES={len(graph.get('edges', []))}"
    )
    print(
        f"GRAPH_VALIDATION_ERRORS={len(errors)}"
    )

    for error in errors:
        print(error)

    if errors:
        print("GRAPH_IR_VALIDATION=FAIL")
        return 1

    print("GRAPH_IR_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
