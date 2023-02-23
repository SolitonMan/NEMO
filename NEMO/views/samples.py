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
from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, Sample, StaffCharge, StaffChargeProject, UsageEvent, UsageEventProject, Reservation, ReservationProject, Project

@login_required
@require_GET
def samples(request):
	if request.user.is_superuser:
		sample_list = Sample.objects.all().order_by('identifier')
	else:
		sample_list = Sample.objects.filter(Q(project__in=request.user.projects.all()) | Q(created_by=request.user)).order_by('identifier')
	return render(request, 'sample/samples.html', {'samples': sample_list})


@login_required
@require_GET
def get_samples(request):
	project_id = request.GET.get('project_id', None)
	entry_number = request.GET.get('entry_number', None)
	try:
		sample_list = Sample.objects.filter(project__in=[project_id]).order_by('identifier')
	except:
		sample_list = None

	if sample_list is not None and  sample_list.count() == 0:
		sample_list = None

	return render(request, 'sample/get_samples.html', {'samples': sample_list, "entry_number": entry_number})


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def create_or_modify_sample(request, sample_id):
	dictionary = {
		'sample_id': sample_id,
	}

	try:
		sample = Sample.objects.get(id=sample_id)
	except:
		sample = None


	if request.method == "GET":
		dictionary['form'] = SampleForm(instance=sample)
		return render(request, 'sample/create_or_modify_sample.html', dictionary)

	elif request.method == "POST":
		form = SampleForm(request.POST, instance=sample)
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



