-- automatizacion 0003: nombre del proceso en los registros de actividad (logs)

ALTER TABLE process_log ADD COLUMN IF NOT EXISTS process_name VARCHAR(200) NOT NULL DEFAULT '';

UPDATE process_log l SET process_name = COALESCE(NULLIF(e.process_name, ''), p.name, '')
  FROM process_execution e
  LEFT JOIN process p ON p.id = e.process_id
 WHERE l.execution_id = e.id AND l.process_name = '';
