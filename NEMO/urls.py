from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.views.static import serve
from rest_framework import routers

from NEMO.models import GlobalFlag
from NEMO.scheduler import start_scheduler
from NEMO.views import (
	abuse, accounts_and_projects, alerts, api, area_access, authentication, calendar, configuration_agenda, consumables,
	contact_staff, customization, email, feedback, get_projects, history, interlock, jumbotron, kiosk, landing,
	maintenance, mobile, notifications, usage, news, qualifications, remote_work, requirements_admin, resources, safety, samples, sidebar,
	staff_charges, status_dashboard, tasks, tool_control, training, tutorials, users, work_orders
)

# REST API URLs
router = routers.DefaultRouter()
router.register(r'users', api.UserViewSet)
router.register(r'projects', api.ProjectViewSet)
router.register(r'accounts', api.AccountViewSet)
router.register(r'tools', api.ToolViewSet)
router.register(r'reservations', api.ReservationViewSet)
router.register(r'usage_events', api.UsageEventViewSet)
router.register(r'area_access_records', api.AreaAccessRecordViewSet)
router.register(r'tasks', api.TaskViewSet)
router.register(r'scheduled_outages', api.ScheduledOutageViewSet)

urlpatterns = [
	path('admin/', admin.site.urls),
	# Authentication & error pages:
	path('valid/', include('microsoft_auth.urls', namespace='microsoft')),
	path('login/', authentication.login_user, name='login'),
	path('logout/', authentication.logout_user, name='logout'),
	path('choose_core/', authentication.choose_core, name='choose_core'),

	# Create a notification scheme
	path('create_notification_scheme/', notifications.notification_scheme_tool_action, name='create_notification_scheme'),
	path('save_notification_scheme/', notifications.save_notification_scheme_tool_action, name='save_notification_scheme'),
	path('delete_notification_scheme/', notifications.delete_notification_scheme, name='delete_notification_scheme'),

	# Root URL defaults to the calendar page on desktop systems, and the mobile homepage for mobile devices:
	path('', landing.landing, name='landing'),
	path('check_url/', landing.check_url, name='check_url'),

	# Get a list of projects for a user:
	path('get_projects/', get_projects.get_projects, name='get_projects'),
	path('get_projects_for_tool_control/', get_projects.get_projects_for_tool_control, name='get_projects_for_tool_control'),
	path('get_projects_for_self/<int:tool_id>/', get_projects.get_projects_for_self, name='get_projects_for_self'),
	path('get_areas/', get_projects.get_areas, name='get_areas'),

	# Tool control:
	path('tools/', tool_control.tools, name='tools'),
	path('create_or_modify_tool/<int:tool_id>/', tool_control.create_or_modify_tool, name='create_or_modify_tool'),
	path('tool_control/<int:tool_id>/', tool_control.tool_control, name='tool_control'),
	path('tool_control/<int:tool_id>/<int:qualified_only>/<int:core_only>/', tool_control.tool_control, name='tool_control'),
	path('tool_control/', tool_control.tool_control, name='tool_control'),
	path('tool_status/<int:tool_id>/', tool_control.tool_status, name='tool_status'),
	path('use_tool_for_other/', tool_control.use_tool_for_other, name='use_tool_for_other'),
	path('tool_configuration/', tool_control.tool_configuration, name='tool_configuration'),
	path('create_comment/', tool_control.create_comment, name='create_comment'),
	path('hide_comment/<int:comment_id>/', tool_control.hide_comment, name='hide_comment'),
	path('enable_tool/<int:tool_id>/user/<int:user_id>/project/<int:project_id>/staff_charge/<str:staff_charge>/billing_mode/<str:billing_mode>/', tool_control.enable_tool, name='enable_tool'),
	path('enable_tool_multi/', tool_control.enable_tool_multi, name='enable_tool_multi'),
	path('disable_tool/<int:tool_id>/', tool_control.disable_tool, name='disable_tool'),
	path('past_comments_and_tasks/', tool_control.past_comments_and_tasks, name='past_comments_and_tasks'),
	path('ten_most_recent_past_comments_and_tasks/<int:tool_id>/', tool_control.ten_most_recent_past_comments_and_tasks, name='ten_most_recent_past_comments_and_tasks'),
	path('usage_event_projects_save/', tool_control.usage_event_projects_save, name='usage_event_projects_save'),
	path('create_usage_event/', tool_control.create_usage_event, name='create_usage_event'),
	path('save_usage_event/', tool_control.save_usage_event, name='save_usage_event'),
	path('save_operator_comment/', tool_control.save_operator_comment, name='save_operator_comment'),
	path('save_tool_comment/', tool_control.save_tool_comment, name='save_tool_comment'),
	path('save_fixed_comment/', tool_control.save_fixed_comment, name='save_fixed_comment'),
	path('toggle_tool_watching/', tool_control.toggle_tool_watching, name='toggle_tool_watching'),

	# Tasks:
	path('create_task/', tasks.create, name='create_task'),
	path('cancel_task/<int:task_id>/', tasks.cancel, name='cancel_task'),
	path('update_task/<int:task_id>/', tasks.update, name='update_task'),
	path('task_update_form/<int:task_id>/', tasks.task_update_form, name='task_update_form'),
	path('task_resolution_form/<int:task_id>/', tasks.task_resolution_form, name='task_resolution_form'),

	# Calendar:
	path('calendar/<int:tool_id>/<int:qualified_only>/<int:core_only>/', calendar.calendar, name='calendar'),
	path('calendar/', calendar.calendar, name='calendar'),
	path('event_feed/', calendar.event_feed, name='event_feed'),
	path('create_reservation/', calendar.create_reservation, name='create_reservation'),
	path('create_outage/', calendar.create_outage, name='create_outage'),
	path('resize_reservation/', calendar.resize_reservation, name='resize_reservation'),
	path('resize_outage/', calendar.resize_outage, name='resize_outage'),
	path('move_reservation/', calendar.move_reservation, name='move_reservation'),
	path('move_outage/', calendar.move_outage, name='move_outage'),
	path('cancel_reservation/<int:reservation_id>/', calendar.cancel_reservation, name='cancel_reservation'),
	path('cancel_outage/<int:outage_id>/', calendar.cancel_outage, name='cancel_outage'),
	path('set_reservation_title/<int:reservation_id>/', calendar.set_reservation_title, name='set_reservation_title'),
	path('event_details/reservation/<int:reservation_id>/', calendar.reservation_details, name='reservation_details'),
	path('event_details/outage/<int:outage_id>/', calendar.outage_details, name='outage_details'),
	path('event_details/usage/<int:event_id>/', calendar.usage_details, name='usage_details'),
	path('event_details/area_access/<int:event_id>/', calendar.area_access_details, name='area_access_details'),
	path('proxy_reservation/', calendar.proxy_reservation, name='proxy_reservation'),
	path('create_notification/', calendar.create_notification, name='create_notification'),
	path('delete_notification/', calendar.delete_notification, name='delete_notification'),
	path('save_notifications/', calendar.save_notifications, name='save_notifications'),
	path('create_reservation_calendar_invite/<int:reservation_id>/', calendar.create_reservation_calendar_invite, name='create_reservation_calendar_invite'),
	path('create_reservation_customer_calendar_invite/<int:reservation_id>/', calendar.create_reservation_customer_calendar_invite, name='create_reservation_customer_calendar_invite'),
	path('multi_calendar/', calendar.multi_calendar_view, name='multi_calendar'),
	path('sequential_tool_schedule/', calendar.sequential_tool_schedule, name='sequential_tool_schedule'),

	# Requirements:
	path('requirements/', requirements_admin.manage_requirements, name='manage_requirements'),
	path('user_requirements/', users.user_requirements, name='user_requirements'),
	path('add_requirement/', requirements_admin.add_requirement, name='add_requirement'),
	path('check_user_requirements/', requirements_admin.check_user_requirements, name='check_user_requirements'),
	path('requirements/edit/<int:requirement_id>/', requirements_admin.edit_requirement, name='edit_requirement'),
	path('requirements/manage_service_type_requirements/', requirements_admin.manage_service_type_requirements, name='manage_service_type_requirements'),
	path('requirements/service_type_requirements_ajax/', requirements_admin.service_type_requirements_ajax, name='service_type_requirements_ajax'),
	path('complete_user_requirement/', users.complete_user_requirement, name='complete_user_requirement'),

	# Qualifications:
	path('qualifications/', qualifications.qualifications, name='qualifications'),
	path('modify_qualifications/', qualifications.modify_qualifications, name='modify_qualifications'),
	path('get_qualified_users/', qualifications.get_qualified_users, name='get_qualified_users'),
	path('promote_user/<int:user_id>/<int:tool_id>/', qualifications.promote_user, name='promote_user'),
	path('demote_user/<int:user_id>/<int:tool_id>/', qualifications.demote_user, name='demote_user'),

	# Staff charges:
	path('staff_charges/', staff_charges.staff_charges, name='staff_charges'),
	path('ad_hoc_staff_charge/', staff_charges.ad_hoc_staff_charge, name='ad_hoc_staff_charge'),
	path('ad_hoc_overlap_resolution/', staff_charges.ad_hoc_overlap_resolution, name='ad_hoc_overlap_resolution'),
	path('staff_charge_entry/', staff_charges.staff_charge_entry, name='staff_charge_entry'),
	path('ad_hoc_staff_charge_entry/', staff_charges.ad_hoc_staff_charge_entry, name='ad_hoc_staff_charge_entry'),
	path('begin_staff_charge/', staff_charges.begin_staff_charge, name='begin_staff_charge'),
	path('end_staff_charge/<int:modal_flag>/', staff_charges.end_staff_charge, name='end_staff_charge'),
	path('begin_staff_area_charge/', staff_charges.begin_staff_area_charge, name='begin_staff_area_charge'),
	path('end_staff_area_charge/', staff_charges.end_staff_area_charge, name='end_staff_area_charge'),
	path('staff_charge_projects_save/<int:modal_flag>/', staff_charges.staff_charge_projects_save, name='staff_charge_projects_save'),
	path('continue_staff_charge/<int:staff_charge_id>/', staff_charges.continue_staff_charge, name='continue_staff_charge'),
	path('save_staff_comment/', staff_charges.save_staff_comment, name='save_staff_comment'),
	path('save_sc_customer_comment/', staff_charges.save_sc_customer_comment, name='save_sc_customer_comment'),
	path('save_customer_comment/', staff_charges.save_sc_customer_comment, name='save_customer_comment'),

	# Status dashboard:
	path('status_dashboard/', status_dashboard.status_dashboard, name='status_dashboard'),

	# Jumbotron:
	path('jumbotron/', jumbotron.jumbotron, name='jumbotron'),
	path('jumbotron_content/', jumbotron.jumbotron_content, name='jumbotron_content'),

	# Utility functions:
	path('refresh_sidebar_icons/', sidebar.refresh_sidebar_icons, name='refresh_sidebar_icons'),

	# Laboratory feedback
	path('feedback/', feedback.feedback, name='feedback'),

	# Laboratory rules tutorial
	# TODO: this should be removed, since this is really a job for a Learning Management System...
	path('nanofab_rules_tutorial/', tutorials.nanofab_rules, name='nanofab_rules'),

	# Configuration agenda for staff:
	path('configuration_agenda/', configuration_agenda.configuration_agenda, name='configuration_agenda'),
	path('configuration_agenda/near_future/', configuration_agenda.configuration_agenda, {'time_period': 'near_future'}, name='configuration_agenda_near_future'),

	# Email broadcasts:
	path('get_email_form/', email.get_email_form, name='get_email_form'),
	path('get_email_form_for_user/<int:user_id>/', email.get_email_form_for_user, name='get_email_form_for_user'),
	path('send_email/', email.send_email, name='send_email'),
	path('email_broadcast/', email.email_broadcast, name='email_broadcast'),
	path('email_broadcast/<str:audience>/', email.email_broadcast, name='email_broadcast'),
	path('compose_email/', email.compose_email, name='compose_email'),
	path('send_broadcast_email/', email.send_broadcast_email, name='send_broadcast_email'),

	# Maintenance:
	path('maintenance/<str:sort_by>/', maintenance.maintenance, name='maintenance'),
	path('maintenance/', maintenance.maintenance, name='maintenance'),
	path('task_details/<int:task_id>/', maintenance.task_details, name='task_details'),

	# Resources:
	path('resources/', resources.resources, name='resources'),
	path('resources/modify/<int:resource_id>/', resources.modify_resource, name='modify_resource'),
	path('resources/schedule_outage/', resources.schedule_outage, name='schedule_resource_outage'),
	path('resources/delete_scheduled_outage/<int:outage_id>/', resources.delete_scheduled_outage, name='delete_scheduled_resource_outage'),

	# Consumables:
	path('consumables/', consumables.consumables, name='consumables'),
	path('get_consumables/', consumables.get_consumables, name='get_consumables'),
	path('save_withdraw_notes/', consumables.save_withdraw_notes, name='save_withdraw_notes'),
	path('create_order/', consumables.create_order, name='create_order'),
	path('order_list/<int:for_user>/', consumables.order_list, name='order_list'),
	path('order_detail/<int:order_id>/', consumables.order_detail, name='order_detail'),
	path('mark_item_fulfilled/<int:item_id>/<int:do_mail>/', consumables.mark_item_fulfilled, name='mark_item_fulfilled'),
	path('mark_item_cancelled/<int:item_id>/<int:do_mail>/', consumables.mark_item_cancelled, name='mark_item_cancelled'),

	# Training:
	# path('training/', training.training, name='training'),
	# path('training_entry/', training.training_entry, name='training_entry'),
	# path('charge_training/', training.charge_training, name='charge_training'),

	# Safety:
	path('safety/', safety.safety, name='safety'),
	path('safety/resolved', safety.resolved_safety_issues, name='resolved_safety_issues'),
	path('safety/update/<int:ticket_id>/', safety.update_safety_issue, name='update_safety_issue'),

	# Mobile:
	path('choose_tool/then/<str:next_page>/', mobile.choose_tool, name='choose_tool'),
	path('new_reservation/<int:tool_id>/', mobile.new_reservation, name='new_reservation'),
	path('new_reservation/<int:tool_id>/<str:date>/', mobile.new_reservation, name='new_reservation'),
	path('make_reservation/', mobile.make_reservation, name='make_reservation'),
	path('view_calendar/<int:tool_id>/', mobile.view_calendar, name='view_calendar'),
	path('view_calendar/<int:tool_id>/<str:date>/', mobile.view_calendar, name='view_calendar'),

	# Contact staff:
	path('contact_staff/', contact_staff.contact_staff, name='contact_staff'),

	# Area access:
	path('change_project/', area_access.change_project, name='change_project'),
	path('change_project/<int:new_project>/', area_access.change_project, name='change_project'),
	path('force_area_logout/<int:user_id>/', area_access.force_area_logout, name='force_area_logout'),
	path('self_log_in/', area_access.self_log_in, name='self_log_in'),
	path('save_area_access_comment/', area_access.save_area_access_comment, name='save_area_access_comment'),
	path('ad_hoc_area_access_record/', area_access.ad_hoc_area_access_record, name='ad_hoc_area_access_record'),
	path('save_aa_customer_comment/', area_access.save_aa_customer_comment, name='save_aa_customer_comment'),
	path('end_area_access_charge/', area_access.end_area_access_charge, name='end_area_access_charge'),

	# Laboratory usage:
	path('usage/', usage.usage, name='usage'),
	path('billing_information/<str:timeframe>/', usage.billing_information, name='billing_information'),

	# Alerts:
	path('alerts/', alerts.alerts, name='alerts'),
	path('delete_alert/<int:alert_id>/', alerts.delete_alert, name='delete_alert'),

	# News:
	path('news/', news.view_recent_news, name='view_recent_news'),
	path('news/archive/', news.view_archived_news, name='view_archived_news'),
	path('news/archive/<int:page>/', news.view_archived_news, name='view_archived_news'),
	path('news/archive_story/<int:story_id>/', news.archive_story, name='archive_story'),
	path('news/new/', news.new_news_form, name='new_news_form'),
	path('news/update/<int:story_id>/', news.news_update_form, name='news_update_form'),
	path('news/publish/', news.publish, name='publish_new_news'),
	path('news/publish/<int:story_id>/', news.publish, name='publish_news_update'),

	# Media
	path('media/<path:path>/', serve, {'document_root': settings.MEDIA_ROOT}, name='media'),
]

