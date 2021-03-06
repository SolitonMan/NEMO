# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-08-27 12:55
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0012_auto_20190826_1214'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='project',
            name='accesses',
        ),
        migrations.RemoveField(
            model_name='project',
            name='events',
        ),
        migrations.RemoveField(
            model_name='project',
            name='staff_charges',
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='projects',
            field=models.ManyToManyField(through='NEMO.AreaAccessRecordProject', to='NEMO.Project'),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='projects',
            field=models.ManyToManyField(through='NEMO.StaffChargeProject', to='NEMO.Project'),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='projects',
            field=models.ManyToManyField(through='NEMO.UsageEventProject', to='NEMO.Project'),
        ),
    ]
