from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.http import HttpResponseRedirect

from NEMO.models import ContactInformation, ContactInformationCategory
from NEMO.views.authentication import check_for_core


@login_required
@require_GET
def contact_staff(request):
	if check_for_core(request):
		return HttpResponseRedirect("/choose_core/")
	dictionary = {
		'categories': ContactInformationCategory.objects.all(),
		'people': ContactInformation.objects.all(),
	}
	return render(request, 'contact_staff.html', dictionary)
