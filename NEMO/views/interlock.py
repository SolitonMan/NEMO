import requests

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.models import InterlockCard, Interlock, Tool, User
from NEMO.scheduler import pulse_interlocks #, force_scheduler

@staff_member_required(login_url=None)
def interlocks(request):
	interlocks = Interlock.objects.all()

	dictionary = {
		'interlocks': interlocks,
	}

	return render(request, 'interlock/interlocks.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def pulse_interlock(request, interlock_id=None):
	try:
		ilock = Interlock.objects.get(id=interlock_id)
		ilock.pulse()
		return HttpResponse("The interlock was pulsed")
	except Interlock.DoesNotExist:
		return HttpResponeBadRequest("No interlock was found matching your request.")

@staff_member_required(login_url=None)
@require_GET
def pulse_all(request):
	pulse_interlocks()
	return HttpResponse("Pulse all interlocks initiated.  All interlocks not currently in use will be pulsed.")

@login_required
@require_GET
def open_interlock(request, interlock_id=None):
	try:
		ilock = Interlock.objects.get(id=interlock_id)
		ilock.unlock()
		return HttpResponse("The interlock was opened")
	except Interlock.DoesNotExist:
		return HttpResponeBadRequest("No interlock was found matching your request.")



"""
@staff_member_required(login_url=None)
def force_scheduler(request):
	if request.user.is_superuser:
		force_scheduler(request)
		HttpResponseRedirect(reverse('landing'))
"""
