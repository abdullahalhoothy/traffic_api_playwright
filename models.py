#!/usr/bin/python3
# -*- coding: utf-8 -*-

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str


class LocationRequest(BaseModel):
    lat: float
    lng: float
    storefront_direction: str = "north"
    day: Optional[str] = None
    time: Optional[str] = None


class LocationResponse(BaseModel):
    request_id: str
    result: Dict[str, Any]


class MultiLocationResponse(BaseModel):
    request_id: str
    locations_count: int
    completed: int
    result: List[Dict[str, Any]]
    error: Optional[str] = None


class MultiLocationRequest(BaseModel):
    locations: List[LocationRequest]
    proxy: Optional[str] = None
