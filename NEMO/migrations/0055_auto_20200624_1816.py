# Generated by Django 2.2.12 on 2020-06-24 18:17

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0054_auto_20200624_0714'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='project',
            name='ibis_account',
        ),
        migrations.RemoveField(
            model_name='project',
            name='simba_cost_center',
        ),
    ]