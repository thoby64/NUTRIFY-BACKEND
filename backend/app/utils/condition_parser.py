"""
Condition parser and nutrient mapping for meal planning
Handles parsing user-entered conditions like "calories <= 400, protein >= 20"
"""

import re
from typing import Dict, List, Tuple, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from app.models.models import Food, FoodNutrient, Nutrient


# Curated nutrient alias dictionary.
# Exact database nutrient codes remain the primary matching strategy.
NUTRIENT_MAPPING = {
    # Macronutrients
    'calories': 'ENERGY_KC',
    'calorie': 'ENERGY_KC',
    'energy': 'ENERGY_KC',
    'energies': 'ENERGY_KC',
    'kcal': 'ENERGY_KC',
    'kilocalorie': 'ENERGY_KC',
    'kilocalories': 'ENERGY_KC',
    'kj': 'ENERGY_KC',
    'kilojoule': 'ENERGY_KC',
    'kilojoules': 'ENERGY_KC',
    'protein': 'PROCNT',
    'prot': 'PROCNT',
    'fat': 'FAT',
    'fats': 'FAT',
    'lipid': 'FAT',
    'lipids': 'FAT',
    'carbs': 'CHOCDF',
    'carb': 'CHOCDF',
    'carbohydrates': 'CHOCDF',
    'carbohydrate': 'CHOCDF',
    'fiber': 'FIBTG',
    'fibre': 'FIBTG',
    'sugars': 'SUGAR',
    'water': 'WATER',
    
    # Minerals
    'iron': 'FE',
    'fe': 'FE',
    'calcium': 'CA',
    'ca': 'CA',
    'zinc': 'ZN',
    'zn': 'ZN',
    'magnesium': 'MG',
    'mg': 'MG',  # Careful: could also be milligrams
    'potassium': 'K',
    'k': 'K',
    'phosphorus': 'P',
    'p': 'P',
    'copper': 'CU',
    'cu': 'CU',
    'manganese': 'MN',
    'mn': 'MN',
    'sodium': 'NA',
    'na': 'NA',
    'selenium': 'SE',
    'se': 'SE',
    
    # Vitamins
    'vitamin a': 'VITA',
    'vita': 'VITA',
    'vitamin c': 'VITC',
    'vitc': 'VITC',
    'vitamin d': 'VITD',
    'vitd': 'VITD',
    'vitamin e': 'VITE',
    'vite': 'VITE',
    'thiamine': 'THIA',
    'thia': 'THIA',
    'vitamin b1': 'THIA',
    'riboflavin': 'RIBF',
    'ribf': 'RIBF',
    'vitamin b2': 'RIBF',
    'niacin': 'NIA',
    'nia': 'NIA',
    'vitamin b3': 'NIA',
    'pantothenic': 'PANT',
    'pant': 'PANT',
    'vitamin b5': 'PANT',
    'pyridoxine': 'VIT B6',
    'vitamin b6': 'VIT B6',
    'b6': 'VIT B6',
    'cobalamin': 'VIT B12',
    'vitamin b12': 'VIT B12',
    'b12': 'VIT B12',
    'folate': 'FOL',
    'fol': 'FOL',
    'vitamin b9': 'FOL',
    'biotin': 'BIOTIN',
    
    # Amino Acids
    'tryptophan': 'TRP',
    'trp': 'TRP',
    'lysine': 'LYS',
    'lys': 'LYS',
    'tyrosine': 'TYR',
    'tyr': 'TYR',
    'threonine': 'THR',
    'thr': 'THR',
    'isoleucine': 'ILE',
    'ile': 'ILE',
    'leucine': 'LEU',
    'leu': 'LEU',
    'methionine': 'MET',
    'met': 'MET',
    'cysteine': 'CYS',
    'cys': 'CYS',
    'phenylalanine': 'PHE',
    'phe': 'PHE',
    'valine': 'VAL',
    'val': 'VAL',
    'arginine': 'ARG',
    'arg': 'ARG',
    'histidine': 'HIS',
    'his': 'HIS',
    'alanine': 'ALA',
    'ala': 'ALA',
    'aspartic': 'ASP',
    'asp': 'ASP',
    'asparagine': 'ASN',
    'asn': 'ASN',
    'glutamic': 'GLU',
    'glu': 'GLU',
    'glutamine': 'GLN',
    'gln': 'GLN',
    'glycine': 'GLY',
    'gly': 'GLY',
    'proline': 'PRO',
    'pro': 'PRO',
    'serine': 'SER',
    'ser': 'SER',
}