if settings.ALLOW_CONDITIONAL_URLS:
	urlpatterns += [
		# API
		path('api/', include(router.urls)),

		# Tablet area access
		path('welcome_screen/<int:door_id>/', area_access.welcome_screen, name='welcome_screen'),
		path('farewell_screen/<int:door_id>/', area_access.farewell_screen, name='farewell_screen'),
		path('login_to_area/<int:door_id>/<int:area_id>/', area_access.login_to_area, name='login_to_area'),
		path('logout_of_area/<int:door_id>/<int:area_id>/', area_access.logout_of_area, name='logout_of_area'),
		path('logout_of_area/', area_access.logout_of_area, name='logout_of_area_form'),
		path('open_door/<int:door_id>/', area_access.open_door, name='open_door'),

		# Tablet kiosk
		path('kiosk/enable_tool/', kiosk.enable_tool, name='enable_tool_from_kiosk'),
		path('kiosk/disable_tool/', kiosk.disable_tool, name='disable_tool_from_kiosk'),
		path('kiosk/choices/', kiosk.choices, name='kiosk_choices'),
		path('kiosk/category_choices/<str:category>/<int:user_id>/', kiosk.category_choices, name='kiosk_category_choices'),
		path('kiosk/tool_information/<int:tool_id>/<int:user_id>/<str:back>/', kiosk.tool_information, name='kiosk_tool_information'),
		path('kiosk/<str:location>/', kiosk.kiosk, name='kiosk'),
		path('kiosk/', kiosk.kiosk, name='kiosk'),

		# Area access
		path('area_access/', area_access.area_access, name='area_access'),
		path('new_area_access_record/', area_access.new_area_access_record, name='new_area_access_record'),
		path('new_area_access_record/<int:customer>/', area_access.new_area_access_record, name='new_area_access_customer'),

		# General area occupancy table, for use with Kiosk and Area Access tablets
		path('occupancy/', status_dashboard.occupancy, name='occupancy'),

		# Reminders and periodic events
		path('email_reservation_reminders/', calendar.email_reservation_reminders, name='email_reservation_reminders'),
		path('email_usage_reminders/', calendar.email_usage_reminders, name='email_usage_reminders'),
		path('cancel_unused_reservations/', calendar.cancel_unused_reservations, name='cancel_unused_reservations'),

		# Abuse
		path('abuse/', abuse.abuse, name='abuse'),
		path('abuse/user_drill_down/', abuse.user_drill_down, name='user_drill_down'),

		# Interlock Control
		path('interlocks/', interlock.interlocks, name='interlocks'),
		path('pulse_interlock/<int:interlock_id>/', interlock.pulse_interlock, name='pulse_interlock'),
		path('pulse_all/', interlock.pulse_all, name='pulse_all_interlocks'),
		path('open_interlock/<int:interlock_id>/', interlock.open_interlock, name='open_interlock'),

		# User management
		path('users/', users.users, name='users'),
		path('user/<int:user_id>/', users.create_or_modify_user, name='create_or_modify_user'),
		path('user/new/', users.create_or_modify_user, name='create_or_modify_user'),
		path('deactivate_user/<int:user_id>/', users.deactivate, name='deactivate_user'),
		path('reset_password/<int:user_id>/', users.reset_password, name='reset_password'),
		path('unlock_account/<int:user_id>/', users.unlock_account, name='unlock_account'),
		path('delegates/', users.delegates, name='delegates'),
		path('delete_delegate/<int:pi_id>/<int:delegate_id>/', users.delete_delegate, name='delete_delegate'),
		path('add_delegate/<int:pi_id>/<int:delegate_id>/', users.add_delegate, name='add_delegate'),
		path('user_profile/<int:user_id>/', users.user_profile, name='user_profile'),
		path('save_user_profile/', users.save_user_profile, name='save_user_profile'),

		# Account & project management
		path('accounts_and_projects/', accounts_and_projects.accounts_and_projects, name='accounts_and_projects'),
		path('project/<int:identifier>/', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'project'}, name='project'),
		path('account/<int:identifier>/', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'account'}, name='account'),
		path('toggle_active/<str:kind>/<int:identifier>/', accounts_and_projects.toggle_active, name='toggle_active'),
		path('create_project/', accounts_and_projects.create_project, name='create_project'),
		path('create_account/', accounts_and_projects.create_account, name='create_account'),
		path('remove_user/<int:user_id>/from_project/<int:project_id>/', accounts_and_projects.remove_user_from_project, name='remove_user_from_project'),
		path('add_user/<int:user_id>/to_project/<int:project_id>/', accounts_and_projects.add_user_to_project, name='add_user_to_project'),

		# Account, project, and user history
		path('history/<str:item_type>/<int:item_id>/', history.history, name='history'),

		# Work Orders
		path('work_orders/', work_orders.work_orders, name='work_orders'),
		path('save_work_order/', work_orders.add_work_order, name='save_work_order'),
		path('create_work_order/', work_orders.create_work_order, name='create_work_order'),
		path('delete_work_order/<int:work_order_id>/', work_orders.delete_work_order, name='delete_work_order'),
		path('work_order_transactions/<int:work_order_id>/', work_orders.work_order_transactions, name='work_order_transactions'),
		path('add_work_order_transaction/<int:work_order_id>/<int:content_type_id>/<int:object_id>/', work_orders.add_work_order_transaction, name='add_work_order_transaction'),
		path('remove_work_order_transaction/<int:work_order_transaction_id>/', work_orders.remove_work_order_transaction, name='remove_work_order_transaction'),
		path('update_work_order_status/<int:work_order_id>/<int:status_id>/', work_orders.update_work_order_status, name='update_work_order_status'),

		# Remote work
		path('remote_work/', remote_work.remote_work, name='remote_work'),
		path('validate_staff_charge/<int:staff_charge_id>/', remote_work.validate_staff_charge, name='validate_staff_charge'),
		path('validate_usage_event/<int:usage_event_id>/', remote_work.validate_usage_event, name='validate_usage_event'),
		path('validate_area_access_record/<int:area_access_record_id>/', remote_work.validate_area_access_record, name='validate_area_access_record'),
		path('validate_consumable_withdraw/<int:consumable_withdraw_id>/', remote_work.validate_consumable_withdraw, name='validate_consumable_withdraw'),
		path('contest_staff_charge/<int:staff_charge_id>/', remote_work.contest_staff_charge, name='contest_staff_charge'),
		path('contest_usage_event/<int:usage_event_id>/', remote_work.contest_usage_event, name='contest_usage_event'),
		path('contest_area_access_record/<int:area_access_record_id>/', remote_work.contest_area_access_record, name='contest_area_access_record'),
		path('contest_consumable_withdraw/<int:consumable_withdraw_id>/', remote_work.contest_consumable_withdraw, name='contest_consumable_withdraw'),
		path('save_contest/', remote_work.save_contest, name='save_contest'),
		path('review_contested_items/', remote_work.review_contested_items, name='review_contested_items'),
		path('resolve_staff_charge_contest/', remote_work.resolve_staff_charge_contest, name='resolve_staff_charge_contest'),
		path('resolve_usage_event_contest/', remote_work.resolve_usage_event_contest, name='resolve_usage_event_contest'),
		path('resolve_area_access_record_contest/', remote_work.resolve_area_access_record_contest, name='resolve_area_access_record_contest'),
		path('resolve_consumable_withdraw_contest/', remote_work.resolve_consumable_withdraw_contest, name='resolve_consumable_withdraw_contest'),
		path('save_contest_resolution/', remote_work.save_contest_resolution, name='save_contest_resolution'),
		path('contest_transaction_entry/', remote_work.contest_transaction_entry, name='contest_transaction_entry'),

		# Site customization
		path('customization/', customization.customization, name='customization'),
		path('customize/<str:element>/', customization.customize, name='customize'),

		# Samples
		path('samples/', samples.samples, name='samples'),
		path('create_or_modify_sample/<int:sample_id>/', samples.create_or_modify_sample, name='create_or_modify_sample'),
		path('get_samples/', samples.get_samples, name='get_samples'),
		path('modal_create_sample/<int:project_id>/', samples.modal_create_sample, name='modal_create_sample'),
		path('sample_history/<int:sample_id>/', samples.sample_history, name='sample_history'),
		path('sample_history/', samples.sample_history, name='sample_history_user'),
		path('save_sample_comment/', samples.save_sample_comment, name='save_sample_comment'),
		path('remove_sample/', samples.remove_sample, name='remove_sample'),
		path('add_run_existing_sample/', samples.add_run_existing_sample, name='add_run_existing_sample'),
		path('modal_select_sample/<int:project_id>/', samples.modal_select_sample, name='modal_select_sample'),
	]

if settings.DEBUG:
	# Static files
	urlpatterns += [
		path('static/<path:path>/', serve, {'document_root': settings.STATIC_ROOT}, name='static'),
	]

	try:
		# Django debug toolbar
		import debug_toolbar
		urlpatterns += [
			path('__debug__/', include(debug_toolbar.urls)),
		]
	except ImportError:
		pass
