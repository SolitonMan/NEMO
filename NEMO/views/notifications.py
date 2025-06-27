from datetime import timedelta

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q, CharField, Value
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.models import Core, UsageEvent, UsageEventProject, StaffCharge, StaffChargeProject, AreaAccessRecord, AreaAccessRecordProject, Consumable, ConsumableWithdraw, Reservation, ReservationProject, News, Notification, SafetyIssue, User, NotificationSchemeToolAction, Tool, Reservation


def delete_expired_notifications():
	Notification.objects.filter(expiration__lt=timezone.now()).delete()


def get_notifications(user, notification_type):
	content_type = ContentType.objects.get_for_model(notification_type)
	notifications = Notification.objects.filter(user=user, content_type=content_type)
	if notifications:
		notification_ids = list(notifications.values_list('object_id', flat=True))
		notifications.delete()
		return notification_ids
	else:
		return None


def get_notification_counts(user):
	counts = {}
	for t in Notification.Types.Choices:
		model = t[0]
		content_type = ContentType.objects.get(app_label='NEMO', model=model)
		counts[model] = Notification.objects.filter(user=user, content_type=content_type).count()
	return counts


def create_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	Notification.objects.filter(content_type=content_type, object_id=story.id).delete()  # Delete all existing notifications for this story, so we don't have multiple notifications for the same story
	users = User.objects.filter(is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread news story notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=story)


def delete_news_notification(story):
	content_type = ContentType.objects.get_for_model(News)
	Notification.objects.filter(content_type=content_type, object_id=story.id).delete()


def create_safety_notification(safety_issue):
	users = User.objects.filter(is_staff=True, is_active=True)
	expiration = timezone.now() + timedelta(days=30)  # Unread safety issue notifications always expire after 30 days
	for u in users:
		Notification.objects.create(user=u, expiration=expiration, content_object=safety_issue)


def delete_safety_notification(issue):
	content_type = ContentType.objects.get_for_model(SafetyIssue)
	Notification.objects.filter(content_type=content_type, object_id=issue.id).delete()


def notification_scheme_tool_action(request, msg=None):
	tools = Tool.objects.filter(Q(core_id__in=request.user.core_ids.all()) | Q(primary_owner=request.user) | Q(backup_owners__in=[request.user])).order_by('name')
	if NotificationSchemeToolAction.objects.filter(created_by=request.user).exists():
		schemes = NotificationSchemeToolAction.objects.filter(created_by=request.user)
	else:
		schemes = None

	dictionary = {
		'schemes': schemes,
		'tool_list': tools,
		'msg': msg,
	}
	return render(request, 'notifications/tool_action_scheme.html', dictionary)


@staff_member_required
@require_POST
def save_notification_scheme_tool_action(request):
	tool = get_object_or_404(Tool, id=int(request.POST.get("tool_select")))
	recipient = request.POST.get("recipient_select")
	event = request.POST.get("event_select")
	frequency = request.POST.get("frequency_select")

	scheme = NotificationSchemeToolAction()
	scheme.tool = tool
	scheme.recipient = recipient
	scheme.event = event
	scheme.frequency = frequency
	scheme.created = timezone.now()
	scheme.created_by = request.user
	scheme.updated = timezone.now()
	scheme.updated_by = request.user
	scheme.save()

	return notification_scheme_tool_action(request, "Scheme has been added")


@staff_member_required
@require_POST
def delete_notification_scheme(request):
	try:
		notification_scheme = get_object_or_404(NotificationSchemeToolAction, id=int(request.POST.get("scheme_id")))
		notification_scheme.delete()

		msg = "Scheme successfully deleted"

	except:
		msg = "Scheme wasn't deleted"

	return notification_scheme_tool_action(request,msg)
