from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import F, Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.models import UsageEvent, StaffCharge, User
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
	if operator:
		usage_events = usage_events.exclude(~Q(operator_id=operator.id))
		staff_charges = staff_charges.exclude(~Q(staff_member_id=operator.id))

	dictionary = {
		'usage': usage_events,
		'staff_charges': staff_charges,
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
def contest_staff_charge(request, staff_charge_id):
	dictionary = {
		'contest_type': 'Staff Charge',
		'usage_event': None,
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
	}
	usage_event = get_object_or_404(UsageEvent, id=usage_event_id)
	dictionary['usage_event'] = usage_event
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
		if description == "Other":
			description = request.POST.get("other_reason")
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
		if description == "Other":
			description = request.POST.get("other_reason")
		description += " DESCRIPTION:" + request.POST.get("contest_description")
		usage_event.contest_description = description
		usage_event.contested_date = timezone.now()
		usage_event.updated = timezone.now()
		usage_event.save()

	return HttpResponseRedirect('/remote_work/')

@staff_member_required(login_url=None)
def review_contested_items(request):
	dictionary = {}

	if request.user.is_superuser:
		dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_resolved=False)
		dictionary['usage'] = UsageEvent.objects.filter(validated=False, contested=True, contest_resolved=False)
	else:
		dictionary['staff_charges'] = StaffCharge.objects.filter(validated=False, contested=True, contest_resolved=False, staff_member__core_ids__in=request.user.core_ids.all())
		dictionary['usage'] = UsageEvent.objects.filter(validated=False, contested=True, contest_resolved=False, operator__core_ids__in=request.user.core_ids.all())

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
