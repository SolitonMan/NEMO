# Generated by Django 2.2.12 on 2020-06-11 13:36

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0046_auto_20200610_1908'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='organization',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.Organization'),
        ),
    ]