from django import forms
from django.contrib import admin
from django.contrib.admin import register, widgets
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Permission
from django.utils import timezone

from microsoft_auth.models import MicrosoftAccount
from microsoft_auth.admin import MicrosoftAccountAdmin

from NEMO.actions import lock_selected_interlocks, synchronize_with_tool_usage, unlock_selected_interlocks
from NEMO.models import Account, ActivityHistory, Alert, Area, AreaAccessRecord, AreaAccessRecordProject, AreaRequirement, BillingType, Comment, Configuration, ConfigurationHistory, Consumable, ConsumableOrder, ConsumableOrderItem, ConsumableUnit, ConsumableCategory, ConsumableType, ConsumableWithdraw, ContactInformation, ContactInformationCategory, ContestTransaction, ContestTransactionData, ContestTransactionNewData, Core, CreditCostCollector, Customization, Door, EmailLog, GlobalFlag, Interlock, InterlockCard, InterlockType, LandingPageChoice, LockBilling, MembershipHistory, News, Notification, NsfCategory, Organization, OrganizationType, PhysicalAccessLevel, PhysicalAccessLog, Project, Project2DCC, Requirement, Reservation, ReservationConfiguration, ReservationProject, Resource, ResourceCategory, SafetyIssue, Sample, ScheduledOutage, ScheduledOutageCategory, ServiceType, StaffCharge, StaffChargeProject, Task, TaskCategory, TaskHistory, TaskStatus, Tool, ToolRequirement, TrainingSession, UsageEvent, UsageEventProject, User, UserType, UserProfile, UserProfileSetting, UserRequirementProgress
from NEMO.utilities import send_mail
from NEMO.views.customization import get_customization, get_media_file_contents


admin.site.site_header = "LEO"
admin.site.site_title = "LEO"
admin.site.index_title = "Detailed administration"
admin.site.disable_action('delete_selected')

def change_view(self, request, object_id=None, form_url='', extra_context=None):
	return super().change_view(request, object_id, form_url, extra_context=dict(show_delete=False))

def record_remote_many_to_many_changes_and_save(request, obj, form, change, many_to_many_field, save_function_pointer):
	"""
	Record the changes in a many-to-many field that the model does not own. Then, save the many-to-many field.
	"""
	# If the model object is being changed then we can get the list of previous members.
	if change:
		original_members = set(obj.user_set.all())
	else:  # The model object is being created (instead of changed) so we can assume there are no members (initially).
		original_members = set()
	current_members = set(form.cleaned_data[many_to_many_field])
	added_members = []
	removed_members = []

	# Log membership changes if they occurred.
	symmetric_difference = original_members ^ current_members
	if symmetric_difference:
		if change:  # the members have changed, so find out what was added and removed...
			# We can can see the previous members of the object model by looking it up
			# in the database because the member list hasn't been committed yet.
			added_members = set(current_members) - set(original_members)
			removed_members = set(original_members) - set(current_members)

		else:  # a model object is being created (instead of changed) so we can assume all the members are new...
			added_members = form.cleaned_data[many_to_many_field]

	# A primary key for the object is required to make many-to-many field changes.
	# If the object is being changed then it has already been assigned a primary key.
	if not change:
		save_function_pointer(request, obj, form, change)
	obj.user_set.set(form.cleaned_data[many_to_many_field])
	save_function_pointer(request, obj, form, change)

	# Record which members were added to the object.
	for user in added_members:
		new_member = MembershipHistory()
		new_member.authorizer = request.user
		new_member.parent_content_object = obj
		new_member.child_content_object = user
		new_member.action = MembershipHistory.Action.ADDED
		new_member.save()

	# Record which members were removed from the object.
	for user in removed_members:
		ex_member = MembershipHistory()
		ex_member.authorizer = request.user
		ex_member.parent_content_object = obj
		ex_member.child_content_object = user
		ex_member.action = MembershipHistory.Action.REMOVED
		ex_member.save()


def record_local_many_to_many_changes(request, obj, form, many_to_many_field):
	"""
	Record the changes in a many-to-many field that the model owns.
	"""
	if many_to_many_field in form.changed_data:
		original_members = set(getattr(obj, many_to_many_field).all())
		current_members = set(form.cleaned_data[many_to_many_field])
		added_members = set(current_members) - set(original_members)
		for a in added_members:
			p = MembershipHistory()
			p.action = MembershipHistory.Action.ADDED
			p.authorizer = request.user
			p.child_content_object = obj
			p.parent_content_object = a
			p.save()
		removed_members = set(original_members) - set(current_members)
		for a in removed_members:
			p = MembershipHistory()
			p.action = MembershipHistory.Action.REMOVED
			p.authorizer = request.user
			p.child_content_object = obj
			p.parent_content_object = a
			p.save()


