# Guion · Cómo funciona Novvus

Notas del orador de la presentación `index.html`. En el navegador se muestran con la tecla **N**.
Duración objetivo: **33 – 35 minutos** más preguntas.

| Bloque | Diapositivas | Tiempo |
|---|---|---|
| Apertura: qué es y qué problema resuelve | 1 – 5 | 6:30 |
| Cómo está construido y cómo se instala | 6 – 13 | 10:30 |
| Recorrido por el sistema, con el agente | 14 – 23 | 11:00 |
| Integración y resultados | 24 – 28 | 6:00 |

---

## 01 · Cómo funciona Novvus

Abrir con la idea central: Novvus es una suite empresarial modular. A lo largo de esta presentación veremos qué problema resuelve, cómo está construida por dentro y cómo un clic en ventas termina en una factura sin que nadie capture dos veces el mismo dato. Todo lo que se muestra proviene de un ambiente real con datos cargados.

## 02 · Ocho módulos sobre un núcleo común

*01 · Introducción* · tiempo sugerido 1:30

Definición corta y tres cifras que ordenan la charla: ocho módulos, 116 tablas, un solo acceso. Aclarar que no se replicó un ERP completo: se priorizó un recorrido comercial verificable de punta a punta.

## 03 · Datos dispersos y captura duplicada

*02 · Problema* · tiempo sugerido 1:30

No atacar a Odoo ni a nadie: describir el costo real de la dispersión. La propuesta no es “más funciones”, es que el dato viaje una sola vez y quede registro de cada paso.

## 04 · Núcleo y módulos: responsabilidades separadas

*03 · Concepto* · tiempo sugerido 1:30

Analogía del edificio: el kernel es la recepción y el conserje —valida quién entra, a qué piso va y deja el registro—; cada módulo es una oficina especializada con su propio archivo. Ninguna oficina entra al archivo de otra.

## 05 · Catálogo de módulos

*04 · Módulos* · tiempo sugerido 1:00

No leer los ocho. Señalar tres o cuatro y decir que todos comparten la misma forma de instalarse: manifiesto, permisos, migraciones y eventos. La categoría la declara el propio módulo.

## 06 · Una interfaz común

*05 · Experiencia* · tiempo sugerido 1:00

Esta captura es la primera impresión del usuario. Insistir en que los números no son maquetas: vienen de la base, con 71 oportunidades y 116 empresas cargadas para la demostración.

## 07 · Capas y límites de confianza

*06 · Arquitectura* · tiempo sugerido 1:30

Recorrer las cinco filas de arriba abajo. Subrayar la consecuencia práctica: para agregar un módulo no se toca ni la web ni el kernel. Y si un módulo se compromete, no alcanza al usuario ni a la base. El diagrama con flechas está en el reporte técnico, capítulo 2.

## 08 · Ciclo de una petición

*07 · Petición* · tiempo sugerido 1:30

Recorrer los seis pasos con el dedo. Ejemplo concreto: abrir facturas del cliente X. El kernel comprueba el permiso facturacion.invoices.read, firma la llamada, el módulo consulta su esquema con RLS y el kernel anota la lectura.

## 09 · Componentes de la plataforma

*08 · Tecnologías* · tiempo sugerido 1:30

No entrar en cada librería. La idea es que cada tecnología está donde aporta: Rust en el borde de confianza, Python en el negocio, Postgres en el aislamiento. Mencionar que el SDK es lo que hace que ocho módulos se vean y se comporten igual.

## 10 · Requisitos de instalación

*09 · Requisitos* · tiempo sugerido 1:30

Separar tres audiencias: el usuario solo abre el navegador; el equipo técnico necesita WSL2 y Docker Engine, no Docker Desktop; producción exige TLS, secretos nuevos, respaldos fuera del servidor y monitoreo. Aclarar que 8 GB y 4 GB son el mínimo probado, no una recomendación de capacidad.

## 11 · Puesta en marcha

*10 · Instalación* · tiempo sugerido 1:30

No leer el bloque completo: señalar los tres momentos. Primero copiar el paquete a /opt/novvus; segundo, decidir si se restaura el respaldo de demo o se arranca vacío; tercero, construir el runtime de los módulos y abrirlo en el 8077. El bootstrap es idempotente: repetirlo no rompe nada.

## 12 · Seguridad centralizada

*11 · Seguridad* · tiempo sugerido 1:00

Aquí vale la pena la frase clave: la seguridad vive en el kernel y en la base, no en la buena voluntad de cada módulo. En la captura se ven los ocho usuarios de demostración con roles distintos.

## 13 · Esquema de la base de datos

*12 · Modelo de datos* · tiempo sugerido 1:00

Explicar la cadena como el recorrido del negocio: la empresa origina la oportunidad, la oportunidad se cotiza, la cotización se convierte en factura y en proyecto. Los importes se guardan como numeric(14,2), nunca como texto.

## 14 · Recorrido por la aplicación

Cambio de ritmo: hasta aquí la teoría, ahora el sistema. Avisar que todas las capturas son del ambiente de demostración, no maquetas.

## 15 · Inicio de sesión

*14 · Acceso* · tiempo sugerido 1:00

Si se hace demo en vivo, entrar con la cuenta de administración y luego cambiar a ventas@novvus.demo para mostrar que el menú cambia según el rol. Ese contraste explica los permisos mejor que cualquier diapositiva.

