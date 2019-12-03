from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from django.http import HttpResponseRedirect

from NEMO.models import Alert, AreaAccessRecord, ConsumableWithdraw, LandingPageChoice, Reservation, Resource, StaffCharge, UsageEvent
from NEMO.views.alerts import delete_expired_alerts
from NEMO.views.area_access import able_to_self_log_in_to_area
from NEMO.views.notifications import delete_expired_notifications, get_notificaiton_counts


@login_required
@require_GET
def landing(request):

	delete_expired_alerts()
	delete_expired_notifications()
	usage_events = UsageEvent.objects.filter(operator=request.user.id, end=None).prefetch_related('tool', 'project')

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
		if UsageEvent.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False).exists() or StaffCharge.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False).exists() or AreaAccessRecord.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False).exists() or ConsumableWithdraw.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False).exists():
			contested_items = True
	else:
		if UsageEvent.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, operator__core_ids__in=request.user.core_ids.all()).exists() or StaffCharge.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, staff_member__core_ids__in=request.user.core_ids.all()).exists() or AreaAccessRecord.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, staff_charge__staff_member__core_ids__in=request.user.core_ids.all()).exists() or ConsumableWithdraw.objects.filter(contested=True, validated=False, contest_record__contest_resolved=False, merchant__core_ids__in=request.user.core_ids.all()).exists():
			contested_items = True


	if UsageEvent.objects.filter(operator=request.user, validated=False, contested=False).exists() or StaffCharge.objects.filter(staff_member=request.user, validated=False, contested=False).exists():
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
	dictionary = {
		'now': timezone.now(),
		'alerts': Alert.objects.filter(Q(user=None) | Q(user=request.user), debut_time__lte=timezone.now()),
		'usage_events': usage_events,
		'upcoming_reservations': Reservation.objects.filter(user=request.user.id, end__gt=timezone.now(), cancelled=False, missed=False, shortened=False).exclude(tool_id__in=tools_in_use, start__lte=fifteen_minutes_from_now).order_by('start')[:3],
		'disabled_resources': Resource.objects.filter(available=False),
		'landing_page_choices': landing_page_choices,
		'notification_counts': get_notificaiton_counts(request.user),
		'self_log_in': able_to_self_log_in_to_area(request.user),
		'active_area_access': active_area_access,
		'contested_items': contested_items,
		'validation_needed': validation_needed,
	}
	return render(request, 'landing.html', dictionary)
