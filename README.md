# ArchiDocGen geometry service

A Python service (FastAPI, PyMuPDF, OpenCV) that reads architects' PDFs and draws the occupancy,
fire and accessibility sheets from the real CAD geometry. The ArchiDocGen backend calls it.

- Start here: [CLAUDE.md](CLAUDE.md).
- Rules per feature: [specs/](specs/).
- The previous long README (scores and lessons as of October 2026) is in
  [docs/archive/README-2026-10.md](docs/archive/README-2026-10.md); its still-true parts are now in
  `specs/`.

```bash
docker build -t archidocgen-geometry:dev .
docker run --rm -p 8090:8090 archidocgen-geometry:dev
```
