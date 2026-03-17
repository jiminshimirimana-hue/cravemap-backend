from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import os
import time
import uuid

app = FastAPI()

# Disable CORS. Do not remove this for full-stack development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Database setup
DB_PATH = os.environ.get("DB_PATH", "/data/app.db")

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id TEXT PRIMARY KEY,
            restaurant_id TEXT NOT NULL,
            author TEXT NOT NULL,
            text TEXT NOT NULL,
            rating INTEGER NOT NULL DEFAULT 5,
            timestamp REAL NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_restaurant ON comments(restaurant_id)")
    conn.commit()
    conn.close()

@app.on_event("startup")
async def startup():
    init_db()

# --- Models ---

class CommentCreate(BaseModel):
    restaurant_id: str
    author: str
    text: str
    rating: int = 5

class CommentResponse(BaseModel):
    id: str
    restaurant_id: str
    author: str
    text: str
    rating: int
    timestamp: float

# --- Routes ---

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/api/comments/{restaurant_id}", response_model=list[CommentResponse])
async def get_comments(restaurant_id: str):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, restaurant_id, author, text, rating, timestamp FROM comments WHERE restaurant_id = ? ORDER BY timestamp DESC",
        (restaurant_id,)
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.get("/api/comments/{restaurant_id}/count")
async def get_comment_count(restaurant_id: str):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as count FROM comments WHERE restaurant_id = ?",
        (restaurant_id,)
    ).fetchone()
    conn.close()
    return {"count": row["count"]}

@app.post("/api/comments/counts")
async def get_comment_counts(restaurant_ids: list[str]):
    conn = get_db()
    placeholders = ",".join("?" for _ in restaurant_ids)
    rows = conn.execute(
        f"SELECT restaurant_id, COUNT(*) as count FROM comments WHERE restaurant_id IN ({placeholders}) GROUP BY restaurant_id",
        restaurant_ids
    ).fetchall()
    conn.close()
    counts = {row["restaurant_id"]: row["count"] for row in rows}
    return counts

@app.post("/api/comments", response_model=CommentResponse, status_code=201)
async def create_comment(comment: CommentCreate):
    if not comment.author.strip():
        raise HTTPException(status_code=400, detail="Author name is required")
    if not comment.text.strip():
        raise HTTPException(status_code=400, detail="Comment text is required")
    if comment.rating < 1 or comment.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    comment_id = str(uuid.uuid4())
    timestamp = time.time()

    conn = get_db()
    conn.execute(
        "INSERT INTO comments (id, restaurant_id, author, text, rating, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
        (comment_id, comment.restaurant_id, comment.author.strip(), comment.text.strip(), comment.rating, timestamp)
    )
    conn.commit()
    conn.close()

    return {
        "id": comment_id,
        "restaurant_id": comment.restaurant_id,
        "author": comment.author.strip(),
        "text": comment.text.strip(),
        "rating": comment.rating,
        "timestamp": timestamp,
    }

@app.delete("/api/comments/{comment_id}")
async def delete_comment(comment_id: str):
    conn = get_db()
    result = conn.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
    conn.commit()
    deleted = result.rowcount
    conn.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"deleted": True}

# Serve frontend static files
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.isdir(STATIC_DIR):
    @app.get("/")
    async def serve_index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
