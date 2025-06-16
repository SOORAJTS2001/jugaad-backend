from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# --- Pydantic Models ---
class UserInput(BaseModel):
    uid: str
    email: str
    pincode: str | None = "682020"
    username: str | None = None
    item_id: str | None = None


class AddedItemsRequest(BaseModel):
    uid: str
    email: str
    username: str
    url: str
    pincode: str | None = "682020"
    min_price: float | None = None
    max_price: float | None = None
    min_offer: float | None = None
    max_offer: float | None = None
    notes: str | None = None


class ItemsPriceLoggerBaseModel(BaseModel):
    item_id: str
    pincode: str
    selling_price: float
    last_updated_timestamp: datetime | None = None


class AddedItemsResponse(BaseModel):
    item_id: str
    source_url: Optional[str] = None
    pincode: str
    max_price: Optional[float] = None
    max_offer: Optional[float] = None
    name: Optional[str] = None
    mrp_price: Optional[float] = None
    selling_price: Optional[float] = None
    discount_percent: Optional[float] = None
    discount_price: Optional[float] = None
    max_order_quantity: Optional[int] = None
    is_available: Optional[bool] = None
    image_url: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    price_change: Optional[str] = None
    logs: list[ItemsPriceLoggerBaseModel] | None = None
    last_updated_timestamp: datetime | None = None

    class Config:
        from_attributes = True


class MailTemplate(BaseModel):
    user_email: str
    item_name: str
    image_url: str
    source_url: str
    prev_price: str
    curr_price: str
    change_percent: str

class LocationResponse(BaseModel):
    pincode:str
    name:str
    division:str
    region:str
    circle:str
