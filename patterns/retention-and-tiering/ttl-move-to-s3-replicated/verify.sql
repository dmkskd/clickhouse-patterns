-- system.remote_data_paths exposes each S3 object used by a local part.
-- One row per prefix proves distinct cold object sets for ch-01 and ch-02.
SELECT
    multiIf(
        remote_path LIKE '%ttl-replicated/ch-01/%', 'ch-01',
        remote_path LIKE '%ttl-replicated/ch-02/%', 'ch-02',
        'unexpected'
    ) AS replica_prefix,
    countDistinct(remote_path) AS remote_objects,
    sum(size) AS compressed_bytes
FROM clusterAllReplicas('patterns', system.remote_data_paths)
WHERE disk_name = 'cold_s3' AND remote_path LIKE '%ttl-replicated/%'
GROUP BY replica_prefix
ORDER BY replica_prefix;
