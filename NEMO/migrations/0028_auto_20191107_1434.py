# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2019-11-07 19:35
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0027_auto_20191106_0840'),
    ]

    operations = [
        migrations.AddField(
            model_name='areaaccessrecord',
            name='auto_validated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='contest_description',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='contest_resolved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='contest_resolved_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='contested',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='contested_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='validated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='areaaccessrecord',
            name='validated_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='auto_validated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='contest_description',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='contest_resolved',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='contest_resolved_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='contested',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='contested_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='updated',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='validated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='validated_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='auto_validated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='auto_validated',
            field=models.BooleanField(default=False),
        ),
    ]
