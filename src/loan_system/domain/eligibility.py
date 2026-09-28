"""Điều kiện vay theo BR01."""

from datetime import date

MIN_AGE = 20
MAX_AGE = 60


def age_on(dob: date, today: date) -> int:
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def is_age_eligible(dob: date, today: date) -> bool:
    return MIN_AGE <= age_on(dob, today) <= MAX_AGE
