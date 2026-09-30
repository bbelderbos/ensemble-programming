from dataclasses import dataclass


@dataclass(frozen=True)
class Roles:
    driver: str | None
    navigator: str | None
    timekeeper: str | None


def assign_roles(rotation: list[str], segment: int) -> Roles:
    """Roles shift one seat per segment, so the navigator drives next."""
    if not rotation:
        return Roles(driver=None, navigator=None, timekeeper=None)

    def seat(offset: int) -> str:
        return rotation[(segment + offset) % len(rotation)]

    # With fewer than three people the navigator (or solo driver) keeps time
    return Roles(
        driver=seat(0),
        navigator=seat(1) if len(rotation) > 1 else None,
        timekeeper=seat(min(2, len(rotation) - 1)),
    )
