# Generated by Django 3.2.15 on 2023-11-10 14:31

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0093_user_watching'),
    ]

    operations = [
        migrations.CreateModel(
            name='Project2DCC',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('project_id', models.CharField(max_length=20, unique=True)),
                ('project_type', models.IntegerField(choices=[(-1, 'Unknown'), (1, 'Research'), (2, 'Sample'), (3, 'RSVP')], default=-1)),
            ],
        ),
        migrations.AddField(
            model_name='probationaryqualifications',
            name='disabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AlterField(
            model_name='tool',
            name='qualification_duration',
            field=models.PositiveIntegerField(blank=True, default=182, help_text="The tool may indicate the number of days without use a user will be considered qualified.  The default is 182 days (6 months).  Each night a script will run to check a user's last date of use for a tool against this time period.  If the date of last use is greater than the qualification_duration value the user will be set to limited status.  This change can be reversed in LEO.", null=True),
        ),
        migrations.AddConstraint(
            model_name='project2dcc',
            constraint=models.UniqueConstraint(fields=('project_id',), name='2dcc unique name'),
        ),
        migrations.AddField(
            model_name='user',
            name='projects2dcc',
            field=models.ManyToManyField(blank=True, help_text='Project identifiers from List for use with 2DCC projects', to='NEMO.Project2DCC'),
        ),
    ]