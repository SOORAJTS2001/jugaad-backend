import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from base_models import MailTemplate
from mailer import send_mail
from models import DBUser, UserSelectedItems, Items, ItemsPriceLogger

DATABASE_URL = "sqlite+aiosqlite:///./sql_app.db"
PRICE_ENDPOINT = "https://www.jiomart.com/catalog/productdetails/get/"
CONCURRENT_REQUESTS = 20

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
Session = async_sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


@asynccontextmanager
async def httpx_client():
    """
    Yields a single shared AsyncClient for the whole run.
    httpx's default connection pool is already async‑safe and keeps TCP connections alive.
    """
    async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": "JioMartPriceTracker/1.0"},
            http2=True,  # optional; harmless if server is HTTP/1.1
            follow_redirects=True,
    ) as client:
        yield client


async def get_latest_price(session: AsyncSession, item_id: str, pincode: str) -> ItemsPriceLogger | None:
    stmt = (
        select(ItemsPriceLogger)
        .where(
            ItemsPriceLogger.item_id == item_id,
            ItemsPriceLogger.pincode == pincode
        )
        .order_by(desc(ItemsPriceLogger.last_updated_timestamp))
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def fetch_price(client: httpx.AsyncClient, item_id: str, pincode: str, source_url: str) -> dict:
    response = await client.get(f"{PRICE_ENDPOINT}{item_id}", headers={
        "accept": "application/json, text/javascript, */*; q=0.01",
        "accept-language": "en-US,en;q=0.9",
        "pin": "682020",
        "priority": "u=0, i",
        "referer": source_url,
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "x-requested-with": "XMLHttpRequest"
    })
    response.raise_for_status()
    raw = response.json()

    # Map payload to DB columns
    return {
        "item_id": item_id,
        "pincode": pincode,
        "source_url": source_url,
        "image_url": "https://www.jiomart.com" + raw["data"]["image_url"],
        "name": raw["data"]["gtm_details"]['name'],
        "mrp_price": raw["data"]["mrp"],
        "selling_price": raw["data"]["selling_price"],
        "discount_percent": raw["data"]["discount_pct"],
        "discount_price": raw["data"]["discount"],
        "max_order_quantity": raw["data"]["max_qty_in_order"],
        "is_available": True if raw["data"]["availability_status"] == 'A' else False,
        "brand": raw["data"]['gtm_details']['brand'],
        "category": raw["data"]['gtm_details']['category'],
        "last_updated_timestamp": datetime.now(timezone.utc),
    }


async def price_match(user: DBUser, selected_item: UserSelectedItems, item_price: dict,
                      async_session: AsyncSession) -> bool:
    if item_price['selling_price'] < selected_item.max_price or item_price['discount_percent'] > selected_item.max_offer:
        current_price = item_price['selling_price']
        prev_price: ItemsPriceLogger = await get_latest_price(async_session, selected_item.item_id, user.pincode)
        change_percent = round(((prev_price.selling_price - current_price) / prev_price.selling_price) * 100)
        send_mail(
            MailTemplate(
                user_email=user.email,
                item_name=item_price['name'],
                image_url=item_price['image_url'],
                source_url=item_price['source_url'],
                prev_price=str(prev_price.selling_price),
                curr_price=str(current_price),
                change_percent=str(change_percent),
            )
        )
        return True
    return False


async def process_user(user: DBUser, async_session: AsyncSession, client: httpx.AsyncClient):
    logging.info("Processing user %s", user.uid)
    for selected_item in user.selected_items:
        item = await async_session.get(Items, (selected_item.item_id, user.pincode))
        item_price = await fetch_price(client, item.item_id, user.pincode, item.source_url)
        if await price_match(user, selected_item, item_price, async_session):
            print("Mail sent to the user about offer")
        for k, v in item_price.items():
            if hasattr(item, k):
                setattr(item, k, v)
        del item_price['image_url']
        async_session.add(ItemsPriceLogger(**item_price))
    await async_session.commit()


async def worker():
    print("Worker Started")
    async with Session() as session, httpx_client() as client:
        users = (await session.execute(
            select(DBUser).options(selectinload(DBUser.selected_items))
        )).scalars().all()
        for user in users:
            print(user.uid)
            await process_user(user, session, client)


if __name__ == "__main__":
    asyncio.run(worker())
