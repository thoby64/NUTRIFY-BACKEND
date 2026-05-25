"""
Planning validation helpers
Turns structured rules and nutrient targets into practical validation output.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.models.models import ClientPlanningProfile, PlanningMealFood, PlanningNutrientTarget, PlanningPlan, PlanningPlanDay, PlanningPlanMeal, PlanningRule


SPLIT_PATTERN = re.compile(r"[,;/\n]+|\band\b|\bor\b", re.IGNORECASE)
STOPWORDS = {
    "meal",
    "meals",
    "food",
    "foods",
    "item",
    "items",
    "daily",
    "day",
    "plan",
    "with",
    "from",
    "into",
    "that",
    "this",
    "must",
    "should",
}
EXCLUSION_MARKERS = [
    "avoid",
    "exclude",
    "excluding",
    "without",
    "no ",
    "free from",
    "allergy to",
    "allergic to",
    "restrict",
    "restriction",
    "limit",
]
INCLUSION_MARKERS = [
    "include",
    "prefer",
    "choose",
    "use",
    "add",
    "focus on",
]

PROFILE_GUARDRAIL_DEFINITIONS = [
    {
        "id": "low_sodium_support",
        "title": "Low-sodium guardrail",
        "keywords": ["low sodium", "hypertension", "high blood pressure", "heart failure", "edema", "oedema"],
        "thresholds": {
            "meal": [{"nutrient_code": "NA", "max_value": 700.0, "unit": "mg"}],
            "day": [{"nutrient_code": "NA", "max_value": 2000.0, "unit": "mg"}],
            "plan": [{"nutrient_code": "NA", "max_value": 2000.0, "unit": "mg", "per_day_average": True}],
        },
    },
    {
        "id": "renal_support",
        "title": "Renal support guardrail",
        "keywords": ["renal", "kidney", "ckd", "dialysis"],
        "thresholds": {
            "meal": [
                {"nutrient_code": "NA", "max_value": 700.0, "unit": "mg"},
                {"nutrient_code": "K", "max_value": 900.0, "unit": "mg"},
            ],
            "day": [
                {"nutrient_code": "NA", "max_value": 2000.0, "unit": "mg"},
                {"nutrient_code": "K", "max_value": 3000.0, "unit": "mg"},
                {"nutrient_code": "P", "max_value": 1000.0, "unit": "mg"},
            ],
            "plan": [
                {"nutrient_code": "NA", "max_value": 2000.0, "unit": "mg", "per_day_average": True},
                {"nutrient_code": "K", "max_value": 3000.0, "unit": "mg", "per_day_average": True},
                {"nutrient_code": "P", "max_value": 1000.0, "unit": "mg", "per_day_average": True},
            ],
        },
    },
    {
        "id": "glycemic_balance_support",
        "title": "Glycemic balance guardrail",
        "keywords": ["diabetes", "diabetic", "prediabetes", "insulin resistance", "gestational diabetes", "pcos"],
        "thresholds": {
            "meal": [
                {"nutrient_code": "CHOCDF", "max_value": 75.0, "unit": "g"},
                {"nutrient_code": "FIBTG", "min_value": 5.0, "unit": "g"},
            ],
        },
    },
    {
        "id": "iron_support",
        "title": "Iron support guardrail",
        "keywords": ["anemia", "anaemia", "iron deficiency", "pregnancy", "prenatal"],
        "thresholds": {
            "day": [{"nutrient_code": "FE", "min_value": 8.0, "unit": "mg"}],
            "plan": [{"nutrient_code": "FE", "min_value": 8.0, "unit": "mg", "per_day_average": True}],
        },
    },
    {
        "id": "bone_support",
        "title": "Bone support guardrail",
        "keywords": ["osteoporosis", "osteopenia", "bone health", "fracture risk"],
        "thresholds": {
            "day": [{"nutrient_code": "CA", "min_value": 1000.0, "unit": "mg"}],
            "plan": [{"nutrient_code": "CA", "min_value": 1000.0, "unit": "mg", "per_day_average": True}],
        },
    },
]


def normalize_text(value: Optional[str]) -> str:
    """Normalize text for keyword matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", (value or "").lower())).strip()


