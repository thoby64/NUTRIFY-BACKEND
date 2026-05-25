from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ============ Nutrient Type Schemas ============
class NutrientTypeBase(BaseModel):
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


class NutrientTypeCreate(NutrientTypeBase):
    pass


class NutrientTypeResponse(NutrientTypeBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============ Nutrient Schemas ============
class NutrientBase(BaseModel):
    name: str
    unit: Optional[str] = None
    abbreviation: Optional[str] = None
    description: Optional[str] = None


class NutrientCreate(NutrientBase):
    nutrient_type_id: int


class NutrientResponse(NutrientBase):
    id: int
    nutrient_type_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class NutrientWithTypeResponse(NutrientResponse):
    nutrient_type: NutrientTypeResponse


# ============ Food Group Schemas ============
class FoodGroupBase(BaseModel):
    name: str
    description: Optional[str] = None


class FoodGroupCreate(FoodGroupBase):
    pass


class FoodGroupResponse(FoodGroupBase):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============ Food Nutrient Schemas ============
class FoodNutrientBase(BaseModel):
    nutrient_id: int
    nutrient_type_id: int
    value: Optional[float] = None
    per_unit: str = "100g"
    data_source: Optional[str] = None


class FoodNutrientResponse(FoodNutrientBase):
    id: int
    food_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class FoodNutrientWithDetails(BaseModel):
    """Food nutrient with full nutrient details"""
    id: int
    value: Optional[float]
    per_unit: str
    nutrient_id: int
    nutrient_type_id: int
    nutrient_name: str
    nutrient_unit: Optional[str]
    nutrient_type_name: str
    data_source: Optional[str]
    
    class Config:
        from_attributes = True


# ============ Food Schemas ============
class FoodBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None


class FoodCreate(FoodBase):
    food_group_id: int


class FoodResponse(FoodBase):
    id: int
    food_group_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class FoodWithGroupResponse(FoodResponse):
    food_group: FoodGroupResponse


class FoodWithNutrients(FoodWithGroupResponse):
    """Food with all nutrient data"""
    nutrients: List[FoodNutrientWithDetails] = []


# ============ Search & Filter Schemas ============
class NutrientCondition(BaseModel):
    """Single nutrient condition for filtering"""
    nutrient_id: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    operator: str = Field(default="range", description="range, min, max, equals")


class FoodSearchRequest(BaseModel):
    """Request body for food search"""
    food_group_id: Optional[int] = None
    nutrient_conditions: Optional[List[NutrientCondition]] = None
    search_name: Optional[str] = None
    sort_by_nutrient_id: Optional[int] = None
    sort_order: str = "desc"  # asc or desc
    limit: int = Field(default=100, le=1000)
    offset: int = Field(default=0, ge=0)


class FoodSearchResponse(BaseModel):
    """Response for food search results"""
    total_count: int
    limit: int
    offset: int
    foods: List[FoodWithNutrients]


class NutrientGrouped(BaseModel):
    """Nutrients grouped by type"""
    nutrient_type_id: int
    nutrient_type_name: str
    nutrients: List[FoodNutrientWithDetails]


class FoodCompleteResponse(BaseModel):
    """Complete food item with nutrients grouped by type"""
    id: int
    name: str
    code: Optional[str]
    description: Optional[str]
    food_group_id: int
    food_group_name: str
    nutrient_groups: List[NutrientGrouped] = []
    created_at: datetime
