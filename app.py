import asyncio
import logging
import os.path
import re
from typing import AsyncGenerator

import geopandas as gpd
import httpx
from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from haversine import haversine, Unit
from shapely.geometry import Point
from sqlalchemy import select, tuple_, desc, delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.responses import JSONResponse

from base_models import UserInput, AddedItemsRequest, AddedItemsResponse, ItemsPriceLoggerBaseModel, LocationResponse, \
    ItemMetadata, ItemDetailInput
from models import Base, DBUser, Items, ItemsPriceLogger, UserSelectedItems
from scheduler import start_scheduler
from settings import async_engine

LOGGER = logging.getLogger("app")

# --- FastAPI App Setup ---
app = FastAPI()

origins = [
    "http://localhost:8080",  # Your frontend's origin
    "https://jugaad-frontend.vercel.app",
    "http://192.168.31.160:8080"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allows all headers
)

# --- Database Configuration ---
# Use 'sqlite+aiosqlite' dialect for asynchronous SQLite with SQLAlchemy
ROOT_DIR = os.path.dirname(__file__)
PRICE_ENDPOINT = "https://www.jiomart.com/catalog/productdetails/get"
REVIEW_SUMMARY_ENDPOINT = "https://reviews-ratings.jio.com/customer/op/v1/review/summary/"
REVIEW_ENDPOINT = "https://reviews-ratings.jio.com/customer/op/v1/review/product-statistics/"
ITEM_DISTANCE_ENDPOINT = "https://www.jiomart.com/mst/rest/v1/5/pin/"
PINCODE_BOUNDARIES = os.path.join(ROOT_DIR, "postcode_boundaries.geojson")

# Create an asynchronous engine
# connect_args={"check_same_thread": False} is STILL needed for SQLite,
# even with aiosqlite, as aiosqlite still runs its operations in a thread pool.

# Asynchronous sessionmaker
AsyncSessionLocal = async_sessionmaker(
    async_engine,
    expire_on_commit=False,  # Prevents objects from expiring after commit, useful for returning them
    class_=AsyncSession  # This is crucial for async sessions
)


# --- Database Dependency (Async) ---
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency that provides an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
        await session.close()  # Ensure session is closed


async def is_existing_user(db, user_uid: str):
    stmt = select(DBUser).where(DBUser.uid == user_uid)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()  # Use scalar_one_or_none() for a single result


async def get_metadata(item_id: str, pincode: str, user_lat: float | None = None,
                       user_lng: float | None = None) -> ItemMetadata:
    metadata = ItemMetadata()
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
    async with httpx.AsyncClient() as client:
        async with asyncio.TaskGroup() as tg:
            summary_task = tg.create_task(client.get(f"{REVIEW_SUMMARY_ENDPOINT}{item_id}", headers=headers))
            rating_task = tg.create_task(client.get(f"{REVIEW_ENDPOINT}{item_id}", headers=headers))
            distance_task = tg.create_task(client.get(f"{ITEM_DISTANCE_ENDPOINT}{pincode}", headers=headers))

        # Process responses after all complete
        summary_result = summary_task.result().json()
        if summary_result.get("resultInfo", {}).get("status") == "SUCCESS" and summary_result.get("data"):
            metadata.summary = summary_result["data"].get("summary")

        rating_result = rating_task.result().json()
        if rating_result.get("resultInfo", {}).get("status") == "SUCCESS" and rating_result.get("data"):
            metadata.rating = rating_result["data"].get("averageRating")

        distance_result = distance_task.result().json()
        if distance_result.get("status") == "success" and user_lng and user_lng:
            loc = distance_result.get("result", {})
            lat, lng = loc.get("lat"), loc.get("lon")
            distance = haversine((user_lat, user_lng), (lat, lng), unit=Unit.KILOMETERS)
            metadata.distance = round(distance,2)

    return metadata


gdf = None  # GeoDataFrame for pin code polygons


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info(f"Incoming request: {request.method} {request.url}")
    response = await call_next(request)
    return response


