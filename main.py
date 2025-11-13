#!/usr/bin/python3
# -*- coding: utf-8 -*-


import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from playwright.async_api import ProxySettings, async_playwright
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.util import md5_hex

from auth import authenticate_user, create_access_token, get_current_user
from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    PROXY_BYPASS,
    PROXY_PASSWORD,
    PROXY_SERVER,
    PROXY_USERNAME,
    RATE,
    logger,
)
from db import Base, engine, get_db
from models import (
    LocationRequest,
    LocationResponse,
    MultiLocationRequest,
    MultiLocationResponse,
    Token,
)
from models_db import Job, TrafficLog, User
from playwright_traffic_analysis import (
    analyze_location_traffic,
    setup_context_with_cookies,
)

# FastAPI app
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
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

    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            proxy=(
                ProxySettings(
                    server=PROXY_SERVER,
                    bypass=PROXY_BYPASS,
                    username=PROXY_USERNAME,
                    password=PROXY_PASSWORD,
                )
                if PROXY_SERVER
                else None
            ),
        )

        context = await setup_context_with_cookies(browser)

        app.state.browser_context = context
    except Exception as e:
        raise

    yield

    # Cleanup
    try:
        await context.close()
    except:
        pass
    await browser.close()
    await playwright.stop()
    logger.info("✅ Cleanup completed")


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


async def process_single_location(
    browser_context, loc: LocationRequest, base_url: str
) -> dict[str, Any]:
    traffic_results = await analyze_location_traffic(
        browser_context,
        loc.lat,
        loc.lng,
        loc.day,
        loc.time,
        loc.storefront_direction,
        save_to_static=True,
        request_base_url=base_url,
    )
    return {"payload": loc, "result": traffic_results}


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
# @app.post("/token", response_model=Token)
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
# @app.post("/analyze-locations")
@limiter.limit(RATE)
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

    browser_context = getattr(request.app.state, "browser_context", None)
    if not browser_context:
        raise HTTPException(status_code=503, detail="Browser Context not available")

    try:
        results = await asyncio.gather(
            *(
                # analyze_location_traffic(
                #     browser_context,
                #     loc.lat,
                #     loc.lng,
                #     loc.day,
                #     loc.time,
                #     loc.storefront_direction,
                #     save_to_static=True,
                #     request_base_url=request.base_url,
                # )
                process_single_location(browser_context, loc, request.base_url)
                for loc in payload.locations
            ),
            return_exceptions=True,
        )
        completed_result = [
            r.get("result") for r in results if not isinstance(r, Exception)
        ]
        response = MultiLocationResponse(
            request_id=uuid.uuid4().hex,
            locations_count=len(payload.locatioins),
            completed=len(completed_result),
            result=completed_result,
            error="\n".join(str(r) for r in results if isinstance(r, Exception)),
        )

        # save result to DB
        try:
            job = Job(
                uuid=response.request_id,
                locations_count=response.locations_count,
                completed=response.completed,
                user_id=user.id,
            )
            db.add(job)

            for res in results:
                if isinstance(res, Exception):
                    continue

                log = TrafficLog(
                    lat=res["payload"].get("lat"),
                    lng=res["payload"].get("lng"),
                    storefront_direction=res["storefront_direction"].get(
                        "storefront_direction"
                    ),
                    day=res["payload"].get("day"),
                    time=res["payload"].get("time"),
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
        logger.error(f"Direct processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@app.get("/fetch-location", response_model=LocationResponse)
# @app.get("/fetch-point", response_model=LocationResponse)
async def get_job(
    request: Request,
    payload: LocationRequest,
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
        request_record = result.scalar_one_or_none()
        return LocationResponse(
            request_id=request_record.job_id, result=request_record.result
        )
    except Exception as e:
        logger.warning(
            f"DB: Failed to get request record for {payload.lat}, {payload.lng}: {e}"
        )


@app.post("/process-location", response_model=LocationResponse)
# @app.post("/process-point", response_model=LocationResponse)
@limiter.limit(RATE)
async def get_job(
    request: Request,
    payload: LocationRequest,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    browser_context = getattr(request.app.state, "browser_context", None)
    if not browser_context:
        raise HTTPException(status_code=503, detail="Browser Context not available")

    try:
        result = await process_single_location(
            browser_context, payload, request.base_url
        )

        response = LocationResponse(
            request_id=uuid.uuid4().hex, result=result["result"]
        )

        # save result to DB
        try:
            job = Job(
                uuid=response.request_id,
                locations_count=1,
                completed=1,
                user_id=user.id,
            )
            db.add(job)

            log = TrafficLog(
                lat=result["payload"].get("lat"),
                lng=result["payload"].get("lng"),
                storefront_direction=result["storefront_direction"].get(
                    "storefront_direction"
                ),
                day=result["payload"].get("day"),
                time=result["payload"].get("time"),
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
        logger.error(f"Direct processing failed: {e}")
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


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

    # Check browser automation status
    browser_context = getattr(app.state, "browser_context", None)
    if browser_context:
        health_status["dependencies"]["browser_automation"] = {
            "status": "healthy",
            "details": "Playwright browser context is available",
        }
    else:
        health_status["status"] = "unhealthy"
        health_status["dependencies"]["browser_automation"] = {
            "status": "unhealthy",
            "error": "Browser context not initialized",
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

    # Browser automation check
    browser_context = getattr(app.state, "browser_context", None)
    critical_checks.append(("browser_automation", bool(browser_context)))

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
#     uvicorn.run(app, host="0.0.0.0", port=8000, workers=1, reload=True)
