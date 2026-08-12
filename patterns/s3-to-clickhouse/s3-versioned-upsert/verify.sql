-- After batch 1, a corrective batch 2, and a re-load of batch 1, FINAL keeps the
-- highest version per id: 1000 distinct events, with ids 0..99 showing the batch-2
-- correction ('refund'). Re-loading the older batch 1 cannot overwrite them.
SELECT count() AS rows, countIf(kind = 'refund') AS corrected
FROM demo.events FINAL;
