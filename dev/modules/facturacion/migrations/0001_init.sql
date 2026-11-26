-- facturacion 0001: initial schema

CREATE TABLE invoice (
    number VARCHAR(40) NOT NULL DEFAULT '',
    company_id UUID,
    contact_id UUID,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    issue_date DATE,
    due_date DATE,
    currency VARCHAR(3) NOT NULL DEFAULT 'MXN',
    subtotal NUMERIC(14,2) NOT NULL DEFAULT 0,
    tax NUMERIC(14,2) NOT NULL DEFAULT 0,
    total NUMERIC(14,2) NOT NULL DEFAULT 0,
    paid_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    notes VARCHAR(4000) NOT NULL DEFAULT '',
    owner_user_id UUID,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);
CREATE INDEX ix_invoice_org_id ON invoice (org_id);
ALTER TABLE invoice ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON invoice
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE invoice_line (
    invoice_id UUID NOT NULL,
    description VARCHAR(400) NOT NULL DEFAULT '',
    quantity NUMERIC(12,2) NOT NULL DEFAULT 1,
    unit_price NUMERIC(14,2) NOT NULL DEFAULT 0,
    tax_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
    line_total NUMERIC(14,2) NOT NULL DEFAULT 0,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(invoice_id) REFERENCES invoice (id) ON DELETE CASCADE
);
CREATE INDEX ix_invoice_line_org_id ON invoice_line (org_id);
ALTER TABLE invoice_line ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_line FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON invoice_line
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE payment (
    invoice_id UUID NOT NULL,
    amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    payment_date DATE,
    method VARCHAR(20) NOT NULL DEFAULT 'transfer',
    reference VARCHAR(120) NOT NULL DEFAULT '',
    notes VARCHAR(4000) NOT NULL DEFAULT '',
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    FOREIGN KEY(invoice_id) REFERENCES invoice (id) ON DELETE CASCADE
);
CREATE INDEX ix_payment_org_id ON payment (org_id);
ALTER TABLE payment ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON payment
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE IF NOT EXISTS _processed_events (
    event_id uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);