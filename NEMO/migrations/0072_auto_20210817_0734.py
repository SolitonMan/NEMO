# Generated by Django 2.2.12 on 2021-08-17 07:35

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0071_auto_20210816_1554'),
    ]

    operations = [
        migrations.AddField(
            model_name='areaaccessrecord',
            name='cost_per_sample_run',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='cost_per_sample_run',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='cost_per_sample_run',
            field=models.BooleanField(default=False),
        ),
    ]
