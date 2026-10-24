"""URL-friendly make and model names for the Explore models pages. Existing rows get
theirs here, so there's no need to reload the marts."""

from django.db import migrations, models
from django.utils.text import slugify


def fill_slugs(apps, schema_editor):
    ModelYearFailRate = apps.get_model("checker", "ModelYearFailRate")
    rows = list(ModelYearFailRate.objects.all())
    for row in rows:
        row.make_slug = slugify(row.make)[:100]
        row.model_slug = slugify(row.model)[:100]
    ModelYearFailRate.objects.bulk_update(rows, ["make_slug", "model_slug"], batch_size=2000)


class Migration(migrations.Migration):

    dependencies = [("checker", "0002_mart_statistics")]

    operations = [
        migrations.AddField("modelyearfailrate", "make_slug",
                            models.SlugField(default="", max_length=100)),
        migrations.AddField("modelyearfailrate", "model_slug",
                            models.SlugField(default="", max_length=100)),
        migrations.AddIndex("modelyearfailrate",
                            models.Index(fields=["make_slug", "model_slug"], name="make_model_slug_idx")),
        migrations.RunPython(fill_slugs, migrations.RunPython.noop),
    ]
