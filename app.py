import logging
import os.path
import re
from typing import AsyncGenerator

import geopandas as gpd
import httpx
from fastapi import FastAPI, HTTPException, status, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from shapely.geometry import Point
from sqlalchemy import select, tuple_, desc
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from base_models import UserInput, AddedItemsRequest, AddedItemsResponse, ItemsPriceLoggerBaseModel, LocationResponse
from models import DBUser, Items, ItemsPriceLogger, UserSelectedItems
from scheduler import start_scheduler
from settings import async_engine, Base

# --- FastAPI App Setup ---
app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:8080",  # Your frontend's origin
    "https://jugaad-frontend.vercel.app",
    "http://192.168.29.206:8080"
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
    print(f"✅ Loaded Pincodes")


# --- FastAPI Lifecycle Events ---
@app.on_event("startup")
async def startup_event():
    # Create tables if they don't exist
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✅ SQLite database  initialized and table checked.")
    await start_scheduler()
    print("✅ Scheduler started")


@app.on_event("shutdown")
async def shutdown_event():
    # Dispose of the engine connection pool
    await async_engine.dispose()
    print("✅ FastAPI shutdown and database engine disposed.")


# --- API Endpoint ---
@app.post("/signup")
async def signup_or_get_user(user: UserInput, db: AsyncSession = Depends(get_db_session)):
    # 1. Check if user exists by UID
    # Use await session.execute() for async queries
    existing_user = await is_existing_user(db, user.uid)
    if existing_user:
        print(f"User with UID {user.uid} already exists.")
        return existing_user  # SQLAlchemy object directly converted by Pydantic's from_attributes
    else:
        print(f"Creating new user with UID {user.uid}.")
        # 2. Create new user
        new_user = DBUser(
            uid=user.uid,
            username=user.username,
            email=user.email,
            pincode=user.pincode
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
            "pin": "682020",
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
            pincode=request.pincode,
            discount_percent=response["data"]["discount_pct"],
            discount_price=response["data"]["discount"],
            max_order_quantity=response["data"]["max_qty_in_order"],
            is_available=(response["data"]["availability_status"] == "A") or False,
            image_url=item_image_url,
            brand=response["data"]["gtm_details"]["brand"],
            category=response["data"]["gtm_details"]["category"],

        )
        item_logger = ItemsPriceLogger(**item.to_dict())
        await db.refresh(existing_user, attribute_names=["selected_items"])
        selected_item = UserSelectedItems(
            user_uid=existing_user.uid,
            item_id=item_id,
            min_price=request.min_price,
            max_price=request.max_price or item.selling_price,
            min_offer=request.min_offer,
            max_offer=request.max_offer or item.discount_percent,
        )
        if selected_item not in existing_user.selected_items:
            existing_user.selected_items.append(selected_item)
            db.add(existing_user)
        db.add(item_logger)
        await db.merge(item)
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
                item = AddedItemsResponse.model_validate(item)
                item.price_change = str(item.mrp_price - item.selling_price)
                item.max_price = existing_item.max_price
                item.max_offer = existing_item.max_offer
                items.append(item)
    return items


@app.post("/get-item", response_model=AddedItemsResponse)
async def get_item(user: UserInput, db: AsyncSession = Depends(get_db_session)):
    existing_user: DBUser = await is_existing_user(db, user.uid)
    if not existing_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    stmt = select(Items).where(Items.item_id == user.item_id)
    result = await db.execute(stmt)
    result = result.scalar_one_or_none()
    item = AddedItemsResponse.model_validate(result)
    stmt = select(ItemsPriceLogger).where(
        ItemsPriceLogger.item_id == user.item_id and ItemsPriceLogger.pincode == user.pincode).order_by(
        desc(ItemsPriceLogger.last_updated_timestamp))
    result = await db.execute(stmt)
    logs = []
    for log in result.scalars().all():
        logs.append(ItemsPriceLoggerBaseModel(**log.to_dict()))
    item.logs = logs
    item.last_updated_timestamp = logs[0].last_updated_timestamp
    return item


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
@app.get("/")
async def read_root():
    return {"message": "Welcome to the FastAPI backend!"}
