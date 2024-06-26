# Generated by Django 3.2.15 on 2023-05-02 11:42

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0090_auto_20230428_0759'),
    ]

    operations = [
        migrations.CreateModel(
            name='StaffChargeProjectSample',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notes', models.TextField(blank=True, null=True)),
                ('active_flag', models.BooleanField(default=True)),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True)),
                ('updated', models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True)),
                ('sample', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.sample')),
                ('staff_charge_project', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.staffchargeproject')),
            ],
        ),
        migrations.CreateModel(
            name='AreaAccessRecordProjectSample',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('notes', models.TextField(blank=True, null=True)),
                ('active_flag', models.BooleanField(default=True)),
                ('created', models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True)),
                ('updated', models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True)),
                ('area_access_record_project', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.areaaccessrecordproject')),
                ('sample', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.sample')),
            ],
        ),
        migrations.AddField(
            model_name='areaaccessrecordproject',
            name='sample_detail',
            field=models.ManyToManyField(blank=True, related_name='aarp_sample_detail', through='NEMO.AreaAccessRecordProjectSample', to='NEMO.Sample'),
        ),
        migrations.AddField(
            model_name='staffchargeproject',
            name='sample_detail',
            field=models.ManyToManyField(blank=True, related_name='scp_sample_detail', through='NEMO.StaffChargeProjectSample', to='NEMO.Sample'),
        ),
    ]
