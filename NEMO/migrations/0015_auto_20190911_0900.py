# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-09-11 13:02
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0014_auto_20190827_1027'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usageevent',
            name='project',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='usage_event_project', to='NEMO.Project'),
        ),
        migrations.AlterField(
            model_name='usageevent',
            name='user',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='usage_event_user', to=settings.AUTH_USER_MODEL),
        ),
    ]
