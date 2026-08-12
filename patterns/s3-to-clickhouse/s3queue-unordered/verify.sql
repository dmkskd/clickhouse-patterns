-- S3Queue processed all three files exactly once: 3000 rows from 3 distinct files.
SELECT count() AS rows, uniqExact(source_file) AS files FROM demo.events;