def record_active_state(request, obj, form, field_name, is_initial_creation):
	"""
	Record whether the account, project, or user is active when the active state is changed.
	"""
	if field_name in form.changed_data or is_initial_creation:
		activity_entry = ActivityHistory()
		activity_entry.authorizer = request.user
		activity_entry.action = getattr(obj, field_name)
		activity_entry.content_object = obj
		activity_entry.save()


class ToolAdminForm(forms.ModelForm):
	class Meta:
		model = Tool
		fields = '__all__'

#	qualified_users = forms.ModelMultipleChoiceField(
#		queryset=User.objects.all(),
#		required=False,
#		widget=FilteredSelectMultiple(
#			verbose_name='Users',
#			is_stacked=False
#		)
#	)

	backup_owners = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	interlocks = forms.ModelMultipleChoiceField(
		queryset=Interlock.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Interlocks',
			is_stacked=False
		)
	)

	required_resources = forms.ModelMultipleChoiceField(
		queryset=Resource.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Required resources',
			is_stacked=False
		)
	)

	nonrequired_resources = forms.ModelMultipleChoiceField(
		queryset=Resource.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Nonrequired resources',
			is_stacked=False
		)
	)

	service_types = forms.ModelMultipleChoiceField(
		queryset=ServiceType.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Service Types',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			#self.fields['qualified_users'].initial = self.instance.user_set.all()
			self.fields['required_resources'].initial = self.instance.required_resource_set.all()
			self.fields['nonrequired_resources'].initial = self.instance.nonrequired_resource_set.all()


class ToolRequirementInline(admin.TabularInline):
    model = ToolRequirement
    extra = 1

class AreaRequirementInline(admin.TabularInline):
    model = AreaRequirement
    extra = 1

@register(Tool)
class ToolAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'core_id', 'visible', 'operational', 'primary_owner')
	list_filter = ('visible', 'operational', 'core_id')
	inlines = [ToolRequirementInline]
	form = ToolAdminForm

	search_fields = ('name', 'category')
	autocomplete_fields = ['primary_owner', 'credit_cost_collector']
