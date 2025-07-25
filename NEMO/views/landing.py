import requests

from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.http import HttpResponseRedirect

from NEMO.models import Alert, AreaAccessRecord, ConsumableWithdraw, LandingPageChoice, Reservation, Resource, StaffCharge, UsageEvent, User
from NEMO.views.alerts import delete_expired_alerts
from NEMO.views.area_access import able_to_self_log_in_to_area
from NEMO.views.notifications import delete_expired_notifications, get_notification_counts
from NEMO.views.remote_work import get_dummy_projects


@login_required
@require_GET
def landing(request):

	delete_expired_alerts()
	delete_expired_notifications()
	usage_events = UsageEvent.objects.filter(operator=request.user.id, end=None, active_flag=True).prefetch_related('tool', 'project')

	aar = request.user.area_access_record()
	if aar is not None:
		if usage_events:
			active_area_access = usage_events.filter(tool__requires_area_access=aar.area)
		else:
			active_area_access = False
	else:
		active_area_access = False

	contested_items = False
	if request.user.is_superuser:
		if UsageEvent.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, active_flag=True).exists() or StaffCharge.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, active_flag=True).exists() or AreaAccessRecord.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, active_flag=True).exists() or ConsumableWithdraw.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, active_flag=True).exists():
			contested_items = True
	else:
		if request.user.is_staff:
			group_name="Core Admin"
			if request.user.groups.filter(name=group_name).exists():
				if StaffCharge.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, staff_member__core_ids__in=request.user.core_ids.all(), active_flag=True).exclude(staff_member=request.user).exists() or UsageEvent.objects.filter(Q(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True), Q(tool__primary_owner=request.user) | Q(tool__backup_owners__in=[request.user])).exclude(operator=request.user).exists() or AreaAccessRecord.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, staff_charge__staff_member__core_ids__in=request.user.core_ids.all(), active_flag=True).exclude(staff_charge__staff_member=request.user).exists() or ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, consumable__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(customer=request.user).exists():
					contested_items = True
			else:
				if UsageEvent.objects.filter(Q(validated=False, contested=True, contest_record__contest_resolved=False, active_flag=True), Q(tool__primary_owner=request.user) | Q(tool__backup_owners__in=[request.user])).exclude(operator=request.user).exists() or ConsumableWithdraw.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, consumable__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(customer=request.user).exists() or AreaAccessRecord.objects.filter(validated=False, contested=True, contest_record__contest_resolved=False, area__core_id__in=request.user.core_ids.all(), active_flag=True).exclude(staff_charge__staff_member=request.user).exists():
					contested_items = True

	ue_count = UsageEvent.objects.filter(operator=request.user, validated=False, active_flag=True, end__isnull=False).count()
	sc_count = StaffCharge.objects.filter(staff_member=request.user, validated=False, active_flag=True, end__isnull=False).count()
	ar_count = AreaAccessRecord.objects.filter(user=request.user, validated=False, active_flag=True, end__isnull=False).count()
	cw_count = ConsumableWithdraw.objects.filter(validated=False, merchant=request.user, active_flag=True).count()

	validation_needed = False
	#if UsageEvent.objects.filter(operator=request.user, validated=False, active_flag=True).exists() or StaffCharge.objects.filter(staff_member=request.user, validated=False, active_flag=True).exists() or AreaAccessRecord.objects.filter(user=request.user, validated=False, active_flag=True).exists() or ConsumableWithdraw.objects.filter(validated=False, merchant=request.user, active_flag=True).exists():
	if ue_count > 0 or sc_count > 0 or ar_count > 0 or cw_count > 0:
		validation_needed = True
	else:
		validation_needed = False

	tools_in_use = [u.tool_id for u in usage_events]
	fifteen_minutes_from_now = timezone.now() + timedelta(minutes=15)
	landing_page_choices = LandingPageChoice.objects.all()
	if request.device == 'desktop':
		landing_page_choices = landing_page_choices.exclude(hide_from_desktop_computers=True)
	if request.device == 'mobile':
		landing_page_choices = landing_page_choices.exclude(hide_from_mobile_devices=True)
	if not request.user.is_staff and not request.user.is_superuser and not request.user.is_technician:
		landing_page_choices = landing_page_choices.exclude(hide_from_users=True)


	user_delegate = False
	if not request.user.groups.filter(name="Technical Staff").exists() and not request.user.groups.filter(name="Financial Admin").exists() and not request.user.groups.filter(name="PI").exists() and not request.user.is_superuser:
		if User.objects.filter(pi_delegates=request.user).exists():
			user_delegate = True


	dictionary = {
		'now': timezone.now(),
		'alerts': Alert.objects.filter(Q(user=None) | Q(user=request.user), debut_time__lte=timezone.now()),
		'usage_events': usage_events,
		'upcoming_reservations': Reservation.objects.filter(user=request.user.id, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False).exclude(tool_id__in=tools_in_use, start__lte=fifteen_minutes_from_now).order_by('start')[:3],
		'disabled_resources': Resource.objects.filter(available=False),
		'landing_page_choices': landing_page_choices,
		'notification_counts': get_notification_counts(request.user),
		'self_log_in': able_to_self_log_in_to_area(request.user),
		'active_area_access': active_area_access,
		'contested_items': contested_items,
		'validation_needed': validation_needed,
		'user_delegate': user_delegate,
		'ue_count': ue_count,
		'sc_count': sc_count,
		'ar_count': ar_count,
		'cw_count': cw_count,
	}
	return render(request, 'landing.html', dictionary)


@staff_member_required(login_url=None)
@require_http_methods(['GET','POST'])
def check_url(request):
	if request.method == "GET":
		return render(request, 'requester.html', {})
	else:
		url = request.POST.get("URL")
		resp = requests.get(url, timeout=3.0)

		dictionary = {
			'src': url,
			'postback': True,
			'response_text': resp.text,
		}
		return render(request, 'requester.html', dictionary)
