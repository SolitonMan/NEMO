import datetime
import json
import socket
import struct
import requests
import xmltodict
from datetime import timedelta
from logging import getLogger

from django.conf import settings
from django.contrib import auth
from django.contrib.auth.models import BaseUserManager, Group, Permission
from django.contrib.contenttypes.fields import GenericForeignKey, GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.core.mail import send_mail
from django.db import models
from django.db.models import Q, Subquery
from django.db.models.signals import pre_delete
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotFound, HttpResponseServerError, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone

from NEMO.utilities import send_mail, EmailCategory, format_datetime, SettingType
from NEMO.views.constants import ADDITIONAL_INFORMATION_MAXIMUM_LENGTH
from NEMO.widgets.configuration_editor import ConfigurationEditor


class CalendarDisplay(models.Model):
	"""
	Inherit from this class to express that a class type is able to be displayed in the NEMO calendar.
	Calling get_visual_end() will artificially lengthen the end time so the event is large enough to
	be visible and clickable.
	"""
	start = None
	end = None

	def get_visual_end(self):
		if self.end is None:
			return max(self.start + timedelta(minutes=15), timezone.now())
		else:
			return max(self.start + timedelta(minutes=15), self.end)

	class Meta:
		abstract = True


class UserManager(BaseUserManager):
	def create_user(self, username, first_name, last_name, email):
		user = User()
		user.username = username
		user.first_name = first_name
		user.last_name = last_name
		user.email = email
		user.date_joined = timezone.now()
		user.save()
		return user

	def create_superuser(self, username, first_name, last_name, email, password=None):
		user = self.create_user(username, first_name, last_name, email)
		user.is_superuser = True
		user.is_staff = True
		user.training_required = False
		user.save()
		return user


class UserType(models.Model):
	name = models.CharField(max_length=50, unique=True)

	def __str__(self):
		return self.name

	class Meta:
		ordering = ['name']


class User(models.Model):
	# Personal information:
	username = models.CharField(max_length=100, unique=True)
	first_name = models.CharField(max_length=100)
	last_name = models.CharField(max_length=100)
	email = models.EmailField(verbose_name='email address')
	type = models.ForeignKey(UserType, null=True, on_delete=models.SET_NULL)
	domain = models.CharField(max_length=100, blank=True, help_text="The Active Directory domain that the account resides on")
	contact = models.ForeignKey('ContactInformation', on_delete=models.SET_NULL, null=True, blank=True)

	# Physical access fields
	badge_number = models.PositiveIntegerField(null=True, blank=True, unique=True, help_text="The badge number associated with this user. This number must correctly correspond to a user in order for the tablet-login system (in the lobby) to work properly.")
	access_expiration = models.DateField(blank=True, null=True, help_text="The user will lose all access rights after this date. Typically this is used to ensure that safety training has been completed by the user every year.")
	physical_access_levels = models.ManyToManyField('PhysicalAccessLevel', blank=True, related_name='users')

	# Permissions
	is_active = models.BooleanField('active', default=True, help_text='Designates whether this user can log in to LEO. Unselect this instead of deleting accounts.')
	is_staff = models.BooleanField('staff status', default=False, help_text='Designates whether the user can log into this admin site.')
	is_technician = models.BooleanField('technician status', default=False, help_text='Specifies how to bill staff time for this user. When checked, customers are billed at technician rates.')
	is_superuser = models.BooleanField('superuser status', default=False, help_text='Designates that this user has all permissions without explicitly assigning them.')
	training_required = models.BooleanField(default=False, help_text='When selected, the user is blocked from all reservation and tool usage capabilities.')
	groups = models.ManyToManyField(Group, blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of his/her group.')
	user_permissions = models.ManyToManyField(Permission, blank=True, help_text='Specific permissions for this user.')
	pi_delegates = models.ManyToManyField('self', blank=True, help_text='Users that a PI gives permission to manage accounts and their users on behalf of that PI')

	# Important dates
	date_joined = models.DateTimeField(default=timezone.now)
	last_login = models.DateTimeField(null=True, blank=True)

	# Laboratory information:
	watching = models.ManyToManyField('Tool', blank=True, help_text='Tools watched for notifications', related_name="tool_watchers")
	probationary_qualifications = models.ManyToManyField('Tool', blank=True, help_text='A detailed table for user qualifications', through='ProbationaryQualifications', related_name='probationary_qualifications')
	qualifications = models.ManyToManyField('Tool', blank=True, help_text='Select the tools that the user is qualified to use.')
	projects = models.ManyToManyField('Project', blank=True, help_text='Select the projects that this user is currently working on.')
	projects2dcc = models.ManyToManyField('Project2DCC', blank=True, help_text='Project identifiers from List for use with 2DCC projects')

	USERNAME_FIELD = 'username'
	REQUIRED_FIELDS = ['first_name', 'last_name', 'email']
	objects = UserManager()

	# Core relationship
	core_ids = models.ManyToManyField('Core', related_name="user_core", blank=True)
	credit_cost_collector = models.ForeignKey('CreditCostCollector', on_delete=models.SET_NULL, null=True, blank=True, related_name='user_credit_account')

	user_comment = models.TextField(null=True, blank=True)
	## multiple project and user UsageEvents
	#events = model.ManyToManyField(UsageEvent, through='UsageEventProject')

	def has_perm(self, perm, obj=None):
		"""
		Returns True if the user has each of the specified permissions. If
		object is passed, it checks if the user has all required perms for this object.
		"""

		# Active superusers have all permissions.
		if self.is_active and self.is_superuser:
			return True

		# Otherwise we need to check the backends.
		for backend in auth.get_backends():
			if hasattr(backend, "has_perm"):
				if obj is not None:
					if backend.has_perm(self, perm, obj):
						return True
				else:
					if backend.has_perm(self, perm):
						return True
		return False

	def has_perms(self, perm_list, obj=None):
		for perm in perm_list:
			if not self.has_perm(perm, obj):
				return False
		return True

	def has_module_perms(self, app_label):
		"""
		Returns True if the user has any permissions in the given app label.
		Uses pretty much the same logic as has_perm, above.
		"""
		# Active superusers have all permissions.
		if self.is_active and self.is_superuser:
			return True

		for backend in auth.get_backends():
			if hasattr(backend, "has_module_perms"):
				if backend.has_module_perms(self, app_label):
					return True
		return False

	def check_password(self, raw_password):
		return False

	@property
	def is_authenticated(self):
		return True

	@property
	def is_anonymous(self):
		return False

	def get_username(self):
		return self.username

	def email_user(self, subject, message, from_email=None):
		""" Sends an email to this user. """
		#send_mail(subject=subject, message='', from_email=from_email, recipient_list=[self.email], html_message=message)
		send_mail(subject, message, from_email, [self.email])

	def get_full_name(self):
		fname = ""

		if not self.is_active:
			fname += "[INACTIVE] "

		fname += self.first_name + ' ' + self.last_name + ' (' + self.username + ')'
		return fname

	def get_first_last(self):
		fname = self.first_name + ' ' + self.last_name
		return fname

	def get_short_name(self):
		return self.first_name

	def in_area(self):
		return AreaAccessRecord.objects.filter(user=self, end=None, active_flag=True).exists()

	def area_access_record(self):
		try:
			return AreaAccessRecord.objects.get(user=self, end=None)
		except AreaAccessRecord.DoesNotExist:
			return None

	def billing_to_project(self):
		access_record = self.area_access_record()
		if access_record is None:
			return None
		else:
			if access_record.project is None:
				return access_record.projects.all()[0]
			else:
				return access_record.project

	def active_project_count(self):
		return self.projects.filter(active=True, start_date__lte=timezone.now(), end_date__gte=timezone.now()).count()

	def active_projects(self):
		return self.projects.filter(active=True, start_date__lte=timezone.now(), end_date__gte=timezone.now()).order_by('project_number')

	def all_projects(self):
		return self.projects

	def charging_staff_time(self):
		return StaffCharge.objects.filter(staff_member=self, end=None, active_flag=True).exists()

	def get_staff_charge(self):
#		try:
#			return StaffCharge.objects.filter(staff_member=self, end=None, active_flag=True)[0]
#		except:
#			return None
		try:
			sc = StaffCharge.objects.filter(staff_member=self, end=None, active_flag=True)

			if sc is not None:
				if sc[0].core_id_override is not None:
					sc = sc.annotate(core_id_override_name=Subquery(Core.objects.filter(id=sc[0].core_id_override).values('name')))
				if sc[0].credit_cost_collector_override is not None:
					sc = sc.annotate(credit_cost_collector_override_name=Subquery(CreditCostCollector.objects.filter(id=sc[0].credit_cost_collector_override).values('name')))

				return sc[0]
			else:
				return None
		except:
			return None

	def get_overridden_staff_charges(self):
		try:
			return StaffCharge.objects.filter(staff_member=self.id, charge_end_override=True, override_confirmed=False, active_flag=True)
		except StaffCharge.DoesNotExist:
			return None 

	def current_reservation_for_tool(self, tool):
		current_reservation = None
		try:
			if Reservation.objects.filter(start__lte=timezone.now()+timedelta(0,0,0,0,15,0,0), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=self, tool=tool).exists():
				current_reservation = Reservation.objects.filter(start__lte=timezone.now()+timedelta(0,0,0,0,15,0,0), end__gt=timezone.now(), cancelled=False, missed=False, shortened=False, user=self, tool=tool).order_by('start')[0]
				#current_reservation = Reservation.objects.get(start__lte=timezone.now()+timedelta(0,0,0,0,15,0,0), end__gt=timezone.now(), cancelled=False, missed=False, user=self, tool=tool)
		except Reservation.DoesNotExist:
			pass
		return current_reservation

	def current_tool_use(self, tool):
		current_tool_use = None
		try:
			current_tool_use = UsageEvent.objects.filter(end=None, operator=self, tool=tool)
		except UsageEvent.DoesNotExist:
			pass
		return current_tool_use

	def get_current_tools(self):
		current_tools = None
		try:
			current_tools = UsageEvent.objects.filter(end=None, operator=self, active_flag=True)
		except UsageEvent.DoesNotExist:
			pass
		return current_tools

	def set_password(self, raw_password):
		return False;

	class Meta:
		ordering = ['first_name']
		permissions = (
			("trigger_timed_services", "Can trigger timed services"),
			("use_billing_api", "Can use billing API"),
			("kiosk", "Kiosk services"),
		)

	def __str__(self):
		return self.get_full_name()

class UserProfile(models.Model):
	user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True)
	setting = models.ForeignKey('UserProfileSetting', on_delete=models.SET_NULL, null=True, blank=True)
	value = models.TextField(null=True, blank=True)

