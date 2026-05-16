import datetime
import io
import csv
import os
import uuid
import httpx
from fastapi import FastAPI, Request, File, UploadFile, Form
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse
import openpyxl
from openpyxl.utils import get_column_letter

app = FastAPI()

# Секретный ключ для сессий
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-change-in-production")

# Папка для загрузок
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

templates = Jinja2Templates(directory="templates")

# Внешний API
EXTERNAL_API_BASE = "http://5.129.248.80:8000"

# ------------- Вспомогательные функции -------------
def get_session_dir(session_id: str) -> str:
    """Путь к папке сессии."""
    path = os.path.join(UPLOAD_DIR, session_id)
    os.makedirs(path, exist_ok=True)
    return path

def log_action(session: dict, action: str, response: str):
    """Добавление записи в лог сессии."""
    if "logs" not in session:
        session["logs"] = []
    session["logs"].append({
        "id": len(session["logs"]) + 1,
        "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "action": action,
        "response": response
    })

async def fetch_models(client: httpx.AsyncClient) -> list[str]:
    """Получить список доступных моделей с внешнего API."""
    try:
        resp = await client.get(f"{EXTERNAL_API_BASE}/models")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "models" in data:
            return data["models"]
        if isinstance(data, list):
            return data
        return []
    except Exception as e:
        print(f"Ошибка получения моделей: {e}")
        return []

async def call_train_api(client: httpx.AsyncClient, model_name: str,
                         file_path: str, start_row: int, end_row: int) -> dict:
    """Отправить запрос на обучение во внешний API."""
    with open(file_path, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        train_data = [row for i, row in enumerate(reader) if start_row - 1 <= i < end_row]

    payload = {"model": model_name, "data": train_data}
    resp = await client.post(f"{EXTERNAL_API_BASE}/train", json=payload)
    resp.raise_for_status()
    return resp.json()

# ------------- Маршруты -------------

@app.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html", {"show_welcome": True})

@app.post("/start")
async def start(request: Request):
    return RedirectResponse(url="/data", status_code=303)

# Вкладка "Данные" (GET) – теперь показывает сохранённые данные
@app.get("/data")
async def data_get(request: Request):
    session = request.session
    session_id = session.get("session_id")
    context = {"active_tab": "data"}
    if session_id:
        file_path = os.path.join(get_session_dir(session_id), "data.csv")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'rb') as f:
                    content = f.read()
                encodings = ['utf-8', 'windows-1251', 'cp1251', 'latin-1']
                text = None
                for enc in encodings:
                    try:
                        text = content.decode(enc)
                        break
                    except UnicodeDecodeError:
                        continue
                if text:
                    reader = csv.reader(io.StringIO(text))
                    headers = next(reader, None)
                    if headers:
                        all_rows = [row[:len(headers)] for row in reader]
                        n = session.get("n", 5)
                        rows_display = all_rows[:n]
                        context["headers"] = headers
                        context["rows"] = rows_display
                        context["n"] = n
                        context["filename"] = os.path.basename(file_path)
                        context["session_id"] = session_id
            except Exception:
                pass
    return templates.TemplateResponse(request, "index.html", context)

# Загрузка CSV (POST)
@app.post("/data")
async def data_post(request: Request, file: UploadFile = File(...), n: int = Form(5)):
    if not file.filename.endswith('.csv'):
        log_action(request.session, f"Загрузка CSV-файла {file.filename}", "Ошибка: неверный формат")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "data",
            "error": "Пожалуйста, загрузите файл в формате CSV."
        })

    session = request.session
    if "session_id" not in session:
        session["session_id"] = str(uuid.uuid4())
    session_id = session["session_id"]
    session_dir = get_session_dir(session_id)

    file_path = os.path.join(session_dir, "data.csv")
    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    encodings = ['utf-8', 'windows-1251', 'cp1251', 'latin-1']
    text = None
    for enc in encodings:
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        log_action(session, f"Загрузка CSV-файла {file.filename}", "Ошибка: кодировка не определена")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "data",
            "error": "Не удалось прочитать файл."
        })

    try:
        reader = csv.reader(io.StringIO(text))
        headers = next(reader, None)
        if not headers:
            log_action(session, f"Загрузка CSV-файла {file.filename}", "Ошибка: файл пуст")
            return templates.TemplateResponse(request, "index.html", {
                "active_tab": "data",
                "error": "Файл пуст или повреждён."
            })
        all_rows = [row[:len(headers)] for row in reader]
        rows_display = all_rows[:n]
    except Exception:
        log_action(session, f"Загрузка CSV-файла {file.filename}", "Ошибка: структура повреждена")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "data",
            "error": "Ошибка при чтении CSV."
        })

    session["n"] = n
    log_action(session, f"Загрузка CSV-файла {file.filename}", "ОК")
    return templates.TemplateResponse(request, "index.html", {
        "active_tab": "data",
        "headers": headers,
        "rows": rows_display,
        "n": n,
        "filename": file.filename,
        "session_id": session_id
    })

# Вкладка "Обучение" (GET)
# Вкладка "Аналитика" (GET)
@app.get("/analytics")
async def analytics_get(request: Request):
    session = request.session
    session_id = session.get("session_id")
    context = {"active_tab": "analytics"}

    if not session_id:
        context["no_data"] = True
        return templates.TemplateResponse(request, "index.html", context)

    file_path = os.path.join(get_session_dir(session_id), "data.csv")
    if not os.path.exists(file_path):
        context["no_data"] = True
        return templates.TemplateResponse(request, "index.html", context)

    try:
        with open(file_path, 'rb') as f:
            content = f.read()
        encodings = ['utf-8', 'windows-1251', 'cp1251', 'latin-1']
        text = None
        for enc in encodings:
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if not text:
            context["no_data"] = True
            return templates.TemplateResponse(request, "index.html", context)

        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames
        if not headers:
            context["no_data"] = True
            return templates.TemplateResponse(request, "index.html", context)

        all_rows = []
        for row in reader:
            # Преобразуем все значения в числа, если возможно, чтобы корректно находить min/max
            processed_row = {}
            for k, v in row.items():
                try:
                    processed_row[k] = float(v)
                except ValueError:
                    processed_row[k] = v
            all_rows.append(processed_row)

        if not all_rows:
            context["no_data"] = True
            return templates.TemplateResponse(request, "index.html", context)

        # Целевой столбец (последний)
        target_col = headers[-1]

        # Поиск лучшей и худшей строки (по значению целевого столбца)
        best_row = max(all_rows, key=lambda r: r[target_col])
        worst_row = min(all_rows, key=lambda r: r[target_col])
        best_index = all_rows.index(best_row) + 1   # номер строки с учётом заголовка (строка данных с 2-й)
        worst_index = all_rows.index(worst_row) + 1

                # Поиск лучшей и худшей строки (по значению целевого столбца)
        best_row = max(all_rows, key=lambda r: r[target_col])
        worst_row = min(all_rows, key=lambda r: r[target_col])
        best_index = all_rows.index(best_row) + 1
        worst_index = all_rows.index(worst_row) + 1

        # === НОВАЯ ЧАСТЬ: Средний результат ===
        mean_row = {}
        for key in headers:
            try:
                mean_row[key] = round(sum(float(r[key]) for r in all_rows) / len(all_rows), 4)
            except (ValueError, TypeError):
                # Если столбец не числовой – берём первое значение
                mean_row[key] = all_rows[0][key]

        context.update({
            "no_data": False,
            "headers": headers,
            "all_rows": all_rows,
            "target_col": target_col,
            "best_row": best_row,
            "best_index": best_index,
            "worst_row": worst_row,
            "worst_index": worst_index,
            "mean_row": mean_row,          # ← добавили средние данные
        })

    except Exception:
        context["no_data"] = True

    return templates.TemplateResponse(request, "index.html", context)
@app.get("/train")
async def train_get(request: Request):
    session = request.session
    session_id = session.get("session_id")
    models = []
    total_rows = 0
    if session_id:
        file_path = os.path.join(get_session_dir(session_id), "data.csv")
        if os.path.exists(file_path):
            with open(file_path, encoding='utf-8') as f:
                total_rows = sum(1 for _ in f) - 1
        async with httpx.AsyncClient() as client:
            models = await fetch_models(client)

    return templates.TemplateResponse(request, "index.html", {
        "active_tab": "train",
        "models": models,
        "session_id": session_id,
        "total_rows": total_rows
    })

# Запуск обучения (POST)
@app.post("/train")
async def train_post(request: Request,
                     model_name: str = Form(...),
                     train_start: int = Form(...),
                     train_end: int = Form(...)):
    session = request.session
    session_id = session.get("session_id")
    if not session_id:
        log_action(session, "Обучение", "Ошибка: нет данных")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "train",
            "error": "Нет загруженных данных."
        })

    file_path = os.path.join(get_session_dir(session_id), "data.csv")
    if not os.path.exists(file_path):
        log_action(session, "Обучение", "Ошибка: файл не найден")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "train",
            "error": "Файл данных не найден."
        })

    async with httpx.AsyncClient() as client:
        try:
            result = await call_train_api(client, model_name, file_path, train_start, train_end)
            model_id = result.get("model_id")
            session["model_id"] = model_id
            log_action(session, f"Обучение модели {model_name} (строки {train_start}-{train_end})", f"ОК, model_id={model_id}")
            return templates.TemplateResponse(request, "index.html", {
                "active_tab": "train",
                "success": True,
                "model_id": model_id,
                "models": await fetch_models(client)
            })
        except Exception as e:
            log_action(session, f"Обучение модели {model_name}", f"Ошибка: {e}")
            return templates.TemplateResponse(request, "index.html", {
                "active_tab": "train",
                "error": f"Ошибка обучения: {e}",
                "models": await fetch_models(client)
            })

