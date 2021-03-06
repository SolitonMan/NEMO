# Generated by Django 2.2.12 on 2021-01-11 10:43

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0064_areaaccessrecordproject_comment'),
    ]

    operations = [
        migrations.AddField(
            model_name='project',
            name='detailed_invoice',
            field=models.BooleanField(default=False, help_text='A flag to indicate if the customer assigned this project should receive a detailed invoice.  The default is False, indicating that a summarized invoice should be sent.'),
        ),
    ]
