-- The reader's glob covers the two pre-existing objects plus both objects
-- written through the single-key table, so one query returns the original and
-- appended rows together: 3000 rows, of which 1000 are the appended 'refund'
-- rows.
SELECT
    (SELECT count() FROM demo.exports_s3)                  AS in_s3,
    (SELECT countIf(kind = 'refund') FROM demo.exports_s3) AS appended;
