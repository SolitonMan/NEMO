#import datetime
import json
#import pytz

#from datetime import datetime #, timezone
from datetime import datetime, date
from logging import getLogger
#from pytz import timezone
from re import search

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import DateFormat
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, AreaAccessRecordProjectSample, Consumable, ConsumableWithdraw, ContestTransaction, ContestTransactionData, ContestTransactionNewData, Core, CreditCostCollector, LockBilling, Project, UsageEvent, UsageEventProject, UsageEventProjectSample, StaffCharge, StaffChargeProject, StaffChargeProjectSample, Tool, User
from NEMO.utilities import month_list, get_month_timeframe


def get_dummy_projects():
	projects = Project.objects.filter(Q(simba_cost_center__iregex=r'^[a-zA-Z]') | Q(internal_order__iregex=r'^[a-zA-Z]') | Q(wbs_element__iregex=r'^[a-zA-Z]'))
	return projects

#@staff_member_required(login_url=None)
@login_required
@require_GET
def remote_work(request):
	start_date = request.GET.get('date')

	if start_date is None:
		start_date = timezone.now().strftime('%Y-%m-%d')
	else:
		start_date = datetime.strptime(start_date, '%B, %Y').strftime('%Y-%m-%d')

	first_of_the_month, last_of_the_month = get_month_timeframe(start_date)
	operator = request.GET.get('operator')
	if operator:
		if operator == "all staff":
			operator = None
		else:
			operator = get_object_or_404(User, id=operator)
	else:
		operator = request.user
	usage_events = UsageEvent.objects.filter(end__gte=first_of_the_month, end__lte=last_of_the_month, active_flag=True, no_charge_flag=False).exclude(end=None)
	staff_charges = StaffCharge.objects.filter(end__gte=first_of_the_month, end__lte=last_of_the_month, active_flag=True, no_charge_flag=False, ad_hoc_replaced=False).exclude(end=None)
	area_access_records = AreaAccessRecord.objects.filter(end__gte=first_of_the_month, end__lte=last_of_the_month, active_flag=True, no_charge_flag=False).exclude(end=None)
	consumable_withdraws = ConsumableWithdraw.objects.filter(date__gte=first_of_the_month, date__lte=last_of_the_month, active_flag=True, no_charge_flag=False)

	if request.user.groups.filter(name="Core Admin").exists():
		usage_events = usage_events.filter(tool__core_id__in=request.user.core_ids.all())
		staff_charges = staff_charges.filter(staff_member__core_ids__in=request.user.core_ids.all())
		area_access_records = area_access_records.filter(area__core_id__in=request.user.core_ids.all())
		consumable_withdraws = consumable_withdraws.filter(consumable__core_id__in=request.user.core_ids.all())

	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		staff_charges = staff_charges.exclude(~Q(staff_member_id=operator.id))
		#area_access_records = area_access_records.exclude(~Q(staff_charge__staff_member_id=operator.id) & ~(Q(staff_charge__staff_member_id__isnull=True) & Q(customer_id=operator.id)))
		#area_access_records = area_access_records.exclude((~Q(customer_id=operator.id) & Q(customer_id__isnull=False)) | (~Q(user_id=operator.id)) | ~Q(customers__id=operator.id))
		area_access_records = area_access_records.exclude(~Q(user_id=operator.id))
		consumable_withdraws = consumable_withdraws.filter(merchant=operator)

		#if operator == request.user:
			#usage_events = usage_events.exclude(projects__in=get_dummy_projects()).exclude(project__in=get_dummy_projects())
			#staff_charges = staff_charges.exclude(projects__in=get_dummy_projects()).exclude(project__in=get_dummy_projects())
			#area_access_records = area_access_records.exclude(projects__in=get_dummy_projects()).exclude(project__in=get_dummy_projects())
			#consumable_withdraws = consumable_withdraws.exclude(project__in=get_dummy_projects())

	show_buttons = operator == request.user or request.user.is_superuser or request.user.groups.filter(name="Core Admin").exists()

	uep = UsageEventProject.objects.filter(usage_event__in=usage_events, active_flag=True)
	scp = StaffChargeProject.objects.filter(staff_charge__in=staff_charges, active_flag=True)
	aarp = AreaAccessRecordProject.objects.filter(area_access_record__in=area_access_records, active_flag=True)

	staff_list = User.objects.filter(is_staff=True).order_by('last_name', 'first_name')

	if operator is None and request.user.groups.filter(name="Core Admin").exists():
		staff_list = staff_list.filter(core_ids__in=request.user.core_ids.all())

	transactions = {}

	# render usage event and usage event project records into the transactions dictionary
	for u in usage_events:
		transaction_type = "Tool Use"
		transaction_key = "usage_event_" + str(u.id)

		if transaction_key not in transactions:
			transactions[transaction_key] = {
				'type': transaction_type,
				'id': u.id,
				'operator': str(u.operator),
				'tool': str(u.tool),
				'start': u.start,
				'end': u.end,
				'validated': u.validated,
				'contested': u.contested,
				'comment': u.operator_comment,
				'duration': u.duration,
				'quantity': '',
				'rowspan': u.usageeventproject_set.filter(active_flag=True).count(),
				'contest_rejection_reason': '',
				'contest_id': '',
				'contest_resolved_date':'',
				'class': '',
				'customers': '',
				'ad_hoc_created': u.ad_hoc_created,
				'cost_per_sample_run': u.cost_per_sample_run,
				'show_contested': False,
				'days_passed': days_passed(u.end),
			}

			if u.validated:
				transactions[transaction_key]['class'] = 'success-highlight'
				if u.contest_record.all().count() > 0:
					transactions[transaction_key]['class'] = 'success-highlight-contested'
					transactions[transaction_key]['show_contested'] = True
			else:
				if u.contested:
					if u.contest_record.filter(contest_resolved=False).count() == 0:
						# a problem exists because there should be at least one open contest record if the usage event is marked as contested
						transactions[transaction_key]['class'] = 'conflict-highlight'
					elif u.contest_record.filter(contest_resolved=False).count() == 1:
						transactions[transaction_key]['class'] = 'warning-highlight'
					else:
						# more than one contest record open
						transactions[transaction_key]['class'] = 'conflict-highlight'
				else:
					if u.contest_record:
						if u.contest_record.all().count() > 0:
							if u.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolution:
								transactions[transaction_key]['class'] = ''
							else:
								transactions[transaction_key]['class'] = 'danger-highlight'
								transactions[transaction_key]['contest_rejection_reason'] = u.contest_record.all().order_by('-contest_resolved_date')[0].contest_rejection_reason
								transactions[transaction_key]['contest_id'] = u.contest_record.all().order_by('-contest_resolved_date')[0].id
								transactions[transaction_key]['contest_resolved_date'] = u.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolved_date
					else:
						# not validated, not contested, never had a contest
						transactions[transaction_key]['class'] = ''

			customers = {}
			for uep in u.usageeventproject_set.filter(active_flag=True):
				if uep.id not in customers:
					customers[uep.id] = {
						'id': uep.id,
						'customer': str(uep.customer),
						'project': str(uep.project),
						'percent': uep.project_percent,
						'comment': uep.comment,
						'cost_per_sample': uep.cost_per_sample,
						'sample_num': uep.sample_num,
					}
			transactions[transaction_key]['customers'] = customers


	# render staff charge and staff charge project records into the transactions dictionary
	for s in staff_charges:
		transaction_type = "Staff Charge"
		transaction_key = "staff_charge_" + str(s.id)

		if transaction_key not in transactions:
			transactions[transaction_key] = {
				'type': transaction_type,
				'id': s.id,
				'operator': str(s.staff_member),
				'tool': 'Staff Charge' + show_override(s),
				'start': s.start,
				'end': s.end,
				'validated': s.validated,
				'contested': s.contested,
				'comment': s.staff_member_comment,
				'duration': s.duration,
				'quantity': '',
				'rowspan': s.staffchargeproject_set.filter(active_flag=True).count(),
				'contest_rejection_reason': '',
				'contest_id': '',
				'contest_resolved_date': '',
				'class': '',
				'customers': '',
				'ad_hoc_created': s.ad_hoc_created,
				'cost_per_sample_run': s.cost_per_sample_run,
				'related_usage_event': s.related_usage_event,
				'show_contested': False,
				'days_passed': days_passed(s.end),
			}

			if s.validated:
				transactions[transaction_key]['class'] = 'success-highlight'
				if s.contest_record.all().count() > 0:
					transactions[transaction_key]['class'] = 'success-highlight-contested'
					transactions[transaction_key]['show_contested']: True
			else:
				if s.contested:
					if s.contest_record.filter(contest_resolved=False).count() == 0:
 						# a problem exists because there should be at least one open contest record if the staff charge is marked as contested
						transactions[transaction_key]['class'] = 'conflict-highlight'
					elif s.contest_record.filter(contest_resolved=False).count() == 1:
						transactions[transaction_key]['class'] = 'warning-highlight'
					else:
						# more than one contest record open
						transactions[transaction_key]['class'] = 'conflict-highlight'
				else:
					if s.contest_record:
						if s.contest_record.all().count() > 0:
							if s.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolution:
								transactions[transaction_key]['class'] = ''
							else:
								transactions[transaction_key]['class'] = 'danger-highlight'
								transactions[transaction_key]['contest_rejection_reason'] = s.contest_record.all().order_by('-contest_resolved_date')[0].contest_rejection_reason
								transactions[transaction_key]['contest_id'] = s.contest_record.all().order_by('-contest_resolved_date')[0].id
								transactions[transaction_key]['contest_resolved_date'] = s.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolved_date
					else:
						# not validated, not contested, never had a contest
						transactions[transaction_key]['class'] = ''

			customers = {}
			for scp in s.staffchargeproject_set.filter(active_flag=True):
				if scp.id not in customers:
					customers[scp.id] = {
						'id': scp.id,
						'customer': str(scp.customer),
						'project': str(scp.project),
						'percent': scp.project_percent,
						'comment': scp.comment,
					}
			transactions[transaction_key]['customers'] = customers


	# render area access record and area access record project records into the transactions dictionary
	for a in area_access_records:
		transaction_type = "Area Access"
		transaction_key = "area_access_record_" + str(a.id)

		if transaction_key not in transactions:
			transactions[transaction_key] = {
				'type': transaction_type,
				'id': a.id,
				'operator': str(a.staff_charge.staff_member) if a.staff_charge else str(a.customer),
				'tool': str(a.area),
				'start': a.start,
				'end': a.end,
				'validated': a.validated,
				'contested': a.contested,
				'comment': a.comment,
				'duration': a.duration,
				'quantity': '',
				'rowspan': a.areaaccessrecordproject_set.filter(active_flag=True).count(),
				'contest_rejection_reason': '',
				'contest_id': '',
				'contest_resolved_date': '',
				'class': '',
				'customers': '',
				'ad_hoc_created': a.ad_hoc_created,
				'cost_per_sample_run': a.cost_per_sample_run,
				'related_usage_event': a.related_usage_event,
				'show_contested': False,
				'days_passed': days_passed(a.end),
			}

			if a.validated:
				transactions[transaction_key]['class'] = 'success-highlight'
				if a.contest_record.all().count() > 0:
					transactions[transaction_key]['class'] = 'success-highlight-contested'
					transactions[transaction_key]['show_contested'] = True
			else:
				if a.contested:
					if a.contest_record.filter(contest_resolved=False).count() == 0:
 						# a problem exists because there should be at least one open contest record if the staff charge is marked as contested
						transactions[transaction_key]['class'] = 'conflict-highlight'
					elif a.contest_record.filter(contest_resolved=False).count() == 1:
						transactions[transaction_key]['class'] = 'warning-highlight'
					else:
						# more than one contest record open
						transactions[transaction_key]['class'] = 'conflict-highlight'
				else:
					if a.contest_record:
						if a.contest_record.all().count() > 0:
							if a.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolution:
								transactions[transaction_key]['class'] = ''
							else:
								transactions[transaction_key]['class'] = 'danger-highlight'
								transactions[transaction_key]['contest_rejection_reason'] = a.contest_record.all().order_by('-contest_resolved_date')[0].contest_rejection_reason
								transactions[transaction_key]['contest_id'] = a.contest_record.all().order_by('-contest_resolved_date')[0].id
								transactions[transaction_key]['contest_resolved_date'] = a.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolved_date
					else:
						# not validated, not contested, never had a contest
						transactions[transaction_key]['class'] = ''

			customers = {}
			if a.areaaccessrecordproject_set.filter(active_flag=True).count() > 0:
				for aarp in a.areaaccessrecordproject_set.filter(active_flag=True):
					if aarp.id not in customers:
						customers[aarp.id] = {
							'id': aarp.id,
							'customer': str(aarp.customer),
							'project': str(aarp.project),
							'percent': aarp.project_percent,
							'comment': aarp.comment,
						}
			else:
				customers[a.id] = {
					'id': a.id,
					'customer': str(a.customer),
					'project': str(a.project),
					'percent': '100.0',
					'comment': '',
				}

			transactions[transaction_key]['customers'] = customers


	# render the consumable withdraw records into the transactions dictionary
	for c in consumable_withdraws:
		transaction_type = "Withdraw"
		transaction_key = "consumable_withdraw_" + str(c.id)

		if transaction_key not in transactions:
			transactions[transaction_key] = {
				'type': transaction_type,
				'id': c.id,
				'operator': str(c.merchant),
				'tool': str(c.consumable),
				'start': c.date,
				'end': c.date,
				'validated': c.validated,
				'contested': c.contested,
				'comment': c.notes,
				'duration': '',
				'quantity': str(c.quantity) + ' ' + str(c.consumable.unit.abbreviation),
				'rowspan': 1,
				'contest_rejection_reason': '',
				'contest_id': '',
				'contest_resolved_date': '',
				'class': '',
				'customers': '',
				'ad_hoc_created': False,
				'related_usage_event': c.usage_event,
				'show_contested': False,
				'days_passed': days_passed(c.date),
			}

			if c.validated:
				transactions[transaction_key]['class'] = 'success-highlight'
				if c.contest_record.all().count() > 0:
					transactions[transaction_key]['class'] = 'success-highlight-contested'
					transactions[transaction_key]['show_contested'] = True
			else:
				if c.contested:
					if c.contest_record.filter(contest_resolved=False).count() == 0:
 						# a problem exists because there should be at least one open contest record if the staff charge is marked as contested
						transactions[transaction_key]['class'] = 'conflict-highlight'
					elif c.contest_record.filter(contest_resolved=False).count() == 1:
						transactions[transaction_key]['class'] = 'warning-highlight'
					else:
						# more than one contest record open
						transactions[transaction_key]['class'] = 'conflict-highlight'
				else:
					if c.contest_record:
						if c.contest_record.all().count() > 0:
							if c.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolution:
								transactions[transaction_key]['class'] = ''
							else:
								transactions[transaction_key]['class'] = 'danger-highlight'
								transactions[transaction_key]['contest_rejection_reason'] = c.contest_record.all().order_by('-contest_resolved_date')[0].contest_rejection_reason
								transactions[transaction_key]['contest_id'] = c.contest_record.all().order_by('-contest_resolved_date')[0].id
								transactions[transaction_key]['contest_resolved_date'] = c.contest_record.all().order_by('-contest_resolved_date')[0].contest_resolved_date
					else:
						# not validated, not contested, never had a contest
						transactions[transaction_key]['class'] = ''

			customers = {}

			customers[c.id] = {
				'id': c.id,
				'customer': str(c.customer),
				'project': str(c.project),
				'percent': c.project_percent,
				'comment': '',
			}

			transactions[transaction_key]['customers'] = customers

	if request.user.is_superuser:
		staff_list = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
	elif request.user.groups.filter(name="Core Admin").exists():
		staff_list = User.objects.filter(is_staff=True, core_ids__in=request.user.core_ids.all(), is_active=True).order_by('last_name', 'first_name')
	else:
		staff_list = None

	# sort the transaction on start date descending
	t_list = sorted(transactions.items(), key=lambda trans: trans[1]['start'], reverse=True)

	new_t = {}

	for t in t_list:
		new_t[t[0]] = t[1]

	dictionary = {
		'usage': usage_events,
		'staff_charges': staff_charges if request.user.is_staff else None,
		'area_access_records': area_access_records,
		'consumable_withdraws': consumable_withdraws,
		'staff_list': staff_list,
		'month_list': month_list(),
		'selected_staff': operator.id if operator else "all staff",
		'selected_month': datetime.strptime(start_date, '%Y-%m-%d').strftime('%B, %Y'),
		'uep': uep,
		'scp': scp,
		'aarp': aarp,
		'show_buttons': show_buttons,
		'user_is_core_admin': request.user.groups.filter(name="Core Admin").exists(),
		'transactions': new_t,
		'sorted_transactions': t_list,
	}
	return render(request, 'remote_work.html', dictionary)


