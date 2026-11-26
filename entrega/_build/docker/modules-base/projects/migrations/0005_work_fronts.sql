-- projects 0005: work fronts for the tracking matrix (docs/VIEWS.md §8t). Additive.
-- A work front is an independent line of execution inside a project (e.g. «Campo», «Proceso»,
-- «Informe»). A task may belong to one front, so the subtasks of a unit of work (its parent
-- task) form the cells of the matrix. Templates carry their own fronts and template tasks may
-- point at one, so a project born from a template gets its fronts and its cells at once.
-- down: drop the two columns (task.front_id, template_task.template_front_id) and the two
-- tables (template_front, work_front). No semicolons in comments: the runner splits on them.

CREATE TABLE work_front (
    project_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    position INTEGER NOT NULL,
    weight NUMERIC(7, 2) NOT NULL,
    id UUID NOT NULL,
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY (project_id) REFERENCES project (id) ON DELETE CASCADE
);
CREATE INDEX ix_work_front_project_id ON work_front (project_id);
CREATE UNIQUE INDEX ux_work_front_project_name ON work_front (project_id, name) WHERE deleted_at IS NULL;

CREATE TABLE template_front (
    template_id UUID NOT NULL,
    name VARCHAR(120) NOT NULL,
    position INTEGER NOT NULL,
    weight NUMERIC(7, 2) NOT NULL,
    id UUID NOT NULL,
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY (template_id) REFERENCES template (id) ON DELETE CASCADE
);
CREATE INDEX ix_template_front_template_id ON template_front (template_id);

-- NOT VALID, as in 0004: the new columns are NULL on existing rows, and validating would read the
-- referenced table under RLS without a tenant in the migration session.
ALTER TABLE task ADD COLUMN front_id UUID;
ALTER TABLE task ADD CONSTRAINT fk_task_front_id FOREIGN KEY(front_id) REFERENCES work_front (id) ON DELETE SET NULL NOT VALID;
CREATE INDEX ix_task_front_id ON task (front_id);

ALTER TABLE template_task ADD COLUMN template_front_id UUID;
ALTER TABLE template_task ADD CONSTRAINT fk_template_task_template_front_id FOREIGN KEY(template_front_id) REFERENCES template_front (id) ON DELETE SET NULL NOT VALID;

ALTER TABLE work_front ENABLE ROW LEVEL SECURITY;
ALTER TABLE work_front FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON work_front
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

ALTER TABLE template_front ENABLE ROW LEVEL SECURITY;
ALTER TABLE template_front FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON template_front
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
