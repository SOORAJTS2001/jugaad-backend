# ============================================
# mailer_async.py
# --------------------------------------------
"""Async SMTP mailer for JioMart price‑tracker.

Required env vars (Railway → Variables):
    SMTP_HOST   – e.g. "smtp.gmail.com"
    SMTP_PORT   – 587 (STARTTLS) or 465 (SSL)
    SMTP_USER   – username / full email address
    SMTP_PASS   – password or app‑specific token
    SMTP_FROM   – display address seen by the user

Install dependency:
    pip install aiosmtplib
"""
from base_models import MailTemplate
from mailer import send_mail_async

# ============================================
# worker.py
# --------------------------------------------
"""Hourly cron job – fetch prices, notify users, log history.
Run via APScheduler (AsyncIOScheduler) or standalone: `python worker.py`.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from base_models import MailTemplate
from models import DBUser, Items, ItemsPriceLogger, UserSelectedItems
from settings import async_engine, EMAIL_SENT_COUNT

PRICE_ENDPOINT = "https://www.jiomart.com/catalog/productdetails/get/"
ITEM_DISTANCE_ENDPOINT = "https://www.jiomart.com/mst/rest/v1/5/pin/"

CONCURRENT_REQUESTS = 20

Session = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("worker")


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

@asynccontextmanager
async def httpx_client():
    async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "JioMartPriceTracker/1.0"},
            http2=True,
            follow_redirects=True,
    ) as client:
        yield client


async def fetch_cookies(client: httpx.AsyncClient, pincode: str) -> dict:
    LOGGER.info(f"Fetching Cookie For {pincode}")
    """
    Fetches Jiomart regional cookies (city, state code, pincode, new_customer)
    using the ITEM_DISTANCE_ENDPOINT.
    """
    headers = {
        "accept": "application/json",
        "accept-language": "en-US,en;q=0.9",
        "origin": "https://www.jiomart.com",
        "referer": "https://www.jiomart.com/",
        "user-agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
        ),
        "vertical": "jiomart",
    }

    resp = await client.get(f"{ITEM_DISTANCE_ENDPOINT}{pincode}", headers=headers)
    resp.raise_for_status()
    result = resp.json().get("result", {})

    return {
        "nms_mgo_city": result.get("city", ""),
        "nms_mgo_state_code": result.get("state_code", ""),
        "nms_mgo_pincode": pincode,
        "new_customer": "false",  # Must be string to match browser format
    }


async def fetch_price(client: httpx.AsyncClient, item_id: str, pincode: str, source_url: str,
                      cookie: dict) -> dict | None:
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookie.items())
    resp = await client.get(
        f"{PRICE_ENDPOINT}{item_id}",
        headers={
            "accept": "application/json, text/javascript, */*; q=0.01",
            "pin": pincode,
            "referer": source_url,
            "cookie": cookie_str,
            "user-agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
                "Mobile/15E148 Safari/604.1"
            ),
            "x-requested-with": "XMLHttpRequest",
        },
    )
    resp.raise_for_status()
    raw = resp.json()
    if raw['status'] == 'failure':
        LOGGER.warning(f"Could not fetch price for {source_url}")
        return None
    data = raw["data"]
    gtm = data["gtm_details"]
    return {
        "item_id": item_id,
        "pincode": pincode,
        "source_url": source_url,
        "image_url": "https://www.jiomart.com" + data["image_url"],
        "name": gtm["name"],
        "mrp_price": data["mrp"],
        "selling_price": data["selling_price"],
        "discount_percent": data["discount_pct"],
        "discount_price": data["discount"],
        "max_order_quantity": data["max_qty_in_order"],
        "is_available": data["availability_status"] == "A",
        "brand": gtm["brand"],
        "category": gtm["category"],
        "last_updated_timestamp": datetime.now(timezone.utc),
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def get_latest_price(session: AsyncSession, item_id: str, pincode: str) -> ItemsPriceLogger | None:
    stmt = (
        select(ItemsPriceLogger)
        .where((ItemsPriceLogger.item_id == item_id) & (ItemsPriceLogger.pincode == pincode))
        .order_by(desc(ItemsPriceLogger.last_updated_timestamp))
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

async def price_match(
        user: DBUser, selected_item: UserSelectedItems, current_price: dict, session: AsyncSession
) -> UserSelectedItems | None:
    """Return True if mail was sent."""
    prev_price_row = await get_latest_price(session, selected_item.item_id, user.pincode)
    if not prev_price_row:
        return None  # first run – nothing to compare
    if current_price["selling_price"] < prev_price_row.selling_price and current_price[
        "selling_price"] < selected_item.max_price:
        selected_item.email_sent_count = EMAIL_SENT_COUNT
    price_dropped = current_price["selling_price"] < selected_item.max_price
    offer_improved = current_price["discount_percent"] > selected_item.max_offer
    if not any([price_dropped,
                offer_improved]) or selected_item.email_sent_count == 0:  # if current price is not below user threshold
        # or email_sent_count ==0, don't do anything
        return None
    change_percent = round(
        ((selected_item.max_price - current_price["selling_price"]) / prev_price_row.selling_price) * 100
    )
    selected_item.email_sent_count = max(int(selected_item.email_sent_count) - 1, 0)
    await send_mail_async(
        MailTemplate(
            emails_remaining=selected_item.email_sent_count,
            user_email=user.email,
            item_name=current_price["name"],
            image_url=current_price["image_url"],
            source_url=current_price["source_url"],
            prev_price=str(int(selected_item.max_price)),
            curr_price=str(current_price["selling_price"]),
            change_percent=str(change_percent),
        )
    )
    LOGGER.info(f"Email sent to the {user.email=} about {current_price['name']}")
    return selected_item


async def process_user(user: DBUser, client: httpx.AsyncClient):
    LOGGER.info("Processing user %s", user.uid)
    cookie = await fetch_cookies(client, user.pincode)
    async with Session() as session:
        for selected_item in user.selected_items:
            item = await session.get(Items, (selected_item.item_id, user.pincode))
            if not item:
                continue

            current_price = await fetch_price(client, item.item_id, user.pincode, item.source_url, cookie=cookie)
            if not current_price:
                item.is_available = False
                await session.commit()
                continue
            if selected_item := await price_match(user, selected_item, current_price,
                                                  session):  # if there is any change in the selected item add it to db
                session.add(selected_item)

            # update Items row
            for key, val in current_price.items():
                if hasattr(item, key):
                    setattr(item, key, val)

            # log history
            hist_payload = current_price.copy()
            hist_payload.pop("image_url")  # not stored in history
            session.add(ItemsPriceLogger(**hist_payload))

        await session.commit()


# ---------------------------------------------------------------------------
# Cron entry‑point
# ---------------------------------------------------------------------------

SEM = asyncio.Semaphore(CONCURRENT_REQUESTS)


async def _handle_user_sem(user, client):
    async with SEM:
        await process_user(user, client)


async def worker():
    LOGGER.info("✅ Worker started (Asia/Kolkata)")

    # 1. Load users first (single DB session)
    async with Session() as session:
        users = (
            await session.execute(select(DBUser).options(selectinload(DBUser.selected_items)))
        ).scalars().all()

    # 2. Now open client and process users
    async with httpx_client() as client:
        tasks = [asyncio.create_task(_handle_user_sem(u, client)) for u in users]
        await asyncio.gather(*tasks)

    LOGGER.info("🏁 Worker finished – processed %d users", len(users))


if __name__ == "__main__":
    asyncio.run(worker())
# ============================================
