from __future__ import annotations

"""HR zone calculation from max heart rate.

MVP method: percentage of max HR.
  Z1 (Recovery):    50–60%
  Z2 (Aerobic):     60–70%
  Z3 (Tempo):       70–80%
  Z4 (Threshold):   80–90%
  Z5 (Max effort):  90–100%
"""

from dataclasses import dataclass


@dataclass
class HRZones:
    max_hr: int
    z1: tuple[int, int]
    z2: tuple[int, int]
    z3: tuple[int, int]
    z4: tuple[int, int]
    z5: tuple[int, int]

    def to_prompt_lines(self) -> list[str]:
        return [
            f"\n### Пульсовые зоны (макс {self.max_hr} уд/мин)\n",
            f"- **Z1 (восстановление):** {self.z1[0]}–{self.z1[1]} уд/мин",
            f"- **Z2 (аэробная база):** {self.z2[0]}–{self.z2[1]} уд/мин",
            f"- **Z3 (темповая):** {self.z3[0]}–{self.z3[1]} уд/мин",
            f"- **Z4 (пороговая):** {self.z4[0]}–{self.z4[1]} уд/мин",
            f"- **Z5 (максимальная):** {self.z5[0]}–{self.z5[1]} уд/мин",
        ]

    def zone_range(self, zone: str) -> str:
        """Return 'lo–hi' string for a zone label like 'z1'.."""
        mapping = {
            "z1": self.z1, "z2": self.z2, "z3": self.z3,
            "z4": self.z4, "z5": self.z5,
        }
        lo, hi = mapping.get(zone, (0, 0))
        return f"{lo}–{hi}"


def compute_hr_zones(max_hr: int) -> HRZones:
    """Compute HR zones from max HR using percentage method."""
    return HRZones(
        max_hr=max_hr,
        z1=(int(max_hr * 0.50), int(max_hr * 0.60)),
        z2=(int(max_hr * 0.60), int(max_hr * 0.70)),
        z3=(int(max_hr * 0.70), int(max_hr * 0.80)),
        z4=(int(max_hr * 0.80), int(max_hr * 0.90)),
        z5=(int(max_hr * 0.90), max_hr),
    )
