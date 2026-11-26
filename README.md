# Novvus

Plataforma de gestión empresarial que corre en contenedores: ocho módulos de negocio sobre un núcleo propio escrito en Rust, una capa web en Next.js y PostgreSQL 16. Aísla los datos por organización, conecta los módulos por eventos y expone un modo agente para operar el sistema en lenguaje natural.

Versión del núcleo: **0.3.72** · Noviembre de 2026

## Estructura

| Ruta | Qué es |
|---|---|
| `dev/` | Código fuente en desarrollo: SDK, los seis módulos propios, los módulos base y el entorno de pruebas. |
| `entrega/` | Paquete de entrega: PDFs, fuentes HTML, capturas, diagramas y evidencia del host. |
| `documentación-html/` | Sitio de documentación técnica en HTML. |
| `process_steps.csv` | Registro de pasos del proceso de construcción. |
| `LEEME.md` | Guía de instalación y operación, paso a paso. |

## Entrega

- `entrega/Manual-Usuario-Novvus.pdf` — manual de usuario, 31 páginas.
- `entrega/Reporte-Tecnico-Novvus.pdf` — reporte técnico, 30 páginas.
- `entrega/Presentacion-Novvus.pdf` — presentación de 28 diapositivas en 16:9.
- `entrega/Evidencia-Docker.pdf` — anexo de dos páginas con imágenes, contenedores y captura del host.
- `entrega/documentacion/` — fuentes HTML de los dos PDF y hoja de estilo.
- `entrega/presentacion/` — fuente HTML de las diapositivas y `guion.md` con las notas.
- `entrega/capturas/`, `entrega/diagramas/` — 21 capturas PNG y 8 diagramas SVG.
- `entrega/evidencia/` — registro del host, captura del terminal y la imagen del módulo CRM con su suma de verificación.

## Puesta en marcha

Los requisitos y el procedimiento completo están en `LEEME.md`. En resumen:

1. Windows 10/11 con WSL2 y Ubuntu, Docker Engine 24 o superior dentro de WSL (no Docker Desktop), 8 GB de RAM y 4 GB libres.
2. Acceso al registro `ghcr.io/novvus` para las imágenes del núcleo.
3. Copiar `entrega/_build/docker/` a `/opt/novvus`, copiar `.env.example` a `.env`, generar los secretos con `openssl rand -hex 32` y levantar el compose:

```bash
docker compose -f docker-compose.yml -f modules.compose.yml up -d
```

La interfaz queda en `http://localhost:8077`.

## Evidencia

Las imágenes del núcleo son comerciales y no se redistribuyen: la evidencia es su huella `sha256` y el estado del host donde corren. La imagen del módulo CRM es propia y pública en `ghcr.io/saulg-cmyk/crm:0.2.20`; el archivo comprimido `entrega/evidencia/crm-0.2.20.tar.gz` se conserva en el entorno de trabajo pero no se versiona: se puede obtener con `docker pull ghcr.io/saulg-cmyk/crm:0.2.20` y comprobar con el `.sha256` que sí está en el repositorio.