@app.on_event("startup")
def load_geojson():
    global gdf
    gdf = gpd.read_file(PINCODE_BOUNDARIES)
    gdf = gdf.to_crs(epsg=4326)
    LOGGER.info(f"✅ Loaded Pincodes")


# --- FastAPI Lifecycle Events ---
@app.on_event("startup")
async def startup_event():
    # Create tables if they don't exist
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    LOGGER.info("✅ SQLite database  initialized and table checked.")
    await start_scheduler()
    LOGGER.info("✅ Scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    # Dispose of the engine connection pool
    await async_engine.dispose()
    LOGGER.info("✅ FastAPI shutdown and database engine disposed.")


# --- API Endpoint ---
@app.post("/signup")
async def signup_or_get_user(user: UserInput, db: AsyncSession = Depends(get_db_session)):
    # 1. Check if user exists by UID
    # Use await session.execute() for async queries
    existing_user = await is_existing_user(db, user.uid)
    if existing_user:
        LOGGER.warning(f"User with UID {user.uid} already exists.")
        return existing_user  # SQLAlchemy object directly converted by Pydantic's from_attributes
    else:
        LOGGER.warning(f"Creating new user with UID {user.uid}.")
        # 2. Create new user
        new_user = DBUser(
            uid=user.uid,
            username=user.username,
            email=user.email,
            pincode=user.pincode if user.pincode else "682020"
        )
        db.add(new_user)
        try:
            await db.commit()  # Commit the transaction
            await db.refresh(new_user)  # Refresh to load any default values or generated IDs
            return {"status": "success"}
        except Exception as e:
            await db.rollback()  # Rollback on error
            # Check for unique constraint violation (email or username)
            if "UNIQUE constraint failed" in str(e):
                if "users.email" in str(e):
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")
                elif "users.username" in str(e):
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken.")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create user: {e}")


@app.post("/add-items")
async def add_items(request: AddedItemsRequest, db: AsyncSession = Depends(get_db_session)):
    existing_user = await is_existing_user(db, request.uid)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    async with httpx.AsyncClient() as client:
        match = re.search(r'/(\d+)/?$', request.url)
        match = match.group(0)
        response = await client.get(f"{PRICE_ENDPOINT}{match}", headers={
            "accept": "application/json, text/javascript, */*; q=0.01",
            "accept-language": "en-US,en;q=0.9",
            "pin": existing_user.pincode,
            "priority": "u=0, i",
            "referer": request.url,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
            "x-requested-with": "XMLHttpRequest"
        })
        response.raise_for_status()
        response = response.json()
        # Add Product Not Available exception
        item_id = str(response["data"]["product_code"])
        item_image_url = "https://www.jiomart.com" + response["data"]["image_url"]
        item = Items(
            item_id=item_id,
            source_url=request.url,
            name=response["data"]["gtm_details"]["name"],
            mrp_price=response["data"]["mrp"],
            selling_price=response["data"]["selling_price"],
            pincode=existing_user.pincode,
            discount_percent=response["data"]["discount_pct"],
            discount_price=response["data"]["discount"],
            max_order_quantity=response["data"]["max_qty_in_order"],
            is_available=(response["data"]["availability_status"] == "A") or False,
            image_url=item_image_url,
            brand=response["data"]["gtm_details"]["brand"],
            category=response["data"]["gtm_details"]["category"],

        )
        await db.merge(item)
        item_logger = ItemsPriceLogger(**item.to_dict())
        await db.refresh(existing_user, attribute_names=["selected_items"])
        selected_item = UserSelectedItems(
            user_uid=existing_user.uid,
            item_id=item_id,
            pincode=existing_user.pincode,
            min_price=request.min_price,
            max_price=request.max_price or item.selling_price,
            min_offer=request.min_offer,
            max_offer=request.max_offer or item.discount_percent,
        )
        if selected_item not in existing_user.selected_items:
            existing_user.selected_items.append(selected_item)
            db.add(existing_user)
        db.add(item_logger)
        await db.commit()
        return {"status": "success"}


