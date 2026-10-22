#!/usr/bin/env python3
"""Group inventory entries that plausibly compete for the same prompts."""
from __future__ import annotations

import argparse
import re
import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import read_json, write_json  # noqa: E402

STOP = set(
    "a an the and or of to for in on with by from as is are be been use used using uses when this that it its "
    "your you any all skill skills tool tools file files user users claude code run runs runs into via not no "
    "do does if then than so such per new one two also can will should must may into about after before "
    "what which who how where why their they them these those".split()
)
OVERSIZE = 20
WEAK_TOKEN_MAX_DF = 5


def key_of(e: dict, dup_names: set) -> str:
    return f"{e['name']}@{e['source']}" if e["name"] in dup_names else e["name"]


def desc_tokens(e: dict) -> set:
    text = f"{e['name'].replace('-', ' ')} {e.get('description', '')}".lower()
    return {t for t in re.split(r"[^a-z0-9]+", text) if len(t) >= 3 and t not in STOP}


def name_tokens(e: dict) -> set:
    bare = e["name"].split(":")[-1]
    return {t for t in bare.split("-") if len(t) >= 4 and t not in STOP}


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


class UnionFind:
    def __init__(self, keys):
        self.parent = {k: k for k in keys}

    def find(self, k):
        while self.parent[k] != k:
            self.parent[k] = self.parent[self.parent[k]]
            k = self.parent[k]
        return k

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--threshold", type=float, default=0.15)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    inv = read_json(a.inventory) or {}
    entries = [e for e in inv.get("entries", []) if not e.get("disable_model_invocation")]
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["name"]] = counts.get(e["name"], 0) + 1
    dup_names = {n for n, c in counts.items() if c > 1}
    keyed: dict[str, dict] = {}
    warnings: list[str] = []
    for e in entries:
        base = key_of(e, dup_names)
        k, n = base, 1
        while k in keyed:
            n += 1
            k = f"{base}#{n}"
        if k != base:
            warnings.append(f"duplicate key {base}: kept as {k}")
        keyed[k] = e
    uf = UnionFind(keyed.keys())
    reasons: dict[str, list[str]] = {}
    pair_scores: dict[tuple[str, str], float] = {}

    def link(x: str, y: str, why: str) -> None:
        uf.union(x, y)
        reasons.setdefault(x, []).append(why)

    dtok = {k: desc_tokens(e) for k, e in keyed.items()}
    ntok = {k: name_tokens(e) for k, e in keyed.items()}
    by_name: dict[str, list[str]] = {}
    for k, e in keyed.items():
        by_name.setdefault(e["name"], []).append(k)

    # document frequency of name tokens across all entries
    df: dict[str, int] = {}
    for toks in ntok.values():
        for t in toks:
            df[t] = df.get(t, 0) + 1

    strong: list[tuple[str, str, str]] = []
    weak: list[tuple[str, str, str]] = []
    for x, y in combinations(sorted(keyed), 2):
        j = jaccard(dtok[x], dtok[y])
        pair_scores[(x, y)] = round(j, 3)
        if j >= a.threshold:
            strong.append((x, y, f"jaccard {j:.2f}: {x} ~ {y}"))
        if keyed[x]["name"] == keyed[y]["name"]:
            strong.append((x, y, f"same name across scopes: {x} ~ {y}"))
        shared = sorted(t for t in ntok[x] & ntok[y] if df.get(t, 0) <= WEAK_TOKEN_MAX_DF)
        if shared:
            weak.append((x, y, f"name token '{shared[0]}': {x} ~ {y}"))
    for k, e in keyed.items():
        for m in e.get("mentions_skills", []):
            for other in by_name.get(m, []):
                if other != k:
                    strong.append((k, other, f"mentions: {k} -> {other}"))

    for x, y, why in strong:
        link(x, y, why)
    size = lambda r: sum(1 for k in keyed if uf.find(k) == r)  # noqa: E731
    skipped = 0
    for x, y, why in sorted(weak):
        rx, ry = uf.find(x), uf.find(y)
        if rx == ry:
            reasons.setdefault(x, []).append(why)
            continue
        if size(rx) + size(ry) > OVERSIZE:
            skipped += 1
            continue
        link(x, y, why)
    if skipped:
        warnings.append(f"skipped {skipped} weak merges that would exceed {OVERSIZE} members")

    groups: dict[str, list[str]] = {}
    for k in keyed:
        groups.setdefault(uf.find(k), []).append(k)

    clusters, singletons, oversized = [], [], []
    for members in sorted((sorted(m) for m in groups.values()), key=lambda m: m[0]):
        if len(members) == 1:
            singletons.append(members[0])
            continue
        why = sorted({r for m in members for r in reasons.get(m, [])})
        pairs = sorted(
            ({"a": x, "b": y, "jaccard": pair_scores[(x, y)]} for x, y in combinations(members, 2)),
            key=lambda p: -p["jaccard"],
        )[:10]
        cid = f"c{len(clusters) + 1:02d}"
        clusters.append({
            "id": cid,
            "members": members,
            "sources": sorted({keyed[m]["source"] for m in members}),
            "reasons": why,
            "pairs": pairs,
        })
        if len(members) > OVERSIZE:
            oversized.append(cid)

    write_json(a.out, {"threshold": a.threshold, "clusters": clusters, "singletons": sorted(singletons),
                       "oversized": oversized, "warnings": warnings})
    return 0


if __name__ == "__main__":
    sys.exit(main())
