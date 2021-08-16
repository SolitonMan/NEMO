# Generated by Django 2.2.12 on 2021-08-16 15:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0070_reservationnotification'),
    ]

    operations = [
        migrations.AddField(
            model_name='usageeventproject',
            name='cost_per_sample',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True),
        ),
        migrations.AddField(
            model_name='usageeventproject',
            name='sample_num',
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
