from sqlalchemy import Column, Integer, String, Float, DateTime, Date, ForeignKey, Text, UniqueConstraint, Index, Boolean, func, Enum as SQLEnum, JSON
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.core.database import Base
import enum


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp for SQLAlchemy Python defaults."""
    return datetime.now(timezone.utc)


class UserRole(str, enum.Enum):
    """User roles in the system"""
    ADMIN = "admin"
    NUTRITIONIST = "nutritionist"
    MANAGER = "manager"
    EDITOR = "editor"


class FoodGroup(Base):
    """Food group (e.g., Cereals, Fruits and Vegetables)"""
    __tablename__ = "food_groups"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    # Relationships
    foods = relationship("Food", back_populates="food_group", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<FoodGroup(id={self.id}, name='{self.name}')>"


class Food(Base):
    """Individual food items"""
    __tablename__ = "foods"
    
    id = Column(Integer, primary_key=True, index=True)
    food_group_id = Column(Integer, ForeignKey("food_groups.id"), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)
    code = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    __table_args__ = (
        UniqueConstraint("food_group_id", "name", name="uq_food_group_name"),
        Index("idx_food_name", "name"),
    )
    
    # Relationships
    food_group = relationship("FoodGroup", back_populates="foods")
    nutrients = relationship("FoodNutrient", back_populates="food", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Food(id={self.id}, name='{self.name}')>"


class NutrientType(Base):
    """Types of nutrients (amino acids, macronutrients, minerals, vitamins)"""
    __tablename__ = "nutrient_types"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    category = Column(String(100), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    # Relationships
    nutrients = relationship("Nutrient", back_populates="nutrient_type", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<NutrientType(id={self.id}, name='{self.name}')>"


class Nutrient(Base):
    """Individual nutrients within each type"""
    __tablename__ = "nutrients"
    
    id = Column(Integer, primary_key=True, index=True)
    nutrient_type_id = Column(Integer, ForeignKey("nutrient_types.id"), nullable=False, index=True)
    name = Column(String(100), nullable=False, index=True)
    unit = Column(String(50), nullable=True)
    abbreviation = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    __table_args__ = (
        UniqueConstraint("nutrient_type_id", "name", name="uq_nutrient_type_name"),
        Index("idx_nutrient_name", "name"),
    )
    
    # Relationships
    nutrient_type = relationship("NutrientType", back_populates="nutrients")
    food_nutrients = relationship("FoodNutrient", back_populates="nutrient", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Nutrient(id={self.id}, name='{self.name}', unit='{self.unit}')>"


class FoodNutrient(Base):
    """Junction table: Food-Nutrient values"""
    __tablename__ = "food_nutrients"
    
    id = Column(Integer, primary_key=True, index=True)
    food_id = Column(Integer, ForeignKey("foods.id", ondelete="CASCADE"), nullable=False, index=True)
    nutrient_id = Column(Integer, ForeignKey("nutrients.id"), nullable=False, index=True)
    nutrient_type_id = Column(Integer, ForeignKey("nutrient_types.id"), nullable=False, index=True)
    value = Column(Float, nullable=True)
    per_unit = Column(String(50), default="100g")
    data_source = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    __table_args__ = (
        UniqueConstraint("food_id", "nutrient_id", name="uq_food_nutrient"),
        Index("idx_food_nutrient_value", "food_id", "nutrient_type_id", "value"),
        Index("idx_nutrient_type_value", "nutrient_type_id", "value"),
    )
    
    # Relationships
    food = relationship("Food", back_populates="nutrients")
    nutrient = relationship("Nutrient", back_populates="food_nutrients")
    nutrient_type_rel = relationship("NutrientType")
    
    def __repr__(self):
        return f"<FoodNutrient(food_id={self.food_id}, nutrient_id={self.nutrient_id}, value={self.value})>"


class User(Base):
    """User accounts with role-based access control"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    role = Column(SQLEnum(UserRole), default=UserRole.EDITOR, nullable=False, index=True)
    is_active = Column(Boolean, default=True, index=True)
    
    # Track who created this user (admin or manager)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    last_login = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    plans = relationship("NutritionPlan", back_populates="nutritionist", cascade="all, delete-orphan")
    created_by = relationship("User", remote_side=[id], foreign_keys=[created_by_id])
    
    def __repr__(self):
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"


