"""Verify that a mint's served keys re-hash to their advertised keyset ids.

This is the guard the migrator does not perform: it fetches every keyset from
`/v1/keysets` and `/v1/keys/{id}`, recomputes the NUT-02 id from the served
public keys, and compares it with the id the mint advertises. A truncated or
incomplete amount list (for example 32 of 64 denominations) keeps every key
correct but changes the hash, so this catches it before wallets do.

Optionally pass a reference mint URL (usually the still-running Nutshell mint)
to also assert that the served keys are byte-identical.

Usage:
    python scripts/verify_keyset_ids.py http://127.0.0.1:3338
    python scripts/verify_keyset_ids.py http://127.0.0.1:3338 https://mint.example.com

Exit code 1 means do not cut over.
"""

import hashlib
import sys

import httpx


def keys_from_payload(payload):
    if "keysets" in payload and payload["keysets"]:
        entry = payload["keysets"][0]
    elif "keys" in payload:
        entry = payload
    else:
        raise SystemExit(f"unexpected keys payload: {payload}")
    return {str(k): str(v).lower() for k, v in entry.get("keys", {}).items()}


def keyset_id_v1(keys):
    ordered = [keys[amount] for amount in sorted(keys, key=int)]
    pubkeys = b"".join(bytes.fromhex(value) for value in ordered)
    digest = hashlib.sha256(pubkeys).hexdigest()
    return "00" + digest[:14]


def keyset_id_v2(keys, unit, input_fee_ppk, final_expiry, include_zero_expiry=False):
    ordered = sorted(keys, key=int)
    data = ",".join(f"{amount}:{keys[amount]}" for amount in ordered)
    data += f"|unit:{unit}"
    if input_fee_ppk:
        data += f"|input_fee_ppk:{input_fee_ppk}"
    if final_expiry:
        data += f"|final_expiry:{final_expiry}"
    elif include_zero_expiry:
        data += "|final_expiry:0"
    digest = hashlib.sha256(data.encode("utf-8")).hexdigest()
    return "01" + digest[:64]


def candidate_ids(keyset, keys):
    """Return the acceptable ids for a served keyset plus a version label."""
    keyset_id = str(keyset["id"])
    if keyset_id.startswith("00"):
        return [keyset_id_v1(keys)], "v1"
    if keyset_id.startswith("01"):
        unit = keyset.get("unit", "sat")
        fee = int(keyset.get("input_fee_ppk") or 0)
        expiry = int(keyset["final_expiry"]) if keyset.get("final_expiry") else None
        candidates = [keyset_id_v2(keys, unit, fee, expiry)]
        # Some Nutshell releases hashed an explicit zero expiry for keysets that
        # have no final expiry. Accept that legacy calculation as well.
        if expiry is None:
            legacy = keyset_id_v2(keys, unit, fee, 0, include_zero_expiry=True)
            if legacy not in candidates:
                candidates.append(legacy)
        return candidates, "v2"
    return None, f"unknown version prefix {keyset_id[:2]!r}"


def fetch_keysets(client):
    response = client.get("/v1/keysets")
    response.raise_for_status()
    return response.json().get("keysets", [])


def fetch_keys(client, keyset_id):
    response = client.get(f"/v1/keys/{keyset_id}")
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return keys_from_payload(response.json())


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: verify_keyset_ids.py <mint-base-url> [reference-mint-base-url]")
        return 2

    base = sys.argv[1].rstrip("/")
    reference = sys.argv[2].rstrip("/") if len(sys.argv) == 3 else None
    failures = 0

    with httpx.Client(base_url=base, timeout=20) as client:
        keysets = fetch_keysets(client)
        if not keysets:
            print("FAIL no keysets advertised by the mint")
            return 1

        reference_client = httpx.Client(base_url=reference, timeout=20) if reference else None
        try:
            for keyset in keysets:
                keyset_id = str(keyset["id"])
                keys = fetch_keys(client, keyset_id)
                if keys is None:
                    print(f"FAIL keyset {keyset_id}: advertised but /v1/keys/{keyset_id} is 404")
                    failures += 1
                    continue

                candidates, version = candidate_ids(keyset, keys)
                if candidates is None:
                    print(f"FAIL keyset {keyset_id}: {version}")
                    failures += 1
                    continue

                if keyset_id not in candidates:
                    print(
                        f"FAIL keyset {keyset_id} ({version}): served keys hash to "
                        f"{candidates[0]} with {len(keys)} denominations"
                    )
                    failures += 1
                    continue

                summary = f"OK keyset {keyset_id} ({version}): {len(keys)} keys re-hash to id"

                if reference_client is not None:
                    reference_keys = fetch_keys(reference_client, keyset_id)
                    if reference_keys is None:
                        summary += "; reference does not list it (skipped)"
                    elif reference_keys != keys:
                        missing = len(set(reference_keys) - set(keys))
                        extra = len(set(keys) - set(reference_keys))
                        changed = len(
                            k
                            for k in set(keys) & set(reference_keys)
                            if keys[k] != reference_keys[k]
                        )
                        print(
                            f"FAIL keyset {keyset_id}: keys differ from reference "
                            f"(missing={missing} extra={extra} changed={changed})"
                        )
                        failures += 1
                        continue
                    else:
                        summary += "; byte-identical to reference"

                print(summary)
        finally:
            if reference_client is not None:
                reference_client.close()

    if failures:
        print(f"\n{failures} keyset check(s) failed: do not cut over")
        return 1
    print(f"\nAll {len(keysets)} keyset(s) verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