# Allowed operators
ALLOWED_OPERATORS = ['<=', '>=', '=', '<', '>']


MASS_UNIT_FACTORS = {
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "mg": 0.001,
    "milligram": 0.001,
    "milligrams": 0.001,
    "mcg": 0.000001,
    "ug": 0.000001,
    "μg": 0.000001,
    "microgram": 0.000001,
    "micrograms": 0.000001,
}

ENERGY_UNIT_FACTORS = {
    "kcal": 1.0,
    "cal": 1.0,
    "kj": 0.239006,
}


class ParsedCondition:
    """Represents a single parsed condition"""

    def __init__(
        self,
        nutrient_code: str,
        operator: str,
        value: float,
        original_nutrient: str,
        input_unit: Optional[str] = None,
    ):
        self.nutrient_code = nutrient_code  # Database column code (e.g., 'ENERGY_KC')
        self.operator = operator  # One of: <=, >=, =, <, >
        self.value = value  # Numeric threshold
        self.original_nutrient = original_nutrient  # Original user input for reference
        self.input_unit = input_unit.lower() if input_unit else None

    def __repr__(self):
        unit_part = f" {self.input_unit}" if self.input_unit else ""
        return f"ParsedCondition({self.nutrient_code} {self.operator} {self.value}{unit_part})"


class ConditionParseError(Exception):
    """Raised when condition parsing fails"""
    pass


def get_condition_alias_reference() -> Dict[str, List[str]]:
    """Return curated human-friendly aliases grouped by canonical nutrient code."""
    aliases_by_code: Dict[str, List[str]] = {}
    for alias, nutrient_code in NUTRIENT_MAPPING.items():
        aliases_by_code.setdefault(nutrient_code, [])
        if alias not in aliases_by_code[nutrient_code]:
            aliases_by_code[nutrient_code].append(alias)
    return {
        nutrient_code: sorted(aliases)
        for nutrient_code, aliases in aliases_by_code.items()
    }


