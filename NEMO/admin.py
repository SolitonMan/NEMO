from django import forms
from django.contrib import admin
from django.contrib.admin import register, widgets
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.contrib.auth.models import Permission

from NEMO.actions import lock_selected_interlocks, synchronize_with_tool_usage, unlock_selected_interlocks
from NEMO.models import Account, ActivityHistory, Alert, Area, AreaAccessRecord, AreaAccessRecordProject, BillingType, Comment, Configuration, ConfigurationHistory, Consumable, ConsumableUnit, ConsumableCategory, ConsumableWithdraw, ContactInformation, ContactInformationCategory, ContestTransaction, ContestTransactionData, ContestTransactionNewData, Core, CreditCostCollector, Customization, Door, GlobalFlag, Interlock, InterlockCard, LandingPageChoice, LockBilling, MembershipHistory, News, Notification, NsfCategory, Organization, OrganizationType, PhysicalAccessLevel, PhysicalAccessLog, Project, Reservation, ReservationConfiguration, ReservationProject, Resource, ResourceCategory, SafetyIssue, ScheduledOutage, ScheduledOutageCategory, StaffCharge, StaffChargeProject, Task, TaskCategory, TaskHistory, TaskStatus, Tool, TrainingSession, UsageEvent, UsageEventProject, User, UserType

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

	qualified_users = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
			is_stacked=False
		)
	)

	backup_owners = forms.ModelMultipleChoiceField(
		queryset=User.objects.all(),
		required=False,
		widget=FilteredSelectMultiple(
			verbose_name='Users',
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

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		if self.instance.pk:
			self.fields['qualified_users'].initial = self.instance.user_set.all()
			self.fields['required_resources'].initial = self.instance.required_resource_set.all()
			self.fields['nonrequired_resources'].initial = self.instance.nonrequired_resource_set.all()


@register(Tool)
class ToolAdmin(admin.ModelAdmin):
	list_display = ('name', 'category', 'core_id', 'visible', 'operational', 'problematic', 'is_configurable')
	list_filter = ('visible', 'operational', 'core_id')
	form = ToolAdminForm

	search_fields = ('name', 'category')

	def change_view(self, request, object_id, form_url='', extra_context=None):
		if request.user.is_superuser:
			self.fieldsets = (
				(None, {'fields': ('name', 'category', 'core_id', 'credit_cost_collector', 'qualified_users'),}),
				('Current state', {'fields': ('post_usage_questions', 'visible', 'operational'),}),
				('Contact information', {'fields': ('primary_owner', 'backup_owners', 'notification_email_address', 'location', 'phone_number'),}),
				('Usage policy', {'fields': ('reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'requires_area_access', 'grant_physical_access_level_upon_qualification', 'grant_badge_reader_access_upon_qualification', 'interlock', 'allow_delayed_logoff', 'reservation_required', 'allow_autologout'),}),
				('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
			)
		else:
			self.fieldsets = (
				(None, {'fields': ('name', 'category', 'core_id', 'qualified_users'),}),
				('Current state', {'fields': ('visible', 'operational'),}),
				('Contact information', {'fields': ('primary_owner', 'backup_owners', 'notification_email_address', 'location', 'phone_number'),}),
				('Usage policy', {'fields': ('reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'requires_area_access', 'grant_physical_access_level_upon_qualification', 'grant_badge_reader_access_upon_qualification', 'interlock', 'allow_delayed_logoff', 'reservation_required', 'allow_autologout'),}),
				('Dependencies', {'fields': ('required_resources', 'nonrequired_resources'),}),
			)
		return super().change_view(request, object_id, form_url, extra_context)

	def save_model(self, request, obj, form, change):
		"""
		Explicitly record any project membership changes.
		"""
		record_remote_many_to_many_changes_and_save(request, obj, form, change, 'qualified_users', super().save_model)
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


@register(TrainingSession)
class TrainingSessionAdmin(admin.ModelAdmin):
	list_display = ('id', 'trainer', 'trainee', 'tool', 'project', 'type', 'date', 'duration', 'qualified')
	list_filter = ('qualified', 'date', 'type')
	date_hierarchy = 'date'

	search_fields = ('trainer__first_name','trainer__last_name','trainer__first_name','trainer__last_name','project__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(TrainingSessionAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(StaffCharge)
class StaffChargeAdmin(admin.ModelAdmin):
	list_display = ('id', 'staff_member', 'customer', 'start', 'end')
	list_filter = ('start',)
	date_hierarchy = 'start'
	ordering = ['-id']

	search_fields = ('staff_member__first_name','staff_member__last_name','projects__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(StaffChargeAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(StaffChargeProject)
class StaffChargeProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'staff_charge', 'customer', 'project', 'project_percent')

	search_fields = ('customer__first_name','customer__last_name','project__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(StaffChargeProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(AreaAccessRecord)
class AreaAccessRecordAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'area', 'project', 'start', 'end')
	list_filter = ('area', 'start',)
	date_hierarchy = 'start'

	search_fields = ('area__name', 'customers__first_name','customers__last_name','projects__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(AreaAccessRecordAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(AreaAccessRecordProject)
class AreaAccessRecordProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'area_access_record', 'customer', 'project', 'project_percent')

	search_fields = ('customer__first_name','customer__last_name','project__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(AreaAccessRecordProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Configuration)
class ConfigurationAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'name', 'qualified_users_are_maintainers', 'display_priority', 'exclude_from_configuration_agenda')
	filter_horizontal = ('maintainers',)

	search_fields = ('tool__name', 'name', 'consumable__name')

	def change_view(self, request, object_id, form_url='', extra_context=None):
		if not request.user.is_superuser:
			self.exclude = ('current_settings',)
		return super().change_view(request, object_id, form_url, extra_context)

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
	# list_filter = ('owner','organization__name')
	exclude = ('account',)
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
		return super(ProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
	list_display = ('id', 'user', 'creator', 'tool', 'project', 'additional_information', 'start', 'end', 'duration', 'cancelled', 'missed')
	list_filter = ('cancelled', 'missed')
	date_hierarchy = 'start'

	search_fields = ('user__first_name', 'user__last_name', 'tool__name', 'projects__project_number')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(ReservationAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(ReservationConfiguration)
class ReservationConfigurationAdmin(admin.ModelAdmin):
	list_display = ('id', 'reservation', 'configuration', 'consumable')

	search_fields = ('reservation__user__first_name', 'reservation__user__last_name', 'reservation__tool__name', 'reservation__projects__project_number')

	def has_delete_permission(self, request, obj=None):
		return False

@register(ReservationProject)
class ReservationProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'reservation', 'project', 'customer')

	search_fields = ('project__project_number', 'customer__first_name', 'customer__last_name')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(ReservationProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'user', 'operator', 'project', 'start', 'end', 'duration', 'run_data')
	list_filter = ('start', 'end')
	date_hierarchy = 'start'

	search_fields = ('tool__name', 'projects__project_number', 'customers__first_name', 'customers__last_name')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(UsageEventAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False

@register(UsageEventProject)
class UsageEventProjectAdmin(admin.ModelAdmin):
	list_display = ('id', 'usage_event', 'customer', 'project', 'project_percent')

	search_fields = ('project__project_number', 'customer__first_name', 'customer__last_name')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(UsageEventProjectAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


@register(Consumable)
class ConsumableAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'quantity', 'category', 'visible', 'reminder_threshold', 'reminder_email', 'core_id')
	list_filter = ('visible', 'category')
	search_fields = ('name', 'category__name')

	def has_delete_permission(self, request, obj=None):
		return False


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

@register(ConsumableWithdraw)
class ConsumableWithdrawAdmin(admin.ModelAdmin):
	list_display = ('id', 'customer', 'merchant', 'consumable', 'quantity', 'project', 'date')
	date_hierarchy = 'date'

	search_fields = ('customer__first_name', 'customer__last_name', 'merchant__first_name', 'merchant__last_name', 'project__project_number','consumable__name')

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(ConsumableWithdrawAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'credit_cost_collector':
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		return super(ConsumableWithdrawAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

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
	list_display = ('id', 'card', 'channel', 'state', 'tool', 'door')
	actions = [lock_selected_interlocks, unlock_selected_interlocks, synchronize_with_tool_usage]
	readonly_fields = ['state', 'most_recent_reply']

	search_fields = ('tool_name', 'card__server')

	def has_delete_permission(self, request, obj=None):
		return False

@register(Task)
class TaskAdmin(admin.ModelAdmin):
	list_display = ('id', 'urgency', 'tool', 'creator', 'creation_time', 'problem_category', 'cancelled', 'resolved', 'resolution_category')
	list_filter = ('urgency', 'resolved', 'cancelled', 'safety_hazard', 'creation_time')
	date_hierarchy = 'creation_time'

	search_fields = ('tool__name', 'creator__first_name', 'creator__last_name')

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

	def has_delete_permission(self, request, obj=None):
		return False

@register(Comment)
class CommentAdmin(admin.ModelAdmin):
	list_display = ('id', 'tool', 'author', 'creation_date', 'expiration_date', 'visible', 'hidden_by', 'hide_date')
	list_filter = ('visible', 'creation_date')
	date_hierarchy = 'creation_date'
	search_fields = ('content',)

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

	def has_delete_permission(self, request, obj=None):
		return False

@register(MembershipHistory)
class MembershipHistoryAdmin(admin.ModelAdmin):
	list_display = ('__str__', 'parent_content_type', 'parent_object_id', 'action', 'child_content_type', 'child_object_id', 'date', 'authorizer')
	date_hierarchy = 'date'

	def has_delete_permission(self, request, obj=None):
		return False


@register(UserType)
class UserTypeAdmin(admin.ModelAdmin):
	list_display = ('name',)

	def has_delete_permission(self, request, obj=None):
		return False

@register(User)
class UserAdmin(admin.ModelAdmin):
	filter_horizontal = ('groups', 'user_permissions', 'qualifications', 'projects', 'physical_access_levels', 'pi_delegates')
	fieldsets = (
		('Personal information', {'fields': ('first_name', 'last_name', 'username', 'email', 'badge_number', 'type', 'domain', 'credit_cost_collector', 'core_ids')}),
		('Permissions', {'fields': ('is_active', 'is_staff', 'is_technician', 'is_superuser', 'training_required', 'groups', 'user_permissions', 'physical_access_levels', 'pi_delegates')}),
		('Important dates', {'fields': ('date_joined', 'last_login', 'access_expiration')}),
		('Laboratory information', {'fields': ('qualifications', 'projects')}),
	)
	search_fields = ('first_name', 'last_name', 'username', 'email')
	list_display = ('first_name', 'last_name', 'username', 'email', 'is_active', 'domain', 'is_staff', 'is_technician', 'is_superuser', 'date_joined', 'last_login')
	list_filter = ('is_active','groups')

	def save_model(self, request, obj, form, change):
		""" Audit project membership and qualifications when a user is saved. """
		super().save_model(request, obj, form, change)
		record_local_many_to_many_changes(request, obj, form, 'projects')
		record_local_many_to_many_changes(request, obj, form, 'qualifications')
		record_local_many_to_many_changes(request, obj, form, 'physical_access_levels')
		record_local_many_to_many_changes(request, obj, form, 'core_ids')
		record_active_state(request, obj, form, 'is_active', not change)

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == 'credit_cost_collector':
			kwargs["queryset"] = CreditCostCollector.objects.order_by('project__project_number')
		return super(UserAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

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

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContestTransactionData)
class ContestTransactionDataAdmin(admin.ModelAdmin):
	list_display = ('id', 'content_type', 'object_id', 'contest_transaction', 'field_name', 'original_value', 'proposed_value')

	def has_delete_permission(self, request, obj=None):
		return False


@register(ContestTransactionNewData)
class ContestTransactionNewDataAdmin(admin.ModelAdmin):
	list_display = ('id', 'content_type', 'field_name', 'field_value', 'field_group', 'contest_transaction')

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


@register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
	list_display = ('id', 'name', 'organization_type', 'billing_type', 'url')

	search_fields = ('name',)

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

	def formfield_for_foreignkey(self, db_field, request, **kwargs):
		if db_field.name == "project":
			kwargs["queryset"] = Project.objects.order_by('project_number')
		return super(CreditCostCollectorAdmin, self).formfield_for_foreignkey(db_field, request, **kwargs)

	def has_delete_permission(self, request, obj=None):
		return False


