# Generated by Django 2.2.12 on 2021-03-24 12:01

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0067_auto_20210212_0931'),
    ]

    operations = [
        migrations.AlterField(
            model_name='contactinformation',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.ContactInformationCategory'),
        ),
    ]