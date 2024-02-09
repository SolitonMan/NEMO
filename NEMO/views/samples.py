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
from django.core.paginator import Paginator
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
from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, AreaAccessRecordProjectSample, Sample, StaffCharge, StaffChargeProject, StaffChargeProjectSample, UsageEvent, UsageEventProject, UsageEventProjectSample, Reservation, ReservationProject, Project, User

@login_required
@require_http_methods(['GET', 'POST'])
def samples(request):

	if request.method == "GET":
		return render(request, 'sample/samples.html', {'samples': None, 'page_count': 0, 'use_form': True})
	else:
		search_string = request.POST.get('search',None)

		if search_string is None:

			if request.user.is_superuser or request.user.is_staff:
				sample_list = Sample.objects.all().order_by('identifier')
			else:
				sample_list = Sample.objects.filter(Q(project__in=request.user.projects.all()) | Q(created_by=request.user)).order_by('identifier')
		else:
			sample_list = Sample.objects.filter(Q(identifier__icontains=search_string) | Q(nickname__icontains=search_string) | Q(created_by__last_name__icontains=search_string) | Q(created_by__first_name__icontains=search_string) | Q(created_by__username__icontains=search_string))

		paginator = Paginator(sample_list, 50)
		page_number = request.GET.get('page')
		if page_number is None:
			page_number = 1
		#samples = paginator.get_page(page_number)

		page_count = paginator.num_pages

		return render(request, 'sample/samples.html', {'samples': sample_list, 'page_count': page_count, 'use_form': False, 'search_string': search_string, })


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
		sample_list = Sample.objects.filter(project__in=[project_id], active_flag=True).order_by('-updated','-created')
		project = Project.objects.get(id=int(project_id))
	except:
		sample_list = None
		project = request.user.active_projects.all()[0]

	if sample_list is not None and  sample_list.count() == 0:
		sample_list = None

	return render(request, 'sample/get_samples.html', {"samples": sample_list, "entry_number": entry_number, "project": project, "ad_hoc": ad_hoc })


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

		multiple_samples = request.POST.get('create_multiple_samples', None)

		if not form.is_valid():
			return render(request, 'sample/create_or_modify_sample.html', dictionary)

		if multiple_samples:

			sample_count = request.POST.get('sample_count', None)

			if sample_count is not None:

				sample_count = int(sample_count)

				for i in range(1, sample_count+1):
					form = SampleForm(request.user, request.POST, None)
					r = form.save()
					identifier = r.identifier
					if i < 10:
						identifier += "_000" + str(i)
					elif i > 9 and i < 100:
						identifier += "_00" + str(i)
					elif i > 99 and i < 1000:
						identifier += "_0" + str(i)
					else:
						identifier += "_" + str(i)

					r.identifier = identifier
					r.updated = timezone.now()
					r.updated_by = request.user
					r.created = timezone.now()
					r.created_by = request.user
					r.save()

		else:
			form = SampleForm(request.user, request.POST, instance=sample)
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
		raw_sql = '''select 'Tool Use' as transaction_type, s.identifier as identifier, p.project_number, us.username, t.name, u.start as start_date, u.end as end_date, ueps.notes
			from "NEMO_usageevent" u
			left outer join "NEMO_user" us on u.operator_id = us.id
			left outer join "NEMO_usageeventproject" uep on u.id=uep.usage_event_id
			left outer join "NEMO_usageeventprojectsample" ueps on ueps.usage_event_project_id = uep.id
			inner join "NEMO_sample" s on ueps.sample_id = s.id
			inner join "NEMO_project" p on uep.project_id=p.id
			inner join "NEMO_tool" t on t.id = u.tool_id
			where u.operator_id=%s
			UNION
			select 'Staff Charge' as transaction_type, s.identifier as identifier, p.project_number, sm.username, concat(us.first_name,' ',us.last_name), sc.start as start_date, sc.end as end_date, scps.notes
			from "NEMO_staffcharge" sc
			left outer join "NEMO_user" sm on sc.staff_member_id = sm.id
			left outer join "NEMO_staffchargeproject" scp on sc.id=scp.staff_charge_id
			left outer join "NEMO_user" us on scp.customer_id = us.id
			left outer join "NEMO_staffchargeprojectsample" scps on scps.staff_charge_project_id = scp.id
			inner join "NEMO_sample" s on scps.sample_id = s.id
			inner join "NEMO_project" p on scp.project_id=p.id
			where sc.staff_member_id=%s
			UNION
			select 'Area Access' as transaction_type, s.identifier as identifier, p.project_number, us.username, a.name, aar.start as start_date, aar.end as end_date, aarps.notes
			from "NEMO_areaaccessrecord" aar
			left outer join "NEMO_area" a on aar.area_id = a.id
			left outer join "NEMO_user" us on aar.user_id = us.id
			left outer join "NEMO_areaaccessrecordproject" aarp on aar.id=aarp.area_access_record_id
			left outer join "NEMO_areaaccessrecordprojectsample" aarps on aarps.area_access_record_project_id = aarp.id
			inner join "NEMO_sample" s on aarps.sample_id = s.id
			inner join "NEMO_project" p on aarp.project_id=p.id
			where aar.user_id=%s
			order by identifier, start_date'''
		cursor.execute(raw_sql, [request.user.id,request.user.id,request.user.id])
	else:
		raw_sql = '''select 'Tool Use' as transaction_type, s.identifier as identifier, p.project_number, us.username, t.name, u.start as start_date, u.end as end_date, ueps.notes
			from "NEMO_usageevent" u
			left outer join "NEMO_user" us on u.operator_id = us.id
			left outer join "NEMO_usageeventproject" uep on u.id=uep.usage_event_id
			left outer join "NEMO_usageeventprojectsample" ueps on ueps.usage_event_project_id = uep.id
			inner join "NEMO_sample" s on ueps.sample_id = s.id
			inner join "NEMO_project" p on uep.project_id=p.id
			inner join "NEMO_tool" t on t.id = u.tool_id
			where s.id=%s
			UNION
			select 'Staff Charge' as transaction_type, s.identifier as identifier, p.project_number, sm.username, concat(us.first_name,' ',us.last_name), sc.start as start_date, sc.end as end_date, scps.notes
			from "NEMO_staffcharge" sc
			left outer join "NEMO_user" sm on sc.staff_member_id = sm.id
			left outer join "NEMO_staffchargeproject" scp on sc.id=scp.staff_charge_id
			left outer join "NEMO_user" us on scp.customer_id = us.id
			left outer join "NEMO_staffchargeprojectsample" scps on scps.staff_charge_project_id = scp.id
			inner join "NEMO_sample" s on scps.sample_id = s.id
			inner join "NEMO_project" p on scp.project_id=p.id
			where s.id=%s
			UNION
			select 'Area Access' as transaction_type, s.identifier as identifier, p.project_number, us.username, a.name, aar.start as start_date, aar.end as end_date, aarps.notes
			from "NEMO_areaaccessrecord" aar
			left outer join "NEMO_area" a on aar.area_id = a.id
			left outer join "NEMO_user" us on aar.user_id = us.id
			left outer join "NEMO_areaaccessrecordproject" aarp on aar.id=aarp.area_access_record_id
			left outer join "NEMO_areaaccessrecordprojectsample" aarps on aarps.area_access_record_project_id = aarp.id
			inner join "NEMO_sample" s on aarps.sample_id = s.id
			inner join "NEMO_project" p on aarp.project_id=p.id
			where s.id=%s
			order by identifier, start_date'''
		cursor.execute(raw_sql, [sample_id,sample_id,sample_id])

	sh = cursor.fetchall()

	if sample_id is None:
		current_sample = None
	else:
		current_sample = Sample.objects.get(id=sample_id)

	return render(request, "sample/sample_history.html",{"sample_history":sh,"sample_id":sample_id,"current_sample": current_sample})


