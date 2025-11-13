#!/usr/bin/python3
# -*- coding: utf-8 -*-

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)

    jobs = relationship("Job", back_populates="user", cascade="all, delete-orphan")


class TrafficLog(Base):
    __tablename__ = "traffic_logs"

    id = Column(Integer, primary_key=True, index=True)

    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    storefront_direction = Column(String, nullable=False, default="north")
    day = Column(String, nullable=True)
    time = Column(String, nullable=True)
    result = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)

    job = relationship("Job", back_populates="traffic_logs")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)

    request_id = Column(String, unique=True, index=True, nullable=False)
    locations_count = Column(Integer, nullable=False)
    completed = Column(Integer, nullable=False, default=0)
    error = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )

    user = relationship("User", back_populates="jobs")
    traffic_logs = relationship(
        "TrafficLog", back_populates="job", cascade="all, delete-orphan"
    )