class UserProfileSetting(models.Model):
	name = models.CharField(max_length=255)
	setting_type = models.CharField(max_length=255, choices=SettingType.Choices)
	description = models.TextField(null=True, blank=True)
	title = models.CharField(max_length=255, null=True, blank=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['name'], name='unique name')
		]

	def __str__(self):
		return str(self.name)

class ProbationaryQualifications(models.Model):
	user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True)
	tool = models.ForeignKey('Tool', on_delete=models.SET_NULL, null=True, blank=True)
	qualification_date = models.DateTimeField(default=timezone.now, null=True, blank=True)
	probationary_user = models.BooleanField(default=False)
	tool_last_used = models.DateTimeField(null=True, blank=True)
	disabled = models.BooleanField(default=False)


class Project2DCC(models.Model):
	class ProjectType(object):
		UNKNOWN = -1
		RESEARCH = 1
		SAMPLE = 2
		RSVP = 3
		Choices = (
			(UNKNOWN, 'Unknown'),
			(RESEARCH, 'Research'),
			(SAMPLE, 'Sample'),
			(RSVP,'RSVP'),
		)

	project_id = models.CharField(max_length=255, unique=True)
	project_type = models.IntegerField(choices=ProjectType.Choices, default=ProjectType.UNKNOWN)
	leo_project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True)

	class Meta:
		constraints = [
			models.UniqueConstraint(fields=['project_id'], name='2dcc unique name')
		]

	def __str__(self):
		return str(self.project_id)

	@property
	def name(self):
		return str(self.project_id)
	

class UserRelationshipType(models.Model):
	name = models.CharField(max_length=255, unique=True)
	user_1_role = models.CharField(max_length=255)
	user_2_role = models.CharField(max_length=255)
	description = models.TextField(null=True, blank=True)


class UserRelationship(models.Model):
	type = models.ForeignKey(UserRelationshipType, related_name="user_relationship_type", on_delete=models.SET_NULL, null=True)
	user_1 = models.ForeignKey(User, related_name="upper_tier_role", on_delete=models.SET_NULL, null=True, help_text="The person who is the manager, superviser, PI, or other role higher in the structure")
	user_2 = models.ForeignKey(User, related_name="lower_tier_role", on_delete=models.SET_NULL, null=True, help_text="The person who is the subordinate, supervisee, delegate or other role lower in the structure.")


class Tool(models.Model):
	name = models.CharField(max_length=100, unique=True)
	category = models.CharField(max_length=1000, help_text="Create sub-categories using slashes. For example \"Category 1/Sub-category 1\".")
	visible = models.BooleanField(default=True, help_text="Specifies whether this tool is visible to users.")
	operational = models.BooleanField(default=False, help_text="Marking the tool non-operational will prevent users from using the tool.")
	primary_owner = models.ForeignKey(User, related_name="primary_tool_owner", on_delete=models.SET_NULL, null=True, help_text="The staff member who is responsible for administration of this tool.")
	backup_owners = models.ManyToManyField(User, blank=True, related_name="backup_for_tools", help_text="Alternate staff members who are responsible for administration of this tool when the primary owner is unavailable.")
	location = models.CharField(max_length=100, null=True, blank=True)
	phone_number = models.CharField(max_length=100)
	notification_email_address = models.EmailField(blank=True, null=True, help_text="Messages that relate to this tool (such as comments, problems, and shutdowns) will be forwarded to this email address. This can be a normal email address or a mailing list address.")
	infolink = models.CharField(max_length=1000, null=True, blank=True)

	# Policy fields:
	requires_area_access = models.ForeignKey('Area', blank=True, on_delete=models.SET_NULL, null=True, help_text="Indicates that this tool is physically located in a billable area and requires an active area access record in order to be operated.")
	grant_physical_access_level_upon_qualification = models.ForeignKey('PhysicalAccessLevel', null=True, blank=True, on_delete=models.SET_NULL, help_text="The designated physical access level is granted to the user upon qualification for this tool.")
	grant_badge_reader_access_upon_qualification = models.CharField(max_length=100, null=True, blank=True, help_text="Badge reader access is granted to the user upon qualification for this tool.")

	# adding new field to create many to many relationship with the Interlock table.  This will allow each tool
	# to be configured to use as many interlocks as needed.  Each item will be assigned to the tool individually
	interlocks = models.ManyToManyField('Interlock', blank=True, related_name="interlocks")
	interlock = models.OneToOneField('Interlock', blank=True, null=True, on_delete=models.SET_NULL)
	reservation_horizon = models.PositiveIntegerField(default=14, null=True, blank=True, help_text="Users may create reservations this many days in advance. Leave this field blank to indicate that no reservation horizon exists for this tool.")
	minimum_usage_block_time = models.PositiveIntegerField(null=True, blank=True, help_text="The minimum amount of time (in minutes) that a user must reserve this tool for a single reservation. Leave this field blank to indicate that no minimum usage block time exists for this tool.")
	maximum_usage_block_time = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve this tool for a single reservation. Leave this field blank to indicate that no maximum usage block time exists for this tool.")
	maximum_reservations_per_day = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum number of reservations a user may make per day for this tool.")
	minimum_time_between_reservations = models.PositiveIntegerField(null=True, blank=True, help_text="The minimum amount of time (in minutes) that the same user must have between any two reservations for this tool.")
	maximum_future_reservation_time = models.PositiveIntegerField(null=True, blank=True, help_text="The maximum amount of time (in minutes) that a user may reserve from the current time onwards.")
	missed_reservation_threshold = models.PositiveIntegerField(null=True, blank=True, help_text="The amount of time (in minutes) that a tool reservation may go unused before it is automatically marked as \"missed\" and hidden from the calendar. Usage can be from any user, regardless of who the reservation was originally created for. The cancellation process is triggered by a timed job on the web server.")
	allow_delayed_logoff = models.BooleanField(default=False, help_text='Upon logging off users may enter a delay before another user may use the tool. Some tools require "spin-down" or cleaning time after use.')
	post_usage_questions = models.TextField(null=True, blank=True, help_text="")
	reservation_required = models.BooleanField(default=False, help_text='Require that users have a current (within 15 minutes) reservation in order to use the tool')
	allow_autologout = models.BooleanField(default=False, help_text='Allow users to set an end time for the tool run.')
	qualification_duration = models.PositiveIntegerField(default=182, null=True, blank=True, help_text="The tool may indicate the number of days without use a user will be considered qualified.  The default is 182 days (6 months).  Each night a script will run to check a user's last date of use for a tool against this time period.  If the date of last use is greater than the qualification_duration value the user will be set to limited status.  This change can be reversed in LEO.")

	# add a many to many relationship with the consumable table.  This will allow each tool
	consumables = models.ManyToManyField('Consumable', blank=True, help_text="Select the consumables that are required for this tool. Consumables are used to track the amount of consumable used during a tool run.  This is not a required field.", related_name='tool_consumables')

	# Core info
	core_id = models.ForeignKey('Core', related_name="tool_core", on_delete=models.SET_NULL, help_text="The core facility of which this tool is part.", null=True)
	credit_cost_collector = models.ForeignKey('CreditCostCollector', related_name='tool_credit_account', on_delete=models.SET_NULL, null=True, blank=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name

	def get_absolute_url(self):
		from django.urls import reverse
		return reverse('tool_control', args=[self.id])

	def problematic(self):
		return self.task_set.filter(resolved=False, cancelled=False).exists()
	problematic.admin_order_field = 'task'
	problematic.boolean = True

	def problems(self):
		return self.task_set.filter(resolved=False, cancelled=False)

	def comments(self):
		unexpired = Q(expiration_date__isnull=True) | Q(expiration_date__gt=timezone.now())
		return self.comment_set.filter(visible=True).filter(unexpired)

	def required_resource_is_unavailable(self):
		return self.required_resource_set.filter(available=False).exists()

	def nonrequired_resource_is_unavailable(self):
		return self.nonrequired_resource_set.filter(available=False).exists()

	def all_resources_available(self):
		required_resources_available = not self.unavailable_required_resources().exists()
		nonrequired_resources_available = not self.unavailable_nonrequired_resources().exists()
		if required_resources_available and nonrequired_resources_available:
			return True
		return False

	def unavailable_required_resources(self):
		return self.required_resource_set.filter(available=False)

	def unavailable_nonrequired_resources(self):
		return self.nonrequired_resource_set.filter(available=False)

	def in_use(self):
		result = UsageEvent.objects.filter(tool=self.id, end=None, active_flag=True).exists()
		return result

	def delayed_logoff_in_progress(self):
		result = UsageEvent.objects.filter(tool=self.id, end__gt=timezone.now(), active_flag=True, ad_hoc_created=False).exists()
		return result

	def get_delayed_logoff_usage_event(self):
		try:
			return UsageEvent.objects.get(tool=self.id, end__gt=timezone.now(), active_flag=True, ad_hoc_created=False)
		except UsageEvent.DoesNotExist:
			return None

	def scheduled_outages(self):
		""" Returns a QuerySet of scheduled outages that are in progress for this tool. This includes tool outages, and resources outages (when the tool fully depends on the resource). """
		return ScheduledOutage.objects.filter(Q(tool=self.id) | Q(resource__fully_dependent_tools__in=[self.id]), start__lte=timezone.now(), end__gt=timezone.now())

	def scheduled_outage_in_progress(self):
		""" Returns a true if a tool or resource outage is currently in effect for this tool. Otherwise, returns false. """
		return ScheduledOutage.objects.filter(Q(tool=self.id) | Q(resource__fully_dependent_tools__in=[self.id]), start__lte=timezone.now(), end__gt=timezone.now()).exists()

	def is_configurable(self):
		return self.configuration_set.exists()
	is_configurable.admin_order_field = 'configuration'
	is_configurable.boolean = True
	is_configurable.short_description = 'Configurable'

	def get_configuration_information(self, user, start):
		configurations = self.configuration_set.all().order_by('display_priority')
		notice_limit = 0
		able_to_self_configure = True
		for config in configurations:
			notice_limit = max(notice_limit, config.advance_notice_limit)
			# If an item is already excluded from the configuration agenda or the user is not a qualified maintainer, then tool self-configuration is not possible.
			if config.exclude_from_configuration_agenda or not config.user_is_maintainer(user):
				able_to_self_configure = False
		results = {
			'configurations': configurations,
			'notice_limit': notice_limit,
			'able_to_self_configure': able_to_self_configure,
			'additional_information_maximum_length': ADDITIONAL_INFORMATION_MAXIMUM_LENGTH,
		}
		if start:
			results['sufficient_notice'] = (start.replace(tzinfo=None) - timedelta(hours=notice_limit) >= timezone.now().replace(tzinfo=None))
		return results

	def configuration_widget(self, user):
		config_input = {
			'configurations': self.configuration_set.all().order_by('display_priority'),
			'user': user
		}
		configurations = ConfigurationEditor()
		return configurations.render(None, config_input)

	def get_current_usage_event(self):
		""" Gets the usage event for the current user of this tool. """
		try:
			if UsageEvent.objects.filter(end=None, tool=self.id).exists():
				if UsageEvent.objects.filter(end=None, tool=self.id).count() == 1:
					return UsageEvent.objects.get(end=None, tool=self.id)
				else:
					current_usage = None
					for u in UsageEvent.objects.filter(end=None, tool=self.id).order_by('start'):
						if current_usage == None:
							current_usage = u
						else:
							u.end = timezone.now()
							u.updated = timezone.now()
							u.no_charge_flag = True
							u.active_flag = False
							u.save()

					return current_usage
			else:
				return None
						
		except UsageEvent.DoesNotExist:
			return None

	def update_post_usage_questions(self):
		post_usage_questions = []
		for c in self.configuration_set.all():
			if c.available_settings is None or c.available_settings == '':
				if c.current_settings is not None and c.current_settings != '':
					conf = {}
					consumable_id = int(c.current_settings)
					if consumable_id > 0:
						conf["type"] = "textbox"
						conf["title"] = "How much " + c.get_current_setting(0) + " was used?"
						conf["max-width"] = "250"
						if Consumable.objects.get(id=consumable_id).unit:
							conf["suffix"] = str(Consumable.objects.get(id=consumable_id).unit.abbreviation)
						else:
							conf["suffix"] = "each"
						conf["required"] = "true"
						conf["default_choice"] = "null"
						conf["placeholder"] = "0"
						#conf["name"] = str(Consumable.objects.get(id=consumable_id).name)
						conf["name"] = "consumable__" + str(consumable_id) + "__" + str(c.id)
						conf["consumable"] = str(Consumable.objects.get(id=consumable_id).name)
						conf["consumable_id"] = str(consumable_id)
						conf["configuration_id"] = str(c.id)
					else:
						conf["type"] = "textbox"
						conf["title"] = "None option selected"
						conf["max-width"] = "250"
						conf["suffix"] = "each"
						conf["required"] = "false"
						conf["default_choice"] = "null"
						conf["placeholder"] = "0"
						conf["name"] = "None"
						conf["consumable"] = "None"
						conf["consumable_id"] = "0"
						conf["configuration_id"] = str(c.id)
						
					post_usage_questions.append(conf)
		self.post_usage_questions = json.dumps(post_usage_questions)
		self.save()
		return


class ToolUseNotificationLog(models.Model):
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True, help_text="The tool that this configuration option applies to.")
	usage_event = models.ForeignKey('UsageEvent', on_delete=models.SET_NULL, null=True, help_text="The usage event which is running long")
	message = models.TextField(blank=True, null=True, help_text="The HTML message sent to the user")
	sent = models.DateTimeField(null=True, blank=True)

