"""Canonical sport normalization for Garmin and WHOOP activities."""

from __future__ import annotations

# Maps raw sport names (from Garmin typeKey and WHOOP WHOOP_SPORTS values)
# to short canonical keys used in the UI and AI prompts.
CANONICAL_SPORT_MAP: dict[str, str] = {
    # Running
    "running": "run",
    "trail_running": "run",
    "treadmill_running": "run",
    "run": "run",
    # Cycling
    "cycling": "bike",
    "road_biking": "bike",
    "mountain_biking": "bike",
    "indoor_cycling": "bike",
    "bike": "bike",
    # Swimming
    "swimming": "swim",
    "open_water_swimming": "swim",
    "lap_swimming": "swim",
    "swim": "swim",
    # Strength
    "strength": "strength",
    "strength_training": "strength",
    "functional_fitness": "strength",
    "crossfit": "strength",
    # HIIT
    "hiit": "hiit",
    # Walking / hiking
    "walking": "walk",
    "hiking": "walk",
    "walk": "walk",
    # Mobility
    "yoga": "mobility",
    "pilates": "mobility",
    "mobility": "mobility",
    # Other sports
    "rowing": "other",
    "indoor_rowing": "other",
    "boxing": "other",
    "mma": "other",
    "tennis": "other",
    "soccer": "other",
    "basketball": "other",
    "triathlon": "other",
    "ski": "other",
    "resort_skiing_snowboarding": "other",
    "skiing": "other",
    "cross_training": "strength",
    "indoor_cardio": "hiit",
    # Fallback
    "activity": "other",
    "rest": "rest",
}


def normalize_sport(raw: str) -> str:
    """Normalize a raw sport name to a canonical short key.

    Returns the canonical key if found, otherwise returns the raw name as-is.
    Handles None and sport_N patterns from unknown WHOOP IDs.
    """
    if not raw:
        return "other"
    key = raw.lower().strip()
    return CANONICAL_SPORT_MAP.get(key, key)


def merge_activities(activities: list) -> list:
    """Deduplicate activities from Garmin + WHOOP that represent the same workout.

    Two activities are considered the same if they share:
    - same activity_date
    - same normalized sport
    - duration within 20% of each other

    When matched, fields are merged: Garmin provides pace/cadence/power,
    WHOOP provides strain. The merged record keeps the richer data from both.
    """
    if not activities:
        return []

    # Group by (date, sport)
    groups: dict[tuple[str, str], list] = {}
    for a in activities:
        sport = normalize_sport(a.sport)
        key = (a.activity_date, sport)
        groups.setdefault(key, []).append(a)

    merged: list = []
    for (_date, _sport), group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Separate by source
        garmin = [a for a in group if a.source == "garmin"]
        whoop = [a for a in group if a.source == "whoop"]

        if not garmin or not whoop:
            # Multiple from same source — keep all
            merged.extend(group)
            continue

        # Try to match each garmin with a whoop activity by duration similarity
        used_whoop: set[int] = set()
        for g in garmin:
            best_match = None
            best_ratio = 999.0
            for i, w in enumerate(whoop):
                if i in used_whoop:
                    continue
                if g.duration_s and w.duration_s and g.duration_s > 0:
                    ratio = abs(g.duration_s - w.duration_s) / g.duration_s
                    if ratio < best_ratio:
                        best_ratio = ratio
                        best_match = i
                elif not g.duration_s and not w.duration_s:
                    best_match = i
                    best_ratio = 0.0

            if best_match is not None and best_ratio < 0.3:
                # Merge: prefer garmin for pace/cadence/power, whoop for strain
                w = whoop[best_match]
                used_whoop.add(best_match)
                # Create a merged dict representation
                merged.append(_MergedActivity(g, w))
            else:
                merged.append(g)

        # Add unmatched whoop activities
        for i, w in enumerate(whoop):
            if i not in used_whoop:
                merged.append(w)

    # Sort by date descending
    merged.sort(key=lambda a: a.activity_date, reverse=True)
    return merged


class _MergedActivity:
    """Merged view of a Garmin + WHOOP activity pair."""

    def __init__(self, garmin, whoop):
        self.source = "merged"
        self.sport = garmin.sport
        self.activity_date = garmin.activity_date
        self.duration_s = garmin.duration_s or whoop.duration_s
        self.distance_m = garmin.distance_m or whoop.distance_m
        self.calories = garmin.calories or whoop.calories
        self.avg_hr = garmin.avg_hr or whoop.avg_hr
        self.max_hr = garmin.max_hr or whoop.max_hr
        self.whoop_strain = whoop.whoop_strain
        self.avg_pace_s_per_km = garmin.avg_pace_s_per_km
        self.avg_power_w = garmin.avg_power_w
        self.avg_cadence = garmin.avg_cadence
        self.elevation_gain_m = garmin.elevation_gain_m
        self.external_id = garmin.external_id
