import asyncio
import traceback
import os

from playwright.async_api import ProxySettings, async_playwright

from config import PROXY_BYPASS, PROXY_PASSWORD, PROXY_SERVER, PROXY_USERNAME, logger
from playwright_traffic_analysis import (
    analyze_location_traffic,
    setup_context_with_cookies, # This might need to be checked if it resets cookies
)

MAX_JOBS_PER_WORKER = 20

async def worker_loop(job_queue, result_queue):
    """
    A persistent worker that:
    - Starts Playwright
    - Processes incoming tasks
    - Restarts periodically to prevent memory leaks
    """
    job_count = 0
    playwright = None
    browser = None

    try:
        playwright = await async_playwright().start()
        proxy_settings = (
            ProxySettings(
                server=PROXY_SERVER,
                bypass=PROXY_BYPASS,
                username=PROXY_USERNAME,
                password=PROXY_PASSWORD,
            )
            if PROXY_SERVER
            else None
        )
        browser = await playwright.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=[
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-setuid-sandbox",
                "--disable-extensions",
                "--no-first-run",
                "--disable-sync",
                "--disable-default-apps",
                "--hide-scrollbars",
                "--disable-infobars",
                "--mute-audio",
                "--disable-logging",
            ],
            proxy=proxy_settings,
        )

        logger.info(f"✅ Worker {os.getpid()} browser initialized")

        while job_count < MAX_JOBS_PER_WORKER:
            # Use run_in_executor to avoid blocking the event loop
            try:
                job = await asyncio.get_event_loop().run_in_executor(None, job_queue.get)
            except Exception as e:
                logger.error(f"Error getting job from queue: {e}")
                break

            if job == "STOP":
                job_queue.put("STOP") # Pass it on to others if needed (though pool sends N stops)
                return

            job_id, location = job
            job_count += 1

            # Create a FRESH context for every single job to ensure no state/memory leaks
            context = None
            try:
                context = await setup_context_with_cookies(browser)
                
                result = await analyze_location_traffic(
                    context,
                    lat=location["lat"],
                    lng=location["lng"],
                    day_of_week=location.get("day"),
                    target_time=location.get("time"),
                    storefront_direction=location.get("storefront_direction", "north"),
                    zoom=location.get("zoom", 18),
                    save_to_static=location.get("save_to_static", False),
                    request_base_url=location.get("base_url"),
                )

                result_queue.put(
                    (job_id, {"ok": True, "location": location, "result": result})
                )

            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"Error in worker {os.getpid()}: {str(e)}\n{tb}")
                result_queue.put(
                    (
                        job_id,
                        {
                            "ok": False,
                            "location": location,
                            "error": str(e),
                            "traceback": tb,
                        },
                    )
                )
            finally:
                if context:
                    await context.close()

    except Exception as e:
        logger.error(f"Fatal error in worker {os.getpid()}: {e}")
    finally:
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()
        logger.info(f"♻️ Worker {os.getpid()} shutting down (Job count: {job_count})")

def worker_entrypoint(job_queue, result_queue):
    """
    Sync entrypoint required for multiprocessing.
    """
    asyncio.run(worker_loop(job_queue, result_queue))