@login_required
def save_sample_comment(request):
	try:
		uep_id = request.POST.get('uep_id', None)
		scp_id = request.POST.get('scp_id', None)
		aarp_id = request.POST.get('aarp_id', None)
		sample_id = request.POST.get('sample_id', None)
		notes = request.POST.get('notes', None)
		sample = Sample.objects.get(id=int(sample_id))

		if uep_id is not None:
			uep = UsageEventProject.objects.get(id=int(uep_id))

			ueps = UsageEventProjectSample.objects.get(usage_event_project=uep, sample=sample)

			ueps.notes = notes
			ueps.updated = timezone.now()
			ueps.save()

		if scp_id is not None:
			scp = StaffChargeProject.objects.get(id=int(scp_id))

			scps = StaffChargeProjectSample.objects.get(staff_charge_project=scp, sample=sample)

			scps.notes = notes
			scps.updated = timezone.now()
			scps.save()

		if aarp_id is not None:
			aarp = AreaAccessRecordProject.objects.get(id=int(aarp_id))

			aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=aarp, sample=sample)

			aarps.notes = notes
			aarps.updated = timezone.now()
			aarps.save()

	except:
		pass

	return HttpResponse()


@login_required
def remove_sample(request):
	try:
		uep_id = request.POST.get('uep_id', None)
		scp_id = request.POST.get('scp_id', None)
		aarp_id = request.POST.get('aarp_id', None)
		sample_id = request.POST.get('sample_id', None)
		sample = Sample.objects.get(id=int(sample_id))

		if uep_id is not None:
			uep = UsageEventProject.objects.get(id=int(uep_id))

			ueps = UsageEventProjectSample.objects.get(usage_event_project=uep, sample=sample)

			ueps.active_flag = False
			ueps.updated = timezone.now()
			ueps.save()

			# check for a staff charge currently happening
			if StaffCharge.objects.filter(related_usage_event=uep.usage_event, end=None).exists():
				sc = StaffCharge.objects.get(related_usage_event=uep.usage_event, end=None)
				scp = StaffChargeProject.objects.filter(staff_charge=sc, customer=uep.customer, project=uep.project)

				for s in scp:
					if StaffChargeProjectSample.objects.filter(staff_charge_project=s, sample=sample).exists():
						scps = StaffChargeProjectSample.objects.get(staff_charge_project=s, sample=sample)
						scps.active_flag = False
						scps.updated = timezone.now()
						scps.save()

			if AreaAccessRecord.objects.filter(related_usage_event=uep.usage_event, end=None).exists():
				aar = AreaAccessRecord.objects.get(related_usage_event=uep.usage_event, end=None)
				aarp = AreaAccessRecordProject.objects.filter(area_access_record=aar, customer=uep.customer, project=uep.project)

				for a in aarp:
					if AreaAccessRecordProjectSample.objects.filter(area_access_record_project=a, sample=sample).exists():
						aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=a, sample=sample)
						aarps.active_flag = False
						aarps.updated = timezone.now()
						aarps.save()

		if scp_id is not None:
			scp = StaffChargeProject.objects.get(id=int(scp_id))

			scps = StaffChargeProjectSample.objects.get(staff_charge_project=scp, sample=sample)

			scps.active_flag = False
			scps.updated = timezone.now()
			scps.save()

			if AreaAccessRecord.objects.filter(staff_charge=scp.staff_charge, end=None).exists():
				aar = AreaAccessRecord.objects.get(staff_charge=scp.staff_charge, end=None)
				aarp = AreaAccessRecordProject.objects.filter(area_access_record=aar, customer=scp.customer, project=scp.project)

				for a in aarp:
					if AreaAccessRecordProjectSample.objects.filter(area_access_record_project=a, sample=sample).exists():
						aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=a, sample=sample)
						aarps.active_flag = False
						aarps.updated = timezone.now()
						aarps.save()

		if aarp_id is not None:
			aarp = AreaAccessRecordProject.objects.get(id=int(aarp_id))

			aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=aarp, sample=sample)

			aarps.active_flag = False
			aarps.updated = timezone.now()
			aarps.save()	


	except Exception as inst:
		return HttpResponseBadRequest(inst)

	return HttpResponse()


