from datetime import datetime
from logging import getLogger

from django import forms
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.forms import BaseForm, BooleanField, CharField, ChoiceField, DateField, Form, IntegerField, ModelChoiceField, ModelForm
from django.forms.utils import ErrorDict
from django.utils import timezone
from django.utils.dateparse import parse_time, parse_date, parse_datetime

from NEMO.models import Account, Alert, Comment, Consumable, ConsumableWithdraw, Project, SafetyIssue, Sample, ScheduledOutage, Task, TaskCategory, Tool, User, ConsumableOrder, ConsumableOrderItem, Core, ServiceType, UserServiceRequest
from NEMO.utilities import bootstrap_primary_color, format_datetime

logger = getLogger(__name__)

class UserForm(ModelForm):
	class Meta:
		model = User
		fields = ['username', 'first_name', 'last_name', 'email', 'badge_number', 'access_expiration', 'type', 'domain', 'is_active', 'training_required', 'physical_access_levels', 'projects', 'user_shareable_calendar_link','user_comment']


class ToolForm(ModelForm):
	class Meta:
		model = Tool
		fields = ['name', 'visible', 'operational', 'qualification_duration', 'reservation_horizon', 'minimum_usage_block_time', 'maximum_usage_block_time', 'maximum_reservations_per_day', 'minimum_time_between_reservations', 'maximum_future_reservation_time', 'missed_reservation_threshold', 'reservation_required','allow_autologout']
		widgets = {
			'name': forms.TextInput(attrs={'readonly': 'readonly', 'class': 'form-control'}),
			'qualification_duration': forms.NumberInput(attrs={'class': 'form-control'}),
			'reservation_horizon': forms.NumberInput(attrs={'class': 'form-control'}),
			'minimum_usage_block_time': forms.NumberInput(attrs={'class': 'form-control'}),
			'maximum_usage_block_time': forms.NumberInput(attrs={'class': 'form-control'}),
			'maximum_reservations_per_day': forms.NumberInput(attrs={'class': 'form-control'}),
			'minimum_time_between_reservations': forms.NumberInput(attrs={'class': 'form-control'}),
			'maximum_future_reservation_time': forms.NumberInput(attrs={'class': 'form-control'}),
			'missed_reservation_threshold': forms.NumberInput(attrs={'class': 'form-control'}),
		}


class ProjectForm(ModelForm):
	class Meta:
		model = Project
		fields = ['name', 'application_identifier', 'account', 'active']


class AccountForm(ModelForm):
	class Meta:
		model = Account
		fields = ['name', 'active']


class TaskForm(ModelForm):
	problem_category = ModelChoiceField(queryset=TaskCategory.objects.filter(stage=TaskCategory.Stage.INITIAL_ASSESSMENT), required=False, label="Problem category")
	resolution_category = ModelChoiceField(queryset=TaskCategory.objects.filter(stage=TaskCategory.Stage.COMPLETION), required=False, label="Resolution category")
	action = ChoiceField(choices=[('create', 'create'), ('update', 'update'), ('resolve', 'resolve')], label="Action")
	description = CharField(required=False, label="Description")

	class Meta:
		model = Task
		fields = ['tool', 'urgency', 'estimated_resolution_time', 'force_shutdown', 'safety_hazard']

	def __init__(self, user, *args, **kwargs):
		super(TaskForm, self).__init__(*args, **kwargs)
		self.user = user
		self.fields['tool'].required = False
		self.fields['urgency'].required = False

	def clean_description(self):
		return self.cleaned_data['description'].strip()

	def clean(self):
		if any(self.errors):
			return
		super(TaskForm, self).clean()
		action = self.cleaned_data['action']
		if action == 'create':
			if not self.cleaned_data['description']:
				raise ValidationError('You must describe the problem.')
		if action == 'resolve':
			if self.instance.cancelled or self.instance.resolved:
				raise ValidationError("This task can't be resolved because it is marked as 'cancelled' or 'resolved' already.")

	def save(self, commit=True):
		instance = super(TaskForm, self).save(commit=False)
		action = self.cleaned_data['action']
		description = self.cleaned_data['description']
		instance.problem_category = self.cleaned_data['problem_category']
		now = timezone.now()
		if action == 'create':
			instance.problem_description = description
			instance.urgency = Task.Urgency.HIGH if self.cleaned_data['force_shutdown'] or self.cleaned_data['safety_hazard'] else Task.Urgency.NORMAL
			instance.creator = self.user
		if action == 'update':
			instance.last_updated = timezone.now()
			instance.last_updated_by = self.user
			instance.cancelled = False
			instance.resolved = False
			if description:
				preface = f'On {format_datetime(now)} {self.user.get_full_name()} updated this task:\n'
				if instance.progress_description is None:
					instance.progress_description = preface + description
				else:
					instance.progress_description += '\n\n' + preface + description
				instance.progress_description = instance.progress_description.strip()
		if action == 'resolve':
			instance.cancelled = False
			instance.resolved = True
			instance.resolution_time = now
			instance.resolver = self.user
			if 'resolution_category' in self.cleaned_data:
				instance.resolution_category = self.cleaned_data['resolution_category']
			if 'description' in self.cleaned_data:
				if instance.resolution_description:
					preface = f'On {format_datetime(now)} {self.user.get_full_name()} updated the resolution information:\n'
					instance.resolution_description = (instance.resolution_description + '\n\n' + preface + self.cleaned_data['description']).strip()
				else:
					instance.resolution_description = self.cleaned_data['description']
		return super(TaskForm, self).save(commit=True)


