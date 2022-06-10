# Generated by Django 2.2.12 on 2021-11-09 08:06

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('NEMO', '0076_auto_20211104_0837'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProbationaryQualifications',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('qualification_date', models.DateTimeField(blank=True, default=django.utils.timezone.now, null=True)),
                ('probationary_user', models.BooleanField(default=False)),
                ('tool_last_used', models.DateTimeField(blank=True, null=True)),
                ('tool', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='NEMO.Tool')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddField(
            model_name='user',
            name='probationary_qualifications',
            field=models.ManyToManyField(blank=True, help_text='A detailed table for user qualifications', related_name='probationary_qualifications', through='NEMO.ProbationaryQualifications', to='NEMO.Tool'),
        ),
    ]