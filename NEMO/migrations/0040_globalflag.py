# Generated by Django 2.2.12 on 2020-05-12 08:25

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0039_auto_20200508_1112'),
    ]

    operations = [
        migrations.CreateModel(
            name='GlobalFlag',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('active', models.BooleanField(default=False)),
            ],
        ),
    ]