class NutritionPlan(Base):
    """Nutrition plan created by nutritionist for clients"""
    __tablename__ = "nutrition_plans"
    
    id = Column(Integer, primary_key=True, index=True)
    nutritionist_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_name = Column(String(255), nullable=False)
    plan_date = Column(DateTime, default=utcnow, nullable=False)
    
    # Daily targets as free-form text for user flexibility
    daily_targets = Column(Text, nullable=True)
    
    # Plan status
    status = Column(String(50), default="draft", nullable=False)  # 'draft', 'finalized', 'archived'
    
    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    nutritionist = relationship("User", back_populates="plans")
    meals = relationship("Meal", back_populates="plan", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<NutritionPlan(id={self.id}, plan='{self.plan_name}')>"


class Meal(Base):
    """Individual meal within a nutrition plan"""
    __tablename__ = "meals"
    
    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("nutrition_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    meal_name = Column(String(255), nullable=False)
    meal_order = Column(Integer, nullable=False)  # Sequence order (1, 2, 3, etc.)
    
    # Original condition string used to filter foods
    condition_string = Column(String(500), nullable=True)
    
    # Meal composition totals (denormalized for quick access)
    total_energy_kc = Column(Float, nullable=True)
    total_procnt = Column(Float, nullable=True)
    total_fat = Column(Float, nullable=True)
    total_chocdf = Column(Float, nullable=True)
    total_fiber = Column(Float, nullable=True)
    
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    plan = relationship("NutritionPlan", back_populates="meals")
    foods = relationship("MealFood", back_populates="meal", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Meal(id={self.id}, plan_id={self.plan_id}, name='{self.meal_name}')>"


class MealFood(Base):
    """Foods within each meal (with snapshot data)"""
    __tablename__ = "meal_foods"
    
    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("meals.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Reference to original food (optional, for audit trail)
    food_id = Column(Integer, ForeignKey("foods.id"), nullable=True)
    
    # Food information snapshot
    food_name = Column(String(255), nullable=False)
    food_group_name = Column(String(100), nullable=True)
    
    # Portion information
    portion_grams = Column(Float, nullable=False)
    portion_description = Column(String(100), nullable=True)  # e.g., "1 medium", "150g baked"
    
    # COMPLETE NUTRIENT SNAPSHOT AS JSON
    # Preserves exact state of food at time of selection
    # Structure: {"macronutrients": {...}, "vitamins": {...}, "minerals": {...}, "amino_acids": {...}}
    nutrient_snapshot = Column(JSON, nullable=False)
    
    # Pre-calculated nutrients at this portion (convenience field)
    # Structure: {"ENERGY_KC": 247.5, "PROCNT": 46.5, "FAT": 5.4, ...}
    calculated_nutrients = Column(JSON, nullable=False)
    
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    meal = relationship("Meal", back_populates="foods")
    food = relationship("Food")
    
    def __repr__(self):
        return f"<MealFood(id={self.id}, meal_id={self.meal_id}, food='{self.food_name}', portion={self.portion_grams}g)>"


class PasswordResetToken(Base):
    """Password reset tokens for secure password recovery"""
    __tablename__ = "password_reset_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Hash of the token (never store plain tokens)
    token = Column(String(255), unique=True, nullable=False, index=True)
    
    # When this token expires
    expires_at = Column(DateTime, nullable=False, index=True)
    
    # When token was used (if at all) - prevents reuse
    used_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, server_default=func.now())
    
    # Relationships
    user = relationship("User")


class PlanningPlanType(str, enum.Enum):
    """Supported V2 planning plan types"""
    MULTI_DAY = "multi_day"
    WEEKLY_CYCLE = "weekly_cycle"
    TEMPLATE = "template"


class PlanningPlanStatus(str, enum.Enum):
    """Lifecycle for the V2 planning flow"""
    DRAFT = "draft"
    REVIEW = "review"
    FINALIZED = "finalized"
    ARCHIVED = "archived"


class PlanningClient(Base):
    """Privacy-safe planning client reference"""
    __tablename__ = "planning_clients"

    id = Column(Integer, primary_key=True, index=True)
    client_code = Column(String(100), nullable=False, unique=True, index=True)
    display_label = Column(String(255), nullable=False)
    privacy_tier = Column(String(50), default="standard", nullable=False)
    assigned_nutritionist_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(50), default="active", nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    assigned_nutritionist = relationship("User", foreign_keys=[assigned_nutritionist_id])
    created_by = relationship("User", foreign_keys=[created_by_id])
    planning_profile = relationship("ClientPlanningProfile", back_populates="client", uselist=False, cascade="all, delete-orphan")
    plans_v2 = relationship("PlanningPlan", back_populates="client")


class ClientPlanningProfile(Base):
    """Derived, planning-safe client profile data"""
    __tablename__ = "client_planning_profiles"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("planning_clients.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    age_group = Column(String(100), nullable=True)
    sex = Column(String(50), nullable=True)
    goal_summary = Column(Text, nullable=True)
    clinical_summary = Column(Text, nullable=True)
    dietary_pattern = Column(String(255), nullable=True)
    allergies = Column(Text, nullable=True)
    exclusions = Column(Text, nullable=True)
    preferences = Column(Text, nullable=True)
    cultural_notes = Column(Text, nullable=True)
    planning_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    client = relationship("PlanningClient", back_populates="planning_profile")


class PlanningPlan(Base):
    """V2 planning plan with multi-day support"""
    __tablename__ = "planning_plans"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("planning_clients.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    assigned_nutritionist_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    title = Column(String(255), nullable=False, index=True)
    plan_type = Column(SQLEnum(PlanningPlanType), default=PlanningPlanType.MULTI_DAY, nullable=False, index=True)
    start_date = Column(Date, nullable=True)
    days_count = Column(Integer, default=1, nullable=False)
    cycle_length = Column(Integer, nullable=True)
    status = Column(SQLEnum(PlanningPlanStatus), default=PlanningPlanStatus.DRAFT, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    client = relationship("PlanningClient", back_populates="plans_v2")
    created_by = relationship("User", foreign_keys=[created_by_id])
    assigned_nutritionist = relationship("User", foreign_keys=[assigned_nutritionist_id])
    days = relationship("PlanningPlanDay", back_populates="plan", cascade="all, delete-orphan")
    versions = relationship("PlanningPlanVersion", back_populates="plan", cascade="all, delete-orphan")
    rules = relationship("PlanningRule", back_populates="plan", cascade="all, delete-orphan")
    nutrient_targets = relationship("PlanningNutrientTarget", back_populates="plan", cascade="all, delete-orphan")


class PlanningPlanDay(Base):
    """A single day inside a V2 plan"""
    __tablename__ = "planning_plan_days"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("planning_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    day_index = Column(Integer, nullable=False)
    day_name = Column(String(100), nullable=False)
    actual_date = Column(Date, nullable=True)
    template_group = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("plan_id", "day_index", name="uq_planning_plan_day_index"),
    )

    plan = relationship("PlanningPlan", back_populates="days")
    meals = relationship("PlanningPlanMeal", back_populates="day", cascade="all, delete-orphan")
    rules = relationship("PlanningRule", back_populates="day", cascade="all, delete-orphan")
    nutrient_targets = relationship("PlanningNutrientTarget", back_populates="day", cascade="all, delete-orphan")


class PlanningPlanMeal(Base):
    """A meal inside a specific plan day"""
    __tablename__ = "planning_plan_meals"

    id = Column(Integer, primary_key=True, index=True)
    day_id = Column(Integer, ForeignKey("planning_plan_days.id", ondelete="CASCADE"), nullable=False, index=True)
    meal_name = Column(String(255), nullable=False)
    meal_type = Column(String(100), nullable=True)
    meal_time = Column(String(50), nullable=True)
    meal_order = Column(Integer, nullable=False)
    instructions = Column(Text, nullable=True)
    target_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("day_id", "meal_order", name="uq_planning_day_meal_order"),
    )

    day = relationship("PlanningPlanDay", back_populates="meals")
    foods = relationship("PlanningMealFood", back_populates="meal", cascade="all, delete-orphan")
    rules = relationship("PlanningRule", back_populates="meal", cascade="all, delete-orphan")
    nutrient_targets = relationship("PlanningNutrientTarget", back_populates="meal", cascade="all, delete-orphan")


class PlanningMealFood(Base):
    """A selected food item inside a V2 plan meal, preserved as a snapshot"""
    __tablename__ = "planning_meal_foods"

    id = Column(Integer, primary_key=True, index=True)
    meal_id = Column(Integer, ForeignKey("planning_plan_meals.id", ondelete="CASCADE"), nullable=False, index=True)
    food_id = Column(Integer, ForeignKey("foods.id", ondelete="SET NULL"), nullable=True, index=True)
    food_name = Column(String(255), nullable=False)
    food_code = Column(String(50), nullable=True)
    food_group_name = Column(String(100), nullable=True)
    portion_grams = Column(Float, nullable=False)
    portion_description = Column(String(120), nullable=True)
    household_measure = Column(String(120), nullable=True)
    unit_label = Column(String(50), nullable=True)
    preparation_state = Column(String(100), nullable=True)
    notes = Column(Text, nullable=True)
    sort_order = Column(Integer, default=1, nullable=False)
    nutrient_snapshot = Column(JSON, nullable=False)
    calculated_nutrients = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    meal = relationship("PlanningPlanMeal", back_populates="foods")
    food = relationship("Food")


class PlanningPlanVersion(Base):
    """Immutable version record for a finalized V2 plan"""
    __tablename__ = "planning_plan_versions"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("planning_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    status = Column(SQLEnum(PlanningPlanStatus), default=PlanningPlanStatus.DRAFT, nullable=False, index=True)
    snapshot_json = Column(JSON, nullable=True)
    finalized_at = Column(DateTime, nullable=True)
    finalized_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("plan_id", "version_number", name="uq_planning_plan_version_number"),
    )

    plan = relationship("PlanningPlan", back_populates="versions")
    finalized_by = relationship("User", foreign_keys=[finalized_by_id])


class PlanningRule(Base):
    """Structured rule / condition foundation for V2 planning"""
    __tablename__ = "planning_rules"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("planning_clients.id", ondelete="CASCADE"), nullable=True, index=True)
    plan_id = Column(Integer, ForeignKey("planning_plans.id", ondelete="CASCADE"), nullable=True, index=True)
    day_id = Column(Integer, ForeignKey("planning_plan_days.id", ondelete="CASCADE"), nullable=True, index=True)
    meal_id = Column(Integer, ForeignKey("planning_plan_meals.id", ondelete="CASCADE"), nullable=True, index=True)
    scope = Column(String(50), nullable=False, default="plan")
    rule_type = Column(String(100), nullable=False)
    severity = Column(String(50), nullable=False, default="soft")
    title = Column(String(255), nullable=False)
    details = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    plan = relationship("PlanningPlan", back_populates="rules")
    day = relationship("PlanningPlanDay", back_populates="rules")
    meal = relationship("PlanningPlanMeal", back_populates="rules")


class PlanningNutrientTarget(Base):
    """Scoped nutrient targets for plan, day, or meal"""
    __tablename__ = "planning_nutrient_targets"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("planning_plans.id", ondelete="CASCADE"), nullable=True, index=True)
    day_id = Column(Integer, ForeignKey("planning_plan_days.id", ondelete="CASCADE"), nullable=True, index=True)
    meal_id = Column(Integer, ForeignKey("planning_plan_meals.id", ondelete="CASCADE"), nullable=True, index=True)
    nutrient_code = Column(String(100), nullable=False, index=True)
    unit = Column(String(50), nullable=True)
    min_value = Column(Float, nullable=True)
    target_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    plan = relationship("PlanningPlan", back_populates="nutrient_targets")
    day = relationship("PlanningPlanDay", back_populates="nutrient_targets")
    meal = relationship("PlanningPlanMeal", back_populates="nutrient_targets")
    
    def __repr__(self):
        return f"<PlanningNutrientTarget(id={self.id}, nutrient_code={self.nutrient_code}, unit={self.unit})>"