#	readonly_fields = ('qualified_users',)

	def change_view(self, request, object_id, form_url='', extra_context=None):
		if request.user.is_superuser:
			self.fieldsets = (
				(None, {'fields': ('name', 'category', 'core_id', 'credit_cost_collector'),}),
				('Current state', {'fields': ('post_usage_questions', 'visible', 'operational'),}),
				('Contact information', {'fields': ('primary_owner', 'backup_owners', 'notification_email_address', 'location', 'phone_number','infolink'),}),
				('Usage policy', {'fields': ('qualification_duration', 'reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'requires_area_access', 'grant_physical_access_level_upon_qualification', 'grant_badge_reader_access_upon_qualification', 'interlocks', 'allow_delayed_logoff', 'reservation_required', 'allow_autologout','service_types'),}),
				('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
			)
		else:
			self.fieldsets = (
				(None, {'fields': ('name', 'category', 'core_id'),}),
				('Current state', {'fields': ('visible', 'operational'),}),
				('Contact information', {'fields': ('primary_owner', 'backup_owners', 'notification_email_address', 'location', 'phone_number','infolink'),}),
				('Usage policy', {'fields': ('reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'requires_area_access', 'grant_physical_access_level_upon_qualification', 'grant_badge_reader_access_upon_qualification', 'interlocks', 'allow_delayed_logoff', 'reservation_required', 'allow_autologout','service_types'),}),
				('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
			)
		return super().change_view(request, object_id, form_url, extra_context)

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any project membership changes.
		"""
		#record_remote_many_to_many_changes_and_save(request, obj, form, change, 'qualified_users', super().save_model)
		super().save_model(request, obj, form, change)
		if 'required_resources' in form.changed_data:
			obj.required_resource_set.set(form.cleaned_data['required_resources'])
		if 'nonrequired_resources' in form.changed_data:
			obj.nonrequired_resource_set.set(form.cleaned_data['nonrequired_resources'])

	def get_queryset(self, request):
		qs = super().get_queryset(request)
		if request.user.is_superuser:
			return qs
		return qs.filter(core_id__in=request.user.core_ids.all())

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'credit_cost_collector':
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		return super(ToolAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False



#@register(MicrosoftAccount)
class UpdatedMicrosoftAccountAdmin(MicrosoftAccountAdmin):
	list_display = ('id', 'microsoft_id', 'user')
	search_fields = ('microsoft_id', 'user__username', 'user__last_name', 'user__first_name')

	def has_delete_permission(self, request, obj=None):
		return False

admin.site.unregister(MicrosoftAccount)
admin.site.register(MicrosoftAccount, UpdatedMicrosoftAccountAdmin)

@register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
	list_display = ('id', 'trainer', 'trainee', 'tool', 'project', 'type', 'date', 'duration', 'qualified')
	list_filter = ('qualified', 'date', 'type')
	date_hierarchy = 'date'

	search_fields = ('trainee__first_name','trainee__last_name','trainer__first_name','trainer__last_name','project__project_number')
	autocomplete_fields = ['trainer', 'trainee', 'tool', 'project']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(TrainingSessionAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

class StaffChargeAdminForm(forms.ModelForm):
	def clean(self):
		start_date = self.cleaned_data.get('start')
		end_date = self.cleaned_data.get('end')
		if start_date > end_date:
			raise forms.ValidationError("Start date must be before end date.")
		return self.cleaned_data

@register(StaffCharge)
class StaffChargeAdmin(admin.ModelAdmin):
	list_display = ('id', 'staff_member', 'customer', 'start', 'end', 'duration')
	list_filter = ('start',)
	date_hierarchy = 'start'
	ordering = ['-id']

	form = StaffChargeAdminForm

	search_fields = ('staff_member__first_name','staff_member__last_name','projects__project_number')
	autocomplete_fields = ['staff_member', 'customer', 'project']

	exclude = ('related_usage_event','related_override_charge')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(StaffChargeAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(StaffChargeProject)
class StaffChargeProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'staff_charge', 'customer', 'project', 'project_percent')

	search_fields = ('customer__first_name','customer__last_name','project__project_number','staff_charge__id')

	autocomplete_fields = ['staff_charge', 'project', 'customer']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(StaffChargeProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

class AreaAccessRecordAdminForm(forms.ModelForm):
	def clean(self):
		start_date = self.cleaned_data.get('start')
		end_date = self.cleaned_data.get('end')
		if start_date > end_date:
			raise forms.ValidationError("Start date must be before end date.")
		return self.cleaned_data

@register(AreaAccessRecord)
class AreaAccessRecordAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'area', 'project', 'start', 'end')
	list_filter = ('area', 'start',)
	date_hierarchy = 'start'

	form = AreaAccessRecordAdminForm

	search_fields = ('area__name', 'customers__first_name','customers__last_name','projects__project_number')
	autocomplete_fields = ['customer', 'user', 'area', 'project']

	exclude = ('related_usage_event',)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(AreaAccessRecordAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(AreaAccessRecordProject)
class AreaAccessRecordProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'area_access_record', 'customer', 'project', 'project_percent')

	search_fields = ('customer__first_name','customer__last_name','project__project_number')
	autocomplete_fields = ['area_access_record', 'project', 'customer']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(AreaAccessRecordProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'name', 'qualified_users_are_maintainers', 'display_priority', 'exclude_from_configuration_agenda')
	filter_horizontal = ('maintainers',)

	search_fields = ('tool__name', 'name', 'consumable__name')
	autocomplete_fields = ['tool']

	#def change_view(self, request, object_id, form_url='', extra_context=None):
	#	if not request.user.is_superuser:
	#		self.exclude = ('current_settings',)
	#	return super().change_view(request, object_id, form_url, extra_context)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "tool":
			if not request.user.is_superuser:
				kwargs["queryset"] = Tool.objects.filter(core_id__in=request.user.core_ids.all())
		return super().formfield_for_foreignkey(db_field, request, **kwargs)

	def formfield_for_manytomany(self, db_field, request, **kwargs):
		if db_field.name == "consumable":
			vertical = False
			kwargs['widget'] = widgets.FilteredSelectMultiple(
				verbose_name = db_field.verbose_name,
				is_stacked = vertical,
			)
			kwargs['queryset'] = Consumable.objects.all()
			if not request.user.is_superuser:
				kwargs['queryset'] = Consumable.objects.filter(core_id__in=request.user.core_ids.all(), category__name__exact='Consumables')
			else:
				kwargs['queryset'] = Consumable.objects.filter(category__name__exact='Consumables')
		return super().formfield_for_manytomany(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(ConfigurationHistory)
class ConfigurationHistoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'configuration', 'user', 'modification_time', 'slot')
	date_hierarchy = 'modification_time'

	search_fields = ('user__first_name', 'user__last_name', 'configuration__tool__name')

	autocomplete_fields = ['configuration', 'user']

	def has_delete_permission(self, request, obj=None):
		return False


@register(Account)
class AccountAdmin(admin.ModelAdmin):
	list_display = ('id', 'name','simba_cost_center', 'ibis_account', 'owner', 'active')
	search_fields = ('name','simba_cost_center', 'ibis_account')
	list_filter = ('active',)

	def save_model(self, request, obj, form, change):
		""" Audit account and project active status. """
		super().save_model(request, obj, form, change)
		record_active_state(request, obj, form, 'active', not change)

	def has_delete_permission(self, request, obj=None):
		return False


class ProjectAdminForm(forms.ModelForm):
	class Meta:
		model = Project
		fields = '__all__'

	members = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['members'].initial = self.instance.user_set.all()


@register(Project)
class ProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'project_number', 'simba_cost_center', 'internal_order', 'wbs_element', 'account', 'organization', 'owner', 'bill_to', 'end_date', 'active')
	search_fields = ('name', 'organization__name', 'internal_order', 'wbs_element', 'application_identifier', 'account__name', 'simba_cost_center', 'owner__first_name', 'owner__last_name', 'owner__username', 'bill_to__first_name', 'bill_to__last_name', 'bill_to__username', 'project_number')
	autocomplete_fields = ['organization', 'account', 'owner', 'bill_to', 'bill_to_alt', 'billing_type']
	list_filter = ('active',)
	exclude = ('account',)
	autocomplete_fields = ['organization', 'bill_to', 'bill_to_alt', 'owner']
	form = ProjectAdminForm

	def save_model(self, request, obj, form, change):
		"""
		Audit project creation and modification. Also save any project membership changes explicitly.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'members', super().save_model)
		# Make a history entry if a project has been moved under an account.
		# This applies to newly created projects and project ownership reassignment.
		if 'account' in form.changed_data:
			# Create a membership removal entry for the project if it used to belong to another account:
			if change:
				previous_account = MembershipHistory()
				previous_account.authorizer = request.user
				previous_account.child_content_object = obj
				previous_account.parent_content_object = Account.objects.get(pk=form.initial['account'])
				previous_account.action = MembershipHistory.Action.REMOVED
				previous_account.save()

			# Create a membership addition entry for the project with its current account.
			current_account = MembershipHistory()
			current_account.authorizer = request.user
			current_account.child_content_object = obj
			current_account.parent_content_object = obj.account
			current_account.action = MembershipHistory.Action.ADDED
			current_account.save()

		# Record whether the project is active or not.
		record_active_state(request, obj, form, 'active', not change)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "account":
			kwargs["queryset"] = Account.objects.order_by('name')
		if db_field.name == "owner" or db_field.name == "bill_to" or db_field.name == "bill_to_alt":
			kwargs["queryset"] = User.objects.filter(is_active=True).order_by('last_name', 'first_name')
		return super(ProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


class Project2DCCAdminForm(forms.ModelForm):
	class Meta:
		model = Project2DCC
		fields = '__all__'

	members = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['members'].initial = self.instance.user_set.all()


@register(Project2DCC)
class Project2DCCAdmin(admin.ModelAdmin):

	search_fields = ('project_id', 'leo_project__project_number', 'leo_project__name')
	list_display = ('project_id', 'get_project_number', 'get_project_name')
	form = Project2DCCAdminForm
	autocomplete_fields = ['leo_project']

	def get_project_name(self, obj):
		return obj.leo_project.name
	get_project_name.admin_order_field = 'project'
	get_project_name.short_description = 'Project Name'

	def get_project_number(self, obj):
		return obj.leo_project.project_number
	get_project_number.admin_order_field = 'project'
	get_project_number.short_description = 'Project Number'

	def save_model(self, request, obj, form, change):
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'members', super().save_model)
		#super().save_model(request, obj, form, change)

		#record_local_many_to_many_changes(request, obj, form, 'users')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'leo_project':
			kwargs["queryset"] = Project.objects.filter(active=True, end_date__gt=timezone.now().date()).order_by('project_number')
		return super(Project2DCCAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False
	


@register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'creator', 'tool', 'project', 'additional_information', 'start', 'end', 'duration', 'cancelled', 'missed')
	list_filter = ('cancelled', 'missed')
	date_hierarchy = 'start'

	search_fields = ('user__first_name', 'user__last_name', 'tool__name', 'projects__project_number')
	autocomplete_fields = ['user', 'creator', 'tool', 'project']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(ReservationAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ReservationConfiguration)
class ReservationConfigurationAdmin(admin.ModelAdmin):
	list_display = ('id', 'reservation', 'configuration', 'consumable')

	search_fields = ('reservation__user__first_name', 'reservation__user__last_name', 'reservation__tool__name', 'reservation__projects__project_number')
	autocomplete_fields = ['reservation', 'configuration', 'consumable']

	def has_delete_permission(self, request, obj=None):
		return False

@register(ReservationProject)
class ReservationProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'reservation', 'project', 'customer')

	search_fields = ('project__project_number', 'customer__first_name', 'customer__last_name')
	autocomplete_fields = ['reservation', 'project', 'customer']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(ReservationProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

class UsageEventAdminForm(forms.ModelForm):
	def clean(self):
		start_date = self.cleaned_data.get('start')
		end_date = self.cleaned_data.get('end')
		if start_date > end_date:
			raise forms.ValidationError("Start date must be before end date.")
		return self.cleaned_data

@register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'user', 'operator', 'project', 'start', 'end', 'duration', 'run_data')
	list_filter = ('start', 'end')
	date_hierarchy = 'start'

	form = UsageEventAdminForm

	search_fields = ('tool__name', 'projects__project_number', 'customers__first_name', 'customers__last_name')
	autocomplete_fields = ['tool', 'user', 'operator', 'project']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(UsageEventAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

	def clean(self):
		start_date = self.cleaned_data.get('start')
		end_date = self.cleaned_data.get('end')
		if start_date > end_date:
			raise forms.ValidationError("Start date must be before end date.")
		return self.cleaned_data

@register(UsageEventProject)
class UsageEventProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'usage_event', 'customer', 'project', 'project_percent')

	search_fields = ('project__project_number', 'customer__first_name', 'customer__last_name', 'usage_event__id')
	autocomplete_fields = ['usage_event', 'project', 'customer']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(UsageEventProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'quantity', 'category', 'reminder_email', 'core_id', 'supply_manager')
	list_filter = ('visible', 'category')
	search_fields = ('name', 'category__name')
	autocomplete_fields = ['supply_manager']

	def has_delete_permission(self, request, obj=None):
		return False

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "credit_cost_collector":
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		if db_field.name == "supply_manager":
			kwargs["queryset"] = User.objects.filter(
				is_active=True).order_by('last_name', 'first_name')
		return super(ConsumableAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)


@register(ConsumableUnit)
class ConsumableUnitAdmin(admin.ModelAdmin):
	list_display = ('name', 'abbreviation')

	search_fields = ('name', 'abbreviation')

	def has_delete_permission(self, request, obj=None):
		return False

@register(ConsumableCategory)
class ConsumableCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)

	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(ConsumableType)
class ConsumableTypeAdmin(admin.ModelAdmin):
	list_display = ('name',)

	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'merchant', 'consumable', 'quantity', 'project', 'date')
	date_hierarchy = 'date'

	search_fields = ('customer__first_name', 'customer__last_name', 'merchant__first_name', 'merchant__last_name', 'project__project_number','consumable__name')
	autocomplete_fields = ['customer', 'merchant', 'consumable', 'project']

	exclude = ('usage_event',)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(ConsumableWithdrawAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ConsumableOrder)
class ConsumableOrderAdmin(admin.ModelAdmin):
	list_display = ('name',)

	search_fields = ('name',)
	autocomplete_fields = ['user', 'project', 'fulfilled_by', 'cancelled_by']

	def has_delete_permission(self, request, obj=None):
		return False


@register(ConsumableOrderItem)
class ConsumableOrderItemAdmin(admin.ModelAdmin):
	list_display = ('order__name',)

	search_fields = ('order__name',)
	autocomplete_fields = ['order', 'consumable', 'fulfilled_by', 'cancelled_by', 'consumable_withdraw']

	def has_delete_permission(self, request, obj=None):
		return False


@register(InterlockCard)
class InterlockCardAdmin(admin.ModelAdmin):
	list_display = ('server', 'port', 'number', 'even_port', 'odd_port')

	search_fields = ('server',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(Interlock)
class InterlockAdmin(admin.ModelAdmin):
	list_display = ('id', 'card', 'channel', 'state', 'tool')
	actions = [lock_selected_interlocks, unlock_selected_interlocks, synchronize_with_tool_usage]
	readonly_fields = ['state', 'most_recent_reply']

	search_fields = ('tool__name', 'card__server')
	autocomplete_fields = ['card']

	def has_delete_permission(self, request, obj=None):
		return False


@register(InterlockType)
class InterlockTypeAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'power_on_value', 'power_off_value', 'relay_prefix', 'relay_suffix')
	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Task)
class TaskAdmin(admin.ModelAdmin):
	list_display = ('id', 'urgency', 'tool', 'creator', 'creation_time', 'problem_category', 'cancelled', 'resolved', 'resolution_category')
	list_filter = ('urgency', 'resolved', 'cancelled', 'safety_hazard', 'creation_time')
	date_hierarchy = 'creation_time'

	search_fields = ('tool__name', 'creator__first_name', 'creator__last_name')
	autocomplete_fields = ['tool', 'creator', 'resolver', 'last_updated_by']

	def has_delete_permission(self, request, obj=None):
		return False

@register(TaskCategory)
class TaskCategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'stage')

	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(TaskStatus)
class TaskStatusAdmin(admin.ModelAdmin):
	list_display = ('name', 'notify_primary_tool_owner', 'notify_backup_tool_owners', 'notify_tool_notification_email', 'custom_notification_email_address')

	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(TaskHistory)
class TaskHistoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'task', 'status', 'time', 'user')
	readonly_fields = ('time',)
	date_hierarchy = 'time'

	search_fields = ('task__tool__name', 'user__first_name', 'user__last_name')
	autocomplete_fields = ['task', 'user']

	def has_delete_permission(self, request, obj=None):
		return False

@register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'author', 'creation_date', 'expiration_date', 'visible', 'hidden_by', 'hide_date')
	list_filter = ('visible', 'creation_date')
	date_hierarchy = 'creation_date'
	search_fields = ('content',)
	autocomplete_fields = ['tool', 'author', 'hidden_by']

	def has_delete_permission(self, request, obj=None):
		return False

