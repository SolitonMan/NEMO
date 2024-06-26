# Generated by Django 2.2.12 on 2021-09-28 15:18

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0074_consumablewithdraw_cost_per_sample_run'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='bill_to_alt',
            field=models.ForeignKey(blank=True, help_text='The alternate person to contact with an invoice', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bill_to_contact_alt', to=settings.AUTH_USER_MODEL),
        ),
    ]
