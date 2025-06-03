import json

from collections import defaultdict
from django.core.mail import send_mail
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Concat
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
	return render(request, 'consumables/consumables.html', dictionary)


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
			# Save the order
			order = order_form.save(commit=False)
			order.user = request.user
			order.updated = timezone.now()
			order.save()

			# Save the order items
			formset.instance = order
			order_items = formset.save()

			# Group items by supply manager
			supply_manager_items = defaultdict(list)
			for item in order_items:
				if item.consumable.supply_manager:
					supply_manager_items[item.consumable.supply_manager].append(item)

			# Send notifications to each supply manager
			for manager, items in supply_manager_items.items():
				item_list = "\n".join([f"{item.quantity} x {item.consumable.name}" for item in items])
				subject = f"New Order Notification: Items to Fulfill"
				message = f"""
				Hello {manager.get_first_last()},

				A new order has been placed that includes items you manage. Below are the details:

				Order ID: {order.id}
				Ordered By: {order.user.get_full_name()}
				Project: {order.project}
				Items:
				{item_list}

				Please fulfill these items at your earliest convenience.

				Thank you,
				NEMO Team
				"""

				manager.email_user(subject,message,"LEOHelp@psu.edu")

			return render(request, 'consumables/order_confirmation.html', {'order': order})
	else:
		order_form = ConsumableOrderForm(user=request.user)
		formset = ConsumableOrderItemFormSet()

		# Annotate consumables with core names
		consumables = Consumable.objects.filter(category__id=1, visible=True).annotate(
			core_name=F('core_id__name'),
			academic_per_unit=F('consumablerate__academic_per_unit')
		).annotate(
			display_name=Concat(
				F('name'),
				Value(' ('),
				F('core_name'),
				Value(') - $'),
				F('academic_per_unit'),
				Value(' '),
				F('unit__abbreviation'),
				output_field=models.CharField()
			)
		).order_by('name')

		tools = Tool.objects.filter(consumables__isnull=False).order_by('name').distinct()

		# Update all_consumables and consumables_full_list with display_name
		all_consumables = {}
		for tool in tools:
			all_consumables[tool.id] = list(tool.consumables.annotate(
				core_name=F('core_id__name'),
				academic_per_unit=F('consumablerate__academic_per_unit')
			).annotate(
				display_name=Concat(
					F('name'),
					Value(' ('),
					F('core_name'),					
					Value(') - $'),
					F('academic_per_unit'),
					Value(' '),
					F('unit__abbreviation'),
					output_field=models.CharField()
				)
			).values('id', 'display_name').order_by('name'))

		consumables_full_list = list(consumables.values('id', 'display_name').order_by('name'))

		return render(request, 'consumables/create_order.html', {
			'order_form': order_form,
			'formset': formset,
			'consumables': consumables,
			'tools': tools,
			'all_consumables': json.dumps(all_consumables),
			'consumables_full_list': json.dumps(consumables_full_list),
		})


@login_required
def order_list(request, for_user):
	orders = ConsumableOrder.objects.all().order_by('-created')
	for_user = bool(for_user)
	if for_user:
		orders = orders.filter(user=request.user)
	return render(request, 'consumables/order_list.html', {'orders': orders})


