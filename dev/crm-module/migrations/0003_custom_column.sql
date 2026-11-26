-- Per-organization custom-field data column (docs/CUSTOM_FIELDS.md, v2 Fase 4).
ALTER TABLE company ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE contact ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tag ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE pipeline ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE stage ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE opportunity ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE lead ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE activity ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE contact_tag ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE opportunity_tag ADD COLUMN custom jsonb NOT NULL DEFAULT '{}'::jsonb;
