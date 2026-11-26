-- Los datos demo de facturación insertan 'in', pero el modelo StockMovement
-- declara el valor 'in_'. Se normaliza para que la API pueda serializar la fila.
UPDATE mod_inventario.stock_movement
   SET movement_type = 'in_'
 WHERE movement_type = 'in';