class Configuration(models.Model):
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True, help_text="The tool that this configuration option applies to.")
	name = models.CharField(max_length=200, help_text="The name of this overall configuration. This text is displayed as a label on the tool control page.")
	configurable_item_name = models.CharField(blank=True, null=True, max_length=200, help_text="The name of the tool part being configured. This text is displayed as a label on the tool control page. Leave this field blank if there is only one configuration slot.")
	advance_notice_limit = models.PositiveIntegerField(help_text="Configuration changes must be made this many hours in advance.")
	display_priority = models.PositiveIntegerField(help_text="The order in which this configuration will be displayed beside others when making a reservation and controlling a tool. Can be any positive integer including 0. Lower values are displayed first.")
	prompt = models.TextField(blank=True, null=True, help_text="The textual description the user will see when making a configuration choice.")
	consumable = models.ManyToManyField('Consumable', blank=True, help_text="Select the core-specific consumables that are configurable choices for the selected tool.")
	current_settings = models.TextField(blank=True, null=True, help_text="The current configuration settings for a tool. Multiple values are separated by commas.")
	available_settings = models.TextField(blank=True, null=True, help_text="The available choices to select for this configuration option. Multiple values are separated by commas.")
	maintainers = models.ManyToManyField(User, blank=True, help_text="Select the users that are allowed to change this configuration.")
	qualified_users_are_maintainers = models.BooleanField(default=False, help_text="Any user that is qualified to use the tool that this configuration applies to may also change this configuration. Checking this box implicitly adds qualified users to the maintainers list.")
	exclude_from_configuration_agenda = models.BooleanField(default=False, help_text="Reservations containing this configuration will be excluded from the laboratory technician's Configuration Agenda page.")
	absence_string = models.CharField(max_length=100, blank=True, null=True, help_text="The text that appears to indicate absence of a choice.")

	def get_current_setting(self, slot):
		if slot < 0:
			raise IndexError("Slot index of " + str(slot) + " is out of bounds for configuration \"" + self.name + "\" (id = " + str(self.id) + ").")

		if self.available_settings is None or self.available_settings == '':
			id = int(self.current_settings_as_list()[slot])
			if id > 0:
				return Consumable.objects.get(id=id).name
			else:
				return "None"
		return self.current_settings_as_list()[slot]

	def current_settings_as_list(self):
		if self.current_settings is None:
			return []

		if len(self.current_settings) == 0 or len(self.current_settings) is None:
			if len(self.available_settings_as_list()) > 0:
				self.current_settings = self.available_settings_as_list()[0]
			else:
				c = self.consumable.all()[0]
				self.current_settings = str(c.id)

		if len(self.current_settings) is not None and len(self.current_settings) > 0:
			return [x.strip() for x in self.current_settings.split(',')]
		else:
			return []

	def available_settings_as_list(self):
		if self.available_settings is not None and self.available_settings != '':
			return [x.strip() for x in self.available_settings.split(',')]
		else:
			return []

	def get_available_setting(self, choice):
		choice = int(choice)
		if self.available_settings is None or self.available_settings == '':
			# return selected consumable name
			return Consumable.objects.get(id=choice).name
		else:
			available_settings = self.available_settings_as_list()
			return available_settings[choice]

	def get_setting_id(self, choice):
		choice = str(choice)
		for index, option in enumerate(self.available_settings_as_list()):
			if choice == str(option):
				return index
		return None

	def replace_current_setting(self, slot, choice):
		slot = int(slot)
		try:
			current_settings = self.current_settings_as_list()
		except Exception as e:
			current_settings = []
		try:
			if self.consumable.all().count() > 0:
				current_settings[slot] = str(choice)
			else:
				current_settings[slot] = self.get_available_setting(choice)
			self.current_settings = ', '.join(current_settings)
		except:
			self.current_settings = str(choice)

	def range_of_configurable_items(self):
		return range(0, len(self.current_settings.split(',')))

	def user_is_maintainer(self, user):
		if user in self.maintainers.all():
			return True
		if self.qualified_users_are_maintainers and (user in self.tool.user_set.all() or user.is_staff):
			return True
		return False

	class Meta:
		ordering = ['tool', 'name']

	def __str__(self):
		return str(self.tool.name) + ': ' + str(self.name)


class TrainingSession(models.Model):
	class Type(object):
		INDIVIDUAL = 0
		GROUP = 1
		Choices = (
			(INDIVIDUAL, 'Individual'),
			(GROUP, 'Group')
		)

	trainer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="teacher_set")
	trainee = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="student_set")
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True)
	duration = models.PositiveIntegerField(help_text="The duration of the training session in minutes.")
	type = models.IntegerField(choices=Type.Choices)
	date = models.DateTimeField(default=timezone.now)
	qualified = models.BooleanField(default=False, help_text="Indicates that after this training session the user was qualified to use the tool.")

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class StaffCharge(CalendarDisplay):
	staff_member = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='staff_charge_actor')
	customer = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='staff_charge_customer', null=True, blank=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, related_name='staff_charge_project', null=True, blank=True)
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	staff_member_comment = models.TextField(null=True, blank=True)
	validated = models.BooleanField(default=False)
	contested = models.BooleanField(default=False)
	contest_data = GenericRelation('ContestTransactionData')
	contest_record = GenericRelation('ContestTransaction', related_query_name='staff_charge_contests')
	charge_end_override = models.BooleanField(default=False, blank=True)
	override_confirmed = models.BooleanField(default=False, blank=True)
	related_override_charge = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
	ad_hoc_replaced = models.BooleanField(default=False, blank=True)
	ad_hoc_related = models.CharField(max_length=500, blank=True, null=True)
	projects = models.ManyToManyField('Project', through='StaffChargeProject')
	customers = models.ManyToManyField('User', through='StaffChargeProject')
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	validated_date = models.DateTimeField(null=True, blank=True)
	auto_validated = models.BooleanField(default=False)
	no_charge_flag = models.BooleanField(default=False)
	ad_hoc_created = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	core_id_override = models.PositiveIntegerField(null=True, blank=True)
	cost_per_sample_run = models.BooleanField(default=False)
	related_usage_event = models.ForeignKey('UsageEvent', on_delete=models.SET_NULL, related_name='sc_related_usage_event', null=True, blank=True)
	credit_cost_collector_override = models.PositiveIntegerField(null=True, blank=True)
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='staff_charge_transaction')

	def duration(self):
		return calculate_duration(self.start, self.end, "In progress")

	def auto_validate(self):
		self.validated = True
		self.validated_date = timezone.now()
		self.auto_validated = True
		self.updated = timezone.now()
		self.save()

	def description(self):
		ep = StaffChargeProject.objects.filter(staff_charge=self, active_flag=True)
		d = "<table class=\"table\"><thead><tr><th>Customer</th><th>Project</th></tr></thead><tbody>"

		if ep.exists():
			for e in ep:
				d += "<tr><td>" + e.customer.get_full_name() + "</td><td>" + str(e.project) + "</td></tr>"
			d += "</tbody></table>"
		else:
			d += "<tr><td>" + self.customer.get_full_name() + "</td><td>" + str(self.project) + "</td></tr></tbody></table>"
		return d

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)

class StaffChargeProject(models.Model):
	staff_charge = models.ForeignKey('StaffCharge', on_delete=models.SET_NULL, null=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True)
	customer = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)
	project_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	comment = models.TextField(null=True, blank=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	contest_data = GenericRelation('ContestTransactionData')
	no_charge_flag = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	#sample = models.ManyToManyField('Sample', blank=True, related_name='scp_sample')
	sample_detail = models.ManyToManyField('Sample', blank=True, through='StaffChargeProjectSample', related_name='scp_sample_detail')
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='staff_charge_project_transaction')


