-- automatizacion 0002: nombre del proceso en pasos y ejecuciones

ALTER TABLE process_step ADD COLUMN IF NOT EXISTS process_name VARCHAR(200) NOT NULL DEFAULT '';
ALTER TABLE process_execution ADD COLUMN IF NOT EXISTS process_name VARCHAR(200) NOT NULL DEFAULT '';

UPDATE process_step s SET process_name = p.name
  FROM process p WHERE s.process_id = p.id AND s.process_name = '';

UPDATE process_execution e SET process_name = p.name
  FROM process p WHERE e.process_id = p.id AND e.process_name = '';
