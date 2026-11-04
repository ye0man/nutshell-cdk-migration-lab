import json
import sys
from pathlib import Path

import httpx


def normalize(payload):
    if "keysets" in payload and payload["keysets"]:
        entry = payload["keysets"][0]
        return {str(k): str(v) for k, v in entry.get("keys", {}).items()}
    if "keys" in payload:
        return {str(k): str(v) for k, v in payload["keys"].items()}
    raise SystemExit(f"unexpected keys payload: {payload}")


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: compare_keys.py <nutshell-keys.json> <cdk-base-url>")
        return 2
    snapshot = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    base = sys.argv[2].rstrip("/")
    failures = 0
    with httpx.Client(base_url=base, timeout=10) as client:
        for keyset_id, source_payload in snapshot.items():
            response = client.get(f"/v1/keys/{keyset_id}")
            if response.status_code == 404:
                print(f"MISSING keyset {keyset_id} on CDK")
                failures += 1
                continue
            source = normalize(source_payload)
            target = normalize(response.json())
            if source != target:
                missing = sorted(set(source) - set(target))
                extra = sorted(set(target) - set(source))
                changed = sorted(k for k in set(source) & set(target) if source[k] != target[k])
                print(
                    f"MISMATCH keyset {keyset_id}: missing={len(missing)} "
                    f"extra={len(extra)} changed={len(changed)}"
                )
                failures += 1
            else:
                print(f"OK keyset {keyset_id}: {len(source)} keys identical")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
