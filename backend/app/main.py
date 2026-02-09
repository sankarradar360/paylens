from fastapi import FastAPI

app = FastAPI()


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/api/hello')
async def hello():
    return {'message': 'Hello from PayLens backend!'}