@app.post("/get-items", response_model=list[AddedItemsResponse])
async def get_items(user: UserInput, db: AsyncSession = Depends(get_db_session)):
    existing_user: DBUser = await is_existing_user(db, user.uid)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await db.refresh(existing_user, attribute_names=["selected_items"])
    keys = [(item.item_id, existing_user.pincode) for item in existing_user.selected_items]
    stmt = select(Items).where(
        tuple_(Items.item_id, Items.pincode).in_(keys)
    )
    items = []
    result = await db.execute(stmt)
    results = result.scalars().all()
    for item in results:
        for existing_item in existing_user.selected_items:
            if item.item_id == existing_item.item_id:
                stmt = select(ItemsPriceLogger).where(
                    (ItemsPriceLogger.item_id == item.item_id) & (
                            ItemsPriceLogger.pincode == existing_user.pincode)).order_by(
                    desc(ItemsPriceLogger.last_updated_timestamp))
                result = await db.execute(stmt)
                logs = []
                for log in result.scalars().all():
                    logs.append(ItemsPriceLoggerBaseModel(**log.to_dict()))
                item = AddedItemsResponse.model_validate(item)
                item.price_change = str(item.mrp_price - item.selling_price)
                item.max_price = existing_item.max_price
                item.max_offer = existing_item.max_offer
                item.pincode = existing_user.pincode
                item.logs = logs
                items.append(item)
    return items


@app.post("/get-item", response_model=AddedItemsResponse)
async def get_item(input: ItemDetailInput, db: AsyncSession = Depends(get_db_session)):
    stmt = select(Items).where(
        (Items.item_id == input.item_id) & (Items.pincode == input.pincode)
    )
    result = await db.execute(stmt)
    result = result.scalar_one_or_none()
    if not result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    item = AddedItemsResponse.model_validate(result)
    stmt = select(ItemsPriceLogger).where(
        (ItemsPriceLogger.item_id == input.item_id) & (ItemsPriceLogger.pincode == input.pincode)).order_by(
        desc(ItemsPriceLogger.last_updated_timestamp))
    result = await db.execute(stmt)
    logs = []
    for log in result.scalars().all():
        logs.append(ItemsPriceLoggerBaseModel(**log.to_dict()))
    item.logs = logs
    item.last_updated_timestamp = logs[0].last_updated_timestamp
    item.item_metadata = await get_metadata(item_id=item.item_id, pincode=item.pincode, user_lat=input.lat,
                                            user_lng=input.lng)
    return item


@app.post("/delete-item")
async def delete_item(user: UserInput, db: AsyncSession = Depends(get_db_session)):
    existing_user: DBUser = await is_existing_user(db, user.uid)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    await db.refresh(existing_user, attribute_names=["selected_items"])
    del_stmt = delete(UserSelectedItems).where(
        (UserSelectedItems.user_uid == user.uid) &
        (UserSelectedItems.item_id == user.item_id)
    )
    await db.execute(del_stmt)
    await db.commit()

    return {"status": "success"}


@app.get("/reverse")
def reverse_pincode(lat: float, lon: float) -> LocationResponse:
    global gdf
    if gdf is None:
        raise HTTPException(status_code=500, detail="Geo data not loaded")

    point = Point(lon, lat)
    match = gdf[gdf.geometry.contains(point)]

    if not match.empty:
        row = match.iloc[0]
        data = {
            "pincode": str(row.get("Pincode")),
            "name": row.get("Office_Name"),
            "division": row.get("Division"),
            "region": row.get("Region"),
            "circle": row.get("Circle")
        }
        return LocationResponse(**data)
    else:
        raise HTTPException(status_code=404, detail="Pincode not found for given coordinates")


# Example root endpoint
@app.get("/ping", tags=["Health"])
async def health_check(db: AsyncSession = Depends(get_db_session)):
    try:
        await db.execute(text('SELECT 1'))
        return JSONResponse(content={"message": "PONG"})
    except Exception as e:
        logging.error(e)
        return JSONResponse(content={"message": "Oops! I Crashed"})
