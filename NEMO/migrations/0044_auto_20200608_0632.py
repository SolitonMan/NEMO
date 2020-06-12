# Generated by Django 2.2.12 on 2020-06-08 06:33

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0043_auto_20200530_1736'),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsumableType',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=250)),
            ],
            options={
                'verbose_name_plural': 'Consumable types',
                'ordering': ['name'],
            },
        ),
        migrations.AddField(
            model_name='areaaccessrecordproject',
            name='no_charge_flag',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='notes',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='project',
            name='bill_to',
            field=models.ForeignKey(blank=True, help_text='The person to contact with an invoice', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='bill_to_contact', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='staffchargeproject',
            name='no_charge_flag',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='tool',
            name='infolink',
            field=models.CharField(blank=True, max_length=1000, null=True),
        ),
        migrations.AddField(
            model_name='usageeventproject',
            name='no_charge_flag',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='project',
            name='owner',
            field=models.ForeignKey(blank=True, help_text='The owner or person responsible for the Project (Internal Order or WBS Element in SIMBA) as imported via SIMBA download nightly', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='project_owner', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='consumable',
            name='type',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.ConsumableType'),
        ),
    ]