@login_required
def add_run_existing_sample(request):
	try:
		uep_id = request.POST.get('uep_id', None)
		scp_id = request.POST.get('scp_id', None)
		aarp_id = request.POST.get('aarp_id', None)
		sample_id = request.POST.get('sample_id', None)
		sample = Sample.objects.get(id=int(sample_id))

		if uep_id is not None:
			uep = UsageEventProject.objects.get(id=int(uep_id))

			if UsageEventProjectSample.objects.filter(usage_event_project=uep, sample=sample).exists():
				ueps = UsageEventProjectSample.objects.get(usage_event_project=uep, sample=sample)
				ueps.active_flag = True
				ueps.updated = timezone.now()
				ueps.save()
			else:
				#uep.sample.add(sample)
				uep.sample_detail.add(sample)

			# check for a staff charge currently happening that should include this
			if StaffCharge.objects.filter(related_usage_event=uep.usage_event, end=None).exists():
				sc = StaffCharge.objects.get(related_usage_event=uep.usage_event, end=None)
				scp = StaffChargeProject.objects.get(staff_charge=sc, customer=uep.customer, project=uep.project)

				if StaffChargeProjectSample.objects.filter(staff_charge_project=scp, sample=sample).exists():
					scps = StaffChargeProjectSample.objects.get(staff_charge_project=scp, sample=sample)
					scps.active_flag = True
					scps.updated = timezone.now()
					scps.save()
				else:
					#scp.sample.add(sample)
					scp.sample_detail.add(sample)

			# check for an area access record related to the run
			if AreaAccessRecord.objects.filter(related_usage_event=uep.usage_event, end=None).exists():
				aar = AreaAccessRecord.objects.get(related_usage_event=uep.usage_event, end=None)
				aarp = AreaAccessRecordProject.objects.get(area_access_record=aar, customer=uep.customer, project=uep.project)

				if AreaAccessRecordProjectSample.objects.filter(area_access_record_project=aarp, sample=sample).exists():
					aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=aarp, sample=sample)
					aarps.active_flag = True
					aarps.updated = timezone.now()
					aarps.save()
				else:
					#aarp.sample.add(sample)
					aarp.sample_detail.add(sample)

		if scp_id is not None:
			scp = StaffChargeProject.objects.get(id=int(scp_id))

			if StaffChargeProjectSample.objects.filter(staff_charge_project=scp, sample=sample).exists():
				scps = StaffChargeProjectSample.objects.get(staff_charge_project=scp, sample=sample)
				scps.active_flag = True
				scps.updated = timezone.now()
				scps.save()
			else:
				#scp.sample.add(sample)
				scp.sample_detail.add(sample)

			# check for a related area access charge
			if AreaAccessRecord.objects.filter(staff_charge=scp.staff_charge, end=None).exists():
				aar = AreaAccessRecord.objects.get(staff_charge=scp.staff_charge, end=None)
				aarp = AreaAccessRecordProject.objects.get(area_access_record=aar, customer=scp.customer, project=scp.project)

				if AreaAccessRecordProjectSample.objects.filter(area_access_record_project=aarp, sample=sample).exists():
					aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=aarp, sample=sample)
					aarps.active_flag = True
					aarps.updated = timezone.now()
					aarps.save()
				else:
					#aarp.sample.add(sample)
					aarp.sample_detail.add(sample)

		if aarp_id is not None:
			aarp = AreaAccessRecordProject.objects.get(id=int(aarp_id))

			if AreaAccessRecordProjectSample.objects.filter(area_access_record_project=aarp, sample=sample).exists():
				aarps = AreaAccessRecordProjectSample.objects.get(area_access_record_project=aarp, sample=sample)
				aarps.active_flag = True
				aarps.updated = timezone.now()
				aarps.save()
			else:
				#aarp.sample.add(sample)
				aarp.sample_detail.add(sample)

	except Exception as inst:
		return HttpResponseBadRequest(inst)

	return HttpResponse()


@login_required
def modal_select_sample(request, project_id):
	data = {}
	try:
		project = Project.objects.get(id=int(project_id))
		samples = Sample.objects.filter(project=project, active_flag=True)

		data["project"] = project
		data["samples"] = samples
	except:
		data["project"] = None
		data["samples"] = None

	return render(request, "sample/modal_select_sample.html", data)
