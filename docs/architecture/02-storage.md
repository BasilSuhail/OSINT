# 02 — Storage Layout

How data lives on disk: btrfs RAID1, hot/cold split, snapshots, off-site backup.

- [Disks and filesystem](#disks-and-filesystem)
- [Directory layout](#directory-layout)
- [Snapshot policy](#snapshot-policy)
- [Off-site backup](#off-site-backup)
- [Parquet partitioning](#parquet-partitioning)
- [Postgres tuning for Pi 5](#postgres-tuning-for-pi-5)
- [Hot / cold split](#hot--cold-split)
- [Hardware gotchas](#hardware-gotchas)

---

## Disks and filesystem

- 2 x 4 TB USB3 HDD in **UAS-compatible** enclosures
- btrfs RAID1 mirror across both, mounted at `/mnt/data`
- Subvolumes per top-level directory (so snapshots are per-domain)

Why btrfs over alternatives:

| FS | Why not |
|---|---|
| ext4 | No checksums → silent bitrot on USB-attached storage is real and uncatchable |
| zfs | ARC cache eats RAM; on an 8 GB Pi 5 with Postgres, Redis, FastAPI, Celery workers running, there is no room |
| btrfs | Checksums, RAID1, cheap snapshots, mature kernel support on Pi 5, no licensing weirdness |

Create:

```bash
sudo mkfs.btrfs -L data -m raid1 -d raid1 /dev/sda /dev/sdb
sudo mount -o compress=zstd:3,noatime /dev/sda /mnt/data
```

---

## Directory layout

```
/mnt/data/
├── pg/                  Postgres data dir (own subvolume)
├── redis/               Redis AOF persistence
├── parquet/             Cold archive, partitioned
│   ├── gdelt/year=2026/month=06/day=17/*.parquet
│   ├── finance/year=2026/month=06/*.parquet
│   ├── acled/year=2026/*.parquet
│   ├── flights/year=2026/month=06/day=17/*.parquet
│   ├── ships/...
│   └── ...
├── raw/                 Untouched dumps for audit trail
│   ├── gdelt/2026-06-17T06-00.zip
│   ├── finbert-rss/2026-06-17/*.html.gz
│   └── ...
├── snapshots/           btrfs snapshot mounts
└── backups/             Local backup staging before off-site push
```

`raw/` is write-once. Nothing deletes from there except the retention job after the off-site backup confirms a successful upload.

---

## Snapshot policy

Managed by [`btrbk`](https://digint.ch/btrbk/) (Debian package).

| Target | Frequency | Retention |
|---|---|---|
| `/mnt/data/pg` | Hourly | 24 h |
| `/mnt/data` whole | Daily | 7 d |
| `/mnt/data` whole | Weekly | 4 w |

Snapshot creation is atomic and effectively free on btrfs (copy-on-write). A botched migration or a corrupted ingestion run can be rolled back in seconds.

---

## Off-site backup

- Tool: [`restic`](https://restic.net/) (encrypted, deduplicating)
- Remote: [Backblaze B2](https://www.backblaze.com/cloud-storage) ($6/TB/month) **or** [Cloudflare R2](https://www.cloudflare.com/products/r2/) (10 GB free + cheap egress)
- Schedule: nightly cron
- Contents: `pg_dump` output + `restic backup /mnt/data/parquet` + `restic backup /mnt/data/raw`
- Encryption: passphrase stored at `/etc/restic/key` (mode 0400, root-only)
- Restore test: monthly via `scripts/restore-smoke-test.sh` that pulls a random snapshot and verifies one file

If two HDDs die simultaneously, off-site is the only recovery. RAID1 mitigates single-disk failure, not enclosure failure, not power surge, not theft.

---

## Parquet partitioning

Hive-style partitions: `year=YYYY/month=MM/day=DD/`. Readable directly by DuckDB, Polars, Pandas, and Spark with no metadata service.

Why Parquet:

- Columnar → eval queries read only needed columns
- Compressed (zstd in parent btrfs + Parquet's own snappy) → ~5-10x smaller than raw CSV
- Reproducible: eval pipeline pulls Parquet, not Postgres, so historical evaluation does not depend on hot-store retention policy

Example read (in evaluation script):

```python
import polars as pl
df = pl.scan_parquet("/mnt/data/parquet/gdelt/year=2022/month=*/day=*/*.parquet")
```

---

## Postgres tuning for Pi 5

`postgresql.conf` overrides for an 8 GB Pi:

```conf
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 32MB
maintenance_work_mem = 256MB
wal_compression = on
random_page_cost = 1.5         # SSD-tuned, but USB HDD is closer to spinning so test 2.5 too
max_connections = 50
```

No streaming replication (no second host). Disaster recovery is `pg_dump` → restic → off-site. Documented restore procedure in `scripts/restore-postgres.sh`.

---

## Hot / cold split

- **Hot (Postgres)**: events from the last **90 days**. Indexed for dashboard queries and composite worker.
- **Cold (Parquet)**: forever. Eval, audit, replay.
- **Mover job**: nightly Celery task `worker-housekeeping`:
  1. Select events older than 90 days
  2. Write them to a new Parquet file under the right partition
  3. Verify row count matches
  4. Delete from Postgres
  5. Log a row in `housekeeping_runs`

Composite worker reads Postgres for live scoring. Evaluation reads Parquet for historical analysis. The split keeps Postgres small (and fast) without losing data.

---

## Hardware gotchas

These are the failure modes that kill Pi storage builds:

1. **USB → SATA bridge chip matters.** Cheap no-name bridges silently corrupt data under load. Buy enclosures with **JMicron JMS583** or **ASMedia ASM2362**. Verify on the product page before ordering.
2. **Power.** Pi 5 USB3 ports deliver 5 V / 0.9 A. A spinning HDD needs more (especially on spin-up). Enclosures **must be self-powered** with their own 12 V brick. Bus-powered enclosures cause undervoltage events and corruption.
3. **UAS not BOT.** UAS (USB Attached SCSI) is faster and more reliable than the older BOT (Bulk-Only Transport). Confirm enclosure supports UAS or you lose ~50% throughput.
4. **btrfs RAID1 is single-disk-fail survivable, two-disk-fail = total loss.** Off-site backup is non-optional.
5. **Pi 5 active cooler required.** Sustained Postgres + Celery + ingestion will thermal-throttle a passive-cooled Pi 5 in 10 minutes. Active fan + heatsink or it dies.
