-- Card labels and checklists, scoped by organization and task.
CREATE TABLE task_label (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL,
    task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    title VARCHAR(80) NOT NULL DEFAULT '',
    color VARCHAR(6) NOT NULL DEFAULT 'blue',
    CHECK (color IN ('none','blue','green','yellow','orange','red','purple')),
    ext JSONB NOT NULL DEFAULT '{}'::jsonb,
    custom JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at TIMESTAMP WITH TIME ZONE
);
ALTER TABLE task_label ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_label FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON task_label
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
CREATE TABLE task_checklist (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL,
    task_id UUID NOT NULL REFERENCES task(id) ON DELETE CASCADE,
    title VARCHAR(120) NOT NULL,
    ext JSONB NOT NULL DEFAULT '{}'::jsonb,
    custom JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at TIMESTAMP WITH TIME ZONE
);
ALTER TABLE task_checklist ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_checklist FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON task_checklist
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
CREATE TABLE task_checklist_item (
    id UUID PRIMARY KEY,
    org_id UUID NOT NULL,
    checklist_id UUID NOT NULL REFERENCES task_checklist(id) ON DELETE CASCADE,
    title VARCHAR(300) NOT NULL,
    checked BOOLEAN NOT NULL DEFAULT false,
    ext JSONB NOT NULL DEFAULT '{}'::jsonb,
    custom JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    deleted_at TIMESTAMP WITH TIME ZONE
);
ALTER TABLE task_checklist_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_checklist_item FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON task_checklist_item
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
CREATE INDEX ix_task_label_card ON task_label(org_id, task_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_task_checklist_card ON task_checklist(org_id, task_id) WHERE deleted_at IS NULL;
CREATE INDEX ix_task_checklist_item_list ON task_checklist_item(org_id, checklist_id) WHERE deleted_at IS NULL;
