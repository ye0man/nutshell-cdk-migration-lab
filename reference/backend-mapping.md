# Nutshell -> CDK backend mapping (CDK v0.18.3)

The migration copies mint data only. Lightning node identity, channels, macaroons,
and configuration stay where they are, but CDK must be given an equivalent backend.

| Nutshell 0.22 backend | CDK 0.18.3 backend | Operator action |
|---|---|---|
| `FakeWallet` | `fakewallet` | Direct mapping. Tested in the lab. |
| `LndRPCWallet` | `lnd` (gRPC) | Keep the same node, cert, and admin macaroon. Tested only as a design path; not run in the Windows lab. |
| `LndRestWallet` | `lnd` (gRPC) | **CDK 0.18.3 has no LND REST backend.** Expose the LND gRPC port and point CDK at it with the cert and macaroon. |
| `CLNRestWallet` | `cln` (gRPC socket) | **CDK uses the local CLN gRPC socket**, not REST. A remote REST-only CLN needs a local socket or a proxy. |
| `StrikeWallet` | none | No direct CDK backend in 0.18.3. Use a `grpc-processor` sidecar or keep that unit on Nutshell. |
| `SparkL2Wallet` | none | No direct CDK backend in 0.18.3. Use a `grpc-processor` sidecar or keep that unit on Nutshell. |
| Multi-unit (sat/usd/eur) | one `[[payment_backend]]` per unit | Each unit must have a supported CDK backend. A unit whose backend has no equivalent blocks that unit. |

## Data that is not migrated

- **Lightning state**: node identity, channels, pending HTLCs, macaroons.
- **NUT-21 auth ledger**: users, auth keysets, and auth promises live in the
  separate Nutshell auth database. CDK has its own auth database; it is not
  migrated.
- **NUT-19 cache**: the response cache is in memory/Redis and can be discarded.
- **Management RPC state**: reconfigure it in CDK.

## Pending melts

A pending melt must be settled or cancelled before changing the Lightning node or
backend. CDK will try to reconcile the stored payment lookup ID against its own
backend on first start. If the new backend cannot see the same payment, the quote
stays pending and needs manual resolution.

## Recommended cutover posture

- Keep the same lightning node and backend shape where possible.
- For LND REST -> LND gRPC, do a test mint run first and confirm a mint and melt.
- For CLN REST -> CLN gRPC, run CDK on the same host as CLN (or expose the gRPC
  socket securely) and confirm the socket path.
- For Strike/Spark units, do not start CDK with an incomplete backend map.