class StaffChargeProjectSample(models.Model):
	sample = models.ForeignKey('Sample', on_delete=models.SET_NULL, null=True)
	staff_charge_project = models.ForeignKey('StaffChargeProject', on_delete=models.SET_NULL, null=True)
	notes =  models.TextField(null=True, blank=True)
	active_flag = models.BooleanField(default=True)
	created = models.DateTimeField(null=True, blank=True, default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True, default=timezone.now)

class StaffChargeNotificationLog(models.Model):
	staff_charge = models.ForeignKey(StaffCharge, on_delete=models.SET_NULL, null=True)
	message = models.TextField(blank=True, null=True, help_text="The HTML message sent to the user")
	sent = models.DateTimeField(null=True, blank=True)


class Area(models.Model):
	name = models.CharField(max_length=200, help_text='What is the name of this area? The name will be displayed on the tablet login and logout pages.')
	welcome_message = models.TextField(help_text='The welcome message will be displayed on the tablet login page. You can use HTML and JavaScript.')

	# add core id
	core_id = models.ForeignKey('Core', on_delete=models.SET_NULL, related_name='area_core', null=True)
	credit_cost_collector = models.ForeignKey('CreditCostCollector', on_delete=models.SET_NULL, related_name='area_cost_collector', null=True, blank=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class AreaAccessRecord(CalendarDisplay):
	area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True)
	customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='area_user')
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, related_name='area_access_record_project', null=True)
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	staff_charge = models.ForeignKey(StaffCharge, on_delete=models.SET_NULL, blank=True, null=True)
	comment = models.TextField(null=True, blank=True)
	projects = models.ManyToManyField('Project', through='AreaAccessRecordProject')
	customers = models.ManyToManyField('User', through='AreaAccessRecordProject', related_name='AreaAccessRecordMultipleCustomers')
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	validated = models.BooleanField(default=False)
	contested = models.BooleanField(default=False)
	contest_data = GenericRelation('ContestTransactionData')
	contest_record = GenericRelation('ContestTransaction', related_query_name='area_access_record_contests')
	validated_date = models.DateTimeField(null=True, blank=True)
	auto_validated = models.BooleanField(default=False)
	no_charge_flag = models.BooleanField(default=False)
	ad_hoc_created = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	cost_per_sample_run = models.BooleanField(default=False)
	related_usage_event = models.ForeignKey('UsageEvent', on_delete=models.SET_NULL, related_name='aar_related_usage_event', null=True, blank=True)
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='area_access_record_transaction')

	def duration(self):
		return calculate_duration(self.start, self.end, "In progress")

	def auto_validate(self):
		self.validated = True
		self.validated_date = timezone.now()
		self.auto_validated = True
		self.updated = timezone.now()
		self.save()

	def description(self):
		ep = AreaAccessRecordProject.objects.filter(area_access_record=self, active_flag=True)
		if ep.exists():
			d = "<table class=\"table\"><thead><tr><th>Customer</th><th>Project</th></tr></thead><tbody>"
			for e in ep:
				d += "<tr><td>" + e.customer.get_full_name() + "</td><td>" + e.project.name + "</td></tr>"
			d += "</tbody></table>"
		else:
			d = ""
		return d

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class AreaAccessRecordProject(models.Model):
	area_access_record = models.ForeignKey('AreaAccessRecord', on_delete=models.SET_NULL, null=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True)
	customer = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)
	project_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	contest_data = GenericRelation('ContestTransactionData')
	no_charge_flag = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	comment = models.TextField(null=True, blank=True)
	#sample = models.ManyToManyField('Sample', blank=True, related_name='aarp_sample')
	sample_detail = models.ManyToManyField('Sample', blank=True, through='AreaAccessRecordProjectSample', related_name='aarp_sample_detail')
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='area_access_record_project_transaction')


class AreaAccessRecordProjectSample(models.Model):
	sample = models.ForeignKey('Sample', on_delete=models.SET_NULL, null=True)
	area_access_record_project = models.ForeignKey('AreaAccessRecordProject', on_delete=models.SET_NULL, null=True)
	notes =  models.TextField(null=True, blank=True)
	active_flag = models.BooleanField(default=True)
	created = models.DateTimeField(null=True, blank=True, default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True, default=timezone.now)
 

class ConfigurationHistory(models.Model):
	configuration = models.ForeignKey(Configuration, on_delete=models.SET_NULL, null=True)
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	modification_time = models.DateTimeField(default=timezone.now)
	slot = models.PositiveIntegerField()
	setting = models.TextField()

	class Meta:
		ordering = ['-modification_time']
		verbose_name_plural = "Configuration histories"

	def __str__(self):
		return str(self.id)


class Account(models.Model):
	name = models.CharField(max_length=100)
	simba_cost_center = models.CharField(max_length=10, null=True, blank=True)
	ibis_account = models.CharField(max_length=25, unique=True, null=True, blank=True)
	owner = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, help_text="The owner or person responsible for the Account (Cost Center in SIMBA) as imported via SIMBA download nightly")
	active = models.BooleanField(default=True, help_text="Users may only charge to an account if it is active. Deactivate the account to block future billable activity (such as tool usage and consumable check-outs) of all the projects that belong to it.")
	start_date = models.DateField(null=True, blank=True, help_text="The date on which the cost center becomes active")
	end_date = models.DateField(null=True, blank=True, help_text="The date on which the cost center becomes inactive")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return str(self.name + ' [I:' + str(self.ibis_account) + '][S:' + str(self.simba_cost_center) + ']')


def get_new_project_number():
	projects = Project.objects.all()
	today = datetime.date.today()
	year_current = today.strftime("%y")
	max_number = 0

	for p in projects:
		# check if the project's number is from the current year
		if year_current == p.project_number[:2]:
			if int(max_number) < int(p.project_number[3:]):
				max_number = int(p.project_number[3:])

	max_number = int(max_number) + 1

	if len(str(max_number)) == 1:
		max_number = "00" + str(max_number)
	elif len(str(max_number)) == 2:
		max_number = "0" + str(max_number)
	else:
		max_number = str(max_number)

	return str(year_current) + "-" + str(max_number)


class Project(models.Model):
	name = models.CharField(max_length=100)
	project_number = models.CharField(max_length=20, null=True, blank=True, default=get_new_project_number)
	application_identifier = models.CharField(max_length=500, null=True, blank=True)
	account = models.ForeignKey(Account, on_delete=models.SET_NULL, null=True, blank=True, help_text="All charges for this project will be billed to the selected account.")
	simba_cost_center = models.CharField(max_length=10, null=True, blank=True)
	internal_order = models.CharField(max_length=12, null=True, blank=True)
	wbs_element = models.CharField(max_length=12, null=True, blank=True)
	owner = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, help_text="The owner or person responsible for the Project (Internal Order or WBS Element in SIMBA) as imported via SIMBA download nightly", related_name="project_owner")
	organization = models.ForeignKey('Organization', on_delete=models.SET_NULL, null=True, blank=True)
	bill_to =  models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, help_text="The person to contact with an invoice", related_name="bill_to_contact")
	bill_to_alt = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, help_text="The alternate person to contact with an invoice", related_name="bill_to_contact_alt")
	rate_type_id = models.PositiveIntegerField(null=True, blank=True)
	fa_type_id = models.PositiveIntegerField(null=True, blank=True)
	billing_type = models.ForeignKey('BillingType', on_delete=models.SET_NULL, null=True, blank=True, help_text="This field will replace the rate_type_id")
	active = models.BooleanField(default=True, help_text="Users may only charge to a project if it is active. Deactivate the project to block billable activity (such as tool usage and consumable check-outs).")
	start_date = models.DateField(null=True, blank=True, help_text="The date on which the project, internal order or wbs element becomes active")
	end_date = models.DateField(null=True, blank=True, help_text="The date on which the project, internal order or wbs element becomes inactive")
	detailed_invoice = models.BooleanField(default=False, help_text="A flag to indicate if the customer assigned this project should receive a detailed invoice.  The default is False, indicating that a summarized invoice should be sent.")
	group_by_user = models.BooleanField(default=False, help_text="A flag to indicate if the invoice should be grouped by user instead of core.")
	po_number = models.TextField(null=True, blank=True)
	comment = models.TextField(null=True, blank=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		s = ''
		if not self.active:
			s = '[INACTIVE]'

		if s == '' and self.end_date is not None:
			if self.end_date < timezone.now().date():
				s = '[INACTIVE]'

		s += '[' + str(self.project_number) + '] ' + str(self.name) + ' [' + str(self.get_project()) + ']'

		#if self.account is not None:
		#	s += '[IBIS:' + str(self.account.ibis_account) + ']'

		return s

	def get_project(self):
		if self.wbs_element is not None:
			if len(self.wbs_element) > 0:
				return str(self.wbs_element)
		if self.internal_order is not None:
			if len(self.internal_order) > 0:
				return str(self.internal_order)
		return str(self.simba_cost_center)

	def check_date(self, compare_date):
		return (compare_date.date() >= self.start_date) and (compare_date.date() <= self.end_date)

	def check_date_range(self, start_date, end_date):
		return self.check_date(start_date) and self.check_date(end_date)

	def past_end_date(self):
		return self.end_date < timezone.now().date()


def pre_delete_entity(sender, instance, using, **kwargs):
	""" Remove activity history and membership history when an account, project, tool, or user is deleted. """
	content_type = ContentType.objects.get_for_model(sender)
	ActivityHistory.objects.filter(object_id=instance.id, content_type=content_type).delete()
	MembershipHistory.objects.filter(parent_object_id=instance.id, parent_content_type=content_type).delete()
	MembershipHistory.objects.filter(child_object_id=instance.id, child_content_type=content_type).delete()


# Call the function "pre_delete_entity" every time an account, project, tool, or user is deleted:
pre_delete.connect(pre_delete_entity, sender=Account)
pre_delete.connect(pre_delete_entity, sender=Project)
pre_delete.connect(pre_delete_entity, sender=Tool)
pre_delete.connect(pre_delete_entity, sender=User)


class Reservation(CalendarDisplay):
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="reservation_user")
	creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="reservation_creator")
	creation_time = models.DateTimeField(default=timezone.now)
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True)
	project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, blank=True, help_text="Indicates the intended project for this reservation. A missed reservation would be billed to this project.")
	projects = models.ManyToManyField('Project', through='ReservationProject', related_name='reservation_projects')
	customers = models.ManyToManyField('User', through='ReservationProject', related_name='reservation_customers')
	start = models.DateTimeField('start')
	end = models.DateTimeField('end')
	short_notice = models.BooleanField(default=None, help_text="Indicates that the reservation was made after the configuration deadline for a tool. Laboratory staff may not have enough time to properly configure the tool before the user is scheduled to use it.")
	cancelled = models.BooleanField(default=False, help_text="Indicates that the reservation has been cancelled, moved, or resized.")
	cancellation_time = models.DateTimeField(null=True, blank=True)
	cancelled_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
	missed = models.BooleanField(default=False, help_text="Indicates that the tool was not enabled by anyone before the tool's \"missed reservation threshold\" passed.")
	shortened = models.BooleanField(default=False, help_text="Indicates that the user finished using the tool and relinquished the remaining time on their reservation. The reservation will no longer be visible on the calendar and a descendant reservation will be created in place of the existing one.")
	descendant = models.OneToOneField('Reservation', related_name='ancestor', on_delete=models.SET_NULL, null=True, blank=True, help_text="Any time a reservation is moved or resized, the old reservation is cancelled and a new reservation with updated information takes its place. This field links the old reservation to the new one, so the history of reservation moves & changes can be easily tracked.")
	additional_information = models.TextField(null=True, blank=True)
	self_configuration = models.BooleanField(default=False, help_text="When checked, indicates that the user will perform their own tool configuration (instead of requesting that the laboratory staff configure it for them).")
	title = models.TextField(default='', blank=True, max_length=200, help_text="Shows a custom title for this reservation on the calendar. Leave this field blank to display the reservation's user name as the title (which is the default behaviour).")
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)

	def duration(self):
		return self.end - self.start

	def has_not_ended(self):
		return False if self.end < timezone.now() else True

	@property
	def description(self):
		ep = ReservationProject.objects.filter(reservation=self)
		d = "<table class=\"table\"><thead><tr><th>Customer</th><th>Project</th></tr></thead><tbody>"

		if ep.exists():
			for e in ep:
				d += "<tr><td>" + e.customer.get_full_name() + "</td><td>" + str(e.project) + "</td></tr>"
			d += "</tbody></table>"
		else:
			d += "<tr><td>" + self.user.get_full_name() + "</td><td>" + str(self.project) + "</td></tr></tbody></table>"
		return d

	def mark_for_notice(self):

		return true

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)