@register(Resource)
class ResourceAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'available')
	list_filter = ('available', 'category')
	filter_horizontal = ('fully_dependent_tools', 'partially_dependent_tools', 'dependent_areas')

	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ActivityHistory)
class ActivityHistoryAdmin(admin.ModelAdmin):
	list_display = ('__str__', 'content_type', 'object_id', 'action', 'date', 'authorizer')
	date_hierarchy = 'date'
	autocomplete_fields = ['authorizer']

	def has_delete_permission(self, request, obj=None):
		return False

@register(MembershipHistory)
class MembershipHistoryAdmin(admin.ModelAdmin):
	list_display = ('__str__', 'parent_content_type', 'parent_object_id', 'action', 'child_content_type', 'child_object_id', 'date', 'authorizer')
	date_hierarchy = 'date'
	autocomplete_fields = ['authorizer']

	def has_delete_permission(self, request, obj=None):
		return False


@register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
	list_display = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

if admin.site.is_registered(User):
	admin.site.unregister(User)

@register(User)
class UserAdmin(admin.ModelAdmin):
	filter_horizontal = ('groups', 'user_permissions', 'projects', 'projects2dcc', 'physical_access_levels', 'pi_delegates', 'watching')
	fieldsets = (
		('Personal information', {'fields': ('first_name', 'last_name', 'username', 'email', 'badge_number', 'type', 'domain', 'credit_cost_collector', 'core_ids', 'contact', 'projects', 'projects2dcc', 'watching', 'user_shareable_calendar_link','user_comment')}),
		('Permissions', {'fields': ('is_active', 'is_staff', 'is_technician', 'is_superuser', 'training_required', 'groups', 'user_permissions', 'physical_access_levels', 'pi_delegates')}),
		('Important dates', {'fields': ('date_joined', 'last_login', 'access_expiration')}),
	)
	search_fields = ('first_name', 'last_name', 'username', 'email')
	list_display = ('first_name', 'last_name', 'username', 'email', 'is_active', 'is_staff', 'is_superuser', 'date_joined', 'last_login')
	list_filter = ('is_active','groups')
	autocomplete_fields = ['contact']

	def save_model(self, request, obj, form, change):
		""" Audit project membership and qualifications when a user is saved. """
		super().save_model(request, obj, form, change)

		record_local_many_to_many_changes(request, obj, form, 'projects')
		record_local_many_to_many_changes(request, obj, form, 'projects2dcc')
		#record_local_many_to_many_changes(request, obj, form, 'qualifications')
		record_local_many_to_many_changes(request, obj, form, 'physical_access_levels')
		record_local_many_to_many_changes(request, obj, form, 'core_ids')
		record_active_state(request, obj, form, 'is_active', not change)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'credit_cost_collector':
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		return super(UserAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def formfield_for_manytomany(self, db_field, request, **kwargs):
		if db_field.name == 'watching':
			kwargs["queryset"] = Tool.objects.all().order_by('name')
		if db_field.name == 'projects':
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		if db_field.name == 'projects2dcc':
			kwargs["queryset"] = Project2DCC.objects.all().order_by('project_id')
		return super(UserAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(PhysicalAccessLog)
class PhysicalAccessLogAdmin(admin.ModelAdmin):
	list_display = ('user', 'door', 'area', 'time', 'result')
	list_filter = ('door', 'area', 'result')
	search_fields = ('user__first_name','user__last_name')
	date_hierarchy = 'time'

	def has_delete_permission(self, request, obj=None):
		return False

@register(SafetyIssue)
class SafetyIssueAdmin(admin.ModelAdmin):
	list_display = ('id', 'reporter', 'creation_time', 'visible', 'resolved', 'resolution_time', 'resolver')
	list_filter = ('resolved', 'visible', 'creation_time', 'resolution_time')
	readonly_fields = ('creation_time', 'resolution_time')
	search_fields = ('location', 'concern', 'progress', 'resolution',)
	autocomplete_fields = ['reporter', 'resolver']

	def has_delete_permission(self, request, obj=None):
		return False


@register(Door)
class DoorAdmin(admin.ModelAdmin):
	list_display = ('name', 'area', 'interlock', 'get_absolute_url')


@register(Alert)
class AlertAdmin(admin.ModelAdmin):
	list_display = ('title', 'creation_time', 'creator', 'debut_time', 'expiration_time', 'user', 'dismissible')

	search_fields = ('title', 'creator__first_name', 'creator__last_name', 'user__first_name', 'user__last_name')

	def has_delete_permission(self, request, obj=None):
		return False

@register(PhysicalAccessLevel)
class PhysicalAccessLevelAdmin(admin.ModelAdmin):
	list_display = ('name', 'area', 'schedule')

	search_fields = ('name', 'area__name')

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContactInformationCategory)
class ContactInformationCategoryAdmin(admin.ModelAdmin):
	list_display = ('name', 'display_order')

	def has_delete_permission(self, request, obj=None):
		return False

@register(ContactInformation)
class ContactInformationAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'city', 'state', 'zipcode')

	search_fields = ('name', 'category__name', 'city', 'state')

	def has_delete_permission(self, request, obj=None):
		return False


