from datetime import date, timedelta


def generate_basic_roster(start_date: date, number_of_days: int):
    """
    Generate a very basic sample roster.

    This is temporary starter logic.
    Later, we will replace this with real dental clinic rules.
    """

    staff_members = [
        "Radhika",
        "Sangeeta",
        "Adeline",
        "Leslie",
    ]

    roster = []

    for day_number in range(number_of_days):
        current_date = start_date + timedelta(days=day_number)
        staff_name = staff_members[day_number % len(staff_members)]

        roster.append(
            {
                "date": current_date.isoformat(),
                "day": current_date.strftime("%A"),
                "clinic": "Dental Clinic",
                "role": "Reception",
                "staff": staff_name,
            }
        )

    return roster