class ReservationConfiguration(models.Model):
	reservation = models.ForeignKey('Reservation', on_delete=models.SET_NULL, null=True, blank=True)
	configuration = models.ForeignKey('Configuration', on_delete=models.SET_NULL, null=True, blank=True)
	consumable = models.ForeignKey('Consumable', on_delete=models.SET_NULL, null=True, blank=True)
	setting = models.TextField(null=True, blank=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)


class ReservationProject(models.Model):
	reservation = models.ForeignKey('Reservation', on_delete=models.SET_NULL, null=True, blank=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True)
	customer = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)
	sample = models.ManyToManyField('Sample', blank=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)


class ReservationNotification(models.Model):
	reservation = models.ForeignKey('Reservation', on_delete=models.SET_NULL, null=True, blank=True)
	user = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)


class UsageEvent(CalendarDisplay):
	user = models.ForeignKey(User, on_delete=models.SET_NULL, related_name="usage_event_user", null=True, blank=True)
	operator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="usage_event_operator")
	project = models.ForeignKey(Project, on_delete=models.SET_NULL, related_name="usage_event_project", null=True, blank=True)
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True, related_name='+')  # The related_name='+' disallows reverse lookups. Helper functions of other models should be used instead.
	start = models.DateTimeField(default=timezone.now)
	end = models.DateTimeField(null=True, blank=True)
	validated = models.BooleanField(default=False)
	contested = models.BooleanField(default=False)
	contest_data = GenericRelation('ContestTransactionData')
	contest_record = GenericRelation('ContestTransaction', related_query_name='usage_event_contests')
	run_data = models.TextField(null=True, blank=True)
	operator_comment = models.TextField(null=True, blank=True)
	projects = models.ManyToManyField('Project', through='UsageEventProject')
	customers = models.ManyToManyField('User', through='UsageEventProject')
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	validated_date = models.DateTimeField(null=True, blank=True)
	auto_validated = models.BooleanField(default=False)
	no_charge_flag = models.BooleanField(default=False)
	ad_hoc_created = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	end_scheduled_outage = models.BooleanField(default=False)
	cost_per_sample_run = models.BooleanField(default=False)
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='usage_event_transaction')

	# a feature to allow for a tool use to be stopped automatically requires some new fields
	end_time = models.DateTimeField(null=True, blank=True)
	set_for_autologout =  models.BooleanField(default=False)


	def duration(self):
		return calculate_duration(self.start, self.end, "In progress")

	def auto_validate(self):
		self.validated = True
		self.validated_date = timezone.now()
		self.auto_validated = True
		self.updated = timezone.now()
		self.save()

	def description(self):
		ep = UsageEventProject.objects.filter(usage_event=self, active_flag=True)
		d = "<table class=\"table\"><thead><tr><th>Customer</th><th>Project</th></tr></thead><tbody>"

		if ep.exists():
			for e in ep:
				d += "<tr><td>" + e.customer.get_full_name() + "</td><td>" + str(e.project) + "</td></tr>"
			d += "</tbody></table>"
		else:
			if self.user and self.project:
				d += "<tr><td>" + self.user.get_full_name() + "</td><td>" + str(self.project) + "</td></tr></tbody></table>"
			else:
				d += "<tr><td>Cannot find customer</td><td>Cannot find project</td></tr></tbody></table>"
		return d

	class Meta:
		ordering = ['-start']

	def __str__(self):
		return str(self.id)

class UsageEventProject(models.Model):
	usage_event = models.ForeignKey('UsageEvent', on_delete=models.SET_NULL, null=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True)
	project_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	customer = models.ForeignKey('User', on_delete=models.SET_NULL, null=True)
	comment = models.TextField(null=True, blank=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	contest_data = GenericRelation('ContestTransactionData')
	no_charge_flag = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	sample_num = models.IntegerField(null=True, blank=True)
	cost_per_sample = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
	#sample = models.ManyToManyField('Sample', blank=True, related_name='uep_sample')
	sample_detail = models.ManyToManyField('Sample', blank=True, through='UsageEventProjectSample', related_name='uep_sample_detail')
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='usage_event_project_transaction')

class UsageEventProjectSample(models.Model):
	sample = models.ForeignKey('Sample', on_delete=models.SET_NULL, null=True)
	usage_event_project = models.ForeignKey('UsageEventProject', on_delete=models.SET_NULL, null=True)
	notes =  models.TextField(null=True, blank=True)
	active_flag = models.BooleanField(default=True)
	created = models.DateTimeField(null=True, blank=True, default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True, default=timezone.now)

class Consumable(models.Model):
	name = models.CharField(max_length=100)
	category = models.ForeignKey('ConsumableCategory', on_delete=models.SET_NULL, blank=True, null=True)
	type = models.ForeignKey('ConsumableType', on_delete=models.SET_NULL, blank=True, null=True)
	unit = models.ForeignKey('ConsumableUnit', on_delete=models.SET_NULL, blank=True, null=True)
	quantity = models.IntegerField(help_text="The number of items currently in stock.")
	visible = models.BooleanField(default=True)
	reminder_threshold = models.IntegerField(help_text="More of this item should be ordered when the quantity falls below this threshold.")
	reminder_email = models.EmailField(help_text="An email will be sent to this address when the quantity of this item falls below the reminder threshold.")

	# add core_id to manage inventory for the appropriate core
	core_id = models.ForeignKey('Core', on_delete=models.SET_NULL, null=True, blank=True, related_name='consumable_core')
	credit_cost_collector = models.ForeignKey('CreditCostCollector', on_delete=models.SET_NULL, null=True, blank=True, related_name='consumable_cost_collector')

	# add related user for supply manager
	supply_manager = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='supply_manager')
	
	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name + ' (' + str(self.core_id.name) + ')'

class ConsumableUnit(models.Model):
	name = models.CharField(max_length=100)
	abbreviation = models.CharField(max_length=20)

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name

class ConsumableCategory(models.Model):
	name = models.CharField(max_length=100)

	class Meta:
		ordering = ['name']
		verbose_name_plural = 'Consumable categories'

	def __str__(self):
		return self.name


class ConsumableType(models.Model):
	name = models.CharField(max_length=250)
	class Meta:
		ordering = ['name']
		verbose_name_plural = 'Consumable types'

	def __str__(self):
		return self.name


class ConsumableWithdraw(models.Model):
	customer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="consumable_user", help_text="The user who will use the consumable item.")
	merchant = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="consumable_merchant", help_text="The staff member that performed the withdraw.")
	consumable = models.ForeignKey(Consumable, on_delete=models.SET_NULL, null=True)
	quantity = models.PositiveIntegerField()
	project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True, help_text="The withdraw will be billed to this project.")
	project_percent = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
	notes = models.TextField(null=True, blank=True)
	date = models.DateTimeField(default=timezone.now, help_text="The date and time when the user withdrew the consumable.")
	validated = models.BooleanField(default=False)
	contested = models.BooleanField(default=False)
	contest_data = GenericRelation('ContestTransactionData')
	contest_record = GenericRelation('ContestTransaction', related_query_name='consumable_withdraw_contests')
	updated = models.DateTimeField(null=True, blank=True)
	validated_date = models.DateTimeField(null=True, blank=True)
	auto_validated = models.BooleanField(default=False)
	no_charge_flag = models.BooleanField(default=False)
	active_flag = models.BooleanField(default=True)
	cost_per_sample_run = models.BooleanField(default=False)


	# adding related field for UsageEvent for the situation where a consumable is used during tool usage and then the charge is contested
	usage_event = models.ForeignKey('UsageEvent', on_delete=models.SET_NULL, related_name="consumable_usage_event", null=True, blank=True)
	work_order_transaction = GenericRelation('WorkOrderTransaction', related_query_name='consumable_withdraw_transaction')

	def auto_validate(self):
		self.validated = True
		self.validated_date = timezone.now()
		self.auto_validated = True
		self.updated = timezone.now()
		self.save()

	class Meta:
		ordering = ['-date']

	def __str__(self):
		return str(self.id)


