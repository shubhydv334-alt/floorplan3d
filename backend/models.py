from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class OpeningData(BaseModel):
    id: str = Field(default="")
    type: str = Field(..., description="'door' or 'window'")
    position_t: float = Field(0.0)
    width_px: float = Field(0.0)

class WallData(BaseModel):
    id: int = Field(default=0)
    x1: float
    y1: float
    x2: float
    y2: float
    thickness_px: float = Field(default=10.0)
    original_thickness_px: float = Field(default=10.0)
    seg_type: str = Field(..., description="'outer', 'inner', or 'closet'")
    confidence: float = Field(default=1.0)
    length_px: float = Field(default=0.0)
    openings: List[OpeningData] = Field(default_factory=list)

class WindowData(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    orient: str
    gap_px: float
    confidence: float
    wallId: int = Field(default=-1)
    position_t: float = Field(default=0.0)
    opening_width: float = Field(default=0.0)

class DoorData(BaseModel):
    cx: float
    cy: float
    radius_px: float
    arc_start: float
    arc_end: float
    coverage: float
    has_leaf: bool
    confidence: float
    wallId: int = Field(default=-1)
    position_t: float = Field(default=0.0)
    opening_width: float = Field(default=0.0)

class RoomData(BaseModel):
    id: int
    cx: float
    cy: float
    bbox: List[int]
    area_px: float
    area_ratio: float
    aspect_ratio: float
    polygon: List[List[int]] = Field(default_factory=list)
    label: str
    room_type: str
    ocr_text: str = ""
    color: Optional[str] = None
    boundary_closed: bool
    bridged_gaps: List[dict] = Field(default_factory=list)
    validation: str = ""
    dilation_kernel: int

class FurnitureData(BaseModel):
    cx: float
    cy: float
    width: float
    height: float
    angle: float = 0.0
    type: str
    confidence: float = 1.0

class FixtureData(BaseModel):
    cx: float
    cy: float
    width: float
    height: float
    angle: float = 0.0
    type: str
    confidence: float = 1.0

class FloorPlanResult(BaseModel):
    image_width: int
    image_height: int
    outer_walls: List[WallData] = Field(default_factory=list)
    inner_walls: List[WallData] = Field(default_factory=list)
    closets: List[WallData] = Field(default_factory=list)
    windows: List[WindowData] = Field(default_factory=list)
    doors: List[DoorData] = Field(default_factory=list)
    rooms: List[RoomData] = Field(default_factory=list)
    furniture: List[FurnitureData] = Field(default_factory=list)
    fixtures: List[FixtureData] = Field(default_factory=list)
    thresholds: Dict[str, Any] = Field(default_factory=dict)
    debug_images: Dict[str, str] = Field(default_factory=dict)
