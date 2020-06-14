# Generated by Django 2.2.12 on 2020-06-14 13:55

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0048_auto_20200612_0851'),
    ]

    operations = [
        migrations.CreateModel(
            name='FICO_COA',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('business_area', models.CharField(blank=True, max_length=4, null=True)),
                ('department', models.CharField(blank=True, max_length=5, null=True)),
                ('cost_center', models.CharField(blank=True, max_length=10, null=True)),
                ('internal_order', models.CharField(blank=True, max_length=12, null=True)),
                ('wbs_element', models.CharField(blank=True, max_length=12, null=True)),
                ('zdescr', models.CharField(blank=True, max_length=40, null=True)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('chargeable_flag', models.CharField(blank=True, max_length=1, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='FICO_COA_Person_Responsible',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cost_center', models.CharField(blank=True, max_length=10, null=True)),
                ('internal_order', models.CharField(blank=True, max_length=12, null=True)),
                ('wbs_element', models.CharField(blank=True, max_length=12, null=True)),
                ('access_id', models.CharField(blank=True, max_length=8, null=True)),
                ('grant', models.CharField(blank=True, max_length=20, null=True)),
                ('fund', models.CharField(blank=True, max_length=10, null=True)),
                ('grant_valid_to_date', models.DateField(blank=True, null=True)),
                ('sp_indicator', models.CharField(blank=True, max_length=1, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='FICO_GL_ACCT',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gl_account', models.CharField(blank=True, max_length=8, null=True)),
                ('gl_account_name', models.CharField(blank=True, max_length=20, null=True)),
                ('start_date', models.DateField(blank=True, null=True)),
                ('end_date', models.DateField(blank=True, null=True)),
            ],
        ),
    ]
