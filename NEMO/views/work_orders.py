from datetime import datetime, timedelta
from logging import getLogger
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
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import Area, AreaAccessRecord, AreaAccessRecordProject, AreaAccessRecordProjectSample, Consumable, ConsumableWithdraw, ContestTransaction, ContestTransactionData, ContestTransactionNewData, Core, CreditCostCollector, LockBilling, Project, UsageEvent, UsageEventProject, UsageEventProjectSample, StaffCharge, StaffChargeProject, StaffChargeProjectSample, Tool, User, WorkOrder, WorkOrderTransaction
from NEMO.utilities import month_list, get_month_timeframe
from NEMO.views.staff_charges import month_is_locked, month_is_closed, get_billing_date_range


@staff_member_required(login_url=None)
@require_GET
def work_orders(request):
	work_orders = WorkOrder.objects.all()

	return render(request, 'work_orders/work_orders.html', {'work_orders': work_orders})

@staff_member_required(login_url=None)
@require_POST
def add_work_order(request):
	work_order_number = request.POST.get('work_order_number',None)
	notes = request.POST.get('notes',None)
	status = 1
	customer_id = int(request.POST.get('customer', None))

	customer = User.objects.get(id=customer_id)

	work_order = WorkOrder.objects.create(work_order_number=work_order_number, notes=notes, status=status, customer=customer, created=timezone.now(), updated=timezone.now())

	return render(request, 'work_orders/work_order_confirmation.html', {'work_order':work_order})

@staff_member_required(login_url=None)
@require_GET
def create_work_order(request):
	projects = Project.objects.filter(active=True, end_date__gt=timezone.now())
	customers = User.objects.filter(is_active=True, projects__in=projects)

	return render(request, 'work_orders/create_work_order.html', {'customers':customers})

@staff_member_required(login_url=None)
@require_GET
def work_order_transactions(request, work_order_id):
	work_order = WorkOrder.objects.get(id=int(work_order_id))

	work_order_transactions = WorkOrderTransaction.objects.filter(work_order=work_order)

	dictionary = {}

	se_dates = get_billing_date_range()

	#dstart = se_dates['start']

	#dc = dstart.split("/")

	#dy = dc[2]
	#dm = dc[0]
	#dd = dc[1]

	#if len(dm) == 1:
	#	dm = "0" + dm

	#if len(dd) == 1:
	#	dd = "0" + dd

	#dstart = dy + "-" + dm + "-" + dd

	dstart = datetime.strptime(se_dates['start'], '%m/%d/%Y') - timedelta(days=92)

	# get tool transactions
	usage_events = UsageEvent.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True)
	uep = UsageEventProject.objects.filter(usage_event__in=usage_events, customer=work_order.customer, work_order_transaction=None)

	# get staff charges
	staff_charges = StaffCharge.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True)
	scp = StaffChargeProject.objects.filter(staff_charge__in=staff_charges, customer=work_order.customer, work_order_transaction=None)

	# get area access records
	area_access_records = AreaAccessRecord.objects.filter(end__gte=dstart, customers__id=work_order.customer.id, active_flag=True)
	aarp = AreaAccessRecordProject.objects.filter(area_access_record__in=area_access_records, customer=work_order.customer, work_order_transaction=None)

	# get consumable withdraws
	consumable_withdraws = ConsumableWithdraw.objects.filter(date__gte=dstart, customer=work_order.customer, active_flag=True, work_order_transaction=None)

	dictionary["usage_events"] = usage_events
	dictionary["usage_events_cid"] = ContentType.objects.get_for_model(UsageEvent).id
	dictionary["uep"] = uep
	dictionary["usage_event_projects_cid"] = ContentType.objects.get_for_model(UsageEventProject).id
	dictionary["staff_charges"] = staff_charges
	dictionary["staff_charges_cid"] = ContentType.objects.get_for_model(StaffCharge).id
	dictionary["scp"] = scp
	dictionary["staff_charge_projects_cid"] = ContentType.objects.get_for_model(StaffChargeProject).id
	dictionary["area_access_records"] = area_access_records
	dictionary["area_access_records_cid"] = ContentType.objects.get_for_model(AreaAccessRecord).id
	dictionary["aarp"] = aarp
	dictionary["area_access_record_projects_cid"] = ContentType.objects.get_for_model(AreaAccessRecordProject).id
	dictionary["consumable_withdraws"] = consumable_withdraws
	dictionary["consumable_withdraws_cid"] = ContentType.objects.get_for_model(ConsumableWithdraw).id
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
		work_order.save()
	except:
		pass

	return render(request, 'work_orders/work_order_confirmation.html', {'work_order':work_order})