class CommentForm(ModelForm):
	class Meta:
		model = Comment
		fields = ['tool', 'content']

	expiration = IntegerField(label="Expiration date", min_value=0)


class SafetyIssueCreationForm(ModelForm):
	report_anonymously = BooleanField(required=False, initial=False)

	class Meta:
		model = SafetyIssue
		fields = ['reporter', 'concern', 'location']

	def __init__(self, user, *args, **kwargs):
		super(SafetyIssueCreationForm, self).__init__(*args, **kwargs)
		self.user = user

	def clean_update(self):
		return self.cleaned_data['concern'].strip()

	def clean_location(self):
		return self.cleaned_data['location'].strip()

	def save(self, commit=True):
		instance = super(SafetyIssueCreationForm, self).save(commit=False)
		if not self.cleaned_data['report_anonymously']:
			self.instance.reporter = self.user
		if commit:
			instance.save()
		return super(SafetyIssueCreationForm, self).save(commit=commit)


class SafetyIssueUpdateForm(ModelForm):
	update = CharField(required=False, label="Update")

	class Meta:
		model = SafetyIssue
		fields = ['resolved', 'visible']

	def __init__(self, user, *args, **kwargs):
		super(SafetyIssueUpdateForm, self).__init__(*args, **kwargs)
		self.user = user

	def clean_update(self):
		return self.cleaned_data['update'].strip()

	def save(self, commit=True):
		instance = super(SafetyIssueUpdateForm, self).save(commit=False)
		progress_type = 'resolved' if self.cleaned_data['resolved'] else 'updated'
		if progress_type == 'resolved':
			instance.resolution = self.cleaned_data['update']
			instance.resolution_time = timezone.now()
			instance.resolver = self.user
		if progress_type == 'updated' and self.cleaned_data['update']:
			progress = 'On ' + format_datetime(timezone.now()) + ' ' + self.user.get_full_name() + ' updated this issue:\n' + self.cleaned_data['update']
			if instance.progress:
				instance.progress += '\n\n' + progress
			else:
				instance.progress = progress
		return super(SafetyIssueUpdateForm, self).save(commit=commit)


class ConsumableWithdrawForm(ModelForm):
	class Meta:
		model = ConsumableWithdraw
		fields = ['customer', 'project', 'consumable', 'quantity', 'notes']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['consumable'].queryset = Consumable.objects.filter(visible=True)

	def clean_customer(self):
		customer = self.cleaned_data['customer']
		if not customer.is_active:
			raise ValidationError('A consumable withdraw was requested for an inactive user. Only active users may withdraw consumables.')
		return customer

	def clean_project(self):
		project = self.cleaned_data['project']
		if not project.active:
			raise ValidationError('A consumable may only be billed to an active project. The user\'s project is inactive.')
