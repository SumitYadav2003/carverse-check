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
    initial_fails = models.PositiveIntegerField()
    initial_fail_rate_pct = models.FloatField()
    final_fail_rate_pct = models.FloatField()
    # 95% range for the initial failure rate (Wilson score interval)
    initial_fail_rate_low_pct = models.FloatField()
    initial_fail_rate_high_pct = models.FloatField()
    # the rate adjusted for group size (empirical Bayes): small groups pulled towards peers
    estimated_initial_fail_rate_pct = models.FloatField()
    estimated_low_pct = models.FloatField()
    estimated_high_pct = models.FloatField()
    median_mileage = models.PositiveIntegerField(null=True)
    # spread of average miles a year since first use, for placing one car among its model
    mileage_readings = models.PositiveIntegerField()
    miles_per_year_p10 = models.PositiveIntegerField(null=True)
    miles_per_year_p25 = models.PositiveIntegerField(null=True)
    miles_per_year_p50 = models.PositiveIntegerField(null=True)
    miles_per_year_p75 = models.PositiveIntegerField(null=True)
    miles_per_year_p90 = models.PositiveIntegerField(null=True)
    peer_tests = models.PositiveIntegerField()
    peer_initial_fail_rate_pct = models.FloatField()
    peer_final_fail_rate_pct = models.FloatField()
    initial_fail_rate_vs_peers_pts = models.FloatField()
    # how much models of this age genuinely differ (beyond chance), in percentage points
    peer_between_model_sd_pts = models.FloatField()
    # funnel-plot limits around the peer rate for a group of this size
    funnel_low_95_pct = models.FloatField()
    funnel_high_95_pct = models.FloatField()
    funnel_low_998_pct = models.FloatField()
    funnel_high_998_pct = models.FloatField()
    # the buyer-facing verdict: is the adjusted rate clearly and meaningfully above/below peers?
    vs_peers = models.CharField(max_length=10, help_text="higher, lower or within")
    # does the model stand out from other models of its age (outside the 95% funnel)?
    funnel_position = models.CharField(max_length=10, help_text="above, below or inside")

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
    failure_share_low_pct = models.FloatField(help_text="Bottom of the 95% range")
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


class OdometerRounding(models.Model):
    """One row of marts.mart_odometer_rounding: a data-quality check on all odometer
    readings (share by last digit, and ending in 00 / 000), shown on the methodology page."""

    check_key = models.CharField(max_length=32, primary_key=True)
    check_name = models.CharField(max_length=20)
    pattern = models.CharField(max_length=5)
    readings = models.PositiveBigIntegerField()
    total_readings = models.PositiveBigIntegerField()
    share_pct = models.FloatField()
    expected_share_pct = models.FloatField()

    def __str__(self):
        return f"{self.check_name} {self.pattern}: {self.share_pct}%"
