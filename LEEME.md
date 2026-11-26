# Novvus — Sistema de gestión modular

Paquete de entrega del proyecto **Novvus**: plataforma en contenedores, ocho módulos de negocio,
datos de demostración, código fuente de los módulos propios y documentación de usuario y técnica.

Versión del núcleo: **0.3.72** · Noviembre de 2026

---

## 1. Contenido del paquete

| Ruta | Contenido |
|---|---|
| `Manual-Usuario-Novvus.pdf` | Manual de usuario, 31 páginas, con 19 capturas y 8 diagramas. |
| `Reporte-Tecnico-Novvus.pdf` | Reporte técnico, 30 páginas: arquitectura, tecnologías, despliegue y pruebas. |
| `Presentacion-Novvus.pdf` | Presentación de 28 diapositivas en 16:9: qué es Novvus, stack, requisitos de instalación, recorrido con capturas, el modo agente con un ejemplo, anatomía de un módulo e integración. |
| `Evidencia-Docker.pdf` | Anexo de dos páginas: las siete imágenes del host con su digest `sha256`, los once contenedores con su healthcheck, una captura del terminal, el consumo en disco y la imagen del módulo CRM con su archivo. |
| `presentacion/` | Fuente HTML de la presentación (`index.html`, se abre en el navegador) y `guion.md` con las notas del orador. |
| `documentacion/` | Fuentes HTML de ambos documentos y la hoja de estilo compartida (`assets/doc.css`). |
| `capturas/` | Las 21 capturas de pantalla en PNG (1526 × 730; el panel del agente, 468 × 638). |
| `diagramas/` | Los 8 diagramas en SVG vectorial (arquitectura, despliegue, modelo, flujos, eventos). |
| `codigo/sdk/` | SDK de módulos de Novvus (Python). |
| `codigo/modules/` | Los seis módulos propios: reclutamiento, logística, auditorías, automatización, facturación, inventario. |
| `codigo/crm-module/`, `codigo/projects-module/` | Módulos base con ajustes locales (campos desnormalizados, integración). |
| `codigo/Dockerfile.modulo` | Imagen de ejecución de los módulos, con el SDK entregado. |
| `docker/` | Composición de la plataforma, superposición de módulos, `.env` de demostración, respaldo y script de arranque de los módulos propios. |
| `docker/modules-base/` | Manifiesto y migraciones de los módulos base (`crm`, `projects`), que el instalador coloca en `/opt/novvus/modules`. Son necesarios para que el arranque instale esos módulos. |
| `evidencia/` | Registro del host (`docker-evidencia.txt`), captura del terminal (`terminal-docker.png`), la imagen del módulo CRM (`crm-0.2.20.tar.gz` con su `.sha256`), el script que genera el registro (`collect.sh`) y la fuente HTML del anexo. |

---

## 2. Requisitos

- Windows 10/11 con **WSL2** y una distribución Ubuntu.
- **Docker Engine 24 o superior** dentro de WSL. El ambiente se probó con Engine nativo en Ubuntu, no con Docker Desktop.
- 8 GB de RAM y 4 GB libres en disco.
- Acceso al registro `ghcr.io/novvus` para las imágenes del núcleo (`core`, `web`, `bootstrap`, `crm`, `projects`).
- Un navegador basado en Chromium (Chrome, Edge, Brave).

Las imágenes del núcleo son **comerciales**: se consumen como contenedores versionados. El código
fuente entregado corresponde al SDK y a los módulos, que es donde vive la lógica de negocio.

---

## 3. Puesta en marcha

### 3.1 Preparar el directorio

Desde WSL, con este paquete descomprimido en `/mnt/c/.../Novvus-Sistema`:

```bash
sudo mkdir -p /opt/novvus
sudo cp -r /mnt/c/Users/<usuario>/Desktop/Novvus-Sistema/docker/. /opt/novvus/
cd /opt/novvus
```

El archivo `.env` incluido trae los valores de la demostración (contraseña de base, secretos JWT y
token de arranque). Sirve para reproducir el ambiente tal cual; **para producción hay que regenerar
cada secreto** con `openssl rand -hex 32`.

La carpeta `modules-base/` del paquete contiene el manifiesto y las migraciones de `crm` y `projects`.
El instalador oficial los deja en `/opt/novvus/modules`; si parte de este paquete, cópielos antes de
arrancar:

```bash
sudo mkdir -p /opt/novvus/modules
sudo cp -r /opt/novvus/modules-base/. /opt/novvus/modules/
```

### 3.2 Restaurar la base de demostración

Se levanta primero solo PostgreSQL, se restaura el respaldo y después el resto de la plataforma:

```bash
docker compose -f docker-compose.yml -f modules.compose.yml up -d postgres

docker exec -i novvus-prod-postgres-1 \
  pg_restore -U novvus -d novvus --clean --if-exists --no-owner < novvus_demo.dump

docker compose -f docker-compose.yml -f modules.compose.yml up -d
```

El servicio `bootstrap` se ejecuta una vez, aplica las migraciones pendientes de cada módulo y
publica los tokens de servicio. Es idempotente: volver a ejecutarlo sobre una base existente es seguro.

### 3.3 Levantar los módulos propios

Los seis módulos entregados corren junto al kernel, compartiendo su red, y se montan desde el código:

```bash
docker pull ghcr.io/novvus/crm@sha256:30ef4a9f9138007b84f82c06c99140abb1fbc399b693cfbd918462fdec1cc8a4
docker build -f /mnt/c/Users/<usuario>/Desktop/Novvus-Sistema/codigo/Dockerfile.modulo \
  -t novvus-runtime:local /mnt/c/Users/<usuario>/Desktop/Novvus-Sistema/codigo

IMAGE=novvus-runtime:local \
CODE=/mnt/c/Users/<usuario>/Desktop/Novvus-Sistema/codigo/modules \
bash /opt/novvus/run-modulos.sh
```

`run-modulos.sh` usa los tokens de servicio de `modulos.env`, que ya corresponden a la base de
demostración. Si restaura sobre otra instalación, instale cada módulo desde la interfaz y copie el
token que muestra su detalle en `modulos.env`.

### 3.4 Acceso

Abrir <http://localhost:8077>.

| Cuenta | Contraseña | Perfil |
|---|---|---|
| `saulgutierrez143@gmail.com` | `request1` | Administrador |
| `ventas@novvus.demo` | `Demo2026!` | Ventas / CRM |
| `proyectos@novvus.demo` | `Demo2026!` | Proyectos |
| `logistica@novvus.demo` | `Demo2026!` | Logística |
| `rrhh@novvus.demo` | `Demo2026!` | Reclutamiento |
| `auditoria@novvus.demo` | `Demo2026!` | Auditorías |
| `automatizacion@novvus.demo` | `Demo2026!` | Automatización |

Estas credenciales son exclusivas del entorno de demostración local. No las reutilices en un despliegue real: crea cuentas nuevas y rota todos los secretos antes de exponer la plataforma.

Organización de demostración: `01a1a51b-372e-74f3-b194-1b03e034628e`.

---

## 4. Operación diaria

```bash
cd /opt/novvus

# estado de los servicios
docker ps --format "table {{.Names}}\t{{.Status}}"

# registros del kernel (errores de enrutamiento, autenticación)
docker logs --tail 100 novvus-prod-kernel-1

# respaldo de la base
docker exec novvus-prod-postgres-1 pg_dump -U novvus -Fc novvus > novvus_$(date +%F).dump

# levantar o actualizar
docker compose -f docker-compose.yml -f modules.compose.yml up -d
```

Cada módulo expone `GET /health`; la capa web muestra un aviso cuando un módulo no responde y el
kernel registra el error de enrutamiento. El volumen `pgdata` conserva la base entre recreaciones.

---

## 5. Código fuente

```
codigo/
├── Dockerfile.modulo        imagen de ejecución con el SDK entregado
├── sdk/                     SDK: modelos, vistas, permisos, migraciones, eventos
├── crm-module/              módulo CRM (base, con ajustes locales)
├── projects-module/         módulo Proyectos (base, con ajustes locales)
└── modules/
    ├── reclutamiento/       vacantes, candidatos, entrevistas, ofertas
    ├── logistica/           almacenes, envíos, transportistas, órdenes de entrega
    ├── auditorias/          auditorías, listas de verificación, hallazgos, informes
    ├── automatizacion/      procesos, pasos, ejecuciones, bitácoras, notificaciones
    ├── facturacion/         facturas, líneas, pagos
    └── inventario/          productos, existencias, movimientos
```

Cada módulo declara su manifiesto `novvus.toml` (identificador, puerto, permisos, eventos que emite
y escucha), sus modelos, sus vistas y sus migraciones versionadas (`migrations/0001_*.sql`…).

Para crear un módulo nuevo: copie la estructura de `modules/auditorias`, ajuste el manifiesto y los
modelos, y añada una migración. El SDK genera la API REST y aplica el aislamiento por organización.

---

## 6. Puertos

| Servicio | Puerto | Publicado |
|---|---|---|
| web | 8077 → 3000 | Sí, único puerto expuesto |
| kernel | 8000 | No (red interna) |
| postgres | 5432 | No (red interna) |
| crm | 8110 | No (red del kernel) |
| projects | 8120 | No (red del kernel) |
| reclutamiento | 8140 | No (red del kernel) |
| logistica | 8150 | No (red del kernel) |
| auditorias | 8160 | No (red del kernel) |
| automatizacion | 8170 | No (red del kernel) |
| facturacion | 8180 | No (red del kernel) |
| inventario | 8190 | No (red del kernel) |