def show_override(staff_charge):
	ret = ''

	if staff_charge.core_id_override is not None:
		core = get_object_or_404(Core, id=staff_charge.core_id_override)
		ret += '<br/><span style="font-size: 8pt;">Core: ' + str(core) + '</span>'

	if staff_charge.credit_cost_collector_override is not None:
		ccc = get_object_or_404(CreditCostCollector, id=staff_charge.credit_cost_collector_override)
		ret += '<br/><span style="font-size: 8pt;">Collector: ' + str(ccc) + '</span>'

	return ret

def make_aware(date_obj, tz=None):
	if not date_obj:
		return date_obj

	if not tz:
		tz = pytz.timezone('America/New_York')

	aware_date = tz.localize(date_obj)

	return aware_date


@staff_member_required(login_url=None)
@require_POST
def validate_staff_charge(request, staff_charge_id):
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	date_obj = timezone.now()

	staff_charge.validated = True
	staff_charge.updated = date_obj
	staff_charge.validated_date = date_obj
	staff_charge.save()
	return HttpResponse()


#@staff_member_required(login_url=None)
@login_required
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	date_obj = timezone.now()

	usage_event.validated = True
	usage_event.updated = date_obj
	usage_event.validated_date = date_obj
	usage_event.save()
	return HttpResponse()


