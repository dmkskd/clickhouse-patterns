# Replicated MOVE TTL to self-hosted S3

Profiles: `cluster`, `s3`. Driver: `ch-01`.

This is the default, non-zero-copy shape for a replicated table backed by an
S3 disk. `ReplicatedMergeTree` replicates a part to `ch-02`; the same MOVE TTL
then acts on each replica's local part. The two storage fragments deliberately
give `cold_s3` different S3 prefixes, so MinIO contains two object sets:

```
clickhouse/ttl-replicated/ch-01/…  # cold copy owned by ch-01
clickhouse/ttl-replicated/ch-02/…  # cold copy owned by ch-02
```

The `system.parts` readiness checks prove that both replicas have moved their
old part. The third readiness check runs `clusterAllReplicas` over
`system.remote_data_paths` and requires remote objects from two hosts. The
verification output names each replica's actual remote prefix and counts its
remote objects. That is evidence of two physical object sets, not merely two
logical replicas with identical row counts.

`allow_remote_fs_zero_copy_replication = 0` is specified in the DDL so the
demonstration cannot silently switch to shared remote objects. The setting's
default is also `0`; enabling it is experimental in ClickHouse 26.7 and is not
presented here as a production recommendation.
