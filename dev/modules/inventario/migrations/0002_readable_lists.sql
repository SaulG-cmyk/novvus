-- inventario 0002: nombres legibles en stock y movimientos

ALTER TABLE stock_item ADD COLUMN IF NOT EXISTS product_name VARCHAR(200) NOT NULL DEFAULT '';
ALTER TABLE stock_movement ADD COLUMN IF NOT EXISTS product_name VARCHAR(200) NOT NULL DEFAULT '';

UPDATE stock_item s
   SET product_name = p.name
  FROM product p
 WHERE s.product_id = p.id AND s.product_name = '';

UPDATE stock_movement m
   SET product_name = p.name
  FROM product p
 WHERE m.product_id = p.id AND m.product_name = '';
