#!/usr/bin/python3
# -*- coding: utf-8 -*-


import asyncio
import multiprocessing as mp
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import md5_hex

from auth import authenticate_user, create_access_token, get_current_user
from config import ACCESS_TOKEN_EXPIRE_MINUTES, RATE, logger
from db import Base, engine, get_db
from models import (
    LocationData,
    LocationRequest,
    LocationResponse,
    MultiLocationRequest,
    MultiLocationResponse,
    Token,
)
from models_db import Job, TrafficLog, User
from playwright_traffic_analysis import TRAFFIC_SCREENSHOTS_STATIC_PATH
from worker_pool import WorkerPool

POOL = WorkerPool(
    num_workers=mp.cpu_count() * 2
)  # num_workers = default to cpu_count(), for best performance and results quality

# FastAPI app
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # os.makedirs(TRAFFIC_SCREENSHOTS_PATH, exist_ok=True)
    os.makedirs(TRAFFIC_SCREENSHOTS_STATIC_PATH, exist_ok=True)

    # Create database tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Create admin user
    async for db in get_db():
        admin_pw = os.getenv("ADMIN_PASSWORD", "123456").strip()
        result = await db.execute(select(User).filter_by(username="admin"))
        existing_admin = result.scalar_one_or_none()

        if not existing_admin:
            db.add(User(username="admin", hashed_password=md5_hex(admin_pw)))
            await db.commit()
        break

    POOL.start()

    yield

    logger.info("🔄 Starting cleanup process...")
    POOL.stop()


app = FastAPI(title="Google Maps Traffic Analyzer API", lifespan=lifespan)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(
    RateLimitExceeded,
    lambda request, exc: JSONResponse(
        status_code=429, content={"detail": "Too many requests"}
    ),
)

# static directory
os.makedirs("static/images/traffic_screenshots", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Log the error details
    logger.error(f"Global error: {str(exc)}")

    # Return a generic error response
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": "Something went wrong. Please try again later.",
        },
    )


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
    user = await authenticate_user(form_data.username, form_data.password, db)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@app.post("/process-locations")