#@staff_member_required(login_url=None)
@login_required
@require_POST
def validate_area_access_record(request, area_access_record_id):
	area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
	date_obj = timezone.now()

	area_access_record.validated = True
	area_access_record.updated = date_obj
	area_access_record.validated_date = date_obj
	area_access_record.save()
	return HttpResponse()


#@staff_member_required(login_url=None)
@login_required
@require_POST
def validate_consumable_withdraw(request, consumable_withdraw_id):
	consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
	date_obj = timezone.now()

	consumable_withdraw.validated = True
	consumable_withdraw.updated = date_obj
	consumable_withdraw.validated_date = date_obj
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
		'users': User.objects.filter(is_active=True).distinct(),
	}
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	dictionary['staff_charge'] = staff_charge
	#dictionary['scp'] = StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)
	dictionary['scp'] = StaffChargeProject.objects.filter(staff_charge=staff_charge)
	return render(request, 'remote_work_contest.html', dictionary)


@login_required
@require_POST
def contest_usage_event(request, usage_event_id):
	dictionary = {
		'contest_type': 'Usage Event',
		'staff_charge': None,
		'area_access_record': None,
		'consumable_withdraw': None,
		'users': User.objects.filter(is_active=True).distinct(),
	}
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	dictionary['usage_event'] = usage_event
	dictionary['uep'] = UsageEventProject.objects.filter(usage_event=usage_event, active_flag=True)
	if request.user.is_superuser:
		tools = Tool.objects.all()
	else:
		tools = request.user.qualifications.all()
	dictionary['tools'] = tools
	return render(request, 'remote_work_contest.html', dictionary)


@login_required
@require_POST
def contest_area_access_record(request, area_access_record_id):
	dictionary = {
		'contest_type': 'Area Access Record',
		'staff_charge': None,
		'usage_event': None,
		'consumable_withdraw': None,
		'users': User.objects.filter(is_active=True).distinct(),
	}
	area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
	dictionary['area_access_record'] = area_access_record
	dictionary['aarp'] = AreaAccessRecordProject.objects.filter(area_access_record=area_access_record, active_flag=True)
	if request.user.is_superuser:
		areas = Area.objects.all()
	else:
		areas = Area.objects.filter(id__in=request.user.physical_access_levels.all().values_list('area', flat=True))
	dictionary['areas'] = areas
	return render(request, 'remote_work_contest.html', dictionary)


