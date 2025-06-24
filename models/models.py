import uuid

from sqlalchemy import Column, String, Float, Integer, DateTime, PrimaryKeyConstraint, Boolean, \
    ForeignKey, ForeignKeyConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from settings import Base


# --- Database Models ---
class DBUser(Base):
    __tablename__ = "users"

    uid = Column(String, primary_key=True, index=True)
    username = Column(String, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)  # Email is mandatory
    pincode = Column(String)
    selected_items = relationship("UserSelectedItems", cascade="all, delete-orphan")


class UserSelectedItems(Base):
    __tablename__ = "user_selected_items"

    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    user_uid = Column(String, ForeignKey("users.uid"), nullable=False)
    item_id = Column(String, nullable=False)
    pincode = Column(String, nullable=False)  # Add this to match target composite key
    min_price = Column(Float, nullable=True)
    max_price = Column(Float, nullable=True)
    min_offer = Column(Float, nullable=True)
    max_offer = Column(Float, nullable=True)

    def __eq__(self, other):
        return self.item_id == other.item_id

    __table_args__ = (
        ForeignKeyConstraint(
            ["item_id", "pincode"],  # source columns
            ["items.item_id", "items.pincode"],  # target composite PK
            ondelete="CASCADE"
        ),
    )


class Items(Base):
    __tablename__ = "items"
    item_id = Column(String, index=True)
    source_url = Column(String,)
    pincode = Column(String)
    name = Column(String, index=True, nullable=True)
    mrp_price = Column(Float, nullable=True)
    selling_price = Column(Float, nullable=True)
    discount_percent = Column(Float, nullable=True)
    discount_price = Column(Float, nullable=True)
    max_order_quantity = Column(Integer, nullable=True)
    is_available = Column(Boolean, nullable=True)
    image_url = Column(String, nullable=True)
    brand = Column(String, nullable=True)
    category = Column(String, nullable=True)

    def to_dict(self):
        return {
            "item_id": self.item_id,
            "pincode": self.pincode,
            "name": self.name,
            "source_url": self.source_url,
            "mrp_price": self.mrp_price,
            "selling_price": self.selling_price,
            "discount_percent": self.discount_percent,
            "discount_price": self.discount_price,
            "max_order_quantity": self.max_order_quantity,
            "is_available": self.is_available,
        }

    def __repr__(self):
        return f"<Items {self.item_id=} {self.pincode=} {self.name=} {self.selling_price=}>"

    __table_args__ = (
        PrimaryKeyConstraint('item_id', 'pincode', name='pk_item_pincode'),
    )


class ItemsPriceLogger(Base):
    __tablename__ = "items_price_logger"
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    item_id = Column(String, nullable=False)
    source_url = Column(String)
    pincode = Column(String)
    name = Column(String, index=True, nullable=True)
    mrp_price = Column(Float, nullable=True)
    selling_price = Column(Float, nullable=True)
    discount_percent = Column(Float, nullable=True)
    discount_price = Column(Float, nullable=True)
    max_order_quantity = Column(Integer, nullable=True)
    is_available = Column(Boolean, nullable=True)
    brand = Column(String, nullable=True)
    category = Column(String, nullable=True)
    last_updated_timestamp = Column(
        DateTime(timezone=True),  # tell SQLAlchemy this is tz-aware
        server_default=func.now(),
        onupdate=func.now()
    )

    def to_dict(self):
        return {
            "last_updated_timestamp": self.last_updated_timestamp,
            "selling_price": self.selling_price,
            "pincode": self.pincode,
            "item_id": self.item_id,
        }
