"""Traffic simulator: replays the test split (patients the models never saw)
through the router, as users with stable user_ids (patient_nbr), at a
configurable rate. Loops over the test split forever, reshuffling each pass.

  RATE           requests per second (default 120)
  MAX_INFLIGHT   concurrency limit (default 64)
  ROUTER_URL     http://router:8000
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp
import numpy as np
from prometheus_client import Counter, Gauge, start_http_server

from p1 import config
from p1.data import load_split
from p1.features import row_to_payload

log = logging.getLogger("simulator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

ROUTER_URL = os.getenv("ROUTER_URL", "http://router:8000")
RATE = float(os.getenv("RATE", "120"))
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "64"))

SENT = Counter("sim_requests_total", "Requests sent by the simulator", ["status"])
RATE_G = Gauge("sim_target_rate", "Target requests per second")


def load_requests() -> list[dict]:
    while not os.path.exists(os.path.join(config.SPLIT_DIR, "test.csv")):
        log.info("waiting for the test split ...")
        time.sleep(3)
    test = load_split("test")
    return [{"user_id": str(row["patient_nbr"]), "features": row_to_payload(row)}
            for _, row in test.iterrows()]


async def send(client: aiohttp.ClientSession, sem: asyncio.Semaphore, req: dict):
    try:
        async with client.post(ROUTER_URL + "/predict", json=req) as r:
            await r.read()
            SENT.labels(str(r.status)).inc()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        SENT.labels("network_error").inc()
    finally:
        sem.release()


async def wait_router(client: aiohttp.ClientSession):
    while True:
        try:
            async with client.get(ROUTER_URL + "/health") as r:
                if r.status == 200:
                    return
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        log.info("waiting for router and both variants ...")
        await asyncio.sleep(3)


async def main():
    start_http_server(8001)
    RATE_G.set(RATE)
    requests = load_requests()
    log.info("loaded %d test encounters (%d patients); rate=%.0f req/s",
             len(requests), len({r["user_id"] for r in requests}), RATE)
    rng = np.random.default_rng(config.SEED)
    sem = asyncio.Semaphore(MAX_INFLIGHT)
    async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=5.0),
            connector=aiohttp.TCPConnector(limit=MAX_INFLIGHT)) as client:
        await wait_router(client)
        loop = asyncio.get_running_loop()
        interval = 1.0 / RATE
        next_t = loop.time()
        passes = 0
        while True:
            for i in rng.permutation(len(requests)):
                next_t += interval
                delay = next_t - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                await sem.acquire()
                if loop.time() - next_t > 1.0:   # fell behind: resync instead of bursting
                    next_t = loop.time()
                asyncio.create_task(send(client, sem, requests[i]))
            passes += 1
            log.info("completed pass %d over the test split", passes)


if __name__ == "__main__":
    asyncio.run(main())
