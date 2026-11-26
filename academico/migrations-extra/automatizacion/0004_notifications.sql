-- Migración añadida por el entorno académico.
-- El módulo declara el modelo Notification, pero su paquete no incluye la tabla.
-- Esta migración permite probar el recurso `notifications` sin tocar el código de la empresa.

CREATE TABLE IF NOT EXISTS notification (
    user_id UUID,
    title VARCHAR(200) NOT NULL,
    message VARCHAR(4000) DEFAULT '' NOT NULL,
    kind VARCHAR(40) DEFAULT 'info' NOT NULL,
    is_read BOOLEAN DEFAULT false NOT NULL,
    link VARCHAR(500) DEFAULT '' NOT NULL,
    id UUID NOT NULL,
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);

CREATE INDEX IF NOT EXISTS ix_notification_org_id ON notification (org_id);

ALTER TABLE notification ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON notification;
CREATE POLICY tenant_isolation ON notification
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);