def summarize_totals(summary: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map aggregate nutrient totals by nutrient code."""
    totals = {}
    for item in (summary or {}).get("totals", []):
        code = str(item.get("code") or "").upper()
        if code:
            totals[code] = item
    return totals


def _profile_guardrail_text(profile: Optional[ClientPlanningProfile]) -> str:
    if profile is None:
        return ""
    return normalize_text(
        " ".join(
            filter(
                None,
                [
                    profile.goal_summary,
                    profile.clinical_summary,
                    profile.dietary_pattern,
                    profile.planning_notes,
                ],
            )
        )
    )


def infer_profile_guardrails(profile: Optional[ClientPlanningProfile]) -> List[Dict[str, Any]]:
    """Select automatic guardrails based on planning-safe profile context."""
    profile_text = _profile_guardrail_text(profile)
    if not profile_text:
        return []

    active_guardrails = []
    for guardrail in PROFILE_GUARDRAIL_DEFINITIONS:
        if any(keyword in profile_text for keyword in guardrail["keywords"]):
            active_guardrails.append(guardrail)
    return active_guardrails


def evaluate_profile_guardrails(
    profile: Optional[ClientPlanningProfile],
    summary: Optional[Dict[str, Any]],
    scope: str,
    *,
    plan_days_count: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Build clinically meaningful guardrail checks from profile context."""
    guardrails = infer_profile_guardrails(profile)
    if not guardrails:
        return []

    totals = summarize_totals(summary)
    checks: List[Dict[str, Any]] = []
    divisor = max(int(plan_days_count or 1), 1) if scope == "plan" else 1

    for guardrail in guardrails:
        for threshold in guardrail.get("thresholds", {}).get(scope, []):
            nutrient_code = threshold["nutrient_code"].upper()
            total = totals.get(nutrient_code)
            measurement_label = "average per day" if threshold.get("per_day_average") and scope == "plan" else "total"

            if total is None:
                checks.append(
                    {
                        "kind": "guardrail",
                        "guardrail_id": guardrail["id"],
                        "title": guardrail["title"],
                        "severity": "info",
                        "status": "missing_nutrient_measurement",
                        "nutrient_code": nutrient_code,
                        "message": f"{nutrient_code} is not available in the current nutrient summary, so this automatic guardrail still needs professional review.",
                    }
                )
                continue

            actual_value = float(total.get("value") or 0.0)
            if threshold.get("per_day_average") and scope == "plan":
                actual_value = actual_value / divisor

            min_value = threshold.get("min_value")
            max_value = threshold.get("max_value")
            unit = threshold.get("unit") or total.get("unit") or ""

            if max_value is not None and actual_value > float(max_value):
                checks.append(
                    {
                        "kind": "guardrail",
                        "guardrail_id": guardrail["id"],
                        "title": guardrail["title"],
                        "severity": "warning",
                        "status": "above_guardrail_max",
                        "nutrient_code": nutrient_code,
                        "actual_value": round(actual_value, 2),
                        "max_value": float(max_value),
                        "unit": unit,
                        "message": f"{nutrient_code} {measurement_label} {actual_value:.2f} {unit} is above the automatic guardrail maximum of {float(max_value):.2f} {unit}.",
                    }
                )
            elif min_value is not None and actual_value < float(min_value):
                checks.append(
                    {
                        "kind": "guardrail",
                        "guardrail_id": guardrail["id"],
                        "title": guardrail["title"],
                        "severity": "warning",
                        "status": "below_guardrail_min",
                        "nutrient_code": nutrient_code,
                        "actual_value": round(actual_value, 2),
                        "min_value": float(min_value),
                        "unit": unit,
                        "message": f"{nutrient_code} {measurement_label} {actual_value:.2f} {unit} is below the automatic guardrail minimum of {float(min_value):.2f} {unit}.",
                    }
                )

    return checks


def _strip_markers(value: str) -> str:
    cleaned = value.strip()
    for marker in EXCLUSION_MARKERS + INCLUSION_MARKERS:
        if cleaned.startswith(marker):
            cleaned = cleaned[len(marker):].strip(" :-")
    return cleaned


def extract_rule_keywords(rule: PlanningRule) -> List[str]:
    """Extract likely food keywords from a structured rule title/details."""
    raw_fragments = [rule.title or "", rule.details or ""]
    keywords: List[str] = []

    for raw_value in raw_fragments:
        normalized = normalize_text(raw_value)
        if not normalized:
            continue
        for piece in SPLIT_PATTERN.split(normalized):
            cleaned = _strip_markers(piece.strip())
            cleaned = re.sub(r"\b(low|high|moderate|reduced)\b", "", cleaned).strip(" -")
            if len(cleaned) < 3 or cleaned in STOPWORDS:
                continue
            keywords.append(cleaned)

    unique_keywords: List[str] = []
    seen = set()
    for keyword in keywords:
        if keyword not in seen:
            seen.add(keyword)
            unique_keywords.append(keyword)

    return unique_keywords


def rule_has_exclusion_intent(rule: PlanningRule) -> bool:
    """Determine whether a rule is exclusion-oriented."""
    blob = normalize_text(" ".join(filter(None, [rule.rule_type, rule.title, rule.details])))
    return rule.rule_type in {"allergy", "ingredient", "clinical"} or any(marker.strip() in blob for marker in EXCLUSION_MARKERS)


def rule_has_inclusion_intent(rule: PlanningRule) -> bool:
    """Determine whether a rule expresses a desired inclusion/preference."""
    blob = normalize_text(" ".join(filter(None, [rule.rule_type, rule.title, rule.details])))
    return rule.rule_type in {"preference"} or any(marker in blob for marker in INCLUSION_MARKERS)


def rule_supports_auto_check(rule: PlanningRule) -> bool:
    """Whether a rule can be auto-checked by keywords."""
    return bool(extract_rule_keywords(rule))


def _keyword_matches(keyword: str, text: str) -> bool:
    if not keyword or not text:
        return False
    pattern = r"\b" + re.escape(keyword).replace(r"\ ", r"\s+") + r"\b"
    return bool(re.search(pattern, text))


def evaluate_food_against_rules(food_name: str, food_group_name: Optional[str], rules: Sequence[PlanningRule]) -> Dict[str, Any]:
    """Evaluate a catalog food against a set of effective rules."""
    text = normalize_text(f"{food_name} {food_group_name or ''}")
    blocked_by: List[Dict[str, Any]] = []
    warned_by: List[Dict[str, Any]] = []
    info: List[Dict[str, Any]] = []

    for rule in rules:
        if not rule.is_active or not rule_supports_auto_check(rule):
            continue
        keywords = extract_rule_keywords(rule)
        matched = [keyword for keyword in keywords if _keyword_matches(keyword, text)]
        if not matched:
            continue

        payload = {
            "rule_id": rule.id,
            "title": rule.title,
            "severity": rule.severity,
            "rule_type": rule.rule_type,
            "matched_keywords": matched,
        }

        if rule_has_exclusion_intent(rule):
            if rule.severity == "hard":
                blocked_by.append(payload)
            else:
                warned_by.append(payload)
        else:
            info.append(payload)

    return {
        "hard_blocked": len(blocked_by) > 0,
        "blocked_by": blocked_by,
        "warnings": warned_by,
        "info": info,
    }


def evaluate_targets(
    targets: Sequence[PlanningNutrientTarget],
    summary: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Evaluate nutrient targets against aggregated summary totals."""
    totals = {
        item["code"]: item
        for item in (summary or {}).get("totals", [])
        if item.get("code")
    }
    findings: List[Dict[str, Any]] = []

    for target in targets:
        actual = totals.get(target.nutrient_code)
        actual_value = actual.get("value") if actual else None
        unit = target.unit or (actual.get("unit") if actual else "")
        status = "within_range"
        severity = "info"
        message = "Within configured range."

        if actual_value is None:
            status = "missing_nutrient"
            severity = "warning"
            message = "No nutrient value was available for this target."
        elif target.min_value is not None and actual_value < target.min_value:
            status = "below_min"
            severity = "warning"
            message = f"Actual value {actual_value:.2f} is below minimum {target.min_value:.2f}."
        elif target.max_value is not None and actual_value > target.max_value:
            status = "above_max"
            severity = "warning"
            message = f"Actual value {actual_value:.2f} is above maximum {target.max_value:.2f}."
        elif target.target_value is not None and target.min_value is None and target.max_value is None:
            tolerance = max(abs(target.target_value) * 0.05, 1.0)
            delta = abs(actual_value - target.target_value)
            if delta <= tolerance:
                status = "on_target"
                severity = "info"
                message = "Actual value is close to the configured target."
            else:
                status = "off_target"
                severity = "warning"
                message = f"Actual value {actual_value:.2f} differs from target {target.target_value:.2f}."

        findings.append(
            {
                "kind": "target",
                "target_id": target.id,
                "nutrient_code": target.nutrient_code,
                "unit": unit,
                "min_value": target.min_value,
                "target_value": target.target_value,
                "max_value": target.max_value,
                "actual_value": actual_value,
                "status": status,
                "severity": severity,
                "message": message,
            }
        )

    return findings


def build_scope_validation(
    scope_label: str,
    rules: Sequence[PlanningRule],
    targets: Sequence[PlanningNutrientTarget],
    foods: Sequence[PlanningMealFood],
    summary: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build validation results for a specific scope using its own rules/targets."""
    checks: List[Dict[str, Any]] = []

    for rule in rules:
        if not rule.is_active:
            continue
        if not rule_supports_auto_check(rule):
            checks.append(
                {
                    "kind": "rule",
                    "rule_id": rule.id,
                    "title": rule.title,
                    "severity": "info",
                    "status": "manual_review",
                    "message": "This rule needs manual professional review.",
                }
            )
            continue

        if not foods:
            checks.append(
                {
                    "kind": "rule",
                    "rule_id": rule.id,
                    "title": rule.title,
                    "severity": "info",
                    "status": "pending_foods",
                    "message": "No foods are selected yet, so this rule cannot be checked.",
                }
            )
            continue

        keywords = extract_rule_keywords(rule)
        matched_foods = []
        for food in foods:
            text = normalize_text(f"{food.food_name} {food.food_group_name or ''}")
            if any(_keyword_matches(keyword, text) for keyword in keywords):
                matched_foods.append(food.food_name)

        if rule_has_exclusion_intent(rule) and matched_foods:
            checks.append(
                {
                    "kind": "rule",
                    "rule_id": rule.id,
                    "title": rule.title,
                    "severity": "blocker" if rule.severity == "hard" else "warning",
                    "status": "matched_exclusion",
                    "matched_foods": matched_foods,
                    "message": f"Rule matched selected foods: {', '.join(matched_foods[:5])}.",
                }
            )
        elif rule_has_inclusion_intent(rule) and not matched_foods:
            checks.append(
                {
                    "kind": "rule",
                    "rule_id": rule.id,
                    "title": rule.title,
                    "severity": "warning" if rule.severity == "hard" else "info",
                    "status": "missing_preference",
                    "matched_foods": [],
                    "message": "No selected foods appear to satisfy this inclusion/preference rule yet.",
                }
            )

    checks.extend(evaluate_targets(targets, summary))

    blockers_count = len([check for check in checks if check.get("severity") == "blocker"])
    warnings_count = len([check for check in checks if check.get("severity") == "warning"])
    info_count = len([check for check in checks if check.get("severity") == "info"])

    overall_status = "ok"
    if blockers_count > 0:
        overall_status = "blocked"
    elif warnings_count > 0:
        overall_status = "warning"

    return {
        "scope": scope_label,
        "overall_status": overall_status,
        "blockers_count": blockers_count,
        "warnings_count": warnings_count,
        "info_count": info_count,
        "checks": checks,
    }


def get_effective_context(plan: PlanningPlan, day: Optional[PlanningPlanDay] = None, meal: Optional[PlanningPlanMeal] = None) -> Tuple[List[PlanningRule], List[PlanningNutrientTarget]]:
    """Collect inherited active rules and targets for a meal/day context."""
    rules = build_client_profile_rules(getattr(plan.client, "planning_profile", None)) + [rule for rule in plan.rules if rule.is_active]
    targets = list(plan.nutrient_targets)

    if day is not None:
        rules.extend(rule for rule in day.rules if rule.is_active)
        targets.extend(day.nutrient_targets)

    if meal is not None:
        rules.extend(rule for rule in meal.rules if rule.is_active)
        targets.extend(meal.nutrient_targets)

    return rules, targets


def build_client_profile_rules(profile: Optional[ClientPlanningProfile]) -> List[PlanningRule]:
    """Turn planning-safe client profile context into derived validation rules."""
    if profile is None:
        return []

    derived: List[PlanningRule] = []

    def add_rule(rule_type: str, severity: str, title: str, details: Optional[str] = None) -> None:
        derived.append(
            PlanningRule(
                id=None,
                scope="profile",
                rule_type=rule_type,
                severity=severity,
                title=title,
                details=details,
                is_active=True,
            )
        )

    if profile.allergies:
        add_rule("allergy", "hard", f"Avoid allergens: {profile.allergies}", "Derived automatically from the planning-safe client profile.")
    if profile.exclusions:
        add_rule("ingredient", "hard", f"Exclude: {profile.exclusions}", "Derived automatically from the planning-safe client profile.")
    if profile.preferences:
        add_rule("preference", "soft", f"Prefer: {profile.preferences}", "Derived automatically from the planning-safe client profile.")
    if profile.dietary_pattern:
        add_rule("clinical", "hard", f"Respect dietary pattern: {profile.dietary_pattern}", "Derived automatically from the planning-safe client profile.")
    if profile.clinical_summary:
        add_rule("clinical", "soft", f"Clinical context: {profile.clinical_summary}", "Manual professional review is recommended for this context.")

    return derived


def build_effective_plan_validation(plan: PlanningPlan) -> Dict[str, Any]:
    """Build an overall validation view using inherited rules across the whole plan."""
    from app.utils.planning_v2 import aggregate_nutrients_from_meals

    checks: List[Dict[str, Any]] = []
    profile = getattr(plan.client, "planning_profile", None)
    if not plan.days:
        checks.append(
            {
                "kind": "structure",
                "severity": "warning",
                "status": "missing_days",
                "message": "The plan does not contain any days yet.",
            }
        )

    for day in sorted(plan.days, key=lambda item: item.day_index):
        day_foods = [food for meal in day.meals for food in meal.foods]
        if not day.meals:
            checks.append(
                {
                    "kind": "structure",
                    "severity": "warning",
                    "status": "missing_meals",
                    "day_id": day.id,
                    "day_name": day.day_name,
                    "message": f"{day.day_name} has no meals yet.",
                }
            )

        for meal in sorted(day.meals, key=lambda item: item.meal_order):
            effective_rules, effective_targets = get_effective_context(plan, day, meal)
            meal_foods = sorted(meal.foods, key=lambda item: (item.sort_order, item.id))
            if meal_foods:
                from app.utils.planning_v2 import aggregate_nutrients_from_foods
                summary = aggregate_nutrients_from_foods(meal_foods)
            else:
                summary = {"totals": [], "highlights": [], "foods_count": 0}
                checks.append(
                    {
                        "kind": "structure",
                        "severity": "warning",
                        "status": "empty_meal",
                        "day_id": day.id,
                        "meal_id": meal.id,
                        "day_name": day.day_name,
                        "meal_name": meal.meal_name,
                        "message": f"{meal.meal_name} on {day.day_name} does not have any foods yet.",
                    }
                )

            meal_checks = build_scope_validation(
                f"day-{day.day_index}-meal-{meal.meal_order}",
                effective_rules,
                effective_targets,
                meal_foods,
                summary,
            )["checks"]
            meal_checks.extend(evaluate_profile_guardrails(profile, summary, "meal"))
            for check in meal_checks:
                check["day_id"] = day.id
                check["meal_id"] = meal.id
                check["day_name"] = day.day_name
                check["meal_name"] = meal.meal_name
            checks.extend(meal_checks)

        if day.rules or day.nutrient_targets:
            from app.utils.planning_v2 import aggregate_nutrients_from_meals
            day_summary = aggregate_nutrients_from_meals(day.meals)
            day_checks = build_scope_validation(
                f"day-{day.day_index}",
                [],
                list(day.nutrient_targets),
                day_foods,
                day_summary,
            )["checks"]
            day_checks.extend(evaluate_profile_guardrails(profile, day_summary, "day"))
            for check in day_checks:
                check["day_id"] = day.id
                check["day_name"] = day.day_name
            checks.extend(day_checks)
        else:
            day_guardrails = evaluate_profile_guardrails(profile, aggregate_nutrients_from_meals(day.meals), "day")
            for check in day_guardrails:
                check["day_id"] = day.id
                check["day_name"] = day.day_name
            checks.extend(day_guardrails)

    plan_summary = aggregate_nutrients_from_meals([meal for day in plan.days for meal in day.meals])
    if plan.rules or plan.nutrient_targets:
        plan_foods = [food for day in plan.days for meal in day.meals for food in meal.foods]
        plan_checks = build_scope_validation(
            "plan",
            [],
            list(plan.nutrient_targets),
            plan_foods,
            plan_summary,
        )["checks"]
        checks.extend(plan_checks)

    checks.extend(
        evaluate_profile_guardrails(
            profile,
            plan_summary,
            "plan",
            plan_days_count=max(len(plan.days), plan.days_count or 1),
        )
    )

    blockers_count = len([check for check in checks if check.get("severity") == "blocker"])
    warnings_count = len([check for check in checks if check.get("severity") == "warning"])
    info_count = len([check for check in checks if check.get("severity") == "info"])

    overall_status = "ok"
    if blockers_count > 0:
        overall_status = "blocked"
    elif warnings_count > 0:
        overall_status = "warning"

    return {
        "scope": "effective_plan",
        "overall_status": overall_status,
        "blockers_count": blockers_count,
        "warnings_count": warnings_count,
        "info_count": info_count,
        "checks": checks,
    }
