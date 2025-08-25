from datetime import datetime
from sqlalchemy import Column, DateTime, Integer, String

from .database import Base


class PresenceRecord(Base):
    __tablename__ = "presence_records"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    display_name = Column(String)
    availability = Column(String)
    activity = Column(String)
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    oidc_sub = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True, nullable=True)
    name = Column(String, nullable=True)
