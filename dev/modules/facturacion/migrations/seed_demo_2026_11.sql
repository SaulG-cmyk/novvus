-- Datos demo: facturación e inventario (idempotente por folio/SKU)
SET app.org_id = '01a1a51b-372e-74f3-b194-1b03e034628e';

-- ---------- FACTURACIÓN ----------
INSERT INTO mod_facturacion.invoice
  (org_id, number, customer_name, status, issue_date, due_date, currency, subtotal, tax, total, paid_amount, notes)
VALUES
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-001','Grupo Alucaps Mexicana','paid','2026-09-05','2026-10-05','MXN',52000,8320,60320,60320,'Servicio de ingeniería y montaje'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-002','Sánchez y Martín','paid','2026-09-18','2026-10-18','MXN',18500,2960,21460,21460,'Mantenimiento preventivo'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-003','INTERPUERTO SALINAS','overdue','2026-09-22','2026-10-22','MXN',34000,5440,39440,0,'Suministro de refacciones'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-004','Productos Mendoza','paid','2026-10-01','2026-10-31','MXN',7500,1200,8700,8700,'Auditoría de calidad'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-005','Cementos del Bajío','overdue','2026-10-06','2026-11-05','MXN',26800,4288,31088,10000,'Proyecto de automatización'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-006','TUBACERO','sent','2026-10-14','2026-11-14','MXN',41200,6592,47792,0,'Fabricación de estructura metálica'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-007','CAJAS DE CARTÓN CONVERBOX','sent','2026-10-21','2026-11-21','MXN',52000,8320,60320,0,'Línea de empaque'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-008','Sipro','paid','2026-10-27','2026-11-27','MXN',9600,1536,11136,11136,'Consultoría técnica'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-009','Guanajuato Tooling','draft','2026-11-02','2026-12-02','MXN',14800,2368,17168,0,'Propuesta de mejora continua'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-010','Aceros y Corrugados','sent','2026-11-06','2026-12-06','MXN',22750,3640,26390,0,'Instalación eléctrica industrial'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-011','Maderas Concordia','draft','2026-11-10','2026-12-10','MXN',6400,1024,7424,0,'Diagnóstico de procesos'),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','FAC-2026-012','SYSCOM Querétaro','paid','2026-11-12','2026-12-12','MXN',31000,4960,35960,35960,'Integración de sistemas')
ON CONFLICT DO NOTHING;

INSERT INTO mod_facturacion.invoice_line
  (org_id, invoice_id, invoice_number, description, quantity, unit_price, tax_rate, line_total)
SELECT i.org_id, i.id, i.number, 'Servicio profesional: ' || i.customer_name, 1, i.subtotal, 16, i.subtotal
  FROM mod_facturacion.invoice i
 WHERE i.number LIKE 'FAC-2026-%'
   AND NOT EXISTS (SELECT 1 FROM mod_facturacion.invoice_line l WHERE l.invoice_id = i.id);

INSERT INTO mod_facturacion.payment
  (org_id, invoice_id, invoice_number, amount, payment_date, method, reference, notes)
SELECT i.org_id, i.id, i.number, i.paid_amount,
       COALESCE(i.due_date, CURRENT_DATE) - 3, 'transfer', 'TRF-' || i.number, 'Pago recibido'
  FROM mod_facturacion.invoice i
 WHERE i.paid_amount > 0
   AND NOT EXISTS (SELECT 1 FROM mod_facturacion.payment p WHERE p.invoice_id = i.id);

-- ---------- INVENTARIO ----------
INSERT INTO mod_inventario.product (org_id, sku, name, description, unit, price, is_active)
VALUES
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-001','Perfil estructural 4"','Acero galvanizado calibre 14','pz',890.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-002','Placa de acero 1/4"','Placa laminada en caliente','pz',1450.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-003','Tornillo hexagonal 1/2"','Grado 8, caja de 100 piezas','cja',320.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-004','Soldadura E6013','Electrodo 3/32, caja de 5 kg','cja',410.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-005','Pintura epóxica gris','Bidón de 19 litros','bid',2980.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-006','Cable THW calibre 10','Rollo de 100 m','rollo',2150.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-007','Contactor 40 A','Trifásico 220 V','pz',780.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-008','Guarda motor 25 A','Con ajuste térmico','pz',650.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-009','Rodamiento 6205','Balero sellado','pz',185.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-010','Banda dentada 8M','Perfil industrial 1200 mm','pz',540.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-011','Sensor inductivo M12','PNP, 24 V, IP67','pz',1290.00,true),
  ('01a1a51b-372e-74f3-b194-1b03e034628e','INV-012','Kit de seguridad PPE','Casco, lentes, guantes y chaleco','kit',950.00,true)
ON CONFLICT DO NOTHING;

INSERT INTO mod_inventario.stock_item
  (org_id, product_id, product_name, quantity, min_stock, location)
SELECT p.org_id, p.id, p.name,
       3 + (row_number() OVER (ORDER BY p.sku) * 7) % 40,
       CASE WHEN p.sku IN ('INV-003','INV-009','INV-011') THEN 12 ELSE 5 END,
       CASE WHEN p.sku LIKE '%0' THEN 'Almacén principal · A-2' ELSE 'Almacén principal · B-1' END
  FROM mod_inventario.product p
 WHERE NOT EXISTS (SELECT 1 FROM mod_inventario.stock_item s WHERE s.product_id = p.id);

INSERT INTO mod_inventario.stock_movement
  (org_id, product_id, product_name, movement_type, quantity, reference, notes, movement_date)
SELECT s.org_id, s.product_id, s.product_name, 'in', s.quantity, 'OC-2026-' || right(s.product_name, 2),
       'Recepción de compra', now() - (interval '10 days' * (row_number() OVER (ORDER BY s.product_name)))
  FROM mod_inventario.stock_item s
 WHERE NOT EXISTS (
   SELECT 1 FROM mod_inventario.stock_movement m WHERE m.product_id = s.product_id AND m.movement_type = 'in'
 );

INSERT INTO mod_inventario.stock_movement
  (org_id, product_id, product_name, movement_type, quantity, reference, notes, movement_date)
SELECT s.org_id, s.product_id, s.product_name, 'out', 2, 'ENV-' || lpad((row_number() OVER (ORDER BY s.product_name))::text, 3, '0'),
       'Salida por envío a cliente', now() - (interval '2 days' * (row_number() OVER (ORDER BY s.product_name)))
  FROM mod_inventario.stock_item s
 WHERE NOT EXISTS (
   SELECT 1 FROM mod_inventario.stock_movement m WHERE m.product_id = s.product_id AND m.movement_type = 'out'
 );

ALTER TABLE mod_inventario.product OWNER TO novvus_mod_inventario_owner;
ALTER TABLE mod_inventario.stock_item OWNER TO novvus_mod_inventario_owner;
ALTER TABLE mod_inventario.stock_movement OWNER TO novvus_mod_inventario_owner;
ALTER TABLE mod_facturacion.invoice OWNER TO novvus_mod_facturacion_owner;
ALTER TABLE mod_facturacion.invoice_line OWNER TO novvus_mod_facturacion_owner;
ALTER TABLE mod_facturacion.payment OWNER TO novvus_mod_facturacion_owner;