class ConsumableOrder(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='order_user')
	project = models.ForeignKey(Project, on_delete=models.CASCADE)
	order_date = models.DateTimeField(auto_now_add=True)
	fulfilled = models.BooleanField(default=False)
	cancelled = models.BooleanField(default=False)
	created = models.DateTimeField(default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True)
	name = models.CharField(max_length=100, null=True, blank=True)
	description = models.TextField(null=True, blank=True)
	fulfilled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='order_fulfilled_by')
	cancelled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='order_cancelled_by')

	def __str__(self):
		return f"Order {self.id} - {self.name} - by {self.user.get_full_name()}"


class ConsumableOrderItem(models.Model):
	order = models.ForeignKey(ConsumableOrder, related_name='items', on_delete=models.CASCADE)
	consumable = models.ForeignKey(Consumable, on_delete=models.CASCADE)
	quantity = models.PositiveIntegerField()
	fulfilled = models.BooleanField(default=False)
	cancelled = models.BooleanField(default=False)
	notes = models.TextField(null=True, blank=True)
	fulfilled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='item_fulfilled_by')
	cancelled_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name='item_cancelled_by')
	created = models.DateTimeField(default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True)

	def __str__(self):
		return f"{self.quantity} of {self.consumable.name}"



class ContestTransaction(models.Model):
	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')

	contest_description = models.TextField(null=True, blank=True)
	contested_date = models.DateTimeField(null=True, blank=True)
	contest_resolved = models.BooleanField(default=False)
	contest_resolved_date = models.DateTimeField(null=True, blank=True)
	contest_resolution = models.BooleanField(default=False)
	contest_rejection_reason = models.TextField(null=True, blank=True)
	no_charge_flag = models.BooleanField(default=False)

	class Meta:
		ordering = ['content_type','-object_id']

	def __str__(self):
		return str(self.id)


class ContestTransactionData(models.Model):
	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')

	contest_transaction = models.ForeignKey('ContestTransaction', on_delete=models.SET_NULL, null=True)

	field_name = models.CharField(max_length=50)
	original_value = models.CharField(max_length=250)
	proposed_value = models.CharField(max_length=250)

	class Meta:
		ordering = ['content_type','-object_id']

	def __str__(self):
		return str(self.id)


class ContestTransactionNewData(models.Model):
	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	contest_transaction = models.ForeignKey('ContestTransaction', on_delete=models.SET_NULL, null=True)
	field_name = models.CharField(max_length=50)
	field_value = models.CharField(max_length=250)
	field_group = models.CharField(max_length=20)

	class Meta:
		ordering = ['content_type','contest_transaction']

	def __str__(self):
		return str(self.id)


class InterlockType(models.Model):
	name = models.CharField(max_length=100)
	relay_prefix = models.CharField(max_length=100, null=True, blank=True)
	relay_suffix = models.CharField(max_length=100, null=True, blank=True)
	power_on_value = models.IntegerField(null=True, blank=True)
	power_off_value = models.IntegerField(null=True, blank=True)

	class Meta:
		ordering = ['name']

	def __str__(self):
		 return str(self.name)


class InterlockCard(models.Model):
	server = models.CharField(max_length=100)
	port = models.PositiveIntegerField()
	number = models.PositiveIntegerField()
	even_port = models.PositiveIntegerField()
	odd_port = models.PositiveIntegerField()
	type = models.ForeignKey('InterlockType', on_delete=models.SET_NULL, null=True)
	

	class Meta:
		ordering = ['server', 'number']

	def __str__(self):
		return str(self.server) + ', card ' + str(self.number)


class Interlock(models.Model):
	class State(object):
		UNKNOWN = -1
		# The numeric command types for the interlock hardware:
		UNLOCKED = 1
		LOCKED = 2
		Choices = (
			(UNKNOWN, 'Unknown'),
			(UNLOCKED, 'Unlocked'),  # The 'unlocked' and 'locked' constants match the hardware command types to control the interlocks.
			(LOCKED, 'Locked'),
		)

	card = models.ForeignKey(InterlockCard, on_delete=models.SET_NULL, null=True)
	channel = models.PositiveIntegerField()
	state = models.IntegerField(choices=State.Choices, default=State.UNKNOWN)
	most_recent_reply = models.TextField(default="None")

	def unlock(self):
		return self.__issue_command(self.State.UNLOCKED)

	def lock(self):
		return self.__issue_command(self.State.LOCKED)

	def __issue_command(self, command_type):

		interlocks_logger = getLogger("NEMO.interlocks")

		try:
			# get command type value for card
			cmd_int = 0

			if command_type == self.State.LOCKED:
				cmd_int = self.card.type.power_off_value
			if command_type == self.State.UNLOCKED:
				cmd_int = self.card.type.power_on_value

			# build uri to toggle relay then call requests.get()
			uri = 'http://' + str(self.card.server) + '/state.xml?'
			if self.card.type.relay_prefix is not None:
				uri = uri + str(self.card.type.relay_prefix)
			uri = uri + str(self.channel)
			if self.card.type.relay_suffix is not None:
				uri = uri + str(self.card.type.relay_suffix)
			uri = uri + '=' + str(cmd_int)
			req = requests.get(uri, timeout=3.0)

			self.most_recent_reply = "Executed " + uri + " successfully at " + str(timezone.localtime(timezone.now()))
			self.state = command_type
			self.save()
			return self.state == command_type
		except requests.ConnectionError as e:
			self.most_recent_reply = "The request failed at " + str(timezone.localtime(timezone.now())) + " with the following message: " + str(e)
			self.save()
			return False
		except requests.Timeout as e:
			self.most_recent_reply = "The request failed at " + str(timezone.localtime(timezone.now())) + " with the following message: " + str(e)
			self.save()
			return False
		except requests.RequestException as e:
			self.most_recent_reply = "The request failed at " + str(timezone.localtime(timezone.now())) + " with the following message: " + str(e)
			self.save()
			return False
		except Exception as e:
			self.most_recent_reply = "The request failed at " + str(timezone.localtime(timezone.now())) + "with the following message: " + str(e)
			self.save()
			return False


	def pulse(self):
		try:
			return self.__issue_command(self.State.LOCKED)

		except requests.exceptions.RequestException as e:
			#print(e)
			self.most_recent_reply = "The request failed at " + str(timezone.localtime(timezone.now())) + " with the message: " + str(e)
			self.save()
			return False

	def remote_state(self):
		uri = 'http://' + str(self.card.server) + '/state.xml'
		req = None

		try:
			req = requests.get(uri, timeout=0.01)
			data = xmltodict.parse(req.text)
			s = str(self.card.type.relay_prefix) + str(self.channel)
			if self.card.type.relay_suffix is not None:
				s = s + str(self.card.type.relay_suffix)
			s = s.lower()
			req = data['datavalues'][s]

		except requests.exceptions.RequestException as e:
			return "The request failed at " + str(timezone.localtime(timezone.now())) + " with the message: " + str(e)

		return str(req)

	class Meta:
		unique_together = ('card', 'channel')
		ordering = ['card__server', 'card__number', 'channel']

	def __str__(self):
		return str(self.card) + ", channel " + str(self.channel)


class Task(models.Model):
	class Urgency(object):
		LOW = -1
		NORMAL = 0
		HIGH = 1
		Choices = (
			(LOW, 'Low'),
			(NORMAL, 'Normal'),
			(HIGH, 'High'),
		)
	urgency = models.IntegerField(choices=Urgency.Choices)
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True, help_text="The tool that this task relates to.")
	force_shutdown = models.BooleanField(default=None, help_text="Indicates that the tool this task relates to will be shutdown until the task is resolved.")
	safety_hazard = models.BooleanField(default=None, help_text="Indicates that this task represents a safety hazard to the laboratory.")
	creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_tasks", help_text="The user who created the task.")
	creation_time = models.DateTimeField(default=timezone.now, help_text="The date and time when the task was created.")
	problem_category = models.ForeignKey('TaskCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='problem_category')
	problem_description = models.TextField(blank=True, null=True)
	progress_description = models.TextField(blank=True, null=True)
	last_updated = models.DateTimeField(null=True, blank=True, help_text="The last time this task was modified. (Creating the task does not count as modifying it.)")
	last_updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, help_text="The last user who modified this task. This should always be a staff member.")
	estimated_resolution_time = models.DateTimeField(null=True, blank=True, help_text="The estimated date and time that the task will be resolved.")
	cancelled = models.BooleanField(default=False)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(null=True, blank=True, help_text="The timestamp of when the task was marked complete or cancelled.")
	resolver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='task_resolver', help_text="The staff member who resolved the task.")
	resolution_description = models.TextField(blank=True, null=True)
	resolution_category = models.ForeignKey('TaskCategory', on_delete=models.SET_NULL, null=True, blank=True, related_name='resolution_category')

	class Meta:
		ordering = ['-creation_time']

	def __str__(self):
		return str(self.id)

	def current_status(self):
		""" Returns the textual description of the current task status """
		try:
			return TaskHistory.objects.filter(task_id=self.id).latest().status
		except TaskHistory.DoesNotExist:
			return None


class TaskCategory(models.Model):
	class Stage(object):
		INITIAL_ASSESSMENT = 0
		COMPLETION = 1
		Choices = (
			(INITIAL_ASSESSMENT, 'Initial assessment'),
			(COMPLETION, 'Completion'),
		)
	name = models.CharField(max_length=100)
	stage = models.IntegerField(choices=Stage.Choices)

	class Meta:
		verbose_name_plural = "Task categories"
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class TaskStatus(models.Model):
	name = models.CharField(max_length=200, unique=True)
	notify_primary_tool_owner = models.BooleanField(default=False, help_text="Notify the primary tool owner when a task transitions to this status")
	notify_backup_tool_owners = models.BooleanField(default=False, help_text="Notify the backup tool owners when a task transitions to this status")
	notify_tool_notification_email = models.BooleanField(default=False, help_text="Send an email to the tool notification email address when a task transitions to this status")
	custom_notification_email_address = models.EmailField(blank=True, help_text="Notify a custom email address when a task transitions to this status. Leave this blank if you don't need it.")
	notification_message = models.TextField(blank=True)

	def __str__(self):
		return self.name

	class Meta:
		verbose_name_plural = 'task statuses'
		ordering = ['name']


class TaskHistory(models.Model):
	task = models.ForeignKey(Task, on_delete=models.SET_NULL, null=True, help_text='The task that this historical entry refers to', related_name='history')
	status = models.CharField(max_length=200, help_text="A text description of the task's status")
	time = models.DateTimeField(auto_now_add=True, help_text='The date and time when the task status was changed')
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, help_text='The user that changed the task to this status')

	class Meta:
		verbose_name_plural = 'task histories'
		ordering = ['time']
		get_latest_by = 'time'


