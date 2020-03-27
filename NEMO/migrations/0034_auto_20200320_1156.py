# -*- coding: utf-8 -*-
# Generated by Django 1.11.20 on 2020-03-20 11:59
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0033_lockbilling'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserRelationship',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ],
        ),
        migrations.CreateModel(
            name='UserRelationshipType',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('user_1_role', models.CharField(max_length=255)),
                ('user_2_role', models.CharField(max_length=255)),
                ('description', models.TextField(blank=True, null=True)),
            ],
        ),
        migrations.AddField(
            model_name='user',
            name='pi_delegates',
            field=models.ManyToManyField(blank=True, help_text='Users that a PI gives permission to manage accounts and their users on behalf of that PI', related_name='_user_pi_delegates_+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='userrelationship',
            name='type',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='user_relationship_type', to='NEMO.UserRelationshipType'),
        ),
        migrations.AddField(
            model_name='userrelationship',
            name='user_1',
            field=models.ForeignKey(help_text='The person who is the manager, superviser, PI, or other role higher in the structure', on_delete=django.db.models.deletion.CASCADE, related_name='upper_tier_role', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='userrelationship',
            name='user_2',
            field=models.ForeignKey(help_text='The person who is the subordinate, supervisee, delegate or other role lower in the structure.', on_delete=django.db.models.deletion.CASCADE, related_name='lower_tier_role', to=settings.AUTH_USER_MODEL),
        ),
    ]