#		if not project.account.active:
#			raise ValidationError('A consumable may only be billed to a project that belongs to an active account. The user\'s account is inactive.')
		return project

	def clean_quantity(self):
		quantity = self.cleaned_data['quantity']
		if quantity < 1:
			raise ValidationError('Please specify a valid quantity of items to withdraw.')
		return quantity

	def clean(self):
		if any(self.errors):
			return
		super(ConsumableWithdrawForm, self).clean()
		quantity = self.cleaned_data['quantity']
		consumable = self.cleaned_data['consumable']
		if quantity > consumable.quantity:
			raise ValidationError('The withdraw was not processed because there are not enough "' + consumable.name + '". (There current quantity in stock is ' + str(consumable.quantity) + '). Please order more as soon as possible.')
		customer = self.cleaned_data['customer']
		project = self.cleaned_data['project']
		if project not in customer.active_projects():
			raise ValidationError('{} is not a member of the project {}. Users can only bill to projects they belong to.'.format(customer, project))

class ConsumableOrderForm(forms.ModelForm):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), required=True)

	class Meta:
		model = ConsumableOrder
		fields = ['project', 'name', 'description']

	def __init__(self, *args, **kwargs):
		user = kwargs.pop('user', None)
		super().__init__(*args, **kwargs)
		if user:
			self.fields['project'].queryset = user.projects.filter(active=True)

class ConsumableOrderItemForm(forms.ModelForm):
	search = forms.CharField(required=False, widget=forms.TextInput(attrs={'placeholder': 'Filter consumables...'}))

	class Meta:
		model = ConsumableOrderItem
		fields = ['search', 'consumable', 'quantity']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['consumable'].queryset = Consumable.objects.filter(category__id=1, visible=True).order_by('name')
   

ConsumableOrderItemFormSet = forms.inlineformset_factory(
    ConsumableOrder, ConsumableOrderItem, form=ConsumableOrderItemForm, extra=1, can_delete=True
)

class ReservationAbuseForm(Form):
	cancellation_horizon = IntegerField(initial=6, min_value=1)
	cancellation_penalty = IntegerField(initial=10)
	target = IntegerField(required=False)
	start = DateField(initial=timezone.now().replace(day=1).date())
	end = DateField(initial=timezone.now().date())

	def clean_cancellation_horizon(self):
		# Convert the cancellation horizon from hours to seconds.
		return self.cleaned_data['cancellation_horizon'] * 60 * 60

	def clean_start(self):
		start = self.cleaned_data['start']
		dt_start = datetime(year=start.year, month=start.month, day=start.day, hour=0, minute=0, second=0, microsecond=0)
		return dt_start.astimezone(timezone.get_current_timezone())


	def clean_end(self):
		end = self.cleaned_data['end']
		dt_end = datetime(year=end.year, month=end.month, day=end.day, hour=23, minute=59, second=59, microsecond=999999)
		return dt_end.astimezone(timezone.get_current_timezone())


class EmailBroadcastForm(Form):
	subject = CharField(required=False)
	color = ChoiceField(choices=((bootstrap_primary_color('info'), 'info'), (bootstrap_primary_color('success'), 'success'), (bootstrap_primary_color('warning'), 'warning'), (bootstrap_primary_color('danger'), 'danger')))
	title = CharField(required=False)
	greeting = CharField(required=False)
	contents = CharField(required=False)
	copy_me = BooleanField(initial=True)

	audience = ChoiceField(choices=[('tool', 'tool'), ('project', 'project'), ('account', 'account'), ('tool_date','tool_date'), ('project_date', 'project_date'), ('user', 'user'), ('group', 'group')], label="Audience")
	selection = IntegerField()
	recipient = CharField(required=False)
	only_active_users = BooleanField(initial=True)

	def clean_title(self):
		return self.cleaned_data['title'].upper()


class AlertForm(ModelForm):

	class Meta:
		model = Alert
		fields = ['title', 'contents', 'debut_time', 'expiration_time']


class ScheduledOutageForm(ModelForm):
	def __init__(self, *positional_arguments, **keyword_arguments):
		super().__init__(*positional_arguments, **keyword_arguments)
		self.fields['details'].required = True

	class Meta:
		model = ScheduledOutage
		fields = ['details', 'start', 'end', 'resource', 'category']

