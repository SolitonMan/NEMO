from datetime import datetime, timedelta
from logging import getLogger
from re import search

from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import DateFormat
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, AreaAccessRecordProjectSample, Consumable, ConsumableWithdraw, ContestTransaction, ContestTransactionData, ContestTransactionNewData, Core, CreditCostCollector, LockBilling, Project, UsageEvent, UsageEventProject, UsageEventProjectSample, StaffCharge, StaffChargeProject, StaffChargeProjectSample, Tool, User, WorkOrder, WorkOrderTransaction
from NEMO.utilities import month_list, get_month_timeframe
from NEMO.views.staff_charges import month_is_locked, month_is_closed, get_billing_date_range


@staff_member_required(login_url=None)
@require_GET
def work_orders(request):
	work_orders = WorkOrder.objects.all().order_by('work_order_number')

	return render(request, 'work_orders/work_orders.html', {'work_orders': work_orders})

@staff_member_required(login_url=None)
@require_POST
def add_work_order(request):
	work_order_number = request.POST.get('work_order_number',None)
	notes = request.POST.get('notes',None)
	status = 1
	customer_id = int(request.POST.get('customer', None))
	work_order_type = int(request.POST.get('work_order_type', None))

	try:
		customer = User.objects.get(id=customer_id)

		work_order = WorkOrder.objects.create(work_order_number=work_order_number, notes=notes, status=status, customer=customer, work_order_type=work_order_type, created=timezone.now(), updated=timezone.now(), created_by=request.user)

		return render(request, 'work_orders/work_order_confirmation.html', {'work_order':work_order})

	except IntegrityError:
		msg = 'The work order number ' + str(work_order_number) + ' you submitted already exists.  Please choose a new value.'
		dictionary = {
			"work_order_number": work_order_number,
			"notes": notes,
			"customer_id": customer_id,
			"work_order_type": work_order_type,
			"error_msg": msg
		}

		projects = Project.objects.filter(active=True, end_date__gt=timezone.now())
		customers = User.objects.filter(is_active=True, projects__in=projects).distinct()

		dictionary["customers"] = customers

		return render(request, 'work_orders/create_work_order.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def create_work_order(request):
	projects = Project.objects.filter(active=True, end_date__gt=timezone.now())
	customers = User.objects.filter(is_active=True, projects__in=projects).distinct()

	return render(request, 'work_orders/create_work_order.html', {'customers':customers})

@staff_member_required(login_url=None)
@require_GET
def work_order_transactions(request, work_order_id):

	# define type ids for reference
	usage_event_tid = ContentType.objects.get_for_model(UsageEvent)
	usage_event_project_tid = ContentType.objects.get_for_model(UsageEventProject)
	staff_charge_tid = ContentType.objects.get_for_model(StaffCharge)
	staff_charge_project_tid = ContentType.objects.get_for_model(StaffChargeProject)
	area_access_record_tid = ContentType.objects.get_for_model(AreaAccessRecord)
	area_access_record_project_tid = ContentType.objects.get_for_model(AreaAccessRecordProject)
	consumable_withdraw_tid = ContentType.objects.get_for_model(ConsumableWithdraw)

	work_order = WorkOrder.objects.get(id=int(work_order_id))
	cost_per_sample_run = work_order.work_order_type == 2
	work_order_transactions = WorkOrderTransaction.objects.filter(work_order=work_order)

	dictionary = {}

	se_dates = get_billing_date_range()

	dstart = datetime.strptime(se_dates['start'], '%m/%d/%Y') - timedelta(days=92)

	# get tool transactions
	if cost_per_sample_run:
		usage_events = UsageEvent.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True)
	else:
		usage_events = UsageEvent.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True, cost_per_sample_run=False)
	uep = UsageEventProject.objects.filter(usage_event__in=usage_events, customer=work_order.customer, work_order_transaction=None)

	# filter by tool transactions already in a work order
	uep = uep.exclude(id__in=WorkOrderTransaction.objects.filter(content_type=usage_event_project_tid)).order_by('-usage_event__start')

	# get staff charges
	if cost_per_sample_run:
		staff_charges = StaffCharge.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True)
	else:
		staff_charges = StaffCharge.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True, cost_per_sample_run=False)
	scp = StaffChargeProject.objects.filter(staff_charge__in=staff_charges, customer=work_order.customer, work_order_transaction=None)

	# filter by staff charge transactions already in a work order
	scp = scp.exclude(id__in=WorkOrderTransaction.objects.filter(content_type=staff_charge_project_tid)).order_by('-staff_charge__start')

	# get area access records
	if cost_per_sample_run:
		area_access_records = AreaAccessRecord.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True)
	else:
		area_access_records = AreaAccessRecord.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True, validated=True, cost_per_sample_run=False)
	aarp = AreaAccessRecordProject.objects.filter(area_access_record__in=area_access_records, customer=work_order.customer, work_order_transaction=None)

	# filter by area access record transactions already in a work order
	aarp = aarp.exclude(id__in=WorkOrderTransaction.objects.filter(content_type=area_access_record_project_tid)).order_by('area_access_record__start')

	# get consumable withdraws
	if cost_per_sample_run:
		consumable_withdraws = ConsumableWithdraw.objects.filter(date__gte=dstart, customer=work_order.customer, active_flag=True, work_order_transaction=None, validated=True)
	else:
		consumable_withdraws = ConsumableWithdraw.objects.filter(date__gte=dstart, customer=work_order.customer, active_flag=True, work_order_transaction=None, validated=True, cost_per_sample_run=False)

	# filter by consumable withdraw transactions already in a work order
	consumable_withdraws = consumable_withdraws.exclude(id__in=WorkOrderTransaction.objects.filter(content_type=consumable_withdraw_tid)).order_by('-date')

	dictionary["usage_events"] = usage_events
	dictionary["usage_events_cid"] = usage_event_tid.id
	dictionary["uep"] = uep
	dictionary["usage_event_projects_cid"] = usage_event_project_tid.id
	dictionary["staff_charges"] = staff_charges
	dictionary["staff_charges_cid"] = staff_charge_tid.id
	dictionary["scp"] = scp
	dictionary["staff_charge_projects_cid"] = staff_charge_project_tid.id
	dictionary["area_access_records"] = area_access_records
	dictionary["area_access_records_cid"] = area_access_record_tid.id
	dictionary["aarp"] = aarp
	dictionary["area_access_record_projects_cid"] = area_access_record_project_tid.id
	dictionary["consumable_withdraws"] = consumable_withdraws
	dictionary["consumable_withdraws_cid"] = consumable_withdraw_tid.id
	dictionary["work_order"] = work_order
	dictionary["work_order_transactions"] = work_order_transactions

	return render(request, 'work_orders/work_order_transactions.html', dictionary)


