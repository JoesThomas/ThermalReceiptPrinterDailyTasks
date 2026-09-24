from datetime import date, datetime

import requests


DVLA_URL = (
    "https://driver-vehicle-licensing.api.gov.uk/"
    "vehicle-enquiry/v1/vehicles"
)


def normalise_registration(registration):
    return (
        str(registration or "")
        .upper()
        .replace(" ", "")
    )


def _parse_date(value):
    if not value:
        return None

    try:
        return datetime.strptime(
            value,
            "%Y-%m-%d",
        ).date()
    except (TypeError, ValueError):
        return None


def get_vehicle_status(
    registration,
    api_key,
):
    registration = normalise_registration(
        registration
    )

    if not registration:
        raise ValueError(
            "Vehicle registration is empty."
        )

    if not api_key:
        raise ValueError(
            "DVLA API key is not configured."
        )

    response = requests.post(
        DVLA_URL,
        headers={
            "x-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "registrationNumber": registration
        },
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    return {
        "registration": registration,
        "make": data.get("make"),
        "colour": data.get("colour"),

        "tax_status": data.get("taxStatus"),
        "tax_due_date": _parse_date(
            data.get("taxDueDate")
        ),

        "mot_status": data.get("motStatus"),
        "mot_expiry_date": _parse_date(
            data.get("motExpiryDate")
        ),
    }


def expiring_vehicle_items(
    vehicle_status,
    today=None,
    days=31,
):
    today = today or date.today()
    warnings = []

    checks = (
        (
            "MOT",
            vehicle_status.get(
                "mot_expiry_date"
            ),
        ),
        (
            "VEHICLE TAX",
            vehicle_status.get(
                "tax_due_date"
            ),
        ),
    )

    for label, expiry in checks:
        if not expiry:
            continue

        days_remaining = (
            expiry - today
        ).days

        if 0 <= days_remaining <= days:
            warnings.append({
                "type": label,
                "expiry_date": expiry,
                "days_remaining": (
                    days_remaining
                ),
            })

    return warnings