---

## 7. Evidencia de imágenes y contenedores

`Evidencia-Docker.pdf` resume el ambiente que produjo las capturas: siete imágenes con su referencia,
tamaño y digest `sha256`, once contenedores con su healthcheck en verde, una captura del terminal y el
consumo en disco. Las imágenes del núcleo son comerciales y **no se redistribuyen**; su huella es la
evidencia verificable.

La única imagen que sí se redistribuye es la del módulo CRM (`ghcr.io/saulg-cmyk/crm:0.2.20`), porque
es propia: va comprimida en `evidencia/crm-0.2.20.tar.gz` (67.4 MB) junto a su suma de verificación.
Es la base que ejecutan los seis módulos de desarrollo, con el código de cada uno montado en
`/app/module`. Para comprobarla e importarla:

```bash
cd /mnt/c/ruta/al/paquete/evidencia
sha256sum -c crm-0.2.20.tar.gz.sha256
docker load -i crm-0.2.20.tar.gz
docker image inspect ghcr.io/saulg-cmyk/crm:0.2.20 --format '{{json .RepoDigests}}'
```

`evidencia/` guarda además el registro crudo (`docker-evidencia.txt`), la captura del terminal
(`terminal-docker.png`), el script que genera el registro (`collect.sh`) y la fuente HTML del anexo.
Desde WSL, con la ruta del paquete:

```bash
bash /mnt/c/ruta/al/paquete/evidencia/collect.sh
```

El script escribe el registro junto a sí mismo y no modifica el sistema: solo consulta
`docker images`, `docker ps` y `docker inspect`.

---

## 8. Documentación

- `Manual-Usuario-Novvus.pdf`: qué es Novvus, primeros pasos, módulos, flujos guiados, buenas
  prácticas, preguntas frecuentes, glosario y anexos.
- `Reporte-Tecnico-Novvus.pdf`: problema y alcance, arquitectura, tecnologías, catálogo de módulos,
  modelo de datos, integración por eventos, seguridad, flujo funcional con evidencia, despliegue,
  proceso de construcción, pruebas y conclusiones.
- `Presentacion-Novvus.pdf`: 28 diapositivas para exponer el sistema, con requisitos de instalación,
  el modo agente y un ejemplo de expediente. Cada lámina trae su nota del orador en
  `presentacion/guion.md`.
- `Evidencia-Docker.pdf`: anexo de dos páginas con el digest de cada imagen, el estado de los
  contenedores, una captura del terminal, el consumo en disco y la imagen del módulo CRM con su
  archivo; el registro se regenera con `evidencia/collect.sh`.
- `presentacion/index.html`: fuente de la presentación. Se abre en el navegador; las flechas navegan,
  `N` muestra las notas, `F` entra a pantalla completa y `@media print` produce el PDF 16:9.
- `documentacion/*.html`: las fuentes de ambos PDF. Se regeneran con la impresión de Chromium:
  ```bash
  msedge --headless=new --no-pdf-header-footer --virtual-time-budget=12000 \
    --print-to-pdf=Manual-Usuario-Novvus.pdf documentacion/manual-usuario.html
  ```
- `diagramas/*.svg` y `capturas/*.png`: material editable e insertable en otras presentaciones.

---

## 9. Límites conocidos

- **Núcleo comercial.** El kernel y la capa web se distribuyen como imágenes; no se entrega su código.
- **Correo.** No hay proveedor SMTP configurado: las automatizaciones registran el envío en su bitácora
  pero no sale correo a Internet.
- **Facturación operativa.** No incluye timbrado, cancelación ante autoridad fiscal ni contabilidad electrónica.
- **Tableros kanban de los módulos añadidos.** No muestran tarjetas en esta versión; la vista de lista sí
  funciona y es la recomendada.
- **Un solo equipo.** El respaldo vive en el mismo anfitrión que la base; para producción hay que copiarlo
  fuera y probar la restauración.
- **Escritorio.** La interfaz se diseñó para pantallas de escritorio; no se evaluó en tablet ni teléfono.

---

## 10. Volumen de datos de la demostración

116 empresas, 44 contactos, 6 leads, 71 oportunidades, 20 actividades, 5 cotizaciones, 11 proyectos,
5 candidatos, 4 envíos, 2 auditorías, 3 hallazgos, 13 facturas, 8 pagos, 13 productos, 26 movimientos
de inventario y 9 procesos de automatización; 8 usuarios, 9 roles y 2 organizaciones.
El respaldo incluye los registros con borrado lógico que la interfaz no muestra.
