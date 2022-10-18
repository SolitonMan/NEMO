from logging import getLogger
from smtplib import SMTPException

from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core import mail
from django.core.validators import validate_email
from django.db.models import Q
from django.db.models.functions import Length
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.template import Template, Context
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from NEMO.forms import EmailBroadcastForm
from NEMO.models import Area, Tool, Account, Core, Project, User, UsageEvent, UsageEventProject, StaffCharge, StaffChargeProject, AreaAccessRecord, AreaAccessRecordProject, Consumable, ConsumableWithdraw
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
@require_http_methods(['GET', 'POST'])
def email_broadcast(request, audience=''):
	dictionary = {
		'date_range': False,
	}

	if audience == 'postback':
		dictionary['posted'] = request.POST.items()
		dictionary['cores_selected'] = request.POST.getlist('cores_selected')
		dictionary['users_selected'] = request.POST.getlist('users_selected')
		dictionary['tools_selected'] = request.POST.getlist('tools_selected')
		dictionary['projects_selected'] = request.POST.getlist('projects_selected')
		dictionary['areas_selected'] = request.POST.getlist('areas_selected')
		dictionary['groups_selected'] = request.POST.getlist('groups_selected')
		return render(request, 'email/display_posted.html', dictionary)

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
	dictionary['user_list'] = User.objects.all().order_by('last_name', 'first_name')
	dictionary['tool_list'] = Tool.objects.all().order_by('name')
	dictionary['project_list'] = Project.objects.all().order_by('project_number')
	dictionary['core_list'] = Core.objects.all().order_by('name')
	dictionary['area_list'] = Area.objects.all().order_by('name')
	dictionary['group_list'] = Group.objects.all().order_by('name')
	return render(request, 'email/email_broadcast.html', dictionary)