def _normalize_lookup_key(value: str) -> str:
    normalized = re.sub(r"[_-]+", " ", str(value or "").strip().lower())
    normalized = re.sub(r"[^a-z0-9\s]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _compact_lookup_key(value: str) -> str:
    return _normalize_lookup_key(value).replace(" ", "")


def _register_alias(
    lookup: Dict[str, str],
    suggestions: Dict[str, str],
    alias: Optional[str],
    nutrient_code: str,
    *,
    display: Optional[str] = None,
) -> None:
    if not alias:
        return

    nutrient_code = str(nutrient_code or "").strip().upper()
    if not nutrient_code:
        return

    normalized = _normalize_lookup_key(alias)
    compact = _compact_lookup_key(alias)
    if normalized:
        lookup.setdefault(normalized, nutrient_code)
        suggestions.setdefault(normalized, display or str(alias).strip())
    if compact and compact != normalized:
        lookup.setdefault(compact, nutrient_code)


def _build_nutrient_lookup(db: Optional[Session] = None) -> Tuple[Dict[str, str], Dict[str, str]]:
    lookup: Dict[str, str] = {}
    suggestions: Dict[str, str] = {}

    for alias, nutrient_code in NUTRIENT_MAPPING.items():
        _register_alias(lookup, suggestions, alias, nutrient_code, display=alias)

    if db is not None:
        nutrients = db.query(Nutrient.name, Nutrient.abbreviation).all()
        for nutrient_name, abbreviation in nutrients:
            nutrient_code = str(nutrient_name or "").strip().upper()
            if not nutrient_code:
                continue
            _register_alias(lookup, suggestions, nutrient_code, nutrient_code, display=nutrient_code)
            _register_alias(lookup, suggestions, abbreviation, nutrient_code, display=abbreviation or nutrient_code)

    return lookup, suggestions


def parse_conditions(condition_string: str, db: Optional[Session] = None) -> List[ParsedCondition]:
    """
    Parse user-entered condition string into structured conditions
    
    Examples:
        "calories <= 400, protein >= 20, iron > 2"
        "carbs 20-40, vitamin c > 10"
    
    Args:
        condition_string: Comma-separated condition string
    
    Returns:
        List of ParsedCondition objects
    
    Raises:
        ConditionParseError: If parsing fails
    """
    
    if not condition_string or not condition_string.strip():
        return []
    
    parsed_conditions = []
    conditions = condition_string.split(',')
    
    for condition in conditions:
        condition = condition.strip()
        if not condition:
            continue
        
        # Try to parse as a single condition with operator
        parsed = _parse_single_condition(condition, db=db)
        if isinstance(parsed, list):
            # Range condition (e.g., "carbs 20-40") returns two conditions
            parsed_conditions.extend(parsed)
        else:
            parsed_conditions.append(parsed)
    
    return parsed_conditions


def _parse_single_condition(condition: str, db: Optional[Session] = None) -> Optional[ParsedCondition | List[ParsedCondition]]:
    """
    Parse a single condition, handling both:
    - Standard format: "nutrient operator value" (e.g., "calories <= 400")
    - Range format: "nutrient min-max" (e.g., "carbs 20-40")
    
    Args:
        condition: Single condition string
    
    Returns:
        ParsedCondition or list of ParsedCondition for range
    
    Raises:
        ConditionParseError: If parsing fails
    """
    
    condition = condition.strip()
    
    # Pattern 1: Standard format with operator
    # Matches: "calories <= 400" or "protein>=20" or "iron > 2"
    standard_pattern = r'^([a-zA-Z0-9_\-\s]+?)\s*(<=|>=|=|<|>)\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Zμ%]+)?$'
    
    match = re.match(standard_pattern, condition)
    if match:
        nutrient_name = match.group(1).strip().lower()
        operator = match.group(2)
        value = float(match.group(3))
        input_unit = match.group(4)
        
        # Map nutrient name to code
        nutrient_code = _map_nutrient_name(nutrient_name, db=db)
        
        return ParsedCondition(nutrient_code, operator, value, nutrient_name, input_unit)
    
    # Pattern 2: Range format
    # Matches: "carbs 20-40" or "protein 20 - 40"
    range_pattern = r'^([a-zA-Z0-9_\-\s]+?)\s+(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*([a-zA-Zμ%]+)?$'
    
    match = re.match(range_pattern, condition)
    if match:
        nutrient_name = match.group(1).strip().lower()
        min_value = float(match.group(2))
        max_value = float(match.group(3))
        input_unit = match.group(4)
        
        # Validate range
        if min_value > max_value:
            raise ConditionParseError(
                f"Invalid range for '{nutrient_name}': {min_value}-{max_value} (min > max)"
            )
        
        nutrient_code = _map_nutrient_name(nutrient_name, db=db)
        
        # Return two conditions: >= min and <= max
        return [
            ParsedCondition(nutrient_code, '>=', min_value, nutrient_name, input_unit),
            ParsedCondition(nutrient_code, '<=', max_value, nutrient_name, input_unit),
        ]
    
    # If no pattern matched, raise error
    raise ConditionParseError(
        f"Invalid condition format: '{condition}'. "
        f"Use format: 'nutrient operator value' (e.g., 'calories <= 400') "
        f"or 'nutrient min-max' (e.g., 'carbs 20-40')"
    )


def _map_nutrient_name(nutrient_name: str, db: Optional[Session] = None) -> str:
    """
    Map user-entered nutrient name to database column code
    
    Args:
        nutrient_name: User-entered name (e.g., 'calories', 'protein', 'iron')
    
    Returns:
        Database column code (e.g., 'ENERGY_KC', 'PROCNT', 'FE')
    
    Raises:
        ConditionParseError: If nutrient name is not recognized
    """
    
    lookup, suggestions = _build_nutrient_lookup(db)
    normalized = _normalize_lookup_key(nutrient_name)
    compact = normalized.replace(" ", "")

    if normalized in lookup:
        return lookup[normalized]
    if compact in lookup:
        return lookup[compact]

    close_matches: List[str] = []
    for key, display in suggestions.items():
        if normalized and (normalized in key or key in normalized or compact == key.replace(" ", "")):
            if display not in close_matches:
                close_matches.append(display)

    if close_matches:
        if len(close_matches) == 1:
            suggestion = close_matches[0]
            suggested_code = lookup.get(_normalize_lookup_key(suggestion)) or lookup.get(_compact_lookup_key(suggestion))
            if suggested_code:
                return suggested_code
        raise ConditionParseError(
            f"Unknown nutrient: '{nutrient_name}'. "
            f"Did you mean one of: {', '.join(close_matches[:5])}?"
        )

    raise ConditionParseError(
        f"Unknown nutrient: '{nutrient_name}'. "
        "Use a database nutrient code like 'ENERGY_KC' or a known alias like 'calories', 'protein', or 'sodium'."
    )


def filter_foods_by_conditions(
    db: Session,
    conditions: List[ParsedCondition],
    mode: str = "all",
) -> List[int]:
    """
    Filter foods that match all conditions
    
    Args:
        db: Database session
        conditions: List of ParsedCondition objects
    
    Returns:
        List of food IDs that match all or any conditions depending on mode
    """
    
    if not conditions:
        # No conditions: return all foods
        return [food.id for food in db.query(Food).all()]

    normalized_mode = str(mode or "all").strip().lower()
    if normalized_mode not in {"all", "any"}:
        raise ConditionParseError("Condition mode must be either 'all' or 'any'.")
    
    query = db.query(Food).distinct()
    subqueries = [
        db.query(FoodNutrient.food_id).filter(_build_nutrient_filter(condition))
        for condition in conditions
    ]

    if normalized_mode == "all":
        for subquery in subqueries:
            query = query.filter(Food.id.in_(subquery))
    else:
        query = query.filter(or_(*[Food.id.in_(subquery) for subquery in subqueries]))
    
    matching_foods = query.all()
    return [food.id for food in matching_foods]


def _build_nutrient_filter(condition: ParsedCondition):
    """
    Build SQLAlchemy filter for a condition
    
    Args:
        condition: ParsedCondition object
    
    Returns:
        SQLAlchemy filter expression
    """
    
    nutrient_filter = FoodNutrient.nutrient.has(
        or_(Nutrient.name == condition.nutrient_code, Nutrient.abbreviation == condition.nutrient_code)
    )
    condition_value = _convert_condition_value(condition)

    if condition.operator == '<=':
        value_filter = FoodNutrient.value <= condition_value
    elif condition.operator == '>=':
        value_filter = FoodNutrient.value >= condition_value
    elif condition.operator == '<':
        value_filter = FoodNutrient.value < condition_value
    elif condition.operator == '>':
        value_filter = FoodNutrient.value > condition_value
    elif condition.operator == '=':
        value_filter = FoodNutrient.value == condition_value
    else:
        raise ConditionParseError(f"Invalid operator: {condition.operator}")
    
    return and_(nutrient_filter, value_filter)


def validate_conditions(condition_string: str, db: Optional[Session] = None) -> Tuple[bool, str]:
    """
    Validate condition string without querying database
    
    Args:
        condition_string: User-entered condition string
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    
    try:
        parse_conditions(condition_string, db=db)
        return True, "Valid"
    except ConditionParseError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Parsing error: {str(e)}"


def describe_conditions(conditions: List[ParsedCondition]) -> List[Dict[str, str]]:
    """Return a UI-friendly summary of parsed conditions."""
    described = []
    for condition in conditions:
        described.append(
            {
                "nutrient_code": condition.nutrient_code,
                "nutrient_name": condition.nutrient_code,
                "original_input": condition.original_nutrient,
                "operator": condition.operator,
                "value": f"{condition.value:g}",
                "unit": condition.input_unit or "",
            }
        )
    return described


def _convert_condition_value(condition: ParsedCondition) -> float:
    """Convert supported user-entered units into the dataset's canonical units."""
    if not condition.input_unit:
        return condition.value

    normalized_unit = condition.input_unit.lower()
    if normalized_unit in MASS_UNIT_FACTORS:
        base_grams = condition.value * MASS_UNIT_FACTORS[normalized_unit]
        expected_unit = _expected_unit_for_nutrient(condition.nutrient_code)
        if expected_unit == "g":
            return base_grams
        if expected_unit == "mg":
            return base_grams * 1000
        if expected_unit == "mcg":
            return base_grams * 1_000_000

    if normalized_unit in ENERGY_UNIT_FACTORS:
        expected_unit = _expected_unit_for_nutrient(condition.nutrient_code)
        value_in_kcal = condition.value * ENERGY_UNIT_FACTORS[normalized_unit]
        if expected_unit == "kcal":
            return value_in_kcal
        if expected_unit == "kj":
            return value_in_kcal / ENERGY_UNIT_FACTORS["kj"]

    return condition.value


def _expected_unit_for_nutrient(nutrient_code: str) -> str:
    nutrient_code = (nutrient_code or "").upper()
    if nutrient_code == "ENERGY_KC":
        return "kcal"
    if nutrient_code in {"NA", "K", "CA", "P", "MG", "FE", "ZN", "CU", "MN"}:
        return "mg"
    if nutrient_code in {"SE", "VITA", "FOL", "VIT B12"}:
        return "mcg"
    return "g"
