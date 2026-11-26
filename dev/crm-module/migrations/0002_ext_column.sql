-- Cross-module extension data column (docs/EXTENSIONS.md §5, v2 Fase 3).
-- Namespaced per extender module: {extender: {field: value}}. Only this
-- module writes it, through the SDK's validated API surface.
ALTER TABLE company ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE contact ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE tag ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE pipeline ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE stage ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE opportunity ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE lead ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE activity ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE contact_tag ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE opportunity_tag ADD COLUMN ext jsonb NOT NULL DEFAULT '{}'::jsonb;
