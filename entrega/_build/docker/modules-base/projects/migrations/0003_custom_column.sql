-- Per-organization custom-field data column (docs/CUSTOM_FIELDS.md, v2 Fase 4).
ALTER TABLE project ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE task ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
