from logging import getLogger
from smtplib import SMTPException

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.db.models import Q
from django.db.models.functions import Length
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.template import Template, Context
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from NEMO.forms import EmailBroadcastForm
from NEMO.models import Tool, Account, Project, User, UsageEvent, UsageEventProject, StaffCharge, StaffChargeProject, AreaAccessRecord, AreaAccessRecordProject, Consumable, ConsumableWithdraw
from NEMO.views.customization import get_media_file_contents


logger = getLogger(__name__)


@login_required
@require_GET
def get_email_form(request):
	recipient = request.GET.get('recipient', '')
	try:
		validate_email(recipient)
	except:
		return HttpResponseBadRequest('Recipient not valid.')
	return render(request, 'email/email_form.html', {'recipient': recipient})


@login_required
@require_GET
def get_email_form_for_user(request, user_id):
	recipient = get_object_or_404(User, id=user_id)
	return render(request, 'email/email_form.html', {'name': recipient.get_full_name(), 'recipient': recipient.email})


@login_required
@require_POST
def send_email(request):
	try:
		recipient = request.POST['recipient']
		validate_email(recipient)
		recipient_list = [recipient]
	except:
		return HttpResponseBadRequest('The intended recipient was not a valid email address. The email was not sent.')
	sender = request.user.email
	subject = request.POST.get('subject')
	body = request.POST.get('body')
	if request.POST.get('copy_me'):
		recipient_list.append(sender)
	try:
		email = EmailMultiAlternatives(subject, from_email=sender, bcc=recipient_list)
		email.attach_alternative(body, 'text/html')
		email.send()
	except SMTPException as error:
		error_message = 'NEMO was unable to send the email through the email server. The error message that NEMO received is: ' + str(error)
		logger.exception(error_message)
		dictionary = {
			'title': 'Email not sent',
			'heading': 'There was a problem sending your email',
			'content': error_message,
		}
		return render(request, 'acknowledgement.html', dictionary)
	dictionary = {
		'title': 'Email sent',
		'heading': 'Your email was sent',
	}
	return render(request, 'acknowledgement.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def email_broadcast(request, audience=''):
	dictionary = {
		'date_range': False,
	}
	if audience == 'tool':
		dictionary['search_base'] = Tool.objects.filter(visible=True)
	elif audience == 'project':
		dictionary['search_base'] = Project.objects.filter(active=True)
	elif audience == 'account':
		dictionary['search_base'] = Account.objects.filter(active=True)
	elif audience == 'user':
		dictionary['search_base'] = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
	elif audience == 'group':
		dictionary['search_base'] = Group.objects.all()
	elif audience == 'tool_date':
		dictionary['search_base'] = Tool.objects.filter(visible=True)
		dictionary['date_range'] = True
	elif audience == 'project_date':
		dictionary['search_base'] = Project.objects.filter(active=True)
		dictionary['date_range'] = True
	elif audience == 'active_users_date':
		dictionary['search_base'] = User.objects.annotate(email_length=Length('email')).filter(is_active=True, email_length__gt=0).order_by('last_name', 'first_name')
		dictionary['date_range'] = True
	elif audience == 'active_users':
		dictionary['users'] = User.objects.annotate(email_length=Length('email')).filter(is_active=True, email_length__gt=0).order_by('last_name', 'first_name')
		dictionary['audience'] = audience
		dictionary['selection'] = None
		dictionary['cc_users'] = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
		dictionary['date_range'] = False
		dictionary['start'] = None
		dictionary['end'] = None
		dictionary['current_time'] = timezone.now()

		generic_email_sample = get_media_file_contents('generic_email.html')
		if generic_email_sample:
			generic_email_context = {
				'title': 'TITLE',
				'greeting': 'Greeting',
				'contents': 'Contents',
			}
			dictionary['generic_email_sample'] = Template(generic_email_sample).render(Context(generic_email_context))

		return render(request, 'email/compose_email.html', dictionary)

	dictionary['audience'] = audience
	return render(request, 'email/email_broadcast.html', dictionary)


@staff_member_required(login_url=None)
@require_GET
def compose_email(request):
	audience = request.GET.get('audience')
	selection = request.GET.get('selection')
	date_range = request.GET.get('date_range')
	start = None
	end = None

	try:
		if audience == 'tool' or audience == 'tool_date':
			tool = request.GET.getlist('tool', None)
			if not tool:
				tool = [selection]
			users = User.objects.filter(qualifications__id__in=tool).distinct()
			if date_range:
				# get start and end times
				start = request.GET.get('start')
				end = request.GET.get('end')

				# find users based on their operation of the tool
				usage_events = UsageEvent.objects.filter(tool__id__in=tool)
				usage_events = usage_events.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
				users = User.objects.filter(Q(id__in=usage_events.values_list('operator', flat=True)) | Q(id__in=usage_events.values_list('customers', flat=True)))

		elif audience == 'project' or audience == 'project_date':
			users = User.objects.filter(projects__id=selection).distinct()
			if date_range:
				# get start and end times
				start = request.GET.get('start')
				end = request.GET.get('end')

				# find users based on charges to a project
				usage_events = UsageEvent.objects.filter(projects__id=selection)
				staff_charges = StaffCharge.objects.filter(projects__id=selection)				
				area_access_records = AreaAccessRecord.objects.filter(projects__id=selection)
				area_staff_charges = StaffCharge.objects.filter(id__in=area_access_records.values_list('staff_charge', flat=True))
				consumable_withdraws = ConsumableWithdraw.objects.filter(project__id=selection)

				users = User.objects.filter(Q(id__in=usage_events.values_list('customers', flat=True)) | Q(id__in=usage_events.values_list('operator', flat=True)) | Q(id__in=staff_charges.values_list('customers', flat=True)) | Q(id__in=staff_charges.values_list('staff_member', flat=True)) | Q(id__in=area_staff_charges.values_list('staff_member', flat=True)) | Q(id__in=area_staff_charges.values_list('customers', flat=True)) | Q(id__in=consumable_withdraws.values_list('merchant', flat=True))| Q(id__in=consumable_withdraws.values_list('customer', flat=True)))

		elif audience == 'active_users_date':
			users = User.objects.filter(is_active=True).order_by('last_name','first_name')
			start = request.GET.get('start')
			end = request.GET.get('end')

			# find users who were active in the system between the start and end dates
			usage_events = UsageEvent.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			staff_charges = StaffCharge.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			area_access_records = AreaAccessRecord.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			area_staff_charges = StaffCharge.objects.filter(id__in=area_access_records.values_list('staff_charge', flat=True))
			consumable_withdraws = ConsumableWithdraw.objects.filter(Q(date__range=[start, end]))

			users = users.filter(Q(id__in=usage_events.values_list('customers', flat=True)) | Q(id__in=usage_events.values_list('operator', flat=True)) | Q(id__in=staff_charges.values_list('customers', flat=True)) | Q(id__in=staff_charges.values_list('staff_member', flat=True)) | Q(id__in=area_staff_charges.values_list('staff_member', flat=True)) | Q(id__in=area_staff_charges.values_list('customers', flat=True)) | Q(id__in=consumable_withdraws.values_list('merchant', flat=True))| Q(id__in=consumable_withdraws.values_list('customer', flat=True)))


		elif audience == 'account':
			users = User.objects.filter(projects__account__id=selection).distinct()
		elif audience == 'user':
			users = User.objects.filter(id=selection).distinct()
		elif audience == 'group':
			users = User.objects.filter(groups__id=selection).distinct()
		else:
			dictionary = {'error': 'You specified an invalid audience'}
			return render(request, 'email/email_broadcast.html', dictionary)
	except Exception as inst:
		dictionary = {'error': inst}
		return render(request, 'email/email_broadcast.html', dictionary)
	generic_email_sample = get_media_file_contents('generic_email.html')
	dictionary = {
		'audience': audience,
		'selection': selection,
		'users': users,
		'cc_users': User.objects.filter(is_active=True).order_by('last_name', 'first_name'),
		'date_range': date_range,
		'start': start,
		'end': end,
		'current_time': timezone.now(),
	}
	if generic_email_sample:
		generic_email_context = {
			'title': 'TITLE',
			'greeting': 'Greeting',
			'contents': 'Contents',
		}
		dictionary['generic_email_sample'] = Template(generic_email_sample).render(Context(generic_email_context))
	return render(request, 'email/compose_email.html', dictionary)


@staff_member_required(login_url=None)
@require_POST
def send_broadcast_email(request):
	if not get_media_file_contents('generic_email.html'):
		return HttpResponseBadRequest('Generic email template not defined. Visit the NEMO customizable_key_values page to upload a template.')
	recipients = request.POST.getlist('recipient', None)
	form = EmailBroadcastForm(request.POST)
	if not form.is_valid():
		return render(request, 'email/compose_email.html', {'form': form})
	dictionary = {
		'title': form.cleaned_data['title'],
		'greeting': form.cleaned_data['greeting'],
		'contents': form.cleaned_data['contents'],
		'template_color': form.cleaned_data['color'],
	}
	content = get_media_file_contents('generic_email.html')
	content = Template(content).render(Context(dictionary))
	users = None
	audience = form.cleaned_data['audience']
	selection = form.cleaned_data['selection']
	active_choice = form.cleaned_data['only_active_users']
	try:
		users = User.objects.filter(id__in=recipients)

		if active_choice:
			users = users.filter(is_active=True)
	except Exception as error:
		warning_message = 'Your email was not sent. There was a problem finding the users to send the email to.'
		dictionary = {'error': warning_message}
		logger.warning(warning_message + ' audience: {}, only_active: {}. The error message that NEMO received is: {}'.format(audience, active_choice, str(error)))
		return render(request, 'email/compose_email.html', dictionary)
	if not users:
		dictionary = {'error': 'The audience you specified is empty. You must send the email to at least one person.'}
		return render(request, 'email/compose_email.html', dictionary)
	subject = form.cleaned_data['subject']
	users = [x.email for x in users]
	if form.cleaned_data['copy_me']:
		users += [request.user.email]
	try:
		email = EmailMultiAlternatives(subject, from_email=request.user.email, bcc=set(users))
		content = content.replace("\r\n\r\n", "</p><p>")
		content = content.replace("\r\n", "<br />")
		email.attach_alternative(content, 'text/html')
		email.send()
	except SMTPException as error:
		error_message = 'NEMO was unable to send the email through the email server. The error message that NEMO received is: ' + str(error)
		logger.exception(error_message)
		dictionary = {
			'title': 'Email not sent',
			'heading': 'There was a problem sending your email',
			'content': error_message,
		}
		return render(request, 'acknowledgement.html', dictionary)
	dictionary = {
		'title': 'Email sent',
		'heading': 'Your email was sent',
	}
	return render(request, 'acknowledgement.html', dictionary)
