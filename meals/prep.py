from __future__ import annotations
from collections import defaultdict

def build_appliance_plan(jobs: list[dict]) -> dict[str, list[str]]:
    """
    Jobs may contain:
      name, equipment, temperature_c, active_minutes, background_minutes
    Compatible oven jobs are grouped by temperature.
    """
    plan = defaultdict(list)
    oven_groups = defaultdict(list)

    for job in jobs:
        equipment = job.get("equipment") or ["worktop"]
        if isinstance(equipment, str):
            equipment = [equipment]
        for appliance in equipment:
            key = appliance.lower()
            if key == "oven":
                temp = job.get("temperature_c", "VARIED")
                oven_groups[temp].append(job)
            else:
                mins = job.get("background_minutes") or job.get("active_minutes") or 0
                plan[key.upper()].append(f"{job['name']} - ~{mins} MIN")

    for temp, group in sorted(oven_groups.items(), key=lambda x: str(x[0])):
        heading = f"OVEN - {temp}C" if isinstance(temp, (int, float)) else "OVEN"
        for job in group:
            mins = job.get("background_minutes") or job.get("active_minutes") or 0
            plan[heading].append(f"{job['name']} - ~{mins} MIN")
    return dict(plan)
