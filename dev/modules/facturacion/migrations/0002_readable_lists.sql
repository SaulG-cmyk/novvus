-- facturacion 0002: nombres legibles en listas

ALTER TABLE invoice ADD COLUMN IF NOT EXISTS customer_name VARCHAR(200) NOT NULL DEFAULT '';
ALTER TABLE invoice_line ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(40) NOT NULL DEFAULT '';
ALTER TABLE payment ADD COLUMN IF NOT EXISTS invoice_number VARCHAR(40) NOT NULL DEFAULT '';

UPDATE invoice_line l
   SET invoice_number = i.number
  FROM invoice i
 WHERE l.invoice_id = i.id AND l.invoice_number = '';

UPDATE payment p
   SET invoice_number = i.number
  FROM invoice i
 WHERE p.invoice_id = i.id AND p.invoice_number = '';
