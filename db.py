#!/usr/bin/python3
# -*- coding: utf-8 -*-

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from config import DB_URL

# Convert to async SQLite URL
# async_db_url = DB_URL.replace("sqlite:///", "sqlite+aiosqlite:///")
engine = create_async_engine(DB_URL, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)
Base = declarative_base()


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
