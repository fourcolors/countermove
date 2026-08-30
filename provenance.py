"""Canonical serialization and Merkle verification for Countermove trees."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from typing import Any


_SIX_PLACES = Decimal("0.000001")
_HASH_LENGTH = 64


def _rounded_float(value: float) -> float:
    """Return *value* rounded to six decimal places using decimal half-even."""
    if not math.isfinite(value):
        raise ValueError("canonical JSON does not permit non-finite floats")

    decimal_value = Decimal(str(value))
    # quantize uses the active decimal context even when the input came from a
    # very large (but finite) Python float.
    digits = len(decimal_value.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(28, digits + abs(decimal_value.adjusted()) + 8)
        try:
            rounded = decimal_value.quantize(_SIX_PLACES, rounding=ROUND_HALF_EVEN)
        except InvalidOperation as exc:
            raise ValueError(f"float cannot be canonicalized: {value!r}") from exc

    # Preserve the JSON number's float identity (59.0 remains 59.0), while
    # ensuring both -0.0 and values rounded down to zero serialize as 0.0.
    if rounded.is_zero():
        return 0.0
    return float(rounded)


def _key_order(value: str) -> bytes:
    """RFC 8785/JCS object-key ordering uses UTF-16 code units."""
    return value.encode("utf-16-be", errors="surrogatepass")


def _normalize(value: Any, field_name: str | None = None) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return _rounded_float(value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical JSON object keys must be strings")
        return {
            key: _normalize(value[key], key)
            for key in sorted(value, key=_key_order)
        }
    if isinstance(value, (list, tuple)):
        normalized = [_normalize(item) for item in value]
        if field_name == "sources":
            try:
                return sorted(normalized)
            except TypeError as exc:
                raise TypeError("sources must contain mutually comparable values") from exc
        if field_name == "segments":
            if not all(isinstance(item, Mapping) and isinstance(item.get("id"), str)
                       for item in normalized):
                raise ValueError("every segment must have a string id")
            return sorted(normalized, key=lambda item: item["id"])
        return normalized
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical(content: Any) -> bytes:
    """Serialize content using Countermove's pinned canonical JSON format."""
    normalized = _normalize(content)
    try:
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        return encoded.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError("canonical JSON requires valid Unicode") from exc


def _validate_digest(digest: Any, child_id: str) -> str:
    if not isinstance(digest, str) or len(digest) != _HASH_LENGTH:
        raise ValueError(f"invalid hash for child {child_id!r}")
    try:
        bytes.fromhex(digest)
    except ValueError as exc:
        raise ValueError(f"invalid hash for child {child_id!r}") from exc
    return digest.lower()


def _ordered_child_hashes(content: Mapping[str, Any], child_hashes: Any) -> list[str]:
    if isinstance(child_hashes, Mapping):
        items = list(child_hashes.items())
    else:
        if isinstance(child_hashes, (str, bytes)) or not isinstance(child_hashes, Sequence):
            raise TypeError("child_hashes must be a mapping or sequence")
        children = content.get("children", [])
        if not isinstance(children, Sequence) or isinstance(children, (str, bytes)):
            raise TypeError("content children must be a sequence")
        if len(children) != len(child_hashes):
            raise ValueError("children and child_hashes must have equal lengths")
        items = list(zip(children, child_hashes))

    if not all(isinstance(child_id, str) for child_id, _ in items):
        raise TypeError("child node ids must be strings")
    if len({child_id for child_id, _ in items}) != len(items):
        raise ValueError("child node ids must be unique")
    return [_validate_digest(digest, child_id) for child_id, digest in sorted(items)]


def node_hash(content: Mapping[str, Any], child_hashes: Any) -> str:
    """Hash node content plus child digests ordered by child-node id.

    ``child_hashes`` may be an ``id -> digest`` mapping or a sequence aligned
    with ``content['children']``. Hash text is appended as its 64 ASCII hex
    characters, matching the pinned ``canonical(content) + concat`` contract.
    """
    if not isinstance(content, Mapping):
        raise TypeError("node content must be a mapping")
    hash_content = {key: value for key, value in content.items()
                    if key not in {"hash", "children"}}
    payload = bytearray(canonical(hash_content))
    for digest in _ordered_child_hashes(content, child_hashes):
        payload.extend(digest.encode("ascii"))
    return hashlib.sha256(payload).hexdigest()


def verify_tree(tree: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute every stored node hash and the stored tree root.

    ``mismatches`` contains node ids whose stored hashes differ, plus a
    ``root_hash`` marker if the tree-level root digest differs. Structural
    errors are reported as readable markers and make ``ok`` false.
    """
    mismatches: list[str] = []
    try:
        nodes = tree["nodes"]
        root_id = tree["root"]
        stored_root_hash = tree["root_hash"]
        if not isinstance(nodes, list) or not isinstance(root_id, str):
            raise ValueError("tree nodes must be a list and root must be a string")

        by_id: dict[str, Mapping[str, Any]] = {}
        for node in nodes:
            if not isinstance(node, Mapping) or not isinstance(node.get("id"), str):
                raise ValueError("every node must be an object with a string id")
            node_id = node["id"]
            if node_id in by_id:
                raise ValueError(f"duplicate node id: {node_id}")
            by_id[node_id] = node
        if root_id not in by_id:
            raise ValueError(f"missing root node: {root_id}")

        computed: dict[str, str] = {}
        visiting: set[str] = set()

        def recompute(node_id: str) -> str:
            if node_id in computed:
                return computed[node_id]
            if node_id in visiting:
                raise ValueError(f"cycle at node: {node_id}")
            node = by_id.get(node_id)
            if node is None:
                raise ValueError(f"missing child node: {node_id}")
            children = node.get("children")
            if not isinstance(children, list) or not all(isinstance(item, str) for item in children):
                raise ValueError(f"invalid children for node: {node_id}")
            if len(set(children)) != len(children):
                raise ValueError(f"duplicate child id at node: {node_id}")

            visiting.add(node_id)
            child_hashes = {child_id: recompute(child_id) for child_id in children}
            visiting.remove(node_id)
            digest = node_hash(node, child_hashes)
            computed[node_id] = digest
            if node.get("hash") != digest:
                mismatches.append(node_id)
            return digest

        recomputed_root = recompute(root_id)
        # The root must commit to every node: an unreachable node is a
        # structural failure, not a benign extra, or a post-decision edit
        # could add self-consistent nodes without changing the root.
        reachable = set(computed)
        for node_id in sorted(by_id):
            if node_id not in reachable:
                mismatches.append(f"unreachable: {node_id}")
                recompute(node_id)
        # Ancestry must be consistent: each child's stored parent is the
        # node that lists it, and the root has no parent.
        for node_id, node in by_id.items():
            for child_id in node.get("children", []):
                child = by_id.get(child_id)
                if child is not None and child.get("parent") != node_id:
                    mismatches.append(f"parent-mismatch: {child_id}")
        if by_id[root_id].get("parent") is not None:
            mismatches.append("root-has-parent")
        if stored_root_hash != recomputed_root:
            mismatches.append("root_hash")
    except (KeyError, TypeError, ValueError) as exc:
        mismatches.append(f"structure: {exc}")

    return {"ok": not mismatches, "mismatches": mismatches}