class SampleForm(ModelForm):
	project_choices = None
	project = forms.ModelMultipleChoiceField(label='Project',queryset=project_choices,required=True)

	class Meta:
		model = Sample
		fields = ['nickname','customer_nickname','description','project','parent_sample','active_flag','identifier']

	def __init__(self, user, *args, **kwargs):
		super(SampleForm, self).__init__(*args, **kwargs)
		if user.is_staff:
			self.project_choices = Project.objects.filter(active=True, end_date__gte=timezone.now().date()).order_by('project_number')
		else:
			self.project_choices = user.active_projects()
		self.fields['project'].queryset = self.project_choices

def nice_errors(form, non_field_msg='General form errors'):
	result = ErrorDict()
	if isinstance(form, BaseForm):
		for field, errors in form.errors.items():
			if field == NON_FIELD_ERRORS:
				key = non_field_msg
			else:
				key = form.fields[field].label
			result[key] = errors
	return result


class MultiCalendarForm(forms.Form):
	users_with_calendars = forms.ModelMultipleChoiceField(
		queryset=User.objects.filter(
			user_shareable_calendar_link__isnull=False
		).exclude(user_shareable_calendar_link__exact='').order_by('last_name', 'first_name'),
		widget=forms.SelectMultiple(attrs={'size': 8, 'class': 'form-control'}),
		label="Users with Shareable Calendars",
		required=False,
	)

	ics_urls = forms.CharField(
		widget=forms.Textarea(attrs={'placeholder': 'Enter one ICS URL per line in the format label:url', 'rows': 4,'class': 'form-control'}),
		label="External Calendar URLs",
		required=False
	)

	tools_selected = forms.ModelMultipleChoiceField(
		queryset=Tool.objects.filter(visible=True).order_by('category', 'name'),
		widget=forms.MultipleHiddenInput,
		required=False,
		label="LEO Tools"
	)

	slot_duration = forms.IntegerField(
		label="Desired Slot Duration (minutes)",
		min_value=1,
		initial=60,
		required=True,
		widget=forms.NumberInput(attrs={'class': 'form-control'})
	)

	window_start = forms.DateTimeField(
		label="Search Window Start",
		required=False,
		widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
	)

	window_end = forms.DateTimeField(
		label="Search Window End",
		required=False,
		widget=forms.DateTimeInput(attrs={'type': 'datetime-local', 'class': 'form-control'})
	)


class ToolDurationForm(forms.Form):
	tool = forms.ModelChoiceField(queryset=Tool.objects.filter(visible=True).order_by('name'), label="Tool")
	duration = forms.IntegerField(min_value=1, label="Duration (minutes)")

ToolDurationFormSet = forms.formset_factory(ToolDurationForm, extra=1, min_num=1, validate_min=True)

class ServiceTypeForm(forms.ModelForm):
	class Meta:
		model = ServiceType
		fields = [
			'name',
			'description',
			'active',
			'core',
			'principle_assignee',
			'secondary_assignee',
		]
		widgets = {
			'description': forms.Textarea(attrs={'rows': 3}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		active_staff = User.objects.filter(is_active=True, is_staff=True).order_by('first_name', 'last_name')
		self.fields['principle_assignee'].queryset = active_staff
		self.fields['secondary_assignee'].queryset = active_staff


class UserServiceRequestEditForm(forms.ModelForm):
	project = forms.ModelChoiceField(queryset=Project.objects.none(), required=False)
	tool = forms.ModelChoiceField(queryset=Tool.objects.none(), required=False, widget=forms.Select(attrs={'class': 'searchable-select'}))
	assignee = forms.ModelChoiceField(queryset=User.objects.none(), required=False)
	training_request = forms.BooleanField(required=False)

	class Meta:
		model = UserServiceRequest
		fields = ['description', 'project', 'assignee', 'training_request', 'tool']

	def __init__(self, *args, **kwargs):
		user_projects = kwargs.pop('user_projects', Project.objects.none())
		tools = kwargs.pop('tools', Tool.objects.none())
		staff_members = kwargs.pop('staff_members', User.objects.none())
		super().__init__(*args, **kwargs)
		self.fields['project'].queryset = user_projects
		self.fields['tool'].queryset = tools
		self.fields['assignee'].queryset = staff_members