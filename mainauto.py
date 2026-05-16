from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
import os

app = FastAPI(title="Auth API")

# Подключаем папку с шаблонами HTML
templates = Jinja2Templates(directory="templates")

security = HTTPBearer()

# ========== НАСТРОЙКИ ПОДКЛЮЧЕНИЯ К БД (НА КОМПЬЮТЕРЕ 1) ==========
# ⚠️ ЗАМЕНИТЕ ЭТИ ДАННЫЕ ⚠️
DB_CONFIG = {
    "dbname": "mywebapp_db",           # имя базы
    "user": "postgres",                # пользователь БД
    "password": "lbrnfnjh",          # ← ПАРОЛЬ ОТ POSTGRESQL
    "host": "10.73.97.112",           # ← IP КОМПЬЮТЕРА 1 (ГДЕ БД)
    "port": "5432"
}

# JWT настройки
SECRET_KEY = "your-secret-key-change-this"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Хеширование паролей
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ========== ФУНКЦИИ ==========
def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=RealDictCursor)

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def hash_password(password):
    return pwd_context.hash(password)

def create_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        return None

# ========== МОДЕЛИ ==========
class UserRegister(BaseModel):
    username: str
    email: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

# ========== API ЭНДПОИНТЫ ==========
@app.post("/api/register")
async def register(user: UserRegister):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Проверка, существует ли пользователь
        cur.execute("SELECT id FROM users WHERE username = %s OR email = %s", (user.username, user.email))
        if cur.fetchone():
            conn.close()
            raise HTTPException(status_code=400, detail="Пользователь или email уже существует")
        
        # Создаём пользователя
        hashed = hash_password(user.password)
        cur.execute(
            "INSERT INTO users (username, email, hashed_password) VALUES (%s, %s, %s) RETURNING id",
            (user.username, user.email, hashed)
        )
        user_id = cur.fetchone()["id"]
        conn.commit()
        conn.close()
        
        return {"success": True, "message": "Регистрация успешна", "user_id": user_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

@app.post("/api/login")
async def login(user: UserLogin):
    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT id, username, email, hashed_password FROM users WHERE username = %s", (user.username,))
        db_user = cur.fetchone()
        conn.close()
        
        if not db_user or not verify_password(user.password, db_user["hashed_password"]):
            raise HTTPException(status_code=401, detail="Неверное имя пользователя или пароль")
        
        token = create_token({"sub": db_user["username"], "user_id": db_user["id"]})
        return {"access_token": token, "token_type": "bearer"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

@app.get("/api/me")
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    payload = decode_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, username, email FROM users WHERE username = %s", (payload["sub"],))
    user = cur.fetchone()
    conn.close()
    
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    
    return user

# ========== СТРАНИЦЫ (через Jinja2 Templates) ==========
@app.get("/", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/site", response_class=HTMLResponse)
async def protected_site(request: Request):
    """Защищённая страница — ваш готовый сайт"""
    return templates.TemplateResponse("index.html", {"request": request})
