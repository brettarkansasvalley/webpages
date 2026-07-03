sqlite3 database.db 'SELECT * FROM json_objects WHERE rowid IN (SELECT MIN(rowid) FROM json_objects GROUP BY source_file)' -json > json_objects.json
