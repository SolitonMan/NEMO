# Generated by Django 2.2.12 on 2020-07-15 11:02

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('contenttypes', '0002_remove_content_type_name'),
        ('NEMO', '0058_auto_20200707_2031'),
    ]

    operations = [
        migrations.AddField(
            model_name='areaaccessrecord',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='areaaccessrecordproject',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='consumablewithdraw',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='contesttransaction',
            name='no_charge_flag',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='staffcharge',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='staffchargeproject',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='usageevent',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='usageeventproject',
            name='active_flag',
            field=models.BooleanField(default=True),
        ),
        migrations.CreateModel(
            name='ContestTransactionNewData',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('field_name', models.CharField(max_length=50)),
                ('field_value', models.CharField(max_length=250)),
                ('field_group', models.CharField(max_length=20)),
                ('content_type', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='contenttypes.ContentType')),
                ('contest_transaction', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.ContestTransaction')),
            ],
            options={
                'ordering': ['content_type', 'contest_transaction'],
            },
        ),
    ]