@app.post("/process-many")
# @limiter.limit(RATE)
async def process_locations(
    request: Request,
    payload: MultiLocationRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not payload.locations:
        raise HTTPException(status_code=400, detail="No locations provided")
    if len(payload.locations) > 20:
        raise HTTPException(status_code=400, detail="Max 20 locations per request")

    try:
        for idx, loc in enumerate(payload.locations):
            # Dispatch jobs to worker pool
            POOL.dispatch(
                idx,
                {
                    "lat": loc.lat,
                    "lng": loc.lng,
                    "day": loc.day,
                    "time": loc.time,
                    "storefront_direction": loc.storefront_direction,
                    "zoom": loc.zoom,
                    "save_to_static": payload.save_to_static,
                    "base_url": str(request.base_url).rstrip("/"),
                },
            )

        results = {} # [None] * len(payload.locations)
        errors = []

        # Collect results
        for _ in range(len(payload.locations)):
            idx, res = await asyncio.get_event_loop().run_in_executor(
                None, POOL.get_result
            )

            if res["ok"]:
                results[idx] = res
            else:
                errors.append(res["error"])

        # Ordered results
        ordered_results = [
            value
            for _, value in sorted(results.items())
            if value and value.get("result") is not None
        ]

        response = MultiLocationResponse(
            request_id=uuid.uuid4().hex,
            locations_count=len(payload.locations),
            completed=len(ordered_results),
            result=[r["result"] for r in ordered_results],
            saved_to_db=payload.save_to_db,
            saved_to_static=payload.save_to_static,
            error="\n".join(errors),
        )

        # Save result to DB if requested
        if payload.save_to_db:
            try:
                job = Job(
                    request_id=response.request_id,
                    locations_count=response.locations_count,
                    completed=response.completed,
                    saved_to_static=payload.save_to_static,
                    user_id=user.id,
                )
                db.add(job)

                for res in ordered_results:
                    log = TrafficLog(
                        lat=res["location"].get("lat"),
                        lng=res["location"].get("lng"),
                        storefront_direction=res["location"].get(
                            "storefront_direction", "north"
                        ),
                        day=res["location"].get("day"),
                        time=res["location"].get("time"),
                        result=res["result"],
                        job_id=response.request_id,
                    )
                    db.add(log)

                await db.commit()
            except Exception as e:
                logger.warning(
                    f"DB: failed to create process request {response.request_id}: {e}"
                )

        return response
    except Exception as e:
        err_msg = f"Processing-many failed: {str(e)}"
        logger.error(err_msg)
        raise HTTPException(status_code=500, detail=err_msg)


@app.post("/process-location", response_model=LocationResponse)
@app.post("/process-one", response_model=LocationResponse)
# @limiter.limit(RATE)
async def get_job(
    request: Request,
    payload: LocationRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        POOL.dispatch(
            0,
            {
                "lat": payload.location.lat,
                "lng": payload.location.lng,
                "day": payload.location.day,
                "time": payload.location.time,
                "storefront_direction": payload.location.storefront_direction,
                "zoom": payload.location.zoom,
                "save_to_static": payload.save_to_static,
                "base_url": str(request.base_url).rstrip("/"),
            },
        )

        _, result = await asyncio.get_event_loop().run_in_executor(
            None, POOL.get_result
        )

        if not result["ok"]:
            raise

        response = LocationResponse(
            request_id=uuid.uuid4().hex,
            result=result["result"],
            saved_to_db=payload.save_to_db,
            saved_to_static=payload.save_to_static,
        )

        # Save result to DB if requested
        if payload.save_to_db:
            try:
                job = Job(
                    request_id=response.request_id,
                    locations_count=1,
                    completed=1,
                    saved_to_static=payload.save_to_static,
                    user_id=user.id,
                )
                db.add(job)

                log = TrafficLog(
                    lat=result["location"].get("lat"),
                    lng=result["location"].get("lng"),
                    storefront_direction=result["location"].get(
                        "storefront_direction", "north"
                    ),
                    day=result["location"].get("day"),
                    time=result["location"].get("time"),
                    result=result["result"],
                    job_id=response.request_id,
                )
                db.add(log)

                await db.commit()
            except Exception as e:
                logger.warning(
                    f"DB: failed to create process request {response.request_id}: {e}"
                )

        return response
    except Exception as e:
        err_msg = f"Processing-one failed: {str(e)}"
        logger.error(err_msg)
        raise HTTPException(status_code=500, detail=err_msg)


@app.get("/fetch-location", response_model=LocationResponse)
async def get_job(
    request: Request,
    payload: LocationData,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    try:
        result = await db.execute(
            select(TrafficLog)
            .join(Job)
            .filter(
                Job.user_id == user.id,
                TrafficLog.lat == payload.lat,
                TrafficLog.lng == payload.lng,
                TrafficLog.storefront_direction == payload.storefront_direction,
                TrafficLog.day == payload.day,
                TrafficLog.time == payload.time,
            )
        )
        saved_to_static = await db.execute(select(Job).filter(Job.user_id == user.id))
        saved_to_static = saved_to_static.scalar_one().saved_to_static
        request_record = result.scalar_one_or_none()
        return LocationResponse(
            request_id=request_record.job_id,
            result=request_record.result,
            saved_to_db=True,
            saved_to_static=saved_to_static,
        )
    except Exception as e:
        logger.warning(
            f"DB: Failed to get request record for {payload.lat}, {payload.lng}: {e}"
        )


@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint to verify the service status and dependencies.
    """
    health_status = {
        "status": "healthy",
        "timestamp": asyncio.get_event_loop().time(),
        "version": "1.0.0",
        "dependencies": {},
    }

    # Check database connection
    try:
        async for db in get_db():
            # Test database connection with a simple query
            result = await db.execute(select(1))
            test_value = result.scalar()
            health_status["dependencies"]["database"] = {
                "status": "healthy",
                "details": "Database connection successful",
            }
            break
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["database"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check worker pool status
    try:
        worker_count = POOL.num_workers
        alive = sum(p.is_alive() for p in POOL.processes)

        health_status["dependencies"]["worker_pool"] = {
            "status": "healthy",
            "details": "Worker Pool is Alive",
            "info": {
                "workers_expected": worker_count,
                "workers_alive": alive,
                "worker_pool_status": "ok" if alive == worker_count else "degraded",
                # Check queues
                "job_queue_size": POOL.job_queue.qsize(),
                "result_queue_size": POOL.result_queue.qsize(),
            },
        }

    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["worker_pool"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    # Check file system permissions
    try:
        test_dirs = ["static", "static/images", "static/images/traffic_screenshots"]
        for dir_path in test_dirs:
            os.makedirs(dir_path, exist_ok=True)
            test_file = os.path.join(dir_path, "health_test.txt")
            with open(test_file, "w") as f:
                f.write("health_check")
            os.remove(test_file)

        health_status["dependencies"]["file_system"] = {
            "status": "healthy",
            "details": "File system permissions are OK",
        }
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["file_system"] = {
            "status": "unhealthy",
            "error": str(e),
        }

    return health_status


@app.get("/health/ready", tags=["Health"])
async def readiness_probe():
    """
    Readiness probe for Kubernetes/container orchestration.
    Checks if the service is ready to accept traffic.
    """
    readiness_status = {
        "status": "ready",
        "timestamp": asyncio.get_event_loop().time(),
    }

    # Check critical dependencies
    critical_checks = []

    # Database check
    try:
        async for db in get_db():
            await db.execute(select(1))
            critical_checks.append(("database", True))
            break
    except Exception:
        critical_checks.append(("database", False))

    # worker pool check
    try:
        worker_count = POOL.num_workers
        alive = sum(p.is_alive() for p in POOL.processes)
        critical_checks.append(("worker_pool", alive == worker_count))
    except Exception:
        critical_checks.append(("worker_pool", False))

    # Determine overall readiness
    all_ready = all(check[1] for check in critical_checks)
    if not all_ready:
        readiness_status["status"] = "not_ready"
        readiness_status["failed_checks"] = [
            check[0] for check in critical_checks if not check[1]
        ]

    return readiness_status


@app.get("/health/live", tags=["Health"])
async def liveness_probe():
    """
    Liveness probe for Kubernetes/container orchestration.
    Simple check to see if the service is alive.
    """
    return {"status": "alive", "timestamp": asyncio.get_event_loop().time()}


@app.get("/")
async def root():
    return {"message": "Google Maps Parallel Processor API"}


# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8000, workers=1, reload=False)