@register(LandingPageChoice)
class LandingPageChoiceAdmin(admin.ModelAdmin):
	list_display = ('display_priority', 'name', 'url', 'open_in_new_tab', 'secure_referral', 'hide_from_mobile_devices', 'hide_from_desktop_computers')
	list_display_links = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Customization)
class CustomizationAdmin(admin.ModelAdmin):
	list_display = ('name', 'value')

	def has_delete_permission(self, request, obj=None):
		return False


@register(ScheduledOutageCategory)
class ScheduledOutageCategoryAdmin(admin.ModelAdmin):
	list_display = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ScheduledOutage)
class ScheduledOutageAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'resource', 'creator', 'title', 'start', 'end')

	search_fields = ('tool__name', 'creator__first_name', 'creator__last_name', 'title')
	autocomplete_fields = ['tool', 'creator']

	def has_delete_permission(self, request, obj=None):
		return False


@register(News)
class NewsAdmin(admin.ModelAdmin):
	list_display = ('id', 'created', 'last_updated', 'archived', 'title')
	list_filter = ('archived',)

	search_fields = ('title',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(Notification)
class NotificationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'expiration', 'content_type', 'object_id')

	search_fields = ('user__first_name', 'user__last_name')

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContestTransaction)
class ContestTransactionAdmin(admin.ModelAdmin):
	list_display = ('id', 'content_type', 'object_id', 'contest_description', 'contested_date', 'contest_resolution')
	list_filter = ('content_type','contest_resolution')

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContestTransactionData)
class ContestTransactionDataAdmin(admin.ModelAdmin):
	list_display = ('id', 'content_type', 'object_id', 'contest_transaction', 'field_name', 'original_value', 'proposed_value')
	list_filter = ('content_type',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContestTransactionNewData)
