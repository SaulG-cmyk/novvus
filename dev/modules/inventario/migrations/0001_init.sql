-- inventario 0001: initial schema

CREATE TABLE product (
    sku VARCHAR(60) NOT NULL DEFAULT '',
    name VARCHAR(200) NOT NULL,
    description VARCHAR(4000) NOT NULL DEFAULT '',
    unit VARCHAR(20) NOT NULL DEFAULT 'pz',
    price NUMERIC(14,2) NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT true,
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
CREATE INDEX ix_product_org_id ON product (org_id);
ALTER TABLE product ENABLE ROW LEVEL SECURITY;
ALTER TABLE product FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON product
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE stock_item (
    product_id UUID NOT NULL,
    warehouse_id UUID,
    quantity NUMERIC(12,2) NOT NULL DEFAULT 0,
    min_stock NUMERIC(12,2) NOT NULL DEFAULT 0,
    location VARCHAR(120) NOT NULL DEFAULT '',
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);
CREATE INDEX ix_stock_item_org_id ON stock_item (org_id);
ALTER TABLE stock_item ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_item FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stock_item
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE stock_movement (
    product_id UUID NOT NULL,
    warehouse_id UUID,
    movement_type VARCHAR(20) NOT NULL DEFAULT 'in',
    quantity NUMERIC(12,2) NOT NULL DEFAULT 0,
    reference VARCHAR(120) NOT NULL DEFAULT '',
    notes VARCHAR(4000) NOT NULL DEFAULT '',
    movement_date TIMESTAMP WITH TIME ZONE,
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL,
    ext JSONB DEFAULT '{}'::jsonb NOT NULL,
    custom JSONB DEFAULT '{}'::jsonb NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
    deleted_at TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id)
);
CREATE INDEX ix_stock_movement_org_id ON stock_movement (org_id);
ALTER TABLE stock_movement ENABLE ROW LEVEL SECURITY;
ALTER TABLE stock_movement FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON stock_movement
    USING (org_id = current_setting('app.org_id')::uuid)
    WITH CHECK (org_id = current_setting('app.org_id')::uuid);

CREATE TABLE IF NOT EXISTS _processed_events (
    event_id uuid PRIMARY KEY,
    processed_at timestamptz NOT NULL DEFAULT now()
);