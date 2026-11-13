# Spec: Deployment

## Rules (current truth)

- **Docker image** (`Dockerfile`):
  - python 3.12-slim;
  - DejaVu fonts for the Georgian text on sheets;
  - Tesseract with Georgian and English.

  It runs `uvicorn app.main:app` on `$PORT`, or 8090 when that is unset.
- **Rebuild the image after any change in `app/`.** The backend calls whatever image is running.
- **Production:** Railway, https://arch-doc-gen-microservice-production.up.railway.app (running; `/health` answers `{"ok":true}`). Required setup:
  - `GEOMETRY_TOKEN` is a long random key, with the same value on the backend;
  - the backend's `GEOMETRY_SERVICE_URL` is this service;
  - keep the port reachable from the backend only;
  - use `/health` as the health check path.
- **`GEOMETRY_WORKERS`:** pages processed in parallel. Peak memory on gegmebi:
  - 1 worker about 360 MB;
  - 2 workers about 600 MB;
  - 4 workers about 1.1 GB.

  Use 1 worker on a 512 MB instance and 2 on 1–2 GB.
- **Local:**

  ```bash
  docker build -t archidocgen-geometry:dev .
  docker run --rm -p 8090:8090 archidocgen-geometry:dev
  ```

  The backend then uses `GEOMETRY_SERVICE_URL=http://localhost:8090`. Recent local runs used a
  container on 8097 with `app/` mounted.

## Related

Backend environment: `georgian-arch-gen-backend/specs/deployment.md`.
