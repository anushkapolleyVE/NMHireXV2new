from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .database import engine
from .models import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create missing tables for a fresh development database.
    # Existing tables/columns are NOT altered by create_all().
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="NM-HireX",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "https://nm-hire-x.vercel.app",
        "https://nm-hire-x-omega.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
def root():
    return {
        "service": "NM-HireX",
        "status": "running",
    }
