import json

from re import search

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.utils.dateformat import DateFormat
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, Consumable, ConsumableWithdraw, ContestTransaction, Project, UsageEvent, UsageEventProject, StaffCharge, StaffChargeProject, Tool, User
from NEMO.utilities import month_list, get_month_timeframe


#@staff_member_required(login_url=None)
@login_required
@require_GET
def remote_work(request):
	first_of_the_month, last_of_the_month = get_month_timeframe(request.GET.get('date'))
	operator = request.GET.get('operator')
	if operator:
		if operator == "all staff":
			operator = None
		else:
			operator = get_object_or_404(User, id=operator)
	else:
		operator = request.user
	usage_events = UsageEvent.objects.filter(start__gte=first_of_the_month, start__lte=last_of_the_month)
	staff_charges = StaffCharge.objects.filter(start__gte=first_of_the_month, start__lte=last_of_the_month)
	area_access_records = AreaAccessRecord.objects.filter(start__gte=first_of_the_month, start__lte=last_of_the_month)
	consumable_withdraws = ConsumableWithdraw.objects.filter(date__gte=first_of_the_month, date__lte=last_of_the_month)
	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		staff_charges = staff_charges.exclude(~Q(staff_member_id=operator.id))
		area_access_records = area_access_records.exclude(~Q(staff_charge__staff_member_id=operator.id))
		consumable_withdraws = consumable_withdraws.exclude(~Q(merchant_id=operator.id))

	dictionary = {
		'usage': usage_events,
		'staff_charges': staff_charges if request.user.is_staff else None,
		'area_access_records': area_access_records,
		'consumable_withdraws': consumable_withdraws if request.user.is_staff else None,
		'staff_list': User.objects.filter(is_staff=True).order_by('last_name', 'first_name'),
		'month_list': month_list(),
		'selected_staff': operator.id if operator else "all staff",
		'selected_month': request.GET.get('date'),
	}
	return render(request, 'remote_work.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def validate_staff_charge(request, staff_charge_id):
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	staff_charge.validated = True
	staff_charge.updated = timezone.now()
	staff_charge.validated_date = timezone.now()
	staff_charge.save()
	return HttpResponse()


#@staff_member_required(login_url=None)
@login_required
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	usage_event.validated = True
	usage_event.updated = timezone.now()
	usage_event.validated_date = timezone.now()
	usage_event.save()
	return HttpResponse()


#@staff_member_required(login_url=None)
@login_required
@require_POST
def validate_area_access_record(request, area_access_record_id):
	area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
	area_access_record.validated = True
	area_access_record.updated = timezone.now()
	area_access_record.validated_date = timezone.now()
	area_access_record.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_POST
def validate_consumable_withdraw(request, consumable_withdraw_id):
	consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
	consumable_withdraw.validated = True
	consumable_withdraw.updated = timezone.now()
	consumable_withdraw.validated_date = timezone.now()
	consumable_withdraw.save()
	return HttpResponse()


@staff_member_required(login_url=None)
@require_POST
def contest_staff_charge(request, staff_charge_id):
	dictionary = {
		'contest_type': 'Staff Charge',
		'usage_event': None,
		'area_access_record': None,
		'consumable_withdraw': None,
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).distinct(),
	}
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	dictionary['staff_charge'] = staff_charge
	dictionary['scp'] = StaffChargeProject.objects.filter(staff_charge=staff_charge)
	return render(request, 'remote_work_contest.html', dictionary)


#@staff_member_required(login_url=None)
@login_required
@require_POST
def contest_usage_event(request, usage_event_id):
	dictionary = {
		'contest_type': 'Usage Event',
		'staff_charge': None,
		'area_access_record': None,
		'consumable_withdraw': None,
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).distinct(),
	}
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	dictionary['usage_event'] = usage_event
	dictionary['uep'] = UsageEventProject.objects.filter(usage_event=usage_event)
	if request.user.is_superuser:
		tools = Tool.objects.all()
	else:
		tools = request.user.qualifications.all()
	dictionary['tools'] = tools
	return render(request, 'remote_work_contest.html', dictionary)


