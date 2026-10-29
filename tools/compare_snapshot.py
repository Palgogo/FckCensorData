#!/usr/bin/env python3
"""Compare a saved FckCensorData snapshot with an upstream list.json.

No audio is downloaded and no library file is changed.  The report records
retrieval time, Git commit identity when supplied, content hashes, and additions
or removals by stable Yandex track_id.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import pathlib
import urllib.request

UTC = dt.timezone.utc


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_json(path: pathlib.Path) -> tuple[bytes, list[dict]]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list")
    return raw, data


def clean(item: dict) -> dict:
    return {
        "track_id": str(item.get("track_id", "")),
        "song": item.get("song", ""),
        "artists": item.get("artists", []),
        "url": item.get("url", ""),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", type=pathlib.Path, required=True)
    p.add_argument("--upstream-url", required=True)
    p.add_argument("--upstream-commit", default="unknown")
    p.add_argument("--out", type=pathlib.Path, required=True)
    args = p.parse_args()

    base_raw, base = load_json(args.baseline)
    with urllib.request.urlopen(args.upstream_url, timeout=60) as r:
        upstream_raw = r.read()
    upstream_document = json.loads(upstream_raw)
    # Current upstream list.json is {"tracks": {"<Yandex ID>": "audio URL"}}.
    # The local 2026-09 snapshot contains titles/artists plus those stable IDs.
    if not isinstance(upstream_document, dict) or not isinstance(upstream_document.get("tracks"), dict):
        raise ValueError("upstream: expected {'tracks': {'<track_id>': '<audio URL>'}}")
    upstream = [
        {"track_id": track_id, "url": audio_url, "song": "", "artists": []}
        for track_id, audio_url in upstream_document["tracks"].items()
    ]

    base_by_id = {clean(x)["track_id"]: clean(x) for x in base if clean(x)["track_id"]}
    upstream_by_id = {clean(x)["track_id"]: clean(x) for x in upstream if clean(x)["track_id"]}
    added_ids = sorted(upstream_by_id.keys() - base_by_id.keys(), key=int)
    removed_ids = sorted(base_by_id.keys() - upstream_by_id.keys(), key=int)
    common_ids = base_by_id.keys() & upstream_by_id.keys()
    # The baseline has Yandex catalogue metadata; upstream list.json stores
    # replacement-audio URLs.  These fields are not semantically comparable.
    # Membership by stable track ID is the only valid diff at this boundary.

    report = {
        "generatedAt": dt.datetime.now(UTC).isoformat(),
        "baseline": {
            "path": str(args.baseline),
            "sha256": sha256(base_raw),
            "tracks": len(base_by_id),
        },
        "upstream": {
            "url": args.upstream_url,
            "commit": args.upstream_commit,
            "sha256": sha256(upstream_raw),
            "tracks": len(upstream_by_id),
        },
        "comparison": {
            "added": len(added_ids),
            "removed": len(removed_ids),
            "changed": "not-applicable (metadata schemas differ)",
            "unchanged": len(common_ids),
        },
        "added": [upstream_by_id[i] for i in added_ids],
        "removed": [base_by_id[i] for i in removed_ids],
        "changed": [],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")

    csv_path = args.out.with_suffix(".summary.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["status", "track_id", "artists", "song", "url"])
        w.writeheader()
        for status, rows in (("added", report["added"]), ("removed", report["removed"])):
            for row in rows:
                w.writerow({**row, "status": status, "artists": "; ".join(row["artists"])})
        for row in report["changed"]:
            x = row["upstream"]
            w.writerow({**x, "status": "changed", "artists": "; ".join(x["artists"])})
    print(json.dumps(report["comparison"], ensure_ascii=False))
    print(args.out)
    print(csv_path)


if __name__ == "__main__":
    main()