@login_required
def order_detail(request, order_id):
	order = get_object_or_404(ConsumableOrder, id=order_id)
	if request.method == 'POST':
		action = request.POST.get('action')
		subject = ""
		plain_message = ""
		html_message = ""

		if action == 'fulfill':
			order.fulfilled = True
			order.fulfilled_date = timezone.now()
			order.fulfilled_by = request.user
			order.updated = timezone.now()
			order.save()
			for item in order.items.all():
				if item.fulfilled == False and item.cancelled == False:
					fulfill_item(item, request.user, 0)

			# send an email to let the user know their order is ready
			subject = "Your order '" + str(order.name) + "' has been fulfilled"
			plain_message = "Hello " + str(order.user.first_name) + ",\n\nYour order '" + str(order.name) + \
			    "' has been fulfilled. You can pick it up at the front desk.\n\nThank you,\nNEMO Team"
			html_message = f"""
			<p>Hello {order.user.first_name},</p>
			<p>Your order <strong>'{order.name}'</strong> has been fulfilled. You can pick it up at the front desk.</p>
			<p>Thank you,<br>NEMO Team</p>
			"""

		if action == 'cancel':
			cancel_msg = request.POST.get('cancel_msg', 'No reason provided')
			order.cancelled = True
			order.cancelled_date = timezone.now()
			order.cancelled_by = request.user
			order.updated = timezone.now()
			order.save()
			for item in order.items.all():
				if item.cancelled == False and item.fulfilled == False:
					cancel_item(item, request.user, 0)
			# send an email to let the user know their order has been cancelled
			subject = "Your order '" + str(order.name) + "' has been cancelled"
			plain_message = "Hello " + str(order.user.first_name) + ",\n\nYour order '" + str(order.name) + \
			    "' has been cancelled. The reason given was: '" + str(cancel_msg) + "'.  If you have any questions you can contact the NEMO team for more information.\n\nThank you,\nNEMO Team"
			html_message = f"""
			<p>Hello {order.user.first_name},</p>
			<p>Your order <strong>'{order.name}'</strong> has been cancelled.  The reason given was:<br/><br/><strong>'{cancel_msg}'</strong></p>
			<p>If you have any questions you can contact the NEMO team for more information.</p>
			<p>Thank you,<br>NEMO Team</p>
			"""

		send_mail(subject,plain_message,"LEOHelp@psu.edu",[order.user.email],html_message=html_message)
		for_user = 0
		if request.user == order.user:
			for_user = 1

		return redirect('order_list', for_user=for_user)

	allow_cancel = True
	for item in order.items.all():
		if item.fulfilled:
			allow_cancel = False
			break
	return render(request, 'consumables/order_detail.html', {'order': order, 'allow_cancel': allow_cancel})


@staff_member_required(login_url=None)
@login_required
def mark_item_fulfilled(request, item_id, do_mail):
    item = get_object_or_404(ConsumableOrderItem, id=item_id)
    fulfill_item(item, request.user, do_mail)
    return redirect('order_detail', order_id=item.order.id)

@login_required
def mark_item_cancelled(request, item_id, do_mail):
    item = get_object_or_404(ConsumableOrderItem, id=item_id)
    cancel_msg = request.POST.get('cancel_msg')
    cancel_item(item, request.user, cancel_msg, do_mail)
    return redirect('order_detail', order_id=item.order.id)


def fulfill_item(item, user, do_mail):
    item.fulfilled = True
    item.fulfilled_date = timezone.now()
    item.fulfilled_by = user
    item.updated = timezone.now()
    item.save()

    consumable_withdraw = ConsumableWithdraw.objects.create(
        customer=item.order.user,
        merchant=user,
        consumable=item.consumable,
        quantity=item.quantity,
        project=item.order.project,
        date=timezone.now(),
        updated=timezone.now(),
        project_percent=100.0
    )
    item.consumable_withdraw = consumable_withdraw
    item.save()

    if do_mail:
        subject = f"Your order for '{item.consumable.name}' has been fulfilled"
        plain_message = f"Hello {item.order.user.first_name},\n\nYour order for '{item.consumable.name}' from the order '{item.order.name}' has been fulfilled. You can pick it up at the front desk.\n\nThank you,\nNEMO Team"
        html_message = f"""
        <p>Hello {item.order.user.first_name},</p>
        <p>Your order for <strong>'{item.consumable.name}'</strong> has been fulfilled. You can pick it up at the front desk.</p>
        <p>Thank you,<br>NEMO Team</p>
        """
        send_mail(
            subject,
            plain_message,
            "LEOHelp@psu.edu",
            [item.order.user.email],
            html_message=html_message
        )

def cancel_item(item, user, cancel_msg, do_mail):
    item.cancelled = True
    item.cancelled_date = timezone.now()
    item.cancelled_by = user
    item.updated = timezone.now()
    item.save()

    if do_mail:
        subject = f"Your order for '{item.consumable.name}' has been cancelled"
        plain_message = f"Hello {item.order.user.first_name},\n\nYour order item '{item.consumable.name}' from order '{item.order.name}' has been cancelled. The reason given was: \n\n {cancel_msg}\n\nYou can contact the NEMO team for more information.\n\nThank you,\nNEMO Team"
        html_message = f"""
            <p>Hello {item.order.user.first_name},</p>
            <p>Your order item <strong>'{item.consumable.name}'</strong> from order <strong>'{item.order.name}'</strong> has been cancelled. The reason given was :</p>
            <p><strong>{cancel_msg}</strong></p>
            <p>If you have any questions please contact the NEMO team for more information.</p>
            <p>Thank you,<br>NEMO Team</p>
            """
        send_mail(
            subject,
            plain_message,
            "LEOHelp@psu.edu",
            [item.order.user.email],
            html_message=html_message
        )

