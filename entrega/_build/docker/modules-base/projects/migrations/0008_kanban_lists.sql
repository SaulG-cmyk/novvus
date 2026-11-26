-- Lists can be arranged independently of workflow statuses. Existing cards stay put.
ALTER TABLE kanban_column ALTER COLUMN status DROP NOT NULL;
ALTER TABLE kanban_column ADD COLUMN position INTEGER NOT NULL DEFAULT 0;
ALTER TABLE kanban_column ADD COLUMN collapsed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE kanban_column ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE kanban_column NO FORCE ROW LEVEL SECURITY;
UPDATE kanban_column SET position = CASE status WHEN 'todo' THEN 0 WHEN 'doing' THEN 1 WHEN 'blocked' THEN 2 WHEN 'review' THEN 3 WHEN 'done' THEN 4 ELSE 5 END;
ALTER TABLE kanban_column FORCE ROW LEVEL SECURITY;
ALTER TABLE task ADD COLUMN kanban_column_id UUID REFERENCES kanban_column(id) ON DELETE SET NULL;
CREATE INDEX ix_task_kanban_column ON task (org_id, kanban_column_id) WHERE deleted_at IS NULL;