## 16 · Menú según módulos instalados

*15 · Menú* · tiempo sugerido 1:00

Aquí se ve por qué el menú nunca queda desfasado: no hay una lista escrita a mano en el código. Si un módulo se desinstala, desaparece; si el rol no lo autoriza, tampoco aparece. El contador de apps confirma el estado real.

## 17 · Oportunidades comerciales

*16 · CRM* · tiempo sugerido 1:00

Aquí empieza el recorrido que se va a seguir. Pedir al público que recuerde una oportunidad concreta de la tabla: al final vamos a ver su factura y su envío.

## 18 · Aceptación de una cotización

*17 · Disparador* · tiempo sugerido 1:30

Este es el momento clave de la presentación. En el sistema real se acepta la cotización y en segundos aparecen los registros. Si hay demo, hacerlo aquí mismo.

## 19 · Registros generados por eventos

*18 · Resultado* · tiempo sugerido 1:00

Hacer visible el hilo: el proyecto menciona la oportunidad, el envío lleva ENV-COT y la factura conserva el importe. Nadie escribió esos datos: los puso el listener.

## 20 · Ejecución y bitácora

*19 · Automatización* · tiempo sugerido 1:00

La automatización no es una caja negra: se puede abrir la corrida y ver qué hizo cada paso. Eso es lo que permite depurar un flujo sin leer código.

## 21 · Modo Agente

*20 · Inteligencia artificial* · tiempo sugerido 1:30

El agente no es un chat aparte: vive en la aplicación, con la sesión del usuario y sus permisos, y eso acota lo que puede ver y hacer. La captura muestra la ventana completa con el panel abierto a la derecha. Señalar que el modelo se elige en la propia interfaz y que la aprobación final sigue siendo humana.

## 22 · Informe NOM-011

*21 · Caso de uso* · tiempo sugerido 1:30

Recorrer los seis pasos en orden y detenerse en el folio SER/2025/07/048789. Aquí está el valor: una instrucción corta produce un expediente trazable y avisa a las personas. Decir de inmediato que es una conversación de ejemplo: en esta entrega no hay proveedor conectado y el agente lo declara si se le escribe.

## 23 · Reclutamiento, auditorías e inventario

*22 · Operación* · tiempo sugerido 1:00

Sirve para mostrar amplitud sin recorrer cada módulo. La idea: no son ocho sistemas distintos, son ocho aplicaciones con el mismo contrato.

## 24 · Eventos entre módulos

*23 · Integración* · tiempo sugerido 1:30

Comparar con una radio interna: quien transmite no sabe cuántos escuchan. Eso permite agregar un módulo nuevo sin tocar los existentes: solo se suscribe al evento.

## 25 · Eventos repetidos

*24 · Idempotencia* · tiempo sugerido 1:00

Este es el detalle que separa una demo de un sistema: los buses reintentan y los usuarios repiten clics. Sin idempotencia, la factura se duplica. Aquí se probó repitiendo el evento a propósito.

## 26 · Estructura de un módulo

*25 · Anatomía* · tiempo sugerido 1:30

Este es el código real de Facturación, resumido. Señalar las tres piezas: el manifiesto dice qué es y qué escucha; los modelos dicen qué guarda; module.py dice qué hace cuando llega el evento. El SDK genera lo demás.

## 27 · Incorporación de un módulo

*26 · Extensión* · tiempo sugerido 1:00

Los seis módulos añadidos se construyeron con este procedimiento. Enfatizar que el costo de sumar un área nueva es bajo: no se toca la plataforma, solo se declara el módulo.

## 28 · Resultados de la entrega

*27 · Alcance* · tiempo sugerido 1:00

Cifras para dar dimensión, no para memorizar. Lo importante es la columna de verificaciones: no solo existe, se probó. Si preguntan por rendimiento, remitir al reporte técnico, capítulo 11.

---

## Preguntas previsibles

- **¿Se puede usar sin internet?** Sí: la plataforma corre en contenedores dentro del servidor de la
  organización. Solo requiere red interna y un navegador.
- **¿Cuánto cuesta agregar un módulo?** Un manifiesto, sus modelos, sus migraciones y, si aplica, sus
  oyentes de eventos. No se recompila el kernel ni la capa web.
- **¿Qué pasa si dos usuarios aceptan la misma cotización?** La idempotencia y la llave de negocio
  evitan que se dupliquen el envío y la factura.
- **¿Dónde están los datos?** En PostgreSQL, con `org_id` y políticas RLS: la base filtra por
  organización, no el código del módulo.
- **¿Es fiscal?** No timbra ante la autoridad; emite y controla el documento y sus pagos.
- **¿El agente ya funciona?** La interfaz y el flujo están; falta conectar un proveedor de modelo.
  En esta entrega se muestra en modo demostración y el propio agente lo declara al escribirle.
- **¿Qué modelo usa?** Se elige en la interfaz; la captura muestra una opción, pero no hay
  proveedor enlazado en esta entrega, así que no se puede afirmar un modelo en operación.
- **¿Se puede instalar sin WSL2?** El camino probado es Windows con WSL2, Ubuntu y Docker
  Engine dentro de WSL. Docker Desktop no se usó; para producción, el criterio es un servidor
  con Docker Engine 24+, TLS y respaldos fuera del anfitrión.