@login_required
@require_POST
def add_work_order_transaction(request, work_order_id, content_type_id, object_id):
	work_order = WorkOrder.objects.get(id=int(work_order_id))
	content_type = ContentType.objects.get_for_id(int(content_type_id))
	content_object = content_type.get_object_for_this_type(id=int(object_id))

	try:
		work_order_transaction = WorkOrderTransaction.objects.create(content_object=content_object, work_order=work_order)
	except:
		pass

	return render(request, 'work_orders/work_order_transaction_confirmation.html', {'work_order_transaction':work_order_transaction})

@login_required
@require_POST
def remove_work_order_transaction(request, work_order_transaction_id):
	work_order_transaction = WorkOrderTransaction.objects.get(id=int(work_order_transaction_id))

	try:
		work_order_transaction.delete()
	except:
		pass

	return render(request, 'work_orders/work_order_transaction_confirmation.html', {'work_order_transaction':work_order_transaction})


@login_required
@require_POST
def update_work_order_status(request, work_order_id, status_id):
	try:
		work_order = WorkOrder.objects.get(id=int(work_order_id))
		work_order.status = int(status_id)
		work_order.updated = timezone.now()
		if int(status_id) == 0:
			work_order.closed = timezone.now()
		else:
			work_order.closed = None
		work_order.save()
	except:
		pass

	return render(request, 'work_orders/work_order_confirmation.html', {'work_order':work_order})


@login_required
@require_POST
def delete_work_order(request, work_order_id):
	work_orders = None
	work_order = WorkOrder.objects.get(id=int(work_order_id))
	error_msg = None

	try:
		if work_order.status != 2:
			work_order_transactions = WorkOrderTransaction.objects.filter(work_order=work_order)

			work_order_transactions.delete()
			work_order.delete()
		else:
			error_msg = "Could not delete work order number " + str(work_order.work_order_number) + " because it has already been processed.  Processed work orders cannot be deleted."
	except:
		error_msg = "Could not delete work order number " + str(work_order.work_order_number) + ".  Please try again, and reach out to LEOHelp@psu.edu if the problem persists."
	
	work_orders = WorkOrder.objects.all().order_by('work_order_number')

	return render(request, 'work_orders/work_orders.html', {'work_orders': work_orders, 'error_msg': error_msg})	
