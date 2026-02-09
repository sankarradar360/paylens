# PayLens

Minimal scaffold: FastAPI backend and React (Vite) frontend with Docker and GitHub Actions.

Prerequisites:
- Docker & docker-compose
- Node.js v16+ and npm
- Python 3.11+

Run locally with docker-compose:

```bash
docker-compose up --build
```

Backend: http://localhost:8000
Frontend: http://localhost:3000

CI:
- GitHub Actions workflow builds and pushes images to Docker Hub using secrets.