class ContestTransactionNewDataAdmin(admin.ModelAdmin):
	list_display = ('id', 'content_type', 'field_name', 'field_value', 'field_group', 'contest_transaction')
	list_filter = ('content_type',)

	def has_delete_permission(self, request, obj=None):
		return False


@register(LockBilling)
class LockBillingAdmin(admin.ModelAdmin):
	list_display = ('id', 'fiscal_year', 'billing_month', 'billing_year', 'is_locked', 'is_closed', 'created', 'updated')
	list_filter = ('billing_year', 'billing_month')

	def has_delete_permission(self, request, obj=None):
		return False

@register(GlobalFlag)
class GlobalFlagAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'active')

	def has_delete_permission(self, request, obj=None):
		return False

@register(ResourceCategory)
class ResourceCategoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'name')

	def has_delete_permission(self, request, obj=None):
		return False

@register(Area)
class AreaAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'welcome_message', 'core_id')
	search_fields = ('name',)
	inlines = [AreaRequirementInline]

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'credit_cost_collector':
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		return super(AreaAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(Permission)
class PermissionAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'content_type', 'codename')

	def has_delete_permission(self, request, obj=None):
		return False

@register(Core)
class CoreAdmin(admin.ModelAdmin):
	list_display = ('id', 'name')

	def has_delete_permission(self, request, obj=None):
		return False

