from django.contrib import admin

from .models import (
    Commitment,
    Debt,
    EssentialEstimate,
    IncomeSource,
    PersonalProfile,
    Preference,
    SavingsGoal,
)

for model in (
    PersonalProfile,
    IncomeSource,
    Commitment,
    Debt,
    EssentialEstimate,
    SavingsGoal,
    Preference,
):
    admin.site.register(model)
