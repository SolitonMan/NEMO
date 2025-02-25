from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_GET
from django.http import HttpResponse, JsonResponse, HttpResponseRedirect

from NEMO.forms import ConsumableWithdrawForm, ConsumableOrderForm, ConsumableOrderItemFormSet
from NEMO.models import Consumable, ConsumableWithdraw, Core, User, ConsumableOrder, ConsumableOrderItem, Tool


@staff_member_required(login_url=None)
@require_http_methods(['GET', 'POST'])
def consumables(request):
	form = ConsumableWithdrawForm(request.POST or None, initial={'quantity': 1})

	dictionary = {
		'users': User.objects.filter(is_active=True),
		'recent': ConsumableWithdraw.objects.filter(merchant=request.user, active_flag=True).order_by('-date')[:10]
	}

	if request.user.is_superuser:
		dictionary['cores'] = Core.objects.all()
		dictionary['consumables'] = Consumable.objects.filter(visible=True).order_by('category', 'name')
	else:
		dictionary['active_core'] = request.session.get('active_core')
		dictionary['consumables'] = Consumable.objects.filter(visible=True, core_id__in=request.user.core_ids.all()).order_by('category', 'name')

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


@login_required
@require_GET
def save_withdraw_notes(request):
	id = request.GET.get('withdraw_id')
	cw = ConsumableWithdraw.objects.get(id=id)
	cw.notes = request.GET.get('withdraw_comment')
	cw.save()
	return HttpResponse()

@login_required
def create_order(request):
	if request.method == 'POST':
		consumables = Consumable.objects.filter(category__id=1, visible=True).order_by('name')
		order_form = ConsumableOrderForm(request.POST, user=request.user)
		formset = ConsumableOrderItemFormSet(request.POST)
		if order_form.is_valid() and formset.is_valid():
			order = order_form.save(commit=False)
			order.user = request.user
			order.updated = timezone.now()
			order.save()
			formset.instance = order
			formset.save()
			return render(request, 'order_confirmation.html', {'order':order})
	else:
		order_form = ConsumableOrderForm(user=request.user)
		formset = ConsumableOrderItemFormSet()
		consumables = Consumable.objects.filter(category__id=1, visible=True).order_by('name')
	tools = Tool.objects.all()
	all_consumables = {}
	for tool in tools:
		all_consumables[tool.id] = list(tool.consumables.values('id', 'name').order_by('name'))

	return render(request, 'create_order.html', {'order_form': order_form, 'formset': formset, 'consumables': consumables, 'tools': tools, 'all_consumables': json.dumps(all_consumables),})

@login_required
def order_list(request):
	orders = ConsumableOrder.objects.filter(fulfilled=False)
	return render(request, 'order_list.html', {'orders': orders})

@login_required
def order_detail(request, order_id):
	order = get_object_or_404(ConsumableOrder, id=order_id)
	if request.method == 'POST':
		order.fulfilled = True
		order.updated = timezone.now()
		order.save()
		for item in order.items.all():
			ConsumableWithdraw.objects.create(
				customer=order.user,
				merchant=request.user,
				consumable=item.consumable,
				quantity=item.quantity,
				project=order.project,
				date=timezone.now(),
				updated=timezone.now(),
				project_percent=100.0
			)
		return redirect('order_list')
	return render(request, 'order_detail.html', {'order': order})