class Comment(models.Model):
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True, help_text="The tool that this comment relates to.")
	author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	creation_date = models.DateTimeField(default=timezone.now)
	expiration_date = models.DateTimeField(blank=True, null=True, help_text="The comment will only be visible until this date.")
	visible = models.BooleanField(default=True)
	hide_date = models.DateTimeField(blank=True, null=True, help_text="The date when this comment was hidden. If it is still visible or has expired then this date should be empty.")
	hidden_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="hidden_comments")
	content = models.TextField()

	class Meta:
		ordering = ['-creation_date']

	def __str__(self):
		return str(self.id)


class ResourceCategory(models.Model):
	name = models.CharField(max_length=200)

	def __str__(self):
		return str(self.name)

	class Meta:
		verbose_name_plural = 'resource categories'
		ordering = ['name']


class Resource(models.Model):
	name = models.CharField(max_length=200)
	category = models.ForeignKey(ResourceCategory, on_delete=models.SET_NULL, blank=True, null=True)
	available = models.BooleanField(default=True, help_text="Indicates whether the resource is available to be used.")
	fully_dependent_tools = models.ManyToManyField(Tool, blank=True, related_name="required_resource_set", help_text="These tools will be completely inoperable if the resource is unavailable.")
	partially_dependent_tools = models.ManyToManyField(Tool, blank=True, related_name="nonrequired_resource_set", help_text="These tools depend on this resource but can operated at a reduced capacity if the resource is unavailable.")
	dependent_areas = models.ManyToManyField(Area, blank=True, related_name="required_resources", help_text="Users will not be able to login to these areas when the resource is unavailable.")
	restriction_message = models.TextField(blank=True, help_text="The message that is displayed to users on the tool control page when this resource is unavailable.")

	class Meta:
		ordering = ['name']

	def __str__(self):
		return self.name


class ActivityHistory(models.Model):
	"""
	Stores the history of when accounts, projects, and users are active.
	This class uses generic relations in order to point to any model type.
	For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
	"""

	class Action(object):
		ACTIVATED = True
		DEACTIVATED = False
		Choices = (
			(ACTIVATED, 'Activated'),
			(DEACTIVATED, 'Deactivated'),
		)

	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')
	action = models.BooleanField(choices=Action.Choices, default=None, help_text="The target state (activated or deactivated).")
	date = models.DateTimeField(default=timezone.now, help_text="The time at which the active state was changed.")
	authorizer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, help_text="The staff member who changed the active state of the account, project, or user in question.")

	class Meta:
		ordering = ['-date']
		verbose_name_plural = 'activity histories'

	def __str__(self):
		if self.action:
			state = "activated"
		else:
			state = "deactivated"
		return str(self.content_type).capitalize() + " " + str(self.object_id) + " " + state


class MembershipHistory(models.Model):
	"""
	Stores the history of membership between related items. For example, users can be members of projects.
	Likewise, projects can belong to accounts. This class uses generic relations in order to point to any model type.
	For more information see: https://docs.djangoproject.com/en/dev/ref/contrib/contenttypes/#generic-relations
	"""

	class Action(object):
		ADDED = True
		REMOVED = False
		Choices = (
			(ADDED, 'Added'),
			(REMOVED, 'Removed'),
		)

	# The parent entity can be either an account or project.
	parent_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, related_name="parent_content_type")
	parent_object_id = models.PositiveIntegerField()
	parent_content_object = GenericForeignKey('parent_content_type', 'parent_object_id')

	# The child entity can be either a project or user.
	child_content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True, related_name="child_content_type")
	child_object_id = models.PositiveIntegerField()
	child_content_object = GenericForeignKey('child_content_type', 'child_object_id')

	date = models.DateTimeField(default=timezone.now, help_text="The time at which the membership status was changed.")
	authorizer = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, help_text="The staff member who changed the membership status of the account, project, or user in question.")
	action = models.BooleanField(choices=Action.Choices, default=None)

	class Meta:
		ordering = ['-date']
		verbose_name_plural = 'membership histories'

	def __str__(self):
		return "Membership change for " + str(self.parent_content_type) + " " + str(self.parent_object_id)


def calculate_duration(start, end, unfinished_reason):
	"""
	Calculates the duration between two timestamps. If 'end' is None (thereby
	yielding the calculation impossible) then 'unfinished_reason' is returned.
	"""
	if start is None or end is None:
		return unfinished_reason
	else:
		return end - start


class Door(models.Model):
	name = models.CharField(max_length=100)
	area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True, related_name='doors')
	interlock = models.OneToOneField(Interlock, on_delete=models.SET_NULL, null=True)

	def __str__(self):
		return str(self.name)

	def get_absolute_url(self):
		return reverse('welcome_screen', args=[self.id])
	get_absolute_url.short_description = 'URL'


class PhysicalAccessLevel(models.Model):
	name = models.CharField(max_length=100)
	area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True)

	class Schedule(object):
		ALWAYS = 0
		WEEKDAYS_7AM_TO_MIDNIGHT = 1
		WEEKENDS = 2
		Choices = (
			(ALWAYS, "Always"),
			(WEEKDAYS_7AM_TO_MIDNIGHT, "Weekdays, 7am to midnight"),
			(WEEKENDS, "Weekends"),
		)
	schedule = models.IntegerField(choices=Schedule.Choices)

	def accessible(self):
		try:
			now = timezone.localtime(timezone.now())
		except:
			now = timezone.now()
		saturday = 6
		sunday = 7
		if self.schedule == self.Schedule.ALWAYS:
			return True
		elif self.schedule == self.Schedule.WEEKDAYS_7AM_TO_MIDNIGHT:
			if now.isoweekday() == saturday or now.isoweekday() == sunday:
				return False
			seven_am = datetime.time(hour=7, tzinfo=timezone.get_current_timezone())
			midnight = datetime.time(hour=23, minute=59, second=59, tzinfo=timezone.get_current_timezone())
			current_time = now.time()
			if seven_am < current_time < midnight:
				return True
		elif self.schedule == self.Schedule.WEEKENDS:
			if now.isoweekday() == saturday or now.isoweekday() == sunday:
				return True
		return False

	def __str__(self):
		return str(self.name)

	class Meta:
		ordering = ['name']


class PhysicalAccessType(object):
	DENY = False
	ALLOW = True
	Choices = (
		(False, 'Deny'),
		(True, 'Allow'),
	)


class PhysicalAccessLog(models.Model):
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	door = models.ForeignKey(Door, on_delete=models.SET_NULL, null=True)
	area = models.ForeignKey(Area, on_delete=models.SET_NULL, null=True)
	time = models.DateTimeField()
	result = models.BooleanField(choices=PhysicalAccessType.Choices, default=None)
	details = models.TextField(null=True, blank=True, help_text="Any details that should accompany the log entry. For example, the reason physical access was denied.")

	class Meta:
		ordering = ['-time']


class SafetyIssue(models.Model):
	reporter = models.ForeignKey(User, on_delete=models.SET_NULL, blank=True, null=True, related_name='reported_safety_issues')
	location = models.CharField(max_length=200, null=True, blank=True)
	creation_time = models.DateTimeField(auto_now_add=True)
	visible = models.BooleanField(default=True, help_text='Should this safety issue be visible to all users? When unchecked, the issue is only visible to staff.')
	concern = models.TextField()
	progress = models.TextField(blank=True, null=True)
	resolution = models.TextField(blank=True, null=True)
	resolved = models.BooleanField(default=False)
	resolution_time = models.DateTimeField(blank=True, null=True)
	resolver = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='resolved_safety_issues', blank=True, null=True)

	class Meta:
		ordering = ['-creation_time']

	def __str__(self):
		return str(self.id)

	def get_absolute_url(self):
		from django.urls import reverse
		return reverse('update_safety_issue', args=[self.id])


class Alert(models.Model):
	title = models.CharField(blank=True, max_length=100)
	contents = models.CharField(max_length=500)
	creation_time = models.DateTimeField(default=timezone.now)
	creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
	debut_time = models.DateTimeField(help_text='The alert will not be displayed to users until the debut time is reached.')
	expiration_time = models.DateTimeField(null=True, blank=True, help_text='The alert can be deleted after the expiration time is reached.')
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='alerts', help_text='The alert will be visible for this user. The alert is visible to all users when this is empty.')
	dismissible = models.BooleanField(default=False, help_text="Allows the user to delete the alert. This is only valid when the 'user' field is set.")

	class Meta:
		ordering = ['-debut_time']

	def __str__(self):
		return str(self.id)


class ContactInformationCategory(models.Model):
	name = models.CharField(max_length=200)
	display_order = models.IntegerField(help_text="Contact information categories are sorted according to display order. The lowest value category is displayed first in the 'Contact information' page.")

	class Meta:
		verbose_name_plural = 'Contact information categories'
		ordering = ['display_order', 'name']

	def __str__(self):
		return str(self.name)


class ContactInformation(models.Model):
	name = models.CharField(max_length=200, help_text="The name of the contact information; this can be related to a user or an organization.")
	image = models.ImageField(null=True, blank=True, help_text='Portraits are resized to 266 pixels high and 200 pixels wide. Crop portraits to these dimensions before uploading for optimal bandwidth usage')
	address1 = models.CharField(max_length=500, blank=True, null=True)
	address2 = models.CharField(max_length=500, blank=True, null=True)
	city = models.CharField(max_length=100, blank=True, null=True)
	state = models.CharField(max_length=50, blank=True, null=True)
	zipcode = models.CharField(max_length=20,  blank=True, null=True)
	country = models.CharField(max_length=50, blank=True, null=True)
	category = models.ForeignKey(ContactInformationCategory, on_delete=models.SET_NULL, null=True, blank=True)
	email = models.EmailField(blank=True, null=True)
	office_phone = models.CharField(max_length=40, blank=True, null=True)
	office_location = models.CharField(max_length=200, blank=True, null=True)
	mobile_phone = models.CharField(max_length=40, blank=True, null=True)
	mobile_phone_is_sms_capable = models.BooleanField(default=True, verbose_name='Mobile phone is SMS capable', help_text="Is the mobile phone capable of receiving text messages? If so, a link will be displayed for users to click to send a text message to the recipient when viewing the 'Contact information' page.")

	class Meta:
		verbose_name_plural = 'Contact information'
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class Notification(models.Model):
	user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='notifications')
	expiration = models.DateTimeField()
	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')

	class Types:
		NEWS = 'news'
		SAFETY = 'safetyissue'
		Choices = (
			(NEWS, 'News creation and updates - notifies all users'),
			(SAFETY, 'New safety issues - notifies staff only')
		)


