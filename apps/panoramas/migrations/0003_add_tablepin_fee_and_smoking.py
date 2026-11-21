# Generated for Task: TablePin Fields Task (FR-004 gap fix, pre-T-021)
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("panoramas", "0002_add_panorama_models_and_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="tablepin",
            name="is_smoking",
            field=models.BooleanField(
                default=False,
                help_text="Whether smoking is allowed at this table (True = allowed, False = prohibited).",
            ),
        ),
        migrations.AddField(
            model_name="tablepin",
            name="reservation_fee_toman",
            field=models.BigIntegerField(
                default=50000,
                help_text="Reservation fee in integer Toman (>= 0). Platform share charged online.",
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AlterField(
            model_name="tablepin",
            name="reservation_fee_toman",
            field=models.BigIntegerField(
                help_text="Reservation fee in integer Toman (>= 0). Platform share charged online.",
                validators=[django.core.validators.MinValueValidator(0)],
            ),
        ),
        migrations.AddConstraint(
            model_name="tablepin",
            constraint=models.CheckConstraint(
                condition=models.Q(("reservation_fee_toman__gte", 0)),
                name="table_pin_reservation_fee_non_negative",
            ),
        ),
    ]
