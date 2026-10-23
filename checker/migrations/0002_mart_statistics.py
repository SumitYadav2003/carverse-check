"""New columns from the statistics added to the marts, plus the odometer rounding check.

The mart tables are always fully replaced by load_mot_marts, so existing rows are cleared
first instead of being given made-up values for the new columns. Run load_mot_marts after
migrating.
"""

from django.db import migrations, models


def clear_mart_rows(apps, schema_editor):
    apps.get_model("checker", "ModelYearDefectCategory").objects.all().delete()
    apps.get_model("checker", "ModelYearFailRate").objects.all().delete()


NEW_RATE_FIELDS = {
    "initial_fails": models.PositiveIntegerField(default=0),
    "initial_fail_rate_low_pct": models.FloatField(default=0),
    "initial_fail_rate_high_pct": models.FloatField(default=0),
    "estimated_initial_fail_rate_pct": models.FloatField(default=0),
    "estimated_low_pct": models.FloatField(default=0),
    "estimated_high_pct": models.FloatField(default=0),
    "mileage_readings": models.PositiveIntegerField(default=0),
    "peer_between_model_sd_pts": models.FloatField(default=0),
    "funnel_low_95_pct": models.FloatField(default=0),
    "funnel_high_95_pct": models.FloatField(default=0),
    "funnel_low_998_pct": models.FloatField(default=0),
    "funnel_high_998_pct": models.FloatField(default=0),
    "vs_peers": models.CharField(default="within", max_length=10,
                                 help_text="higher, lower or within"),
    "funnel_position": models.CharField(default="inside", max_length=10,
                                        help_text="above, below or inside"),
}


class Migration(migrations.Migration):

    dependencies = [("checker", "0001_initial")]

    operations = [
        migrations.RunPython(clear_mart_rows, migrations.RunPython.noop),
        *[migrations.AddField("modelyearfailrate", name, field, preserve_default=False)
          for name, field in NEW_RATE_FIELDS.items()],
        *[migrations.AddField("modelyearfailrate", f"miles_per_year_p{p}",
                              models.PositiveIntegerField(null=True))
          for p in (10, 25, 50, 75, 90)],
        migrations.AddField("modelyeardefectcategory", "failure_share_low_pct",
                            models.FloatField(default=0, help_text="Bottom of the 95% range"),
                            preserve_default=False),
        migrations.CreateModel(
            name="OdometerRounding",
            fields=[
                ("check_key", models.CharField(max_length=32, primary_key=True, serialize=False)),
                ("check_name", models.CharField(max_length=20)),
                ("pattern", models.CharField(max_length=5)),
                ("readings", models.PositiveBigIntegerField()),
                ("total_readings", models.PositiveBigIntegerField()),
                ("share_pct", models.FloatField()),
                ("expected_share_pct", models.FloatField()),
            ],
        ),
    ]
