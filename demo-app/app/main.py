from fastapi import FastAPI

from .routers import reports, users

app = FastAPI(title="Bookstore API")
app.include_router(users.router)
app.include_router(reports.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
