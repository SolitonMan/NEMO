from logging import getLogger

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date, parse_datetime
from django.views.decorators.http import require_POST, require_http_methods

from NEMO.forms import AlertForm
from NEMO.models import Alert

logger = getLogger(__name__)

@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def alerts(request):
	alert_id = request.GET.get('alert_id') or request.POST.get('alert_id')
	try:
		alert = Alert.objects.get(id=alert_id)
	except:
		alert = None
	if request.method == 'GET':
		form = AlertForm(instance=alert)
	elif request.method == 'POST':
#		form = AlertForm(data=request.POST, instance=alert)

#		logger.error(str(form))

		title = request.POST.get('title')
		contents = request.POST.get('contents')
		debut_time = request.POST.get('debut_time')
		expiration_time = request.POST.get('expiration_time')

		logger.error(str(title))
		logger.error(str(contents))
		logger.error(str(debut_time))
		logger.error(str(expiration_time))

		if debut_time == '' or debut_time is None:
			debut_time = timezone.now()
		else:
			debut_time = parse_datetime(str(debut_time))
			debut_time = debut_time.astimezone(timezone.get_current_timezone())

		if expiration_time is not None and expiration_time != '':
			expiration_time = parse_datetime(str(expiration_time))
			expiration_time = expiration_time.astimezone(timezone.get_current_timezone())
		else:
			expiration_time = None

		if not alert:
			alert = Alert()

		alert.title = title
		alert.contents = contents
		alert.debut_time = debut_time
		if expiration_time:	
			alert.expiration_time = expiration_time

		alert.save()

		form = AlertForm()

	else:
		form = AlertForm()
	dictionary = {
		'form': form,
		'editing': True if form.instance.id else False,
		'alerts': Alert.objects.filter(user=None)
	}
	#delete_expired_alerts()
	return render(request, 'alerts.html', dictionary)


@login_required
@require_POST
def delete_alert(request, alert_id):
	try:
		alert = get_object_or_404(Alert, id=alert_id)
		if alert.user == request.user:  # Users can delete their own alerts
			alert.delete()
		elif alert.user is None and request.user.is_staff:  # Staff can delete global alerts
			alert.delete()
	except Http404:
		pass
	return redirect(request.META.get('HTTP_REFERER', 'landing'))


def delete_expired_alerts():
	Alert.objects.filter(expiration_time__lt=timezone.now()).delete()
