"""
Planning substitution helpers
Builds nutrient-aware swap suggestions for selected meal foods.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence


KEY_SUBSTITUTION_NUTRIENTS = [
    {"code": "ENERGY_KC", "label": "Energy", "unit": "kcal", "weight": 0.30},
    {"code": "PROCNT", "label": "Protein", "unit": "g", "weight": 0.28},
    {"code": "CHOCDF", "label": "Carbohydrates", "unit": "g", "weight": 0.18},
    {"code": "FAT", "label": "Fat", "unit": "g", "weight": 0.16},
    {"code": "FIBTG", "label": "Fiber", "unit": "g", "weight": 0.08},
]


def _relative_difference(current_value: float, candidate_value: float) -> float:
    denominator = max(abs(current_value), 1.0)
    return abs(candidate_value - current_value) / denominator


def build_nutrient_deltas(current_nutrients: Dict[str, float], candidate_nutrients: Dict[str, float]) -> List[Dict[str, Any]]:
    """Return key nutrient deltas between the current food and a candidate."""
    deltas = []

    for nutrient in KEY_SUBSTITUTION_NUTRIENTS:
        code = nutrient["code"]
        current_value = float(current_nutrients.get(code, 0) or 0)
        candidate_value = float(candidate_nutrients.get(code, 0) or 0)
        deltas.append(
            {
                "code": code,
                "label": nutrient["label"],
                "unit": nutrient["unit"],
                "current_value": round(current_value, 2),
                "candidate_value": round(candidate_value, 2),
                "delta": round(candidate_value - current_value, 2),
            }
        )

    return deltas


def score_substitution(
    current_nutrients: Dict[str, float],
    candidate_nutrients: Dict[str, float],
    *,
    same_group: bool = False,
    same_exchange: bool = False,
) -> float:
    """Score a candidate food by nutrient similarity to the current food."""
    weighted_difference = 0.0

    for nutrient in KEY_SUBSTITUTION_NUTRIENTS:
        code = nutrient["code"]
        current_value = float(current_nutrients.get(code, 0) or 0)
        candidate_value = float(candidate_nutrients.get(code, 0) or 0)
        weighted_difference += _relative_difference(current_value, candidate_value) * float(nutrient["weight"])

    raw_score = max(0.0, 100.0 - min(weighted_difference * 100.0, 100.0))
    if same_group:
        raw_score = min(100.0, raw_score + 6.0)
    if same_exchange:
        raw_score = min(100.0, raw_score + 8.0)

    return round(raw_score, 1)


def build_similarity_summary(deltas: Sequence[Dict[str, Any]]) -> str:
    """Create a short human explanation for why a substitute is similar or different."""
    if not deltas:
        return "Alternative nutrient profile available."

    ranked = sorted(deltas, key=lambda item: abs(float(item["delta"])), reverse=True)
    closest = sorted(deltas, key=lambda item: abs(float(item["delta"])))[:2]

    close_bits = [
        f"{item['label'].lower()} stays close"
        for item in closest
        if abs(float(item["delta"])) <= max(abs(float(item["current_value"])) * 0.15, 2.0)
    ]
    if close_bits:
        return ", ".join(close_bits).capitalize() + "."

    biggest = ranked[0]
    if float(biggest["delta"]) > 0:
        return f"Higher {biggest['label'].lower()} than the current choice."
    if float(biggest["delta"]) < 0:
        return f"Lower {biggest['label'].lower()} than the current choice."
    return "Very close overall nutrient profile."


def build_replacement_note(previous_food_name: str, new_food_name: str, replacement_reason: Optional[str] = None) -> str:
    """Create a lightweight audit note for a replacement action."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    base_note = f"Replaced {previous_food_name} with {new_food_name} on {timestamp}"
    if replacement_reason:
        return f"{base_note}. Reason: {replacement_reason.strip()}"
    return base_note


def infer_exchange_category(nutrients: Dict[str, float], food_group_name: Optional[str] = None) -> str:
    """Infer a practical exchange-style category from nutrient balance."""
    energy = float(nutrients.get("ENERGY_KC", 0) or 0)
    protein = float(nutrients.get("PROCNT", 0) or 0)
    carbs = float(nutrients.get("CHOCDF", 0) or 0)
    fat = float(nutrients.get("FAT", 0) or 0)
    fiber = float(nutrients.get("FIBTG", 0) or 0)
    group = (food_group_name or "").lower()

    if protein >= 15 and carbs <= 15:
        return "lean_protein"
    if fat >= 12 and protein < 12 and carbs < 15:
        return "fat_source"
    if carbs >= 15 and fiber >= 3:
        return "high_fiber_carb"
    if carbs >= 15:
        return "starchy_carb"
    if "fruit" in group or "vegetable" in group or fiber >= 2:
        return "fruit_veg"
    if energy and protein >= 8 and carbs >= 8:
        return "mixed_meal_component"
    return "general_exchange"
