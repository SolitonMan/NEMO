# Generated by Django 3.2.15 on 2023-02-14 10:27

import datetime
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0086_staffchargenotificationlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='group_by_user',
            field=models.BooleanField(default=False, help_text='A flag to indicate if the invoice should be grouped by user instead of core.'),
        ),
        migrations.CreateModel(
            name='Sample',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('identifier', models.CharField(blank=True, max_length=255, null=True)),
                ('nickname', models.CharField(blank=True, max_length=500, null=True)),
                ('description', models.TextField(blank=True, null=True)),
                ('active_flag', models.BooleanField(default=True)),
                ('created', models.DateTimeField()),
                ('updated', models.DateTimeField(default=datetime.datetime(2023, 2, 14, 10, 27, 2, 132766))),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sample_created_by', to=settings.AUTH_USER_MODEL)),
                ('parent_sample', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='precursor', to='NEMO.sample')),
                ('project', models.ManyToManyField(blank=True, related_name='sample_project', to='NEMO.Project')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sample_updated_by', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='areaaccessrecordproject',
            name='sample',
            field=models.ManyToManyField(blank=True, related_name='aarp_sample', to='NEMO.Sample'),
        ),
        migrations.AddField(
            model_name='reservationproject',
            name='sample',
            field=models.ManyToManyField(blank=True, null=True, to='NEMO.Sample'),
        ),
        migrations.AddField(
            model_name='staffchargeproject',
            name='sample',
            field=models.ManyToManyField(blank=True, related_name='scp_sample', to='NEMO.Sample'),
        ),
        migrations.AddField(
            model_name='usageeventproject',
            name='sample',
            field=models.ManyToManyField(blank=True, related_name='uep_sample', to='NEMO.Sample'),
        ),
    ]