@register(EmailLog)
class EmailLog(admin.ModelAdmin):
	list_display = ('category','when','sender','to')

	def has_delete_permission(self, request, obj=None):
		return False

@register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'organization_type', 'billing_type', 'url')

	search_fields = ('name',)
	autocomplete_fields = ['contact']

	def has_delete_permission(self, request, obj=None):
		return False

@register(OrganizationType)
class OrganizationTypeAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'nsf_category', 'active')

	def has_delete_permission(self, request, obj=None):
		return False

@register(BillingType)
class BillingTypeAdmin(admin.ModelAdmin):
	list_display = ('id', 'name')
	search_fields = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(NsfCategory)
class NsfCategoryAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'sort_order')

	def has_delete_permission(self, request, obj=None):
		return False

@register(CreditCostCollector)
class CreditCostCollectorAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'project', 'core')

	search_fields = ('name', 'project__project_number')
	autocomplete_fields = ['project']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(CreditCostCollectorAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
	list_display = ('user', 'setting', 'value')

	search_fields = ('user', 'setting', 'value')
	autocomplete_fields = ['user']

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "user":
			kwargs["queryset"] = User.objects.order_by('last_name', 'first_name')
		return super(UserProfileAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(UserProfileSetting)
class UserProfileSettingAdmin(admin.ModelAdmin):
	list_display = ('name', 'setting_type')

	search_fields = ('name', 'setting_type')

	def has_delete_permission(self, request, obj=None):
		return False

@register(Sample)
class SampleAdmin(admin.ModelAdmin):
	filter_horizontal = ('project',)
	list_display = ('identifier','nickname','description','get_projects','created_by','created')
	search_fields = ('identifier','nickname','description','project__project_number','created_by__last_name','created_by__first_name','created_by__username')
	autocomplete_fields = ['created_by', 'updated_by', 'parent_sample']

	def get_projects(self, obj):
		return "\n".join([p.project_number for p in obj.project.all()])

	def formfield_for_manytomany(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.filter(active=True,end_date__gte=timezone.now().date()).order_by('project_number')
		return super(SampleAdmin, self).formfield_for_manytomany(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@admin.register(Requirement)
class RequirementAdmin(admin.ModelAdmin):
	list_display = ('name', 'description', 'resource_link', 'retrain_interval_days')
	search_fields = ('name', 'description')

@admin.register(UserRequirementProgress)
class UserRequirementProgressAdmin(admin.ModelAdmin):
	list_display = ('user', 'requirement', 'status', 'completed_on', 'expires_on', 'last_notified')
	search_fields = ('user__username', 'user__first_name', 'user__last_name', 'requirement__name')
	list_filter = ('status', 'expires_on')