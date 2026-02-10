from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os

app = FastAPI()


@app.get('/health')
async def health():
    return JSONResponse({'status': 'ok'})


@app.get('/api/hello')
async def hello():
    return JSONResponse({'message': 'Hello from PayLens backend!'})


# Serve built frontend when available
DIST_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'frontend', 'dist'))
if os.path.isdir(DIST_PATH):
    app.mount('/', StaticFiles(directory=DIST_PATH, html=True), name='frontend')
else:
    @app.get('/')
    async def index():
        return {'status': 'frontend not built'}
