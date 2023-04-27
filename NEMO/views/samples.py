from decimal import *
from re import search

import requests
import json

from copy import deepcopy
from datetime import timedelta
from datetime import datetime
from http import HTTPStatus
from itertools import chain
from logging import getLogger

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.db.models import Q, Max
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.utils.html import escape
from django.utils.safestring import mark_safe
from django.urls import reverse

from NEMO.forms import SampleForm, nice_errors
from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, Sample, StaffCharge, StaffChargeProject, UsageEvent, UsageEventProject, Reservation, ReservationProject, Project, User

@login_required
@require_GET
def samples(request):
	if request.user.is_superuser or request.user.is_staff:
		sample_list = Sample.objects.all().order_by('identifier')
	else:
		sample_list = Sample.objects.filter(Q(project__in=request.user.projects.all()) | Q(created_by=request.user)).order_by('identifier')
	return render(request, 'sample/samples.html', {'samples': sample_list})


@login_required
@require_GET
def get_samples(request):
	project_id = request.GET.get('project_id', None)
	entry_number = request.GET.get('entry_number', None)
	ad_hoc = request.GET.get('ad_hoc', None)
	if ad_hoc is None:
		ad_hoc = False
	else:
		if ad_hoc == "true":
			ad_hoc = True
		else:
			ad_hoc = False


	try:
		sample_list = Sample.objects.filter(project__in=[project_id], active_flag=True).order_by('identifier')
		project = Project.objects.get(id=int(project_id))
	except:
		sample_list = None
		project = request.user.active_projects.all()[0]

	if sample_list is not None and  sample_list.count() == 0:
		sample_list = None

	return render(request, 'sample/get_samples.html', {'samples': sample_list, "entry_number": entry_number, "project": project, "ad_hoc": ad_hoc })


@login_required
@require_http_methods(['GET', 'POST'])
def create_or_modify_sample(request, sample_id):
	dictionary = {
		'sample_id': sample_id,
	}

	try:
		sample = Sample.objects.get(id=sample_id)
		dictionary['new_sample'] = False
	except:
		sample = None
		dictionary['new_sample'] = True


	if request.method == "GET":
		dictionary['users'] = User.objects.filter(is_active=True, projects__active=True).distinct().order_by('last_name')
		dictionary['form'] = SampleForm(request.user, instance=sample)
		return render(request, 'sample/create_or_modify_sample.html', dictionary)

	elif request.method == "POST":
		form = SampleForm(request.user, request.POST, instance=sample)
		dictionary['form'] = form

		if not form.is_valid():
			return render(request, 'sample/create_or_modify_sample.html', dictionary)

		r = form.save()
		r.updated = timezone.now()
		r.updated_by = request.user

		if sample is None:
			r.created = timezone.now()
			r.created_by = request.user

		r.save()

		return redirect('samples')


@login_required
@require_http_methods(['GET', 'POST'])
def modal_create_sample(request, project_id):
	dictionary = {
		'project': Project.objects.get(id=int(project_id)),
		'sample_id': None,
	}
	sample_id = None

	try:
		sample = Sample.objects.get(id=sample_id)
	except:
		sample = None


	if request.method == "GET":
		dictionary['modal_caller'] = request.GET.get('modal_caller', None)
		dictionary['form'] = SampleForm(request.user, instance=sample, initial={'project':[project_id]})
		return render(request, 'sample/modal_create_sample.html', dictionary)

	elif request.method == "POST":
		dictionary['modal_caller'] = request.POST.get('modal_caller', None)

		request_mode = request.POST.get('request_mode')
		form = SampleForm(request.user, request.POST, instance=sample)
		dictionary['form'] = form

		if not form.is_valid():
			return render(request, 'sample/modal_create_sample.html', dictionary)

		r = form.save()
		r.updated = timezone.now()
		r.updated_by = request.user

		if sample is None:
			r.created = timezone.now()
			r.created_by = request.user

		r.save()

		return HttpResponse(r.id)


@login_required
def sample_history(request, sample_id=None):
	cursor = connection.cursor()
	# if no sample is specified retrieve all the sample histories for the current user
	if sample_id is None:
		raw_sql = '''select s.identifier, us.username, t.name, u.start, u.end, p.project_number
			from "NEMO_usageevent" u
			left outer join "NEMO_user" us on u.operator_id = us.id
			left outer join "NEMO_usageeventproject" uep on u.id=uep.usage_event_id
			left outer join "NEMO_usageeventproject_sample" ueps on ueps.usageeventproject_id = uep.id
			inner join "NEMO_sample" s on ueps.sample_id = s.id
			inner join "NEMO_project" p on uep.project_id=p.id
			inner join "NEMO_tool" t on t.id = u.tool_id
			where u.operator_id=%s
			order by s.identifier, u.start'''
		cursor.execute(raw_sql, [request.user.id])
	else:
		raw_sql = '''select s.identifier, us.username, t.name, u.start, u.end, p.project_number
			from "NEMO_usageevent" u
			left outer join "NEMO_user" us on u.operator_id = us.id
			left outer join "NEMO_usageeventproject" uep on u.id=uep.usage_event_id
			left outer join "NEMO_usageeventproject_sample" ueps on ueps.usageeventproject_id = uep.id
			inner join "NEMO_sample" s on ueps.sample_id = s.id
			inner join "NEMO_project" p on uep.project_id=p.id
			inner join "NEMO_tool" t on t.id = u.tool_id
			where s.id=%s
			order by s.identifier, u.start'''
		cursor.execute(raw_sql, [sample_id])

	sh = cursor.fetchall()

	if sample_id is None:
		current_sample = None
	else:
		current_sample = Sample.objects.get(id=sample_id)

	return render(request, "sample/sample_history.html",{"sample_history":sh,"sample_id":sample_id,"current_sample": current_sample})