#@staff_member_required(login_url=None)
@login_required
@require_POST
def contest_area_access_record(request, area_access_record_id):
	dictionary = {
		'contest_type': 'Area Access Record',
		'staff_charge': None,
		'usage_event': None,
		'consumable_withdraw': None,
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).distinct(),
	}
	area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
	dictionary['area_access_record'] = area_access_record
	dictionary['aarp'] = AreaAccessRecordProject.objects.filter(area_access_record=area_access_record)
	if request.user.is_superuser:
		areas = Area.objects.all()
	else:
		areas = Area.objects.filter(area__in=request.user.physical_access_levels.area)
	dictionary['areas'] = areas
	return render(request, 'remote_work_contest.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def contest_consumable_withdraw(request, consumable_withdraw_id):
	dictionary = {
		'contest_type': 'Consumable Withdraw',
		'staff_charge': None,
		'usage_event': None,
		'area_access_record': None,
		'users': User.objects.filter(is_active=True, projects__active=True, projects__account__active=True).distinct(),
	}
	consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
	dictionary['consumable_withdraw'] = consumable_withdraw
	if request.user.is_superuser:
		consumables = Consumable.objects.all()
	else:
		consumables = Consumable.objects.filter(core_id__in=request.user.core_ids.all())
	dictionary['consumables'] = consumables
	return render(request, 'remote_work_contest.html', dictionary)


def is_valid_field(field):
	return search("^(proposed|original)__(area|consumable|quantity|chosen_user|chosen_project|project_percent|tool_id|start|end)__[0-9]+$", field) is not None

#@staff_member_required(login_url=None)
@login_required
@require_POST
def save_contest(request):
	contest_type = request.POST.get("contest_type")
	submission = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			flag, field, id = key.split("__")
			id = int(id)
			if id not in submission:
				submission[id] = {}
				submission[id][field] = {}

			if field not in submission[id]:
				submission[id][field] = {}

			submission[id][field][flag] = value

	
	if contest_type == "Staff Charge":
		staff_charge_id = request.POST.get("staff_charge_id")
		staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
		staff_charge.contested = True
		description = request.POST.get("contest_reason")
		#if description == "Other":
		#	description = request.POST.get("other_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		staff_charge.contest_description = description
		staff_charge.contested_date = timezone.now()
		staff_charge.updated = timezone.now()
		staff_charge.save()

		for id in submission:
			for field in submission[id]:
				if submission[id][field]["proposed"] != submission[id][field]["original"]:
					if field in ("start", "end"):
						content_object = StaffCharge.objects.get(id=id)
					else:
						content_object = StaffChargeProject.objects.get(id=id)
					ContestTransaction.objects.create(content_object=content_object, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

	if contest_type == "Usage Event":
		usage_event_id = request.POST.get("usage_event_id")
		usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
		usage_event.contested = True
		description = request.POST.get("contest_reason")
		#if description == "Other":
		#	description = request.POST.get("other_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		usage_event.contest_description = description
		usage_event.contested_date = timezone.now()
		usage_event.updated = timezone.now()
		usage_event.save()

		for id in submission:
			for field in submission[id]:
				if submission[id][field]["proposed"] != submission[id][field]["original"]:
					if field in ("tool_id", "start", "end"):
						content_object = UsageEvent.objects.get(id=id)
					else:
						content_object = UsageEventProject.objects.get(id=id)
					
					ContestTransaction.objects.create(content_object=content_object, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

	if contest_type == "Area Access Record":
		area_access_record_id = request.POST.get("area_access_record_id")
		area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
		area_access_record.contested = True
		description = request.POST.get("contest_reason")
		#if description == "Other":
		#	description = request.POST.get("other_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		area_access_record.contest_description = description
		area_access_record.contested_date = timezone.now()
		area_access_record.updated = timezone.now()
		area_access_record.save()

		for id in submission:
			for field in submission[id]:
				if submission[id][field]["proposed"] != submission[id][field]["original"]:
					if field in ("area", "start", "end"):
						content_object = AreaAccessRecord.objects.get(id=id)
					else:
						content_object = AreaAccessRecordProject.objects.get(id=id)
					ContestTransaction.objects.create(content_object=content_object, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

	if contest_type == "Consumable Withdraw":
		consumable_withdraw_id = request.POST.get("consumable_withdraw_id")
		consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
		consumable_withdraw.contested = True
		description = request.POST.get("contest_reason")
		#if description == "Other":
		#	description = request.POST.get("other_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		consumable_withdraw.contest_description = description
		consumable_withdraw.contested_date = timezone.now()
		consumable_withdraw.updated = timezone.now()
		consumable_withdraw.save()

		for id in submission:
			for field in submission[id]:
				if submission[id][field]["proposed"] != submission[id][field]["original"]:
					content_object = ConsumableWithdraw.objects.get(id=id)
					ContestTransaction.objects.create(content_object=content_object, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

	return HttpResponseRedirect('/remote_work/')


@staff_member_required(login_url=None)
def review_contested_items(request):
	dictionary = {}

	if request.user.is_superuser:
		dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_resolved=False)
		dictionary['usage'] = UsageEvent.objects.filter(validated=False, contested=True, contest_resolved=False)
		dictionary['area_access_records'] = AreaAccessRecord.objects.filter(validated=False, contested=True, contest_resolved=False)
		dictionary['consumable_withdraws'] = ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_resolved=False)
	else:
		dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_resolved=False, staff_member__core_ids__in=request.user.core_ids.all())
		dictionary['usage'] = UsageEvent.objects.filter(validated=False, contested=True, contest_resolved=False, operator__core_ids__in=request.user.core_ids.all())
		dictionary['area_access_records'] = AreaAccessRecord.objects.filter(validated=False, contested=True, contest_resolved=False, staff_charge__staff_member__core_ids__in=request.user.core_ids.all())
		dictionary['consumable_withdraws'] = ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_resolved=False, consumable__core_id__in=request.user.core_ids.all())

	return render(request, 'remote_work_contest_review.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def resolve_staff_charge_contest(request):
	dictionary = {}

	staff_charge_id = request.POST.get('staff_charge_id')

	if staff_charge_id is None or staff_charge_id == '':
		error = 'A staff charge id was not successfully submitted for resolution'
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	staff_charge_id = int(staff_charge_id)
	staff_charge = StaffCharge.objects.get(id=staff_charge_id)

	if staff_charge is None:
		error = 'A staff charge was not found with id = ' + str(staff_charge_id)
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	dictionary['staff_charge'] = staff_charge

	return render(request, 'remote_work_contest_resolve.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def resolve_usage_event_contest(request):
	dictionary = {}

	usage_event_id = request.POST.get('usage_event_id')

	if usage_event_id is None or usage_event_id == '':
		error = 'A usage event id was not successfully submitted for resolution'
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	usage_event_id = int(usage_event_id)
	usage_event = UsageEvent.objects.get(id=usage_event_id)

	if usage_event is None:
		error = 'A usage event was not found with id = ' + str(usage_event_id)
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	dictionary['usage_event'] = usage_event

	""" 
	as an alternative to the clunky template-based generation, create the HTML here and pass as a string
	This string will contain the form elements, but in order to easily preserve the csrf_token the form 
	will be defined in the template
	"""
	review_form = "<table class=\"table\">"
	review_form += "<tr><th>Contest Description</th><td colspan=\"3\">" + usage_event.contest_description + "</td></tr>"
	review_form += "<tr><th>Operator</th><td>" + str(usage_event.operator) + "</td><td>&nbsp;</td><td>&nbsp;</td></tr>"
	review_form += "<tr><th>Tool</th><td>" + str(usage_event.tool) + "</td><td>"

	# check for tool change
	usage_event_type = ContentType.objects.get_for_model(usage_event)
	if ContestTransaction.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="tool_id").exists():
		ct = ContestTransaction.objects.get(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="tool_id")
		o_id = int(ct.original_value)
		p_id = int(ct.proposed_value)
		review_form += Tool.objects.get(id=o_id) + "</td><td><span style=\"font-weight:bold; color:red;\">" + str(Tool.objects.get(id=p_id)) + "</span><input type=\"hidden\" name=\"proposed__tool_id__" + str(usage_event_id) + "\" value=\"" + str(p_id) + "\" /></td></tr>"
	else:
		review_form += "&nbsp;</td><td>&nbsp;</td></tr>"

	df = DateFormat(usage_event.start)
	review_form += "<tr><th>Start</th><td>" + df.format('Y-m-d H:i:s') + "</td>"
	# check for start change
	if ContestTransaction.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="start").exists():
		ct = ContestTransaction.objects.get(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="start")
		o_value = ct.original_value
		p_value = ct.proposed_value
		review_form += "<td><span style=\"font-weight:bold; color:red;\">" + p_value+ "</span><input type=\"hidden\" name=\"proposed__start__" + str(usage_event_id) + "\" value=\"" + p_value + "\" /></td></tr>"
	else:
		 review_form += "<td>&nbsp;</td><td>&nbsp;</td></tr>"

	df = DateFormat(usage_event.end)
	review_form += "<tr><th>End</th><td>" + df.format('Y-m-d H:i:s') + "</td>"
	# check for end chage
	if ContestTransaction.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="end").exists():
		ct = ContestTransaction.objects.get(content_type__pk=usage_event_type.id, object_id=usage_event.id, field_name="end")
		o_value = ct.original_value
		p_value = ct.proposed_value
		review_form += "<td><span style=\"font-weight:bold; color:red;\">" + p_value + "</span><input type=\"hidden\" name=\"proposed__end__" + str(usage_event_id) + "\" value=\"" + p_value + "\" /></td></tr>"
	else:
		review_form += "<td>&nbsp;</td><td>&nbsp;</td></tr>"

	# look for changes in customer, project and/or project_percent
	review_form += "<tr><td colspan=\"4\"><table class=\"table\">"
	review_form += "<tr><td colspan=\"3\"><hr></td></tr>"
	for uep in UsageEventProject.objects.filter(usage_event=usage_event):
		uep_type = ContentType.objects.get_for_model(uep)

		# add customer
		review_form += "<tr><th>Customer</th><td>" + str(uep.customer) + "</td>"
		if ContestTransaction.objects.filter(content_type__pk=uep_type.id, object_id=uep.id, field_name="chosen_user").exists():
			ct = ContestTransaction.objects.get(content_type__pk=uep_type.id, object_id=uep.id, field_name="chosen_user")
			o_id = int(ct.original_value)
			p_id = int(ct.proposed_value)
			review_form += "<td><span style=\"font-weight:bold; color:red;\">" + str(User.objects.get(id=p_id)) + "</span><input type=\"hidden\" name=\"proposed__chosen_user__" + str(uep.id) + "\" value=\"" + str(p_id) + "\" /></td></tr>"
		else:
			review_form += "<td>&nbsp;</td></tr>"
		# add project
		review_form += "<tr><th>Project</th><td>" + uep.project.application_identifier + "</td>"
		if ContestTransaction.objects.filter(content_type__pk=uep_type.id, object_id=uep.id, field_name="chosen_project").exists():
			ct = ContestTransaction.objects.get(content_type__pk=uep_type.id, object_id=uep.id, field_name="chosen_project")
			o_id = int(ct.original_value)
			p_id = int(ct.proposed_value)
			p_project = Project.objects.get(id=p_id)
			review_form += "<td><span style=\"font-weight:bold; color:red;\">" + p_project.application_identifier + "</span><input type=\"hidden\" name=\"proposed__chosen_project__" + str(uep.id) + "\" value=\"" + str(p_id) + "\" /></td></tr>"
		else:
			review_form += "<td>&nbsp;</td></tr>"
		# add project_percent
		review_form += "<tr><th>Percent</th><td>" + str(uep.project_percent) + "</td>"
		if ContestTransaction.objects.filter(content_type__pk=uep_type.id, object_id=uep.id, field_name="project_percent").exists():
			ct = ContestTransaction.objects.get(content_type__pk=uep_type.id, object_id=uep.id, field_name="project_percent")
			o_value = ct.original_value
			p_value = ct.proposed_value
			review_form += "<td><span style=\"font-weight:bold; color:red;\">" + str(p_value) + "</span><input type=\"hidden\" name=\"proposed__project_percent__" + str(uep.id) + "\" value=\"" + str(p_value) + "\" /></td></tr>"
		else:
			review_form += "<td>&nbsp;</td></tr>"
		review_form += "<tr><td colspan=\"3\"><hr></td></tr>"
	review_form += "</table></td></tr></table>"

	dictionary['review_form'] = review_form

	return render(request, 'remote_work_contest_resolve.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def resolve_area_access_record_contest(request):
	dictionary = {}

	area_access_record_id = request.POST.get('area_access_record_id')

	if area_access_record_id is None or area_access_record_id == '':
		error = 'An area access record id was not successfully submitted for resolution'
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	area_access_record_id = int(area_access_record_id)
	area_access_record = AreaAccessRecord.objects.get(id=area_access_record_id)

	if area_access_record is None:
		error = 'An area access record was not found with id = ' + str(area_access_record_id)
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	dictionary['area_access_record'] = area_access_record

	return render(request, 'remote_work_contest_resolve.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def resolve_consumable_withdraw_contest(request):
	dictionary = {}

	consumable_withdraw_id = request.POST.get('consumable_withdraw_id')

	if consumable_withdraw_id is None or consumable_withdraw_id == '':
		error = 'A consumable withdraw id was not successfully submitted for resolution'
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	consumable_withdraw_id = int(consumable_withdraw_id)
	consumable_withdraw = ConsumableWithdraw.objects.get(id=consumable_withdraw_id)

	if consumable_withdraw is None:
		error = 'A consumable withdraw was not found with id = ' + str(consumable_withdraw_id)
		dictionary['error'] = error
		return render(request, 'remote_work_contest_review.html', dictionary)

	dictionary['consumable_withdraw'] = consumable_withdraw

	return render(request, 'remote_work_contest_resolve.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def save_contest_resolution(request):
	output = "<a href='/review_contested_items/'>Return to contest review</a><br/>\n"

	for key, value in request.POST.items():
		output += key + " = " + value + "<br/>\n"

	output += "<a href='/review_contested_items/'>Return to contest review</a><br/>\n"

	return HttpResponse(output)