@staff_member_required(login_url=None)
@require_http_methods(['GET','POST'])
def compose_email(request):
	audience = request.GET.get('audience')
	selection = request.GET.get('selection')
	#date_range = request.GET.get('date_range')
	#start = None
	#end = None

	areas = request.POST.getlist('areas_selected')
	cores = request.POST.getlist('cores_selected')
	users = request.POST.getlist('users_selected')
	tools = request.POST.getlist('tools_selected')
	projects = request.POST.getlist('projects_selected')
	group_list = request.POST.getlist('groups_selected')
	core_user_list = request.POST.getlist('core_users_selected')
	core_pi_list = request.POST.getlist('core_pis_selected')
	start = request.POST.get('start')
	end = request.POST.get('end')
	date_range = False

	area_users = User.objects.filter(id=0)
	core_users = User.objects.filter(id=0)
	core_user_list_users = User.objects.filter(id=0)
	core_pi_list_users = User.objects.filter(id=0)
	individual_users = User.objects.filter(id=0)
	tool_users = User.objects.filter(id=0)
	project_users = User.objects.filter(id=0)
	group_users = User.objects.filter(id=0)
	active_users = User.objects.filter(id=0)
	individual_projects = Project.objects.filter(id=0)

	if start == '' or start is None:
		start = '2020-07-01 00:00:00'

	if end == '' or end is None:
		end = timezone.now()

	if start is not None and start != '' and end is not None and end != '':
		date_range = True

	try:
		if areas is not None and areas != []:
			area_users = User.objects.filter(physical_access_levels__area__id__in=areas)
			if date_range:
				area_access_records = AreaAccessRecord.objects.filter(area__id__in=areas, end__range=[start, end])
				area_users = User.objects.filter(id__in=area_access_records.values_list('user__id', flat=True))

		#if audience == 'tool' or audience == 'tool_date':
		if tools is not None and tools != []:
			#tool = request.GET.getlist('tool', None)
			#if not tool:
			#	tool = [selection]
			tool_users = User.objects.filter(qualifications__id__in=tools).distinct()
			if date_range:
				# get start and end times
				#start = request.GET.get('start')
				#end = request.GET.get('end')

				# find users based on their operation of the tool
				usage_events = UsageEvent.objects.filter(tool__id__in=tools)
				usage_events = usage_events.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
				tool_users = User.objects.filter(Q(id__in=usage_events.values_list('operator__id', flat=True)) | Q(id__in=usage_events.values_list('customers__id', flat=True)))

		#elif audience == 'project' or audience == 'project_date':
		if projects is not None and projects != []:
			project_users = User.objects.filter(projects__id__in=projects).distinct()
			if date_range:
				# get start and end times
				#start = request.GET.get('start')
				#end = request.GET.get('end')

				# find users based on charges to a project
				usage_events = UsageEvent.objects.filter(projects__id__in=projects, end__range=[start, end])
				staff_charges = StaffCharge.objects.filter(projects__id__in=projects, end__range=[start, end])				
				area_access_records = AreaAccessRecord.objects.filter(projects__id__in=projects, end__range=[start, end])
				area_staff_charges = StaffCharge.objects.filter(id__in=area_access_records.values_list('staff_charge', flat=True))
				consumable_withdraws = ConsumableWithdraw.objects.filter(project__id__in=projects, date__range=[start, end])

				project_users = User.objects.filter(Q(id__in=usage_events.values_list('customers__id', flat=True)) | Q(id__in=usage_events.values_list('operator__id', flat=True)) | Q(id__in=staff_charges.values_list('customers__id', flat=True)) | Q(id__in=staff_charges.values_list('staff_member__id', flat=True)) | Q(id__in=area_staff_charges.values_list('staff_member__id', flat=True)) | Q(id__in=area_staff_charges.values_list('customers__id', flat=True)) | Q(id__in=consumable_withdraws.values_list('merchant__id', flat=True))| Q(id__in=consumable_withdraws.values_list('customer__id', flat=True)))

		#elif audience == 'active_users_date':
		if date_range and areas == [] and cores == [] and users == [] and tools == [] and projects == [] and group_list == [] and core_user_list == [] and core_pi_list == []:
			active_users = User.objects.filter(is_active=True).order_by('last_name','first_name')
			#start = request.GET.get('start')
			#end = request.GET.get('end')

			# find users who were active in the system between the start and end dates
			usage_events = UsageEvent.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			staff_charges = StaffCharge.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			area_access_records = AreaAccessRecord.objects.filter(Q(start__range=[start, end]) | Q(end__range=[start, end]))
			area_staff_charges = StaffCharge.objects.filter(id__in=area_access_records.values_list('staff_charge__id', flat=True))
			consumable_withdraws = ConsumableWithdraw.objects.filter(Q(date__range=[start, end]))

			active_users = active_users.filter(Q(id__in=usage_events.values_list('customers__id', flat=True)) | Q(id__in=usage_events.values_list('operator__id', flat=True)) | Q(id__in=staff_charges.values_list('customers__id', flat=True)) | Q(id__in=staff_charges.values_list('staff_member__id', flat=True)) | Q(id__in=area_staff_charges.values_list('staff_member__id', flat=True)) | Q(id__in=area_staff_charges.values_list('customers__id', flat=True)) | Q(id__in=consumable_withdraws.values_list('merchant__id', flat=True))| Q(id__in=consumable_withdraws.values_list('customer__id', flat=True)))


		if users is not None and users != []:
			individual_users = User.objects.filter(id__in=users)

		if cores is not None and cores != []:
			core_users = User.objects.filter(core_ids__id__in=cores)

		if core_user_list is not None and core_user_list != []:
			tools=Tool.objects.filter(core_id__in=core_user_list)
			usage_events = UsageEvent.objects.filter(tool__in=tools, start__gte=start, end__lte=end)
			usageeventprojects = UsageEventProject.objects.filter(usage_event__in=usage_events)
			core_user_list_users = User.objects.filter(id__in=usageeventprojects.values_list('customer__id', flat=True))

		if core_pi_list is not None and core_pi_list != []:
			tools=Tool.objects.filter(core_id__in=core_pi_list)
			usage_events = UsageEvent.objects.filter(tool__in=tools, start__gte=start, end__lte=end)
			usageeventprojects = UsageEventProject.objects.filter(usage_event__in=usage_events)
			u_projects = Project.objects.filter(id__in=usageeventprojects.values_list('project__id', flat=True))

			staff_members = User.objects.filter(core_ids__in=core_pi_list)
			staff_charges = StaffCharge.objects.filter(staff_member__in=staff_members, start__gte=start, end__lte=end)
			staffchargeprojects = StaffChargeProject.objects.filter(staff_charge__in=staff_charges)
			s_projects = Project.objects.filter(id__in=staffchargeprojects.values_list('project__id', flat=True))

			areas = Area.objects.filter(core_id__in=core_pi_list)
			areaaccessrecords = AreaAccessRecord.objects.filter(area__in=areas, start__gte=start, end__lte=end)
			aarps = AreaAccessRecordProject.objects.filter(area_access_record__in=areaaccessrecords)
			a_projects = Project.objects.filter(id__in=aarps.values_list('project__id', flat=True))

			consumables = Consumable.objects.filter(core_id__in=cores)
			consumablewithdraws = ConsumableWithdraw.objects.filter(consumable__in=consumables, date__gte=start, date__lte=end)
			c_projects = Project.objects.filter(id__in=consumablewithdraws.values_list('project__id', flat=True))

			individual_projects = individual_projects.union(u_projects,s_projects,a_projects,c_projects)

			core_pi_list_users =  User.objects.filter(projects__in=list(individual_projects))

		if group_list is not None and group_list != []:
			groups = Group.objects.filter(id__in=group_list)
			group_users = User.objects.filter(groups__in=groups)

	except Exception as inst:
		dictionary = {'error': str(inst) + str(core_user_list) + str(core_pi_list)}
		dictionary['user_list'] = User.objects.all().order_by('last_name', 'first_name')
		dictionary['tool_list'] = Tool.objects.all().order_by('name')
		dictionary['project_list'] = Project.objects.all().order_by('project_number')
		dictionary['core_list'] = Core.objects.all().order_by('name')
		dictionary['area_list'] = Area.objects.all().order_by('name')
		dictionary['group_list'] = Group.objects.all().order_by('name')
		return render(request, 'email/email_broadcast.html', dictionary)
	generic_email_sample = get_media_file_contents('generic_email.html')

	# consolidate selections into single list of users
	users = individual_users.union(area_users, tool_users, project_users, core_users, group_users, active_users, core_user_list_users, core_pi_list_users).order_by('last_name', 'first_name')

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
	title = request.POST.get('title')
	#form = EmailBroadcastForm(request.POST)
	#if not form.is_valid():
		#return render(request, 'email/compose_email.html', {'form': form})
	dictionary = {
		'title': title.upper(),#  form.cleaned_data['title'],
		'greeting': request.POST.get('greeting'),#  form.cleaned_data['greeting'],
		'contents': request.POST.get('contents'),#  form.cleaned_data['contents'],
		'template_color': request.POST.get('color'),#  form.cleaned_data['color'],
	}
	content = get_media_file_contents('generic_email.html')
	content = Template(content).render(Context(dictionary))
	users = None
	audience = request.POST.get('audience'),#  form.cleaned_data['audience']
	selection = int(request.POST.get('selection')),#  form.cleaned_data['selection']
	active_choice = request.POST.get('only_active_users'),#  form.cleaned_data['only_active_users']
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
	subject = request.POST.get('subject')#  form.cleaned_data['subject']
	if subject == '' or subject is None:
		subject = 'LEO System Email from ' + str(request.user)
	users = [x.email for x in users]
	if request.POST.get('copy_me'):#  form.cleaned_data['copy_me']:
		users += [request.user.email]
	try:
		content = content.replace("\r\n\r\n", "</p><p>")
		content = content.replace("\r\n", "<br />")

		for u in users:
			#email = EmailMultiAlternatives(subject, from_email=request.user.email, bcc=set(users))
			#email = EmailMessage(subject, from_email=request.user.email, to=set(u))
			#email.attach_alternative(content, 'text/html')
			#email.send()
			mail.send_mail(subject, strip_tags(content), request.user.email, [u], html_message=content)

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
