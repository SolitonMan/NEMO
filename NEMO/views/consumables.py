from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET
from django.http import JsonResponse, HttpResponseRedirect

from NEMO.forms import ConsumableWithdrawForm
from NEMO.models import Consumable, ConsumableWithdraw, Core, User


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def consumables(request):
	form = ConsumableWithdrawForm(request.POST or None, initial={'quantity': 1})

	dictionary = {
		'users': User.objects.filter(is_active=True),
		'recent': ConsumableWithdraw.objects.filter(merchant=request.user).order_by('-date')[:10]
	}

	if request.user.is_superuser:
		dictionary['cores'] = Core.objects.all()
		dictionary['consumables'] = Consumable.objects.filter(visible=True).order_by('category', 'name')
	else:
		dictionary['active_core'] = request.session.get('active_core')
		dictionary['consumables'] = Consumable.objects.filter(visible=True, core_id=request.session.get('active_core_id')).order_by('category', 'name')

	if form.is_valid():
		withdraw = form.save(commit=False)
		withdraw.merchant = request.user
		withdraw.updated = timezone.now()
		withdraw.save()
		withdraw.consumable.quantity -= withdraw.quantity
		withdraw.consumable.save()
		dictionary['success'] = 'The withdraw for {} was successfully logged.'.format(withdraw.customer)
		form = ConsumableWithdrawForm(initial={'quantity': 1})
	else:
		if hasattr(form, 'cleaned_data') and 'customer' in form.cleaned_data:
			dictionary['projects'] = form.cleaned_data['customer'].active_projects()

	dictionary['form'] = form
	return render(request, 'consumables.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def get_consumables(request):
	core_id = request.GET.get('core_id')

	if core_id is not None and core_id != '':
		consumables = Consumable.objects.filter(visible=True, core_id=core_id).order_by('category', 'name')
	else:
		consumables = Consumable.objects.filter(visible=True).order_by('category', 'name')

	return JsonResponse(dict(consumables=list(consumables.values('id', 'category__name', 'name'))))
