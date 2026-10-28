# CP027 runbook

This package is a review candidate, not an installed or qualified database. No PostgreSQL version is selected. Upstream URLs in component.json are research targets, not verified release evidence. The abbreviated cached 17.11 image is not adopted. Production stays disabled.

## Admission and pins

Root artifact/lock owner must authenticate the supported release against exact selected application releases, official image source commit/build provenance and platform OCI digest. Record UID/GID, direct nonroot entrypoint, pgBackRest availability/closure, TLS libraries, license texts and SBOM for those same bytes. pgBackRest is a required dependency, not assumed to exist in the official image. A reviewed derived image or authenticated separately mounted tool/closure is necessary. Do not silently install it. F09 owner adopts pins/scanners centrally after independent review; proposal status is in evidence-proposal.json.

The bounded Quadlet template inherits F06's rootless read-only/no-network/capability-drop baseline. Volume and Exec keys, private secret references and database write targets extend F06's deliberately stateless allowlist. The unchanged F06 validator is expected to reject this unresolved component; it is NOT a validation pass. Root security owner must review the extension, exact installed generator output and actual mounts before rendering/installing. No policy or exception change is bundled. RuntimeMaxSec=1800 and Restart=no make this an engineering rehearsal, not an unattended server installation. Persistent service/restart policy needs a separately reviewed profile. Network=none deliberately blocks app TCP use until reviewed private-network policy and exact HBA CIDRs exist.

## Installation and migration

Only after separately admitted execution: provision fresh private data/repository volumes with mapped nonroot ownership and quotas; supply authenticated artifacts without host sockets/network pulls. Mount reviewed configs and private TLS/cipher secret files. Initialize as the authenticated nonroot account using the exact artifact's supported initdb procedure. Never run a vendor entrypoint against existing unrelated data. Verify no unresolved markers remain, generator compatibility and UID maps before any start.

Use sql/bootstrap.sql once against an empty authorized cluster as bootstrap administrator. Provide psql variables through private stdin using SCRAM verifiers, not CLI values. Owners are NOLOGIN, migrators are NOINHERIT and explicitly SET ROLE their own owner; runtime has neither membership nor DDL/TEMP/database creation privileges. sql/001-ledger.sql is a one-time transactional operational-ledger migration per app, run as that app's migrator with owner/runtime identifier variables. Reapplying intentionally fails; record migration checksum externally. No application uses owner/admin/migrator credentials at runtime. Actual application native schemas are migrated only by their supported application migration tooling; these synthetic ledgers do not substitute for native application databases.

Only app_a/app_b are executable synthetic examples. Additional app databases require scoped grants and migrations using the same isolation boundary, not shared runtime credentials. PostgreSQL stores operational intents; use F04 validation before SQL admission. Ledger action_key is computed using F04 compact UTF8 JSON tuple SHA256, never inferred by the table regex. The adapter/account/key uniqueness and tuple uniqueness support atomic INSERT ... ON CONFLICT DO NOTHING RETURNING id reservations; no dispatcher or receipt state machine is implemented here. F05 native APIs remain authoritative. Append-only runtime grants forbid UPDATE/DELETE, and UNKNOWN/reconciliation protocols need their own reviewed append-only receipt migration. This package does not claim full workflow runtime durability qualification.

## Readiness

pg_isready is liveness only and does not prove authenticated application readiness. Require verify-full TLS query as each runtime identity, schema migration checksum, permitted ledger access, denied cross-app access, healthy pgBackRest check/archive status and independent held-consumer readback before app availability. Dependency ordering does not replace readiness. Revoke runtime CONNECT and stop native consumers before maintenance; existing sessions must be drained by the authorized operator, not presumed gone after REVOKE. No outbound switch exists in PostgreSQL.

## Backup and restore

scripts/backup_restore.py exposes fixed pgBackRest stanza-create/check/full-backup/info/restore operations, with bounded execution. Run as the owned nonroot database account in the admitted sandbox. Config contains private cipher-pass reference/value only in a private mounted file, never a committed credential. Root must verify encrypted-repository implementation, retention, archive continuity and successful check before accepting a backup. Retain two full backups plus their WAL; measured disk demand above admission caps requires expansion, not disabled quota.

For restore, stop/drain only the designated disposable cluster/consumer after actual HOLD readback, choose an explicit verified info label, and use a DIFFERENT empty private owned data volume. The helper refuses nonempty targets and never uses delta/force. Root verifies target is not the live source and all ancestors are owned nonsymlink mounts; string inequality alone is insufficient. Verify row snapshot, row counts, sequences, owners, grants, TLS and cross-app denial after isolated startup; obtain actual consumer HOLD receipt. A logical pg_dump may be supplemental only. It cannot satisfy pgBackRest rehearsal.

## Rollback

Keep old image/config pins and previous data volume intact. For failed migration, transaction rollback covers SQL only; never downgrade data files across majors. Stop the candidate, retain failed evidence, and start the verified old artifact with its coherent pre-change backup restored into another empty volume. Application consumers remain held until owner reconciliation and fresh approval. An engineering restart or SQL availability cannot authorize email/calls/publication. Never overwrite the old cluster in place or delete evidence in this package.

## Qualification commands

Future admitted Linux guest only: python -B tests/integration.py --root /work/cp027-empty --bin /approved/bin --certs /approved/ephemeral-tls --admission /approved/admission.json

Root provisions private synthetic server cert/key with SAN localhost, test CA and an unrelated wrong CA, all ephemeral; private keys never enter repository/output. Root supplies exact artifact identity, exact candidate revision and independently verified confinement/cap facts in admission.json. That JSON is evidence binding, not execution authority or proof of its own claims. The runner uses only guest loopback and publishes no host/LAN port. Native guest execution and rootless Quadlet execution are different evidence tracks.

The entrypoint always exits 2 for partial coverage even after its implemented SQL/TLS/restore probes pass. Its explicit remaining checks are actual held-consumer observation, mid-write interrupted-backup behavior, generator/cgroup observation. Root must not translate PARTIAL to component PASS. No tests have been run by this author.
