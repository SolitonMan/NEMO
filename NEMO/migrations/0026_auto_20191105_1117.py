# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-11-05 16:18
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0025_auto_20191029_0701'),
    ]

    operations = [
        migrations.AddField(
            model_name='areaaccessrecord',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='reservation',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='reservation',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='reservationconfiguration',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='reservationconfiguration',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='scheduledoutage',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='scheduledoutage',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='contest_resolved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='contest_resolved_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='contested_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='validated_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='contest_resolved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='contest_resolved_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='contested_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='created',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='updated',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='validated_date',
            field=models.DateTimeField(default=django.utils.timezone.now, null=True),
        ),
    ]
