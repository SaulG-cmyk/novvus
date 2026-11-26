-- Cross-module extension data column (docs/EXTENSIONS.md §5, v2 Fase 3).
ALTER TABLE project ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE task ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
