# Backend (FastAPI)

Run locally:

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Docker:

```bash
docker build -t paylens-backend ./backend
docker run -p 8000:8000 paylens-backend
```
