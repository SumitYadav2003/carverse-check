from django.db import models


class ModelYearFailRate(models.Model):
    """One row of the dbt mart marts.mart_model_year_fail_rates: MOT failure rates for one
    make + model + year of first use, next to all cars first used in the same year.
    Loaded with `python manage.py load_mot_marts`; never edited by hand."""

    model_year_key = models.CharField(max_length=64, primary_key=True)
    make = models.CharField(max_length=100)
    model = models.CharField(max_length=100)
    first_use_year = models.PositiveSmallIntegerField()
    test_year = models.PositiveSmallIntegerField(help_text="Year of the MOT tests behind these figures")
    tests = models.PositiveIntegerField()
    initial_fail_rate_pct = models.FloatField()
    final_fail_rate_pct = models.FloatField()
    median_mileage = models.PositiveIntegerField(null=True)
    peer_tests = models.PositiveIntegerField()
    peer_initial_fail_rate_pct = models.FloatField()
    peer_final_fail_rate_pct = models.FloatField()
    initial_fail_rate_vs_peers_pts = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["make", "model", "first_use_year"],
                                    name="unique_make_model_first_use_year"),
        ]

    def __str__(self):
        return f"{self.first_use_year} {self.make} {self.model}"


class ModelYearDefectCategory(models.Model):
    """One row of marts.mart_model_year_defect_categories."""

    model_year = models.ForeignKey(ModelYearFailRate, on_delete=models.CASCADE,
                                   related_name="defect_categories")
    defect_category = models.CharField(max_length=100)
    tests_with_failure_item = models.PositiveIntegerField()
    tests_with_advisory = models.PositiveIntegerField()
    failure_share_pct = models.FloatField()
    advisory_share_pct = models.FloatField()
    peer_failure_share_pct = models.FloatField()
    peer_advisory_share_pct = models.FloatField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["model_year", "defect_category"],
                                    name="unique_model_year_defect_category"),
        ]

    def __str__(self):
        return f"{self.model_year}: {self.defect_category}"
