from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import AreaAccessRecord, ConsumableWithdraw, UsageEvent, StaffCharge, User
from NEMO.utilities import month_list, get_month_timeframe


@staff_member_required(login_url=None)
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
	usage_events = UsageEvent.objects.filter(operator__is_staff=True, start__gte=first_of_the_month, start__lte=last_of_the_month)
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
		'staff_charges': staff_charges,
		'area_access_records': area_access_records,
		'consumable_withdraws': consumable_withdraws,
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


@staff_member_required(login_url=None)
@require_POST
def validate_usage_event(request, usage_event_id):
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	usage_event.validated = True
	usage_event.updated = timezone.now()
	usage_event.validated_date = timezone.now()
	usage_event.save()
	return HttpResponse()


@staff_member_required(login_url=None)
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
	}
	staff_charge = get_object_or_404(StaffCharge, id=staff_charge_id)
	dictionary['staff_charge'] = staff_charge
	return render(request, 'remote_work_contest.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def contest_usage_event(request, usage_event_id):
	dictionary = {
		'contest_type': 'Usage Event',
		'staff_charge': None,
		'area_access_record': None,
		'consumable_withdraw': None,
	}
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	dictionary['usage_event'] = usage_event
	return render(request, 'remote_work_contest.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def contest_area_access_record(request, area_access_record_id):
	dictionary = {
		'contest_type': 'Area Access Record',
		'staff_charge': None,
		'usage_event': None,
		'consumable_withdraw': None,
	}
	area_access_record = get_object_or_404(AreaAccessRecord, id=area_access_record_id)
	dictionary['area_access_record'] = area_access_record
	return render(request, 'remote_work_contest.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def contest_consumable_withdraw(request, consumable_withdraw_id):
	dictionary = {
		'contest_type': 'Consumable Withdraw',
		'staff_charge': None,
		'usage_event': None,
		'area_access_record': None,
	}
	consumable_withdraw = get_object_or_404(ConsumableWithdraw, id=consumable_withdraw_id)
	dictionary['consumable_withdraw'] = consumable_withdraw
	return render(request, 'remote_work_contest.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def save_contest(request):
	contest_type = request.POST.get("contest_type")
	
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
