"""Reading ComfyUI's API-format graph: nodes, links, and the values behind them.

Node ids are strings (a node in a
subgraph is ``"outer:inner"``), a link is ``[node_id, output_index]``, and a link may point at a
node that was muted or bypassed and so is absent. Class names are facts about the format; no
ComfyUI code is used.
"""

from collections import deque
from collections.abc import Iterator
from typing import Any

# Input names under which a primitive or utility node holds the value it outputs, most likely first.
VALUE_KEYS = (
    "value",
    "seed",
    "noise_seed",
    "int",
    "float",
    "number",
    "Number",
    "string",
    "String",
    "text",
    "Text",
    "populated_text",
    "prompt",
    "STRING",
    "INT",
    "FLOAT",
    "wildcard_text",
    "positive",
)
MAX_HOPS = 6


def is_link(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], (str, int))
        and not isinstance(value[0], bool)
        and isinstance(value[1], int)
        and not isinstance(value[1], bool)
    )


def unwrap(value: Any) -> Any:
    """A widget value that is itself a list is posted as ``{"__value__": [...]}``."""
    if isinstance(value, dict) and set(value) == {"__value__"}:
        return value["__value__"]
    return value


class Graph:
    """The API graph with link resolution and upstream and downstream walks."""

    def __init__(self, prompt: dict[str, Any]) -> None:
        self.nodes: dict[str, dict[str, Any]] = {str(node_id): node for node_id, node in prompt.items() if isinstance(node, dict) and isinstance(node.get("class_type"), str)}
        self._consumers: dict[str, set[str]] | None = None

    def __contains__(self, node_id: str) -> bool:
        return node_id in self.nodes

    def node(self, node_id: str | None) -> dict[str, Any] | None:
        return self.nodes.get(node_id) if node_id is not None else None

    def cls(self, node_id: str | None) -> str:
        node = self.node(node_id)
        return node["class_type"] if node else ""

    def inputs(self, node_id: str | None) -> dict[str, Any]:
        node = self.node(node_id)
        inputs = node.get("inputs") if node else None
        return inputs if isinstance(inputs, dict) else {}

    def title(self, node_id: str) -> str | None:
        meta = (self.node(node_id) or {}).get("_meta")
        title = meta.get("title") if isinstance(meta, dict) else None
        return title if isinstance(title, str) else None

    def follow(self, value: Any) -> tuple[str, int] | None:
        """The ``(node_id, output_index)`` a link points at, or None when it is not a link or the node is absent."""
        if not is_link(value):
            return None
        target = str(value[0])
        return (target, int(value[1])) if target in self.nodes else None

    def link(self, node_id: str | None, name: str) -> tuple[str, int] | None:
        return self.follow(self.inputs(node_id).get(name))

    def link_inputs(self, node_id: str) -> Iterator[tuple[str, str, int]]:
        """Every input of a node that is a link to a present node: ``(input_name, target_id, output_index)``."""
        for name, value in self.inputs(node_id).items():
            hit = self.follow(value)
            if hit is not None:
                yield name, hit[0], hit[1]

    def value(self, node_id: str | None, name: str, _hops: int = 0) -> Any:
        """An input's value, following links through primitive and utility nodes.

        A link is resolved by looking in the target node for an input of the same name, then for
        the usual value names (``value``, ``seed``, ``text``, …). Gives None when nothing scalar is found.
        """
        raw = unwrap(self.inputs(node_id).get(name))
        if not is_link(raw):
            return raw
        hit = self.follow(raw)
        if hit is None or _hops >= MAX_HOPS:
            return None
        target, _ = hit
        target_inputs = self.inputs(target)
        for key in (name, *VALUE_KEYS):
            if key in target_inputs:
                resolved = self.value(target, key, _hops + 1)
                if resolved is not None:
                    return resolved
        # A node with a single linked input (a math expression, a converter) passes it through.
        links = [n for n, v in target_inputs.items() if is_link(v)]
        if len(links) == 1:
            return self.value(target, links[0], _hops + 1)
        return None

    def consumers(self) -> dict[str, set[str]]:
        """For each node, the nodes that take one of its outputs."""
        if self._consumers is None:
            out: dict[str, set[str]] = {node_id: set() for node_id in self.nodes}
            for node_id in self.nodes:
                for _name, target, _index in self.link_inputs(node_id):
                    out[target].add(node_id)
            self._consumers = out
        return self._consumers

    def upstream(self, start: str) -> list[str]:
        """Every node ``start`` depends on, nearest first, ``start`` excluded."""
        seen = {start}
        order: list[str] = []
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for _name, target, _index in self.link_inputs(current):
                if target not in seen:
                    seen.add(target)
                    order.append(target)
                    queue.append(target)
        return order

    def downstream_count(self, start: str) -> int:
        consumers = self.consumers()
        seen = {start}
        queue = deque([start])
        while queue:
            for nxt in consumers.get(queue.popleft(), ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return len(seen) - 1


def workflow_nodes(workflow: dict[str, Any]) -> list[dict[str, Any]]:
    """The editor graph's node list, subgraph definitions included."""
    nodes = [n for n in workflow.get("nodes") or [] if isinstance(n, dict)]
    definitions = workflow.get("definitions")
    if isinstance(definitions, dict):
        for sub in definitions.get("subgraphs") or []:
            if isinstance(sub, dict):
                nodes.extend(n for n in sub.get("nodes") or [] if isinstance(n, dict))
    return nodes
