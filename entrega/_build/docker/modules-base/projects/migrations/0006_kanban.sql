-- Shared column appearance and card labels. No changes to workflow statuses.
ALTER TABLE task ADD COLUMN label_color VARCHAR(6) NOT NULL DEFAULT 'none';
ALTER TABLE task ADD CONSTRAINT ck_task_label_color CHECK (label_color IN ('none', 'blue', 'green', 'yellow', 'orange', 'red', 'purple'));
CREATE TABLE kanban_column (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL,
    status VARCHAR(9) NOT NULL,
    title VARCHAR(80) NOT NULL DEFAULT '',
    color VARCHAR(6) NOT NULL DEFAULT 'none',
    ext JSONB NOT NULL DEFAULT '{}'::jsonb,
    custom JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at TIMESTAMP WITH TIME ZONE,
    UNIQUE (org_id, status),
    CHECK (status IN ('todo', 'doing', 'blocked', 'review', 'done', 'cancelled')),
    CHECK (color IN ('none', 'blue', 'green', 'yellow', 'orange', 'red', 'purple'))
);
ALTER TABLE kanban_column ENABLE ROW LEVEL SECURITY;
ALTER TABLE kanban_column FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON kanban_column
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