@login_required
@require_POST
def contest_consumable_withdraw(request, consumable_withdraw_id):
	dictionary = {
		'contest_type': 'Consumable Withdraw',
		'staff_charge': None,
		'usage_event': None,
		'area_access_record': None,
		'users': User.objects.filter(is_active=True).distinct(),
	}
	consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
	dictionary['consumable_withdraw'] = consumable_withdraw

	consumables = Consumable.objects.all()
	dictionary['consumables'] = consumables
	return render(request, 'remote_work_contest.html', dictionary)


def is_valid_field(field):
	return search("^(proposed|original)__(area|consumable|quantity|chosen_user|chosen_project|project_percent|tool_id|start|end|sample_num|cost_per_sample)__(newentry_)?[0-9_]+$", field) is not None

@login_required
@require_POST
def save_contest(request):
	logger = getLogger(__name__)

	contest_type = request.POST.get("contest_type")
	no_charge_flag = request.POST.get("no_charge_flag")
	submission = {}
	deletion = {}

	for key, value in request.POST.items():
		if is_valid_field(key):
			flag, field, id = key.split("__")
			try:
				id = int(id)
			except:
				id = str(id)

			if id not in submission:
				submission[id] = {}
				submission[id][field] = {}

			if field not in submission[id]:
				submission[id][field] = {}

			submission[id][field][flag] = value
		else:
			if key[:15] == "delete_customer":
				flag, id = key.split("__")

				try:
					id = int(id)
				except:
					id = str(id)

				if id not in deletion:
					deletion[id] = True

	logger.error(str(submission))
	logger.error(str(deletion))
	
	if contest_type == "Staff Charge":
		staff_charge_id = request.POST.get("staff_charge_id")
		staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
		staff_charge.contested = True

		# "resolve" any previous contests for this item
		for c in staff_charge.contest_record.all():
			c.contest_resolution = True
			c.contest_resolved = True
			c.contest_resolved_date = timezone.now()
			c.save()

		description = request.POST.get("contest_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		# create ContestTransaction record
		contest_transaction = ContestTransaction.objects.create(content_object=staff_charge, contest_description=description, contested_date=timezone.now())

		staff_charge.updated = timezone.now()
		staff_charge.save()

		staff_charge_type = ContentType.objects.get_for_model(staff_charge)

		if no_charge_flag:
			contest_transaction.no_charge_flag = True
			contest_transaction.save()
		else:
			for id in submission:
				idstr = str(id)
				
				if idstr[:8] == "newentry":
					fg = str(contest_transaction.id) + "_" + idstr[9:]
					for field in submission[id]:
						ContestTransactionNewData.objects.create(content_type=staff_charge_type, contest_transaction=contest_transaction, field_name=field, field_value=submission[id][field]["proposed"], field_group=fg)
				else:
					if idstr in deletion:
						if deletion[idstr]:		# mark the record to deactive the scp
							ContestTransactionData.objects.create(content_object=StaffChargeProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("start", "end"):
										content_object = StaffCharge.objects.get(id=id)
										ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						else:
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("start", "end"):
										content_object = StaffCharge.objects.get(id=id)
									else:
										content_object = StaffChargeProject.objects.get(id=id)
									ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						del deletion[idstr]
					else:
						for field in submission[id]:
							if submission[id][field]["proposed"] != submission[id][field]["original"]:
								if field in ("start", "end"):
									content_object = StaffCharge.objects.get(id=id)
								else:
									content_object = StaffChargeProject.objects.get(id=id)
								ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

			for id in deletion:
				if deletion[id]:
					ContestTransactionData.objects.create(content_object=StaffChargeProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")


	if contest_type == "Usage Event":
		usage_event_id = request.POST.get("usage_event_id")
		usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
		usage_event.contested = True

		# "resolve" any previous contests
		for c in usage_event.contest_record.all():
			c.contest_resolution = True
			c.contest_resolved = True
			c.contest_resolved_date = timezone.now()
			c.save()

		description = request.POST.get("contest_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		# create ContestTransaction record
		contest_transaction = ContestTransaction.objects.create(content_object=usage_event, contest_description=description, contested_date=timezone.now())

		usage_event.updated = timezone.now()
		usage_event.save()

		usage_event_type = ContentType.objects.get_for_model(usage_event)

		if no_charge_flag:
			contest_transaction.no_charge_flag = True
			contest_transaction.save()
		else:
			for id in submission:
				idstr = str(id)

				if idstr[:8] == "newentry":
					fg = str(contest_transaction.id) + "_" + idstr[9:]
					for field in submission[id]:
						ContestTransactionNewData.objects.create(content_type=usage_event_type, contest_transaction=contest_transaction, field_name=field, field_value=submission[id][field]["proposed"], field_group=fg)
				else:
					if idstr in deletion:
						if deletion[idstr]:
							ContestTransactionData.objects.create(content_object=UsageEventProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("tool_id", "start", "end"):
										content_object = UsageEvent.objects.get(id=id)
										ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						else:
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("tool_id", "start", "end"):
										content_object = UsageEvent.objects.get(id=id)
									else:
										content_object = UsageEventProject.objects.get(id=id)
									ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						del deletion[idstr]
					else:
						for field in submission[id]:
							if str(submission[id][field]["proposed"]) != str(submission[id][field]["original"]):
								if field in ("tool_id", "start", "end"):
									content_object = UsageEvent.objects.get(id=id)
								else:
									content_object = UsageEventProject.objects.get(id=id)
								ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

			for id in deletion:
				if deletion[id]:
					ContestTransactionData.objects.create(content_object=UsageEventProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")


	if contest_type == "Area Access Record":
		area_access_record_id = request.POST.get("area_access_record_id")
		area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
		area_access_record.contested = True

		# "resolve" any previous contests
		for c in area_access_record.contest_record.all():
			c.contest_resolution = True
			c.contest_resolved = True
			c.contest_resolved_date = timezone.now()
			c.save()

		description = request.POST.get("contest_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		# create ContestTransaction record
		contest_transaction = ContestTransaction.objects.create(content_object=area_access_record, contest_description=description, contested_date=timezone.now())

		area_access_record.updated = timezone.now()
		area_access_record.save()

		area_access_record_type = ContentType.objects.get_for_model(area_access_record)

		if no_charge_flag:
			contest_transaction.no_charge_flag = True
			contest_transaction.save()
		else:
			for id in submission:
				idstr = str(id)

				if idstr[:8] == "newentry":
					fg = str(contest_transaction.id) + "_" + idstr[9:]
					for field in submission[id]:
						ContestTransactionNewData.objects.create(content_type=area_access_record_type, contest_transaction=contest_transaction, field_name=field, field_value=submission[id][field]["proposed"], field_group=fg)
				else:
					if idstr in deletion:
						if deletion[idstr]:
							ContestTransactionData.objects.create(content_object=AreaAccessRecordProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("area", "start", "end"):
										content_object = AreaAccessRecord.objects.get(id=id)
										ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						else:
							for field in submission[id]:
								if submission[id][field]["proposed"] != submission[id][field]["original"]:
									if field in ("area", "start", "end"):
										content_object = AreaAccessRecord.objects.get(id=id)
									else:
										content_object = AreaAccessRecordProject.objects.get(id=id)
								ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])
						del deletion[idstr]
					else:
						for field in submission[id]:
							if submission[id][field]["proposed"] != submission[id][field]["original"]:
								if field in ("area", "start", "end"):
									content_object = AreaAccessRecord.objects.get(id=id)
								else:
									content_object = AreaAccessRecordProject.objects.get(id=id)
								ContestTransactionData.objects.create(content_object=content_object, contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

			for id in deletion:
				if deletion[id]:
					ContestTransactionData.objects.create(content_object=AreaAccessRecordProject.objects.get(id=id), contest_transaction=contest_transaction, field_name="delete", original_value="delete", proposed_value="delete")


	if contest_type == "Consumable Withdraw":
		consumable_withdraw_id = request.POST.get("consumable_withdraw_id")
		consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
		consumable_withdraw.contested = True

		# "resolve" any outstanding contests
		for c in consumable_withdraw.contest_record.all():
			c.contest_resolution = True
			c.contest_resolved = True
			c.contest_resolved_date = timezone.now()
			c.save()

		description = request.POST.get("contest_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		# create ContestTransaction record
		contest_transaction = ContestTransaction.objects.create(content_object=consumable_withdraw, contest_description=description, contested_date=timezone.now())

		consumable_withdraw.updated = timezone.now()
		consumable_withdraw.save()

		if no_charge_flag:
			contest_transaction.no_charge_flag = True
			contest_transaction.save()
		else:
			for id in submission:
				for field in submission[id]:
					if submission[id][field]["proposed"] != submission[id][field]["original"]:
						content_object = ConsumableWithdraw.objects.get(id=id)
						ContestTransactionData.objects.create(content_object=content_object,  contest_transaction=contest_transaction, field_name=field, original_value=submission[id][field]["original"], proposed_value=submission[id][field]["proposed"])

	return HttpResponseRedirect('/remote_work/')


@staff_member_required(login_url=None)
def review_contested_items(request):
	dictionary = {}

	if request.user.is_superuser:
		dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True)
		dictionary['usage'] = UsageEvent.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True)
		dictionary['area_access_records'] = AreaAccessRecord.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True)
		dictionary['consumable_withdraws'] = ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True)
	else:
		if request.user.is_staff:
			group_name="Core Admin"
			if request.user.groups.filter(name=group_name).exists():
				dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, staff_member__core_ids__in=request.user.core_ids.all(), active_flag=True).exclude(staff_member=request.user)
				dictionary['usage'] = UsageEvent.objects.filter(Q(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True), Q(tool__primary_owner=request.user) | Q(tool__backup_owners__in=[request.user])).exclude(operator=request.user)
				dictionary['area_access_records'] = AreaAccessRecord.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, staff_charge__staff_member__core_ids__in=request.user.core_ids.all(), area__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(staff_charge__staff_member=request.user)
				dictionary['consumable_withdraws'] = ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, consumable__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(customer=request.user)
			else:
				dictionary['usage'] = UsageEvent.objects.filter(Q(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True), Q(tool__primary_owner=request.user) | Q(tool__backup_owners__in=[request.user])).exclude(operator=request.user)
				dictionary['consumable_withdraws'] = ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, consumable__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(customer=request.user)
				dictionary['area_access_records'] = AreaAccessRecord.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, staff_charge=None, area__core_id__in=request.user.core_ids.all(), active_flag=True)
		
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
	dictionary['contest_type'] = "Staff Charge"

	"""
	form content creation
	"""
	staff_charge_type = ContentType.objects.get_for_model(staff_charge)
	contest_transaction = ContestTransaction.objects.get(content_type__pk=staff_charge_type.id, object_id=staff_charge.id, contest_resolved=False)
	dictionary['contest_transaction'] = contest_transaction
	df = DateFormat(staff_charge.start)
	dictionary['event_start_date'] = staff_charge.start  #df.format('Y-m-d h:i A')
	df = DateFormat(staff_charge.end)
	dictionary['event_end_date'] = staff_charge.end  #df.format('Y-m-d h:i A')
	if ContestTransactionData.objects.filter(content_type__pk=staff_charge_type.id, object_id=staff_charge.id, contest_transaction=contest_transaction, field_name="start").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=staff_charge_type.id, object_id=staff_charge.id, contest_transaction=contest_transaction, field_name="start")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_start_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_start_date'] = None
	if ContestTransactionData.objects.filter(content_type__pk=staff_charge_type.id, object_id=staff_charge.id, contest_transaction=contest_transaction, field_name="end").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=staff_charge_type.id, object_id=staff_charge.id, contest_transaction=contest_transaction, field_name="end")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_end_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_end_date'] = None
	if StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True).exists():
		project_data = {}
		staff_charge_projects = StaffChargeProject.objects.filter(staff_charge=staff_charge, active_flag=True)
		dictionary['staff_charge_projects'] = staff_charge_projects
	
		# process records to enable a single dictionary entry for each result
		for scp in staff_charge_projects:
			scp_type = ContentType.objects.get_for_model(scp)
			if scp.id not in project_data:
				project_data[scp.id] = {}
				project_data[scp.id]["field_names"] = StaffChargeProject._meta.get_fields(True,True)
			for fn in StaffChargeProject._meta.get_fields(True,True):
				if fn.name not in project_data[scp.id] and not fn.is_relation:
					project_data[scp.id][fn.name] = getattr(scp, fn.name)
				elif fn.name not in project_data[scp.id] and fn.name in ("customer","project"):
					project_data[scp.id][fn.name] = getattr(scp, fn.name)
					if fn.name == "customer":
						project_data[scp.id]["original_customer"] = getattr(scp, fn.name)
						project_data[scp.id]["original_customer_id"] = int(getattr(scp, fn.name).id)

					if fn.name == "project":
						project_data[scp.id]["original_project"] = getattr(scp, fn.name)
						project_data[scp.id]["original_project_id"] = int(getattr(scp, fn.name).id)

			contest_data = None
			if ContestTransactionData.objects.filter(content_type__pk=scp_type.id, object_id=scp.id).exists():
				contest_data =  ContestTransactionData.objects.filter(content_type__pk=scp_type.id, object_id=scp.id)
			if contest_data:
				for cd in contest_data:
					if cd.field_name == "delete":
						project_data[scp.id]["delete_flag"] = True

					if cd.field_name == "chosen_user":
						project_data[scp.id]["proposed_customer"] = User.objects.get(id=int(cd.proposed_value))
						project_data[scp.id]["proposed_customer_id"] = int(cd.proposed_value)

					if cd.field_name == "chosen_project":
						project_data[scp.id]["proposed_project"] = Project.objects.get(id=int(cd.proposed_value))
						project_data[scp.id]["proposed_project_id"] = int(cd.proposed_value)

					if cd.field_name == "project_percent":
						project_data[scp.id]["proposed_project_percent"] = cd.proposed_value

			if "delete_flag" not in project_data[scp.id]:
				project_data[scp.id]["delete_flag"] = False

		dictionary['project_data'] = project_data
	else:
		dictionary['staff_charge_projects'] = None
		dictionary['project_data'] = None

	if ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction).exists():
		newdata = {}

		for ctnd in ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction):
			if ctnd.field_group not in newdata:
				newdata[ctnd.field_group] = {}
			if ctnd.field_name == "project_percent":
				newdata[ctnd.field_group][ctnd.field_name] = ctnd.field_value
			if ctnd.field_name == "chosen_user":
				newdata[ctnd.field_group][ctnd.field_name] = User.objects.get(id=int(ctnd.field_value))
			if ctnd.field_name == "chosen_project":
				newdata[ctnd.field_group][ctnd.field_name] = Project.objects.get(id=int(ctnd.field_value))

		dictionary['newdata'] = newdata
	
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
	dictionary['contest_type'] = "Usage Event"

	# as an alternative to the clunky template-based generation, create the HTML here and pass as a string
	# This string will contain the form elements, but in order to easily preserve the csrf_token the form 
	# will be defined in the template
	usage_event_type = ContentType.objects.get_for_model(usage_event)
	contest_transaction = ContestTransaction.objects.get(content_type__pk=usage_event_type.id, object_id=usage_event.id, contest_resolved=False)
	dictionary['contest_transaction'] = contest_transaction
	df = DateFormat(usage_event.start)
	dictionary['event_start_date'] = usage_event.start  #df.format('Y-m-d h:i A')
	df = DateFormat(usage_event.end)
	dictionary['event_end_date'] = usage_event.end  #df.format('Y-m-d h:i A')
	if ContestTransactionData.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, contest_transaction=contest_transaction, field_name="start").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, contest_transaction=contest_transaction, field_name="start")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_start_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_start_date'] = None
	if ContestTransactionData.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, contest_transaction=contest_transaction, field_name="end").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=usage_event_type.id, object_id=usage_event.id, contest_transaction=contest_transaction, field_name="end")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_end_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_end_date'] = None
	if UsageEventProject.objects.filter(usage_event=usage_event, active_flag=True).exists():
		project_data = {}
		usage_event_projects = UsageEventProject.objects.filter(usage_event=usage_event, active_flag=True)
		dictionary['usage_event_projects'] = usage_event_projects

		for uep in usage_event_projects:
			uep_type = ContentType.objects.get_for_model(uep)
			if uep.id not in project_data:
				project_data[uep.id] = {}
			for fn in UsageEventProject._meta.get_fields(True,True):
				if fn.name not in project_data[uep.id] and not fn.is_relation:
					project_data[uep.id][fn.name] = getattr(uep, fn.name)
				elif fn.name not in project_data[uep.id] and fn.name in ("customer","project"):
					project_data[uep.id][fn.name] = getattr(uep, fn.name)

					if fn.name == "customer":
						project_data[uep.id]["original_customer"] = getattr(uep, fn.name)
						project_data[uep.id]["original_customer_id"] = int(getattr(uep, fn.name).id)

					if fn.name == "project":
						project_data[uep.id]["original_project"] = getattr(uep, fn.name)
						project_data[uep.id]["original_project_id"] = int(getattr(uep, fn.name).id)

			contest_data = None
			if ContestTransactionData.objects.filter(content_type__pk=uep_type.id, object_id=uep.id).exists():
				contest_data =  ContestTransactionData.objects.filter(content_type__pk=uep_type.id, object_id=uep.id)
			if contest_data:
				for cd in contest_data:
					if cd.field_name == "delete":
						project_data[uep.id]["delete_flag"] = True

					if cd.field_name == "chosen_user":
						project_data[uep.id]["proposed_customer"] = User.objects.get(id=int(cd.proposed_value))
						project_data[uep.id]["proposed_customer_id"] = int(cd.proposed_value)

					if cd.field_name == "chosen_project":
						project_data[uep.id]["proposed_project"] = Project.objects.get(id=int(cd.proposed_value))
						project_data[uep.id]["proposed_project_id"] = int(cd.proposed_value)

					if cd.field_name == "project_percent":
						project_data[uep.id]["proposed_project_percent"] = cd.proposed_value

					if cd.field_name == "sample_num":
						project_data[uep.id]["proposed_sample_num"] = int(cd.proposed_value)

					if cd.field_name == "cost_per_sample":
						project_data[uep.id]["proposed_cost_per_sample"] = cd.proposed_value

			if "delete_flag" not in project_data[uep.id]:
				project_data[uep.id]["delete_flag"] = False

		dictionary['project_data'] = project_data
	else:
		dictionary['usage_event_projects'] = None
		dictionary['project_data'] = None


	if ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction).exists():
		newdata = {}

		for ctnd in ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction):
			if ctnd.field_group not in newdata:
				newdata[ctnd.field_group] = {}
			if ctnd.field_name == "project_percent":
				newdata[ctnd.field_group][ctnd.field_name] = ctnd.field_value
			if ctnd.field_name == "chosen_user":
				newdata[ctnd.field_group][ctnd.field_name] = User.objects.get(id=int(ctnd.field_value))
			if ctnd.field_name == "chosen_project":
				newdata[ctnd.field_group][ctnd.field_name] = Project.objects.get(id=int(ctnd.field_value))
			if ctnd.field_name == "sample_num":
				newdata[ctnd.field_group][ctnd.field_name] = ctnd.field_value
			if ctnd.field_name == "cost_per_sample":
				newdata[ctnd.field_group][ctnd.field_name] = ctnd.field_value

		dictionary['newdata'] = newdata

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
	dictionary['contest_type'] = "Area Access Record"

	aar_type = ContentType.objects.get_for_model(area_access_record)
	contest_transaction = ContestTransaction.objects.get(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_resolved=False)
	dictionary['contest_transaction'] = contest_transaction
	df = DateFormat(area_access_record.start)
	dictionary['event_start_date'] = area_access_record.start  #df.format('Y-m-d h:i A')
	df = DateFormat(area_access_record.end)
	dictionary['event_end_date'] = area_access_record.end  #df.format('Y-m-d h:i A')
	if ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="area").exists():
		dictionary['proposed_area'] = Area.objects.get(id=int(ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="area")[0].proposed_value))
	if ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="start").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="start")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_start_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_start_date'] = None
	if ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="end").exists():
		date_obj = datetime.strptime(ContestTransactionData.objects.filter(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_transaction=contest_transaction, field_name="end")[0].proposed_value, '%Y-%m-%d %H:%M:%S')
		df = DateFormat(date_obj)
		dictionary['proposed_event_end_date'] = df.format('Y-m-d h:i A')
	else:
		dictionary['proposed_event_end_date'] = None
	if AreaAccessRecordProject.objects.filter(area_access_record=area_access_record, active_flag=True).exists():
		project_data = {}
		area_access_record_projects = AreaAccessRecordProject.objects.filter(area_access_record=area_access_record, active_flag=True)
		dictionary['area_access_record_projects'] = area_access_record_projects

		for aarp in area_access_record_projects:
			aarp_type = ContentType.objects.get_for_model(aarp)
			if aarp.id not in project_data:
				project_data[aarp.id] = {}
			for fn in AreaAccessRecordProject._meta.get_fields(True,True):
				if fn.name not in project_data[aarp.id] and not fn.is_relation:
					project_data[aarp.id][fn.name] = getattr(aarp, fn.name)
				elif fn.name not in project_data[aarp.id] and fn.name in ("customer","project"):
					project_data[aarp.id][fn.name] = getattr(aarp, fn.name)

					if fn.name == "customer":
						project_data[aarp.id]["original_customer"] = getattr(aarp, fn.name)
						project_data[aarp.id]["original_customer_id"] = int(getattr(aarp, fn.name).id)

					if fn.name == "project":
						project_data[aarp.id]["original_project"] = getattr(aarp, fn.name)
						project_data[aarp.id]["original_project_id"] = int(getattr(aarp, fn.name).id)

			contest_data = None
			if ContestTransactionData.objects.filter(content_type__pk=aarp_type.id, object_id=aarp.id).exists():
				contest_data =  ContestTransactionData.objects.filter(content_type__pk=aarp_type.id, object_id=aarp.id)
			if contest_data:
				for cd in contest_data:
					if cd.field_name == "delete":
						project_data[aarp.id]["delete_flag"] = True

					if cd.field_name == "chosen_user":
						project_data[aarp.id]["proposed_customer"] = User.objects.get(id=int(cd.proposed_value))
						project_data[aarp.id]["proposed_customer_id"] = int(cd.proposed_value)

					if cd.field_name == "chosen_project":
						project_data[aarp.id]["proposed_project"] = Project.objects.get(id=int(cd.proposed_value))
						project_data[aarp.id]["proposed_project_id"] = int(cd.proposed_value)

					if cd.field_name == "project_percent":
						project_data[aarp.id]["proposed_project_percent"] = cd.proposed_value

			if "delete_flag" not in project_data[aarp.id]:
				project_data[aarp.id]["delete_flag"] = False

		dictionary['project_data'] = project_data
	else:
		dictionary['area_access_record_projects'] = None
		dictionary['project_data'] = None

	if ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction).exists():
		newdata = {}

		for ctnd in ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction):
			if ctnd.field_group not in newdata:
				newdata[ctnd.field_group] = {}
			if ctnd.field_name == "project_percent":
				newdata[ctnd.field_group][ctnd.field_name] = ctnd.field_value
			if ctnd.field_name == "chosen_user":
				newdata[ctnd.field_group][ctnd.field_name] = User.objects.get(id=int(ctnd.field_value))
			if ctnd.field_name == "chosen_project":
				newdata[ctnd.field_group][ctnd.field_name] = Project.objects.get(id=int(ctnd.field_value))

		dictionary['newdata'] = newdata

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
	dictionary['contest_type'] = "Consumable Withdraw"

	c_type = ContentType.objects.get_for_model(consumable_withdraw)
	contest_transaction = ContestTransaction.objects.get(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_resolved=False)
	dictionary['contest_transaction'] = contest_transaction
	if ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="consumable").exists():
		dictionary['proposed_consumable'] = Consumable.objects.get(id=int(ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="consumable")[0].proposed_value))
	else:
		dictionary['proposed_consumable'] = None
	if ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="quantity").exists():
		dictionary['proposed_quantity'] = ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="quantity")[0].proposed_value
	else:
		dictionary['proposed_quantity'] = None
	if ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="chosen_user").exists():
		dictionary['proposed_customer'] = User.objects.filter(id=int(ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="chosen_user")[0].proposed_value))
	else:
		dictionary['proposed_customer'] = None
	if ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="chosen_project").exists():
		dictionary['proposed_project'] = Project.objects.filter(id=int(ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="chosen_project")[0].proposed_value))
	else:
		dictionary['proposed_project'] = None
	if ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="project_percent").exists():
		dictionary['proposed_percent'] = ContestTransactionData.objects.filter(content_type__pk=c_type.id, object_id=consumable_withdraw.id, contest_transaction=contest_transaction, field_name="project_percent")[0].proposed_value
	else:
		dictionary['proposed_percent'] = None

	return render(request, 'remote_work_contest_resolve.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def save_contest_resolution(request):
	contest_type = request.POST.get("contest_type")
	contest_resolved = request.POST.get("resolve_contest")
	contest_transaction = None
	changes = None
	no_charge_flag = request.POST.get("no_charge_transaction", None)

	if contest_type == "Staff Charge":
		staff_charge_id = request.POST.get("staff_charge_id")
		staff_charge = StaffCharge.objects.get(id=staff_charge_id)
		sc_type = ContentType.objects.get_for_model(staff_charge)
		contest_transaction = ContestTransaction.objects.get(content_type__pk=sc_type.id, object_id=staff_charge.id, contest_resolved=False)

	if contest_type == "Usage Event":
		usage_event_id = request.POST.get("usage_event_id")
		usage_event = UsageEvent.objects.get(id=usage_event_id)
		ue_type = ContentType.objects.get_for_model(usage_event)
		contest_transaction = ContestTransaction.objects.get(content_type__pk=ue_type.id, object_id=usage_event.id, contest_resolved=False)

	if contest_type == "Area Access Record":
		area_access_record_id = request.POST.get("area_access_record_id")
		area_access_record = AreaAccessRecord.objects.get(id=area_access_record_id)
		aar_type = ContentType.objects.get_for_model(area_access_record)
		contest_transaction = ContestTransaction.objects.get(content_type__pk=aar_type.id, object_id=area_access_record.id, contest_resolved=False)

	if contest_type == "Consumable Withdraw":
		consumable_withdraw_id = request.POST.get("consumable_withdraw_id")
		consumable_withdraw = ConsumableWithdraw.objects.get(id=consumable_withdraw_id)
		cw_type = ContentType.objects.get_for_model(consumable_withdraw)
		contest_transaction = ContestTransaction.objects.get(content_type__pk=cw_type.id, object_id=consumable_withdraw.id, contest_resolved=False)

	if contest_resolved == "1":
		# admin has accepted change, update appopriate records and set base transaction validated to True
		if contest_type == "Staff Charge":
			changes = ContestTransactionData.objects.filter(contest_transaction=contest_transaction)
			additions = ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction)
			staff_charge.validated = True
			staff_charge.validated_date = timezone.now()
			staff_charge.contested = False
			staff_charge.updated = timezone.now()
			if no_charge_flag:
				if int(no_charge_flag) == 1:
					staff_charge.no_charge_flag = True

					for scp in staff_charge.staffchargeproject_set.all():
						scp.no_charge_flag = True
						scp.save()
			staff_charge.save()


		if contest_type == "Usage Event":
			changes = ContestTransactionData.objects.filter(contest_transaction=contest_transaction)
			additions = ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction)
			usage_event.validated = True
			usage_event.validated_date = timezone.now()
			usage_event.contested = False
			usage_event.updated = timezone.now()
			if no_charge_flag:
				if int(no_charge_flag) == 1:
					usage_event.no_charge_flag = True

					for uep in usage_event.usageeventproject_set.all():
						uep.no_charge_flag = True
						uep.save()
			usage_event.save()


		if contest_type == "Area Access Record":
			changes = ContestTransactionData.objects.filter(contest_transaction=contest_transaction)
			additions = ContestTransactionNewData.objects.filter(contest_transaction=contest_transaction)
			area_access_record.validated = True
			area_access_record.validated_date = timezone.now()
			area_access_record.contested = False
			area_access_record.updated = timezone.now()
			if no_charge_flag:
				if int(no_charge_flag) == 1:
					area_access_record.no_charge_flag = True

					for aarp in area_access_record.areaaccessrecordproject_set.all():
						aarp.no_charge_flag = True
						aarp.save()
			area_access_record.save()


		if contest_type == "Consumable Withdraw":
			changes = ContestTransactionData.objects.filter(contest_transaction=contest_transaction)
			additions = None
			consumable_withdraw.validated = True
			consumable_withdraw.validated_date = timezone.now()
			consumable_withdraw.contested = False
			consumable_withdraw.updated = timezone.now()
			if no_charge_flag:
				if int(no_charge_flag) == 1:
					consumable_withdraw.no_charge_flag = True
			consumable_withdraw.save()


		contest_transaction.contest_resolved = True
		contest_transaction.contest_resolved_date = timezone.now()
		contest_transaction.contest_resolution = True

		if changes is not None:
			for c in changes:
				field_name = c.field_name

				if field_name == "delete":
					c.content_object.active_flag = False

				if field_name == "start":
					pv = parse_datetime(c.proposed_value)
					c.content_object.start = pv.astimezone(timezone.get_current_timezone())

				if field_name == "end":
					pv = parse_datetime(c.proposed_value)
					c.content_object.end = pv.astimezone(timezone.get_current_timezone())

				if field_name == "area":
					c.content_object.area = Area.objects.get(id=int(c.proposed_value))

				if field_name == "consumable":
					c.content_object.consumable = Consumable.objects.get(id=int(c.proposed_value))

				if field_name == "quantity":
					c.content_object.quantity = int(c.proposed_value)

				if field_name == "chosen_user":
					c.content_object.customer = User.objects.get(id=int(c.proposed_value))

				if field_name == "chosen_project":
					c.content_object.project = Project.objects.get(id=int(c.proposed_value))

				if field_name == "project_percent":
					c.content_object.project_percent = float(c.proposed_value)

				if field_name == "tool_id":
					c.content_object.tool = Tool.objects.get(id=int(c.proposed_value))

				if field_name == "cost_per_sample":
					c.content_object.cost_per_sample = float(c.proposed_value)

				if field_name == "sample_num":
					c.content_object.sample_num = int(c.proposed_value)

				if no_charge_flag is not None:
					if int(no_charge_flag) == 1:
						c.content_object.no_charge_flag = True

				c.content_object.updated = timezone.now()
				c.content_object.save()

		contest_transaction.save()

		if additions is not None:
			new_records = {}
			for a in additions:
				# create a dictionary to group the additions together based on field_group
				if a.field_group not in new_records:
					new_records[a.field_group] = {}
					new_records[a.field_group][a.field_name] = a.field_value
				if a.field_name not in new_records[a.field_group]:
					new_records[a.field_group][a.field_name] = a.field_value

			for key in new_records:

				if contest_type == "Staff Charge":
					content_object = StaffChargeProject()
					content_object.staff_charge = staff_charge

				if contest_type == "Usage Event":
					content_object = UsageEventProject()
					content_object.usage_event = usage_event

				if contest_type == "Area Access Record":
					content_object = AreaAccessRecordProject()
					content_object.area_access_record = area_access_record


				for fld,value in new_records[key].items():

					field_name = fld

					if field_name == "start":
						pv = parse_datetime(value)
						content_object.start = pv.astimezone(timezone.get_current_timezone())
	
					if field_name == "end":
						pv = parse_datetime(value)
						content_object.end = pv.astimezone(timezone.get_current_timezone())
	
					if field_name == "area":
						content_object.area = Area.objects.get(id=int(value))

					if field_name == "consumable":
						content_object.consumable = Consumable.objects.get(id=int(value))

					if field_name == "quantity":
						content_object.quantity = int(value)

					if field_name == "chosen_user":
						content_object.customer = User.objects.get(id=int(value))

					if field_name == "chosen_project":
						content_object.project = Project.objects.get(id=int(value))

					if field_name == "project_percent":
						content_object.project_percent = float(value)

					if field_name == "tool_id":
						content_object.tool = Tool.objects.get(id=int(value))

					if field_name == "cost_per_sample":
						content_object.cost_per_sample = float(value)

					if field_name == "sample_num":
						content_object.sample_num = int(value)

				content_object.updated = timezone.now()
				content_object.save()

	else:
		# resolve contest but flag as rejected so submitter has another chance to contest
		changes = None
		contest_transaction.contest_resolved = True
		contest_transaction.contest_resolved_date = timezone.now()
		contest_transaction.contest_resolution = False
		contest_transaction.contest_rejection_reason = request.POST.get("reject_contest_reason")
		contest_transaction.save()
		contest_transaction.content_object.contested = False
		contest_transaction.content_object.updated = timezone.now()
		contest_transaction.content_object.validated = False
		contest_transaction.content_object.save()


	return HttpResponseRedirect('/review_contested_items/')


@staff_member_required(login_url=None)
@require_GET
def contest_transaction_entry(request):
	entry_number = int(request.GET['entry_number'])
	cost_per_sample_run = int(request.GET['cost_per_sample_run'])
	return render(request, 'contest_transaction_entry.html', {'entry_number': entry_number, 'cost_per_sample_run': cost_per_sample_run })


def days_passed(dt):
	"""Return integer days between given date/datetime or None and today (local timezone)."""
	if dt is None:
		return None
	try:
		dt_date = dt.date()
	except Exception:
		dt_date = dt if isinstance(dt, date) else None
	if dt_date is None:
		return None
	today = timezone.localtime(timezone.now()).date()
	return (today - dt_date).days