class LandingPageChoice(models.Model):
	image = models.ImageField(help_text='An image that symbolizes the choice. It is automatically resized to 128x128 pixels when displayed, so set the image to this size before uploading to optimize bandwidth usage and landing page load time')
	name = models.CharField(max_length=40, help_text='The textual name that will be displayed underneath the image')
	url = models.CharField(max_length=200, verbose_name='URL', help_text='The URL that the choice leads to when clicked. Relative paths such as /calendar/ are used when linking within the LEO site. Use fully qualified URL paths such as https://www.google.com/ to link to external sites.')
	display_priority = models.IntegerField(help_text="The order in which choices are displayed on the landing page, from left to right, top to bottom. Lower values are displayed first.")
	open_in_new_tab = models.BooleanField(default=False, help_text="Open the URL in a new browser tab when it's clicked")
	secure_referral = models.BooleanField(default=True, help_text="Improves security by blocking HTTP referer [sic] information from the targeted page. Enabling this prevents the target page from manipulating the calling page's DOM with JavaScript. This should always be used for external links. It is safe to uncheck this when linking within the LEO site. Leave this box checked if you don't know what this means")
	hide_from_mobile_devices = models.BooleanField(default=False, help_text="Hides this choice when the landing page is viewed from a mobile device")
	hide_from_desktop_computers = models.BooleanField(default=False, help_text="Hides this choice when the landing page is viewed from a desktop computer")
	hide_from_users = models.BooleanField(default=False, help_text="Hides this choice from normal users. When checked, only staff, technicians, and super-users can see the choice")
	notifications = models.CharField(max_length=25, blank=True, null=True, choices=Notification.Types.Choices, help_text="Displays a the number of new notifications for the user. For example, if the user has two unread news notifications then the number '2' would appear for the news icon on the landing page.")

	class Meta:
		ordering = ['display_priority']

	def __str__(self):
		return str(self.name)


class Customization(models.Model):
	name = models.CharField(primary_key=True, max_length=50)
	value = models.TextField()

	class Meta:
		ordering = ['name']

	def __str__(self):
		return str(self.name)


class ScheduledOutageCategory(models.Model):
	name = models.CharField(max_length=200)

	class Meta:
		ordering = ['name']
		verbose_name_plural = "Scheduled outage categories"

	def __str__(self):
		return self.name


class ScheduledOutage(models.Model):
	start = models.DateTimeField()
	end = models.DateTimeField()
	creator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
	title = models.CharField(max_length=100, help_text="A brief description to quickly inform users about the outage")
	details = models.TextField(blank=True, help_text="A detailed description of why there is a scheduled outage, and what users can expect during the outage")
	category = models.CharField(blank=True, max_length=200, help_text="A categorical reason for why this outage is scheduled. Useful for trend analytics.")
	tool = models.ForeignKey(Tool, on_delete=models.SET_NULL, null=True)
	resource = models.ForeignKey(Resource, on_delete=models.SET_NULL, null=True)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)

	def __str__(self):
		return str(self.title)


class News(models.Model):
	title = models.CharField(max_length=200)
	created = models.DateTimeField(help_text="The date and time this story was first published")
	original_content = models.TextField(help_text="The content of the story when it was first published, useful for visually hiding updates 'in the middle' of the story")
	all_content = models.TextField(help_text="The entire content of the story")
	last_updated = models.DateTimeField(help_text="The date and time this story was last updated")
	last_update_content = models.TextField(help_text="The most recent update to the story, useful for visually hiding updates 'in the middle' of the story")
	archived = models.BooleanField(default=False, help_text="A story is removed from the 'Recent News' page when it is archived")
	update_count = models.PositiveIntegerField(help_text="The number of times this story has been updated. When the number of updates is greater than 2, then only the original story and the latest update are displayed in the 'Recent News' page")

	class Meta:
		ordering = ['-last_updated']
		verbose_name_plural = 'News'


class Core(models.Model):
	name = models.CharField(max_length=500)
	
	def __str__(self):
		return str(self.name)

class CreditCostCollector(models.Model):
	name = models.CharField(max_length=500)
	core = models.ForeignKey('Core', on_delete=models.SET_NULL, null=True, blank=True)
	project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True)

	def __str__(self):
		return str(self.name) + '[' + str(self.core) + ']' + '[' + str(self.project.project_number) + ']' 

class LockBilling(models.Model):
	fiscal_year = models.CharField(max_length=20, help_text="indicator for the fiscal year in the format 20192020")
	billing_month = models.PositiveIntegerField(help_text="integer indicating the month: 1 = January, 12 = December")
	billing_year = models.PositiveIntegerField(help_text="the current year for which the month is being locked")
	is_locked = models.BooleanField(default=False)
	is_closed = models.BooleanField(default=False)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)


class GlobalFlag(models.Model):
	name = models.CharField(max_length=200)
	active = models.BooleanField(default=False)

	def __str__(self):
		return self.name

class Organization(models.Model):
	name = models.CharField(max_length=500)
	organization_type = models.ForeignKey('OrganizationType', on_delete=models.SET_NULL, null=True, blank=True)
	billing_type = models.ForeignKey('BillingType', on_delete=models.SET_NULL, null=True, blank=True)
	url = models.CharField(max_length=500, null=True, blank=True)
	contact = models.ForeignKey('ContactInformation', on_delete=models.SET_NULL, null=True, blank=True)

	def __str__(self):
		return self.name

class OrganizationType(models.Model):
	name = models.CharField(max_length=50)
	nsf_category = models.ForeignKey('NsfCategory', on_delete=models.SET_NULL, null=True, blank=True)
	active = models.BooleanField(default=False)

	def __str__(self):
		return self.name

class BillingType(models.Model):
	name = models.CharField(max_length=50)

	def __str__(self):
		return self.name

class NsfCategory(models.Model):
	name = models.CharField(max_length=50)
	sort_order = models.PositiveIntegerField(help_text="Sorting for list that is otherwise not inherently logical")

	def __str__(self):
		return self.name


class FICO_COA_Person_Responsible(models.Model):
	cost_center = models.CharField(max_length=10, null=True, blank=True)
	internal_order = models.CharField(max_length=12, null=True, blank=True)
	wbs_element = models.CharField(max_length=12, null=True, blank=True)
	access_id = models.CharField(max_length=8, null=True, blank=True)
	grant = models.CharField(max_length=20, null=True, blank=True)
	fund = models.CharField(max_length=10, null=True, blank=True)
	grant_valid_to_date = models.DateField(null=True, blank=True)
	sp_indicator = models.CharField(max_length=1, null=True, blank=True)


class FICO_COA(models.Model):
	business_area = models.CharField(max_length=4, null=True, blank=True)
	department = models.CharField(max_length=5, null=True, blank=True)
	cost_center = models.CharField(max_length=10, null=True, blank=True)
	internal_order = models.CharField(max_length=12, null=True, blank=True)
	wbs_element = models.CharField(max_length=12, null=True, blank=True)
	zdescr = models.CharField(max_length=40, null=True, blank=True)
	start_date = models.DateField(null=True, blank=True)
	end_date = models.DateField(null=True, blank=True)
	chargeable_flag = models.CharField(max_length=1, null=True, blank=True)


class FICO_GL_ACCT(models.Model):
	gl_account = models.CharField(max_length=8, null=True, blank=True)
	gl_account_name = models.CharField(max_length=20, null=True, blank=True)
	start_date = models.DateField(null=True, blank=True)
	end_date = models.DateField(null=True, blank=True)



class EmailLog(models.Model):
	category = models.IntegerField(choices=EmailCategory.Choices, default=EmailCategory.GENERAL)
	when = models.DateTimeField(null=False, auto_now_add=True)
	sender = models.EmailField(null=False, blank=False)
	to = models.TextField(null=False, blank=False)
	subject = models.CharField(null=False, max_length=254)
	content = models.TextField(null=False)
	ok = models.BooleanField(null=False, default=True)
	attachments = models.TextField(null=True)

	class Meta:
		ordering = ['-when']


class NotificationSchemeToolAction(models.Model):
	tool = models.ForeignKey('Tool', on_delete=models.SET_NULL, null=True, blank=True)
	recipient = models.CharField(null=False, blank=False, max_length=255)
	event = models.CharField(null=False, blank=False, max_length=50)
	frequency = models.CharField(null=False, blank=False, max_length=255)
	created = models.DateTimeField(null=True, blank=True)
	updated = models.DateTimeField(null=True, blank=True)
	created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='nsta_created_by')
	updated_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='nsta_updated_by')


class Sample(models.Model):
	identifier = models.CharField(null=True,blank=True,max_length=255)
	nickname = models.CharField(null=True,blank=True,max_length=500)
	customer_nickname = models.CharField(null=True,blank=True,max_length=500)
	description = models.TextField(null=True,blank=True)
	project = models.ManyToManyField("Project", blank=True, related_name="sample_project")
	parent_sample = models.ForeignKey('self',null=True,blank=True,on_delete=models.SET_NULL,related_name='precursor')
	active_flag = models.BooleanField(null=False, blank=False, default=True)
	created = models.DateTimeField(null=True, blank=True, default=timezone.now)
	created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sample_created_by')
	updated = models.DateTimeField(null=True, blank=True, default=timezone.now)
	updated_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sample_updated_by')

	def __str__(self):
		return str(self.nickname) + " (" + str(self.created_by) + ") - " + str(self.identifier)


class WorkOrder(models.Model):
	work_order_number = models.CharField(null=True,blank=True,unique=True,max_length=500)
	status = models.PositiveIntegerField()
	customer = models.ForeignKey('User',on_delete=models.SET_NULL, null=True, related_name='customer')
	work_order_type = models.PositiveIntegerField(default=1)
	notes = models.TextField(null=True,blank=True)
	created = models.DateTimeField(null=True, blank=True, default=timezone.now)
	updated = models.DateTimeField(null=True, blank=True)
	closed = models.DateTimeField(null=True, blank=True)
	processed = models.DateTimeField(null=True, blank=True)
	created_by = models.ForeignKey('User',on_delete=models.SET_NULL, null=True, related_name='created_by')

	def __str__(self):
		return "Work Order " + str(self.work_order_number) + " for " + str(self.customer.first_name) + " " + str(self.customer.last_name)

class WorkOrderTransaction(models.Model):
	work_order = models.ForeignKey('WorkOrder',null=True,blank=True,on_delete=models.SET_NULL)
	content_type = models.ForeignKey(ContentType, on_delete=models.SET_NULL, null=True)
	object_id = models.PositiveIntegerField()
	content_object = GenericForeignKey('content_type', 'object_id')

	def __str__(self):
		return "Work Order " + str(self.work_order.work_order_number) + " item " + str(self.content_type.model) + " with id " + str(self.object_id)