# Вкладка "Предсказания" (GET)
@app.get("/predict")
async def predict_get(request: Request):
    session = request.session
    model_trained = "model_id" in session
    return templates.TemplateResponse(request, "index.html", {
        "active_tab": "predict",
        "model_trained": model_trained,
        "model_id": session.get("model_id", "")
    })

# Получение предсказаний (POST)
@app.post("/predict")
async def predict_post(request: Request):
    session = request.session
    model_id = session.get("model_id")
    if not model_id:
        log_action(session, "Предсказание", "Ошибка: модель не обучена")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "predict",
            "error": "Модель не обучена.",
            "model_trained": False
        })

    file_path = os.path.join(get_session_dir(session["session_id"]), "data.csv")
    if not os.path.exists(file_path):
        log_action(session, "Предсказание", "Ошибка: файл данных не найден")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "predict",
            "error": "Файл данных не найден.",
            "model_trained": True
        })

    try:
        with open(file_path, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            all_data = list(reader)
    except Exception as e:
        log_action(session, "Предсказание", f"Ошибка чтения CSV: {e}")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "predict",
            "error": f"Ошибка чтения CSV: {e}",
            "model_trained": True
        })

    if not all_data:
        log_action(session, "Предсказание", "Ошибка: CSV пуст")
        return templates.TemplateResponse(request, "index.html", {
            "active_tab": "predict",
            "error": "CSV-файл пуст.",
            "model_trained": True
        })

    all_columns = list(all_data[0].keys())
    target_col = all_columns[-1]
    y_true = [float(row[target_col]) for row in all_data]
    features = [{k: v for k, v in row.items() if k != target_col} for row in all_data]

    async with httpx.AsyncClient() as client:
        try:
            payload = {"model_id": model_id, "data": features}
            resp = await client.post(f"{EXTERNAL_API_BASE}/predict", json=payload)
            resp.raise_for_status()
            result = resp.json()
            y_pred = [float(val) for val in result["predictions"]]
        except Exception as e:
            log_action(session, "Предсказание", f"Ошибка API: {e}")
            return templates.TemplateResponse(request, "index.html", {
                "active_tab": "predict",
                "error": f"Ошибка предсказания: {e}",
                "model_trained": True
            })

    errors = [pred - true for true, pred in zip(y_true, y_pred)]
    mae = sum(abs(e) for e in errors) / len(errors)
    rmse = (sum(e**2 for e in errors) / len(errors)) ** 0.5
    ss_res = sum(e**2 for e in errors)
    ss_tot = sum((y - sum(y_true)/len(y_true))**2 for y in y_true)
    r2 = 1 - ss_res / ss_tot if ss_tot != 0 else 0

    log_action(session, "Предсказание", "ОК")
    return templates.TemplateResponse(request, "index.html", {
        "active_tab": "predict",
        "model_trained": True,
        "prediction_done": True,
        "y_true": y_true,
        "y_pred": y_pred,
        "errors": errors,
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "target_col": target_col,
        "model_id": model_id
    })

# Вкладка "Логи" (GET)
@app.get("/logs")
def logs(request: Request):
    session = request.session
    logs_list = session.get("logs", [])
    return templates.TemplateResponse(request, "index.html", {
        "active_tab": "logs",
        "logs": logs_list
    })

# Эндпоинт для получения логов (для AJAX)
@app.get("/logs/data")
async def get_logs_data(request: Request):
    session = request.session
    logs_list = session.get("logs", [])
    return {"logs": logs_list}

# Скачивание логов в Excel
@app.get("/logs/download")
async def download_logs(request: Request):
    session = request.session
    logs_list = session.get("logs", [])
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Логи действий"
    headers = ["№", "Время", "Действие пользователя", "Ответ сайта"]
    for col, header in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=header)
    for row_idx, log in enumerate(logs_list, 2):
        ws.cell(row=row_idx, column=1, value=log["id"])
        ws.cell(row=row_idx, column=2, value=log["time"])
        ws.cell(row=row_idx, column=3, value=log["action"])
        ws.cell(row=row_idx, column=4, value=log["response"])
    for col in range(1, 5):
        max_width = 0
        for row in ws.iter_rows(min_col=col, max_col=col, values_only=True):
            for cell in row:
                if cell:
                    max_width = max(max_width, len(str(cell)))
        ws.column_dimensions[get_column_letter(col)].width = max_width + 2
    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": "attachment; filename=logs.xlsx"})
@app.post("/logs/clear")
async def clear_logs(request: Request):
    session = request.session
    session["logs"] = []
    return RedirectResponse(url="/logs", status_code=303)