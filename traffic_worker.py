#!/usr/bin/python3

import asyncio
import traceback

from playwright.async_api import ProxySettings, async_playwright

from config import PROXY_BYPASS, PROXY_PASSWORD, PROXY_SERVER, PROXY_USERNAME, logger
from playwright_traffic_analysis import (
    analyze_location_traffic,
    setup_context_with_cookies,
)


async def worker_loop(job_queue, result_queue):
    """
    A persistent worker that:
    - Starts Playwright ONCE
    - Keeps one browser & context open
    - Processes incoming tasks until shutdown
    """

    # Start Playwright & Browser once
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
            # new
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

    logger.info("✅ Browser resources initialized successfully")

    context = await setup_context_with_cookies(browser)

    while True:
        job = job_queue.get()  # blocking read
        if job == "STOP":
            break

        idx, location = job

        try:
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
                (idx, {"ok": True, "location": location, "result": result})
            )

        except Exception as e:
            tb = traceback.format_exc()
            result_queue.put(
                (
                    idx,
                    {
                        "ok": False,
                        "location": location,
                        "error": str(e),
                        "traceback": tb,
                    },
                )
            )

    # Cleanup on worker exit
    try:
        await context.close()
        await browser.close()
        await playwright.stop()
        logger.info("✅ Browser resources cleaned successfully")
    except Exception as cleanup_errors:
        logger.warning(
            f"❌ Browser resources cleanup completed with errors: {cleanup_errors}"
        )


def worker_entrypoint(job_queue, result_queue):
    """
    Sync entrypoint required for multiprocessing.
    Launches the asyncio loop and starts the worker loop.
    """
    asyncio.run(worker_loop(job_queue, result_queue))
