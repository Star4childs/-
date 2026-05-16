from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/data")
def data(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_tab": "data"
    })

@app.get("/train")
def train(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_tab": "train"          # ← заменили на "train"
    })

@app.get("/predict")
def predict(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_tab": "predict"        # ← заменили на "predict"
    })

@app.get("/logs")
def logs(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "active_tab": "logs"           # ← заменили на "logs"
    })