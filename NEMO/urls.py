from django.urls import path, re_path
from django.conf import settings
from django.conf.urls import url, include
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.views.static import serve
from rest_framework import routers

from NEMO.models import GlobalFlag
from NEMO.scheduler import start_scheduler
from NEMO.views import abuse, accounts_and_projects, alerts, api, area_access, authentication, calendar, configuration_agenda, consumables, contact_staff, customization, email, feedback, get_projects, history, interlock, jumbotron, kiosk, landing, maintenance, mobile, usage, news, qualifications, remote_work, resources, safety, sidebar, staff_charges, status_dashboard, tasks, tool_control, training, tutorials, users

# Use our custom login page instead of Django's built-in one.
#admin.site.login = login_required(admin.site.login)

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
	re_path(r'^admin/', admin.site.urls),
	# Authentication & error pages:
	re_path(r'^valid/', include('microsoft_auth.urls', namespace='microsoft')),
	re_path(r'^login/$', authentication.login_user, name='login'),
	re_path(r'^logout/$', authentication.logout_user, name='logout'),
	re_path(r'^choose_core/$', authentication.choose_core, name='choose_core'),

	# Root URL defaults to the calendar page on desktop systems, and the mobile homepage for mobile devices:
	re_path(r'^$', landing.landing, name='landing'),

	# Get a list of projects for a user:
	re_path(r'^get_projects/$', get_projects.get_projects, name='get_projects'),
	re_path(r'^get_projects_for_tool_control/$', get_projects.get_projects_for_tool_control, name='get_projects_for_tool_control'),
	re_path(r'^get_projects_for_self/(?P<tool_id>\d+)/$', get_projects.get_projects_for_self, name='get_projects_for_self'),
	re_path(r'^get_areas/$', get_projects.get_areas, name='get_areas'),

	# Tool control:
	re_path(r'^tools/$', tool_control.tools, name='tools'),
	re_path(r'^create_or_modify_tool/(?P<tool_id>\d+)/$', tool_control.create_or_modify_tool, name='create_or_modify_tool'),
	re_path(r'^tool_control/(?P<tool_id>\d+)/$', tool_control.tool_control, name='tool_control'),
	re_path(r'^tool_control/(?P<tool_id>\d+)/(?P<qualified_only>\d+)/(?P<core_only>\d+)/$', tool_control.tool_control, name='tool_control'),
	re_path(r'^tool_control/$', tool_control.tool_control, name='tool_control'),
	re_path(r'^tool_status/(?P<tool_id>\d+)/$', tool_control.tool_status, name='tool_status'),
	re_path(r'^use_tool_for_other/$', tool_control.use_tool_for_other, name='use_tool_for_other'),
	re_path(r'^tool_configuration/$', tool_control.tool_configuration, name='tool_configuration'),
	re_path(r'^create_comment/$', tool_control.create_comment, name='create_comment'),
	re_path(r'^hide_comment/(?P<comment_id>\d+)/$', tool_control.hide_comment, name='hide_comment'),
	re_path(r'^enable_tool/(?P<tool_id>\d+)/user/(?P<user_id>\d+)/project/(?P<project_id>\d+)/staff_charge/(?P<staff_charge>(true|false))/billing_mode/(?P<billing_mode>(true|false))/$', tool_control.enable_tool, name='enable_tool'),
	re_path(r'^enable_tool_multi/$', tool_control.enable_tool_multi, name='enable_tool_multi'),
	re_path(r'^disable_tool/(?P<tool_id>\d+)/$', tool_control.disable_tool, name='disable_tool'),
	re_path(r'^past_comments_and_tasks/$', tool_control.past_comments_and_tasks, name='past_comments_and_tasks'),
	re_path(r'^ten_most_recent_past_comments_and_tasks/(?P<tool_id>\d+)/$', tool_control.ten_most_recent_past_comments_and_tasks, name='ten_most_recent_past_comments_and_tasks'),
	re_path(r'^usage_event_projects_save/$', tool_control.usage_event_projects_save, name='usage_event_projects_save'),
	re_path(r'^create_usage_event/$', tool_control.create_usage_event, name='create_usage_event'),
	re_path(r'^save_usage_event/$', tool_control.save_usage_event, name='save_usage_event'),
	re_path(r'^save_operator_comment/$', tool_control.save_operator_comment, name='save_operator_comment'),
	re_path(r'^save_tool_comment/$', tool_control.save_tool_comment, name='save_tool_comment'),

	# Tasks:
	re_path(r'^create_task/$', tasks.create, name='create_task'),
	re_path(r'^cancel_task/(?P<task_id>\d+)/$', tasks.cancel, name='cancel_task'),
	re_path(r'^update_task/(?P<task_id>\d+)/$', tasks.update, name='update_task'),
	re_path(r'^task_update_form/(?P<task_id>\d+)/$', tasks.task_update_form, name='task_update_form'),
	re_path(r'^task_resolution_form/(?P<task_id>\d+)/$', tasks.task_resolution_form, name='task_resolution_form'),

	# Calendar:
	#re_path(r'^calendar/(?P<tool_id>\d+)/$', calendar.calendar, name='calendar'),
	re_path(r'^calendar/(?P<tool_id>\d+)/(?P<qualified_only>\d+)/(?P<core_only>\d+)/$', calendar.calendar, name='calendar'),
	re_path(r'^calendar/$', calendar.calendar, name='calendar'),
	re_path(r'^event_feed/$', calendar.event_feed, name='event_feed'),
	re_path(r'^create_reservation/$', calendar.create_reservation, name='create_reservation'),
	re_path(r'^create_outage/$', calendar.create_outage, name='create_outage'),
	re_path(r'^resize_reservation/$', calendar.resize_reservation, name='resize_reservation'),
	re_path(r'^resize_outage/$', calendar.resize_outage, name='resize_outage'),
	re_path(r'^move_reservation/$', calendar.move_reservation, name='move_reservation'),
	re_path(r'^move_outage/$', calendar.move_outage, name='move_outage'),
	re_path(r'^cancel_reservation/(?P<reservation_id>\d+)/$', calendar.cancel_reservation, name='cancel_reservation'),
	re_path(r'^cancel_outage/(?P<outage_id>\d+)/$', calendar.cancel_outage, name='cancel_outage'),
	re_path(r'^set_reservation_title/(?P<reservation_id>\d+)/$', calendar.set_reservation_title, name='set_reservation_title'),
	re_path(r'^event_details/reservation/(?P<reservation_id>\d+)/$', calendar.reservation_details, name='reservation_details'),
	re_path(r'^event_details/outage/(?P<outage_id>\d+)/$', calendar.outage_details, name='outage_details'),
	re_path(r'^event_details/usage/(?P<event_id>\d+)/$', calendar.usage_details, name='usage_details'),
	re_path(r'^event_details/area_access/(?P<event_id>\d+)/$', calendar.area_access_details, name='area_access_details'),
	re_path(r'^proxy_reservation/$', calendar.proxy_reservation, name='proxy_reservation'),
	re_path(r'^create_notification/$', calendar.create_notification, name='create_notification'),
	re_path(r'^delete_notification/$', calendar.delete_notification, name='delete_notification'),
	re_path(r'^save_notifications/$', calendar.save_notifications, name='save_notifications'),

	# Qualifications:
	re_path(r'^qualifications/$', qualifications.qualifications, name='qualifications'),
	re_path(r'^modify_qualifications/$', qualifications.modify_qualifications, name='modify_qualifications'),
	re_path(r'^get_qualified_users/$', qualifications.get_qualified_users, name='get_qualified_users'),

	# Staff charges:
	re_path(r'^staff_charges/$', staff_charges.staff_charges, name='staff_charges'),
	re_path(r'^ad_hoc_staff_charge/$', staff_charges.ad_hoc_staff_charge, name='ad_hoc_staff_charge'),
	re_path(r'^ad_hoc_overlap_resolution/$', staff_charges.ad_hoc_overlap_resolution, name='ad_hoc_overlap_resolution'),
	re_path(r'^staff_charge_entry/$', staff_charges.staff_charge_entry, name='staff_charge_entry'),
	re_path(r'^ad_hoc_staff_charge_entry/$', staff_charges.ad_hoc_staff_charge_entry, name='ad_hoc_staff_charge_entry'),
	re_path(r'^begin_staff_charge/$', staff_charges.begin_staff_charge, name='begin_staff_charge'),
	re_path(r'^end_staff_charge/(?P<modal_flag>\d+)/$', staff_charges.end_staff_charge, name='end_staff_charge'),
	re_path(r'^begin_staff_area_charge/$', staff_charges.begin_staff_area_charge, name='begin_staff_area_charge'),
	re_path(r'^end_staff_area_charge/$', staff_charges.end_staff_area_charge, name='end_staff_area_charge'),
	re_path(r'^staff_charge_projects_save/(?P<modal_flag>\d+)/$', staff_charges.staff_charge_projects_save, name='staff_charge_projects_save'),
	re_path(r'^continue_staff_charge/(?P<staff_charge_id>\d+)/$', staff_charges.continue_staff_charge, name='continue_staff_charge'),
	re_path(r'^save_staff_comment/$', staff_charges.save_staff_comment, name='save_staff_comment'),
	re_path(r'^save_sc_customer_comment/$', staff_charges.save_sc_customer_comment, name='save_sc_customer_comment'),

	# Status dashboard:
	re_path(r'^status_dashboard/$', status_dashboard.status_dashboard, name='status_dashboard'),

	# Jumbotron:
	re_path(r'^jumbotron/$', jumbotron.jumbotron, name='jumbotron'),
	re_path(r'^jumbotron_content/$', jumbotron.jumbotron_content, name='jumbotron_content'),

	# Utility functions:
	re_path(r'^refresh_sidebar_icons/$', sidebar.refresh_sidebar_icons, name='refresh_sidebar_icons'),

	# Laboratory feedback
	re_path(r'^feedback/$', feedback.feedback, name='feedback'),

	# Laboratory rules tutorial
	# TODO: this should be removed, since this is really a job for a Learning Management System...
	re_path(r'^nanofab_rules_tutorial/$', tutorials.nanofab_rules, name='nanofab_rules'),

	# Configuration agenda for staff:
	re_path(r'^configuration_agenda/$', configuration_agenda.configuration_agenda, name='configuration_agenda'),
	re_path(r'^configuration_agenda/near_future/$', configuration_agenda.configuration_agenda, {'time_period': 'near_future'}, name='configuration_agenda_near_future'),

	# Email broadcasts:
	re_path(r'^get_email_form/$', email.get_email_form, name='get_email_form'),
	re_path(r'^get_email_form_for_user/(?P<user_id>\d+)/$', email.get_email_form_for_user, name='get_email_form_for_user'),
	re_path(r'^send_email/$', email.send_email, name='send_email'),
	re_path(r'^email_broadcast/$', email.email_broadcast, name='email_broadcast'),
	re_path(r'^email_broadcast/(?P<audience>tool|account|project|user|group|tool_date|project_date|active_users|active_users_date)/$', email.email_broadcast, name='email_broadcast'),
	re_path(r'^compose_email/$', email.compose_email, name='compose_email'),
	re_path(r'^send_broadcast_email/$', email.send_broadcast_email, name='send_broadcast_email'),

	# Maintenance:
	re_path(r'^maintenance/(?P<sort_by>urgency|force_shutdown|tool|problem_category|last_updated|creation_time)/$', maintenance.maintenance, name='maintenance'),
	re_path(r'^maintenance/$', maintenance.maintenance, name='maintenance'),
	re_path(r'^task_details/(?P<task_id>\d+)/$', maintenance.task_details, name='task_details'),

	# Resources:
	re_path(r'^resources/$', resources.resources, name='resources'),
	re_path(r'^resources/modify/(?P<resource_id>\d+)/$', resources.modify_resource, name='modify_resource'),
	re_path(r'^resources/schedule_outage/$', resources.schedule_outage, name='schedule_resource_outage'),
	re_path(r'^resources/delete_scheduled_outage/(?P<outage_id>\d+)/$', resources.delete_scheduled_outage, name='delete_scheduled_resource_outage'),

	# Consumables:
	re_path(r'^consumables/$', consumables.consumables, name='consumables'),
	re_path(r'^get_consumables/$', consumables.get_consumables, name='get_consumables'),
	re_path(r'^save_withdraw_notes/$', consumables.save_withdraw_notes, name='save_withdraw_notes'),

	# Training:
	#re_path(r'^training/$', training.training, name='training'),
	#re_path(r'^training_entry/$', training.training_entry, name='training_entry'),
	#re_path(r'^charge_training/$', training.charge_training, name='charge_training'),

	# Safety:
	re_path(r'^safety/$', safety.safety, name='safety'),
	re_path(r'^safety/resolved$', safety.resolved_safety_issues, name='resolved_safety_issues'),
	re_path(r'^safety/update/(?P<ticket_id>\d+)/$', safety.update_safety_issue, name='update_safety_issue'),

	# Mobile:
	re_path(r'^choose_tool/then/(?P<next_page>view_calendar|tool_control)/$', mobile.choose_tool, name='choose_tool'),
	re_path(r'^new_reservation/(?P<tool_id>\d+)/$', mobile.new_reservation, name='new_reservation'),
	re_path(r'^new_reservation/(?P<tool_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.new_reservation, name='new_reservation'),
	re_path(r'^make_reservation/$', mobile.make_reservation, name='make_reservation'),
	re_path(r'^view_calendar/(?P<tool_id>\d+)/$', mobile.view_calendar, name='view_calendar'),
	re_path(r'^view_calendar/(?P<tool_id>\d+)/(?P<date>20\d\d-(0[1-9]|1[012])-(0[1-9]|[12][0-9]|3[01]))/$', mobile.view_calendar, name='view_calendar'),

	# Contact staff:
	re_path(r'^contact_staff/$', contact_staff.contact_staff, name='contact_staff'),

	# Area access:
	re_path(r'^change_project/$', area_access.change_project, name='change_project'),
	re_path(r'^change_project/(?P<new_project>\d+)/$', area_access.change_project, name='change_project'),
	re_path(r'^force_area_logout/(?P<user_id>\d+)/$', area_access.force_area_logout, name='force_area_logout'),
	re_path(r'^self_log_in/$', area_access.self_log_in, name='self_log_in'),
	re_path(r'^save_area_access_comment/$', area_access.save_area_access_comment, name='save_area_access_comment'),
	re_path(r'^ad_hoc_area_access_record/$', area_access.ad_hoc_area_access_record, name='ad_hoc_area_access_record'),
	re_path(r'^save_aa_customer_comment/$', area_access.save_aa_customer_comment, name='save_aa_customer_comment'),

	# Laboratory usage:
	re_path(r'^usage/$', usage.usage, name='usage'),
	re_path(r'^billing_information/(?P<timeframe>((January|February|March|April|May|June|July|August|September|October|November|December), 20\d\d))/$', usage.billing_information, name='billing_information'),

	# Alerts:
	re_path(r'^alerts/$', alerts.alerts, name='alerts'),
	re_path(r'^delete_alert/(?P<alert_id>\d+)/$', alerts.delete_alert, name='delete_alert'),

	# News:
	re_path(r'^news/$', news.view_recent_news, name='view_recent_news'),
	re_path(r'^news/archive/$', news.view_archived_news, name='view_archived_news'),
	re_path(r'^news/archive/(?P<page>\d+)/$', news.view_archived_news, name='view_archived_news'),
	re_path(r'^news/archive_story/(?P<story_id>\d+)/$', news.archive_story, name='archive_story'),
	re_path(r'^news/new/$', news.new_news_form, name='new_news_form'),
	re_path(r'^news/update/(?P<story_id>\d+)/$', news.news_update_form, name='news_update_form'),
	re_path(r'^news/publish/$', news.publish, name='publish_new_news'),
	re_path(r'^news/publish/(?P<story_id>\d+)/$', news.publish, name='publish_news_update'),

	# Media
	re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}, name='media'),
]

if settings.ALLOW_CONDITIONAL_URLS:
	urlpatterns += [
		#re_path(r'^admin/', admin.site.urls),
		re_path(r'^api/', include(router.urls)),

		# Tablet area access
		re_path(r'^welcome_screen/(?P<door_id>\d+)/$', area_access.welcome_screen, name='welcome_screen'),
		re_path(r'^farewell_screen/(?P<door_id>\d+)/$', area_access.farewell_screen, name='farewell_screen'),
		re_path(r'^login_to_area/(?P<door_id>\d+)/(?P<area_id>\d+)/$', area_access.login_to_area, name='login_to_area'),
		re_path(r'^logout_of_area/(?P<door_id>\d+)/(?P<area_id>\d+)/$', area_access.logout_of_area, name='logout_of_area'),
		re_path(r'^logout_of_area/$', area_access.logout_of_area, name='logout_of_area_form'),
		re_path(r'^open_door/(?P<door_id>\d+)/$', area_access.open_door, name='open_door'),

		# Tablet kiosk
		re_path(r'^kiosk/enable_tool/$', kiosk.enable_tool, name='enable_tool_from_kiosk'),
		re_path(r'^kiosk/disable_tool/$', kiosk.disable_tool, name='disable_tool_from_kiosk'),
		re_path(r'^kiosk/choices/$', kiosk.choices, name='kiosk_choices'),
		re_path(r'^kiosk/category_choices/(?P<category>.+)/(?P<user_id>\d+)/$', kiosk.category_choices, name='kiosk_category_choices'),
		re_path(r'^kiosk/tool_information/(?P<tool_id>\d+)/(?P<user_id>\d+)/(?P<back>back_to_start|back_to_category)/$', kiosk.tool_information, name='kiosk_tool_information'),
		re_path(r'^kiosk/(?P<location>.+)/$', kiosk.kiosk, name='kiosk'),
		re_path(r'^kiosk/$', kiosk.kiosk, name='kiosk'),

		# Area access
		re_path(r'^area_access/$', area_access.area_access, name='area_access'),
		re_path(r'^new_area_access_record/$', area_access.new_area_access_record, name='new_area_access_record'),
		re_path(r'^new_area_access_record/(?P<customer>\d+)/$', area_access.new_area_access_record, name='new_area_access_customer'),

		# General area occupancy table, for use with Kiosk and Area Access tablets
		re_path(r'^occupancy/$', status_dashboard.occupancy, name='occupancy'),

		# Reminders and periodic events
		re_path(r'^email_reservation_reminders/$', calendar.email_reservation_reminders, name='email_reservation_reminders'),
		re_path(r'^email_usage_reminders/$', calendar.email_usage_reminders, name='email_usage_reminders'),
		re_path(r'^cancel_unused_reservations/$', calendar.cancel_unused_reservations, name='cancel_unused_reservations'),

		# Abuse:
		re_path(r'^abuse/$', abuse.abuse, name='abuse'),
		re_path(r'^abuse/user_drill_down/$', abuse.user_drill_down, name='user_drill_down'),

		# Interlock Control:
		re_path(r'^interlocks/$', interlock.interlocks, name='interlocks'),
		re_path(r'^pulse_interlock/(?P<interlock_id>\d+)/$', interlock.pulse_interlock, name='pulse_interlock'),
		re_path(r'^pulse_all/$', interlock.pulse_all, name='pulse_all_interlocks'),
		re_path(r'^open_interlock/(?P<interlock_id>\d+)/$', interlock.open_interlock, name='open_interlock'),

		# User management:
		re_path(r'^users/$', users.users, name='users'),
		re_path(r'^user/(?P<user_id>\d+|new)/', users.create_or_modify_user, name='create_or_modify_user'),
		re_path(r'^deactivate_user/(?P<user_id>\d+)/', users.deactivate, name='deactivate_user'),
		re_path(r'^reset_password/(?P<user_id>\d+)/$', users.reset_password, name='reset_password'),
		re_path(r'^unlock_account/(?P<user_id>\d+)/$', users.unlock_account, name='unlock_account'),
		re_path(r'^delegates/$', users.delegates, name='delegates'),
		re_path(r'^delete_delegate/(?P<pi_id>\d+)/(?P<delegate_id>\d+)/$', users.delete_delegate, name='delete_delegate'),
		re_path(r'^add_delegate/(?P<pi_id>\d+)/(?P<delegate_id>\d+)/$', users.add_delegate, name='add_delegate'),

		# Account & project management:
		re_path(r'^accounts_and_projects/$', accounts_and_projects.accounts_and_projects, name='accounts_and_projects'),
		re_path(r'^project/(?P<identifier>\d+)/$', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'project'}, name='project'),
		re_path(r'^account/(?P<identifier>\d+)/$', accounts_and_projects.accounts_and_projects, kwargs={'kind': 'account'}, name='account'),
		re_path(r'^toggle_active/(?P<kind>account|project)/(?P<identifier>\d+)/$', accounts_and_projects.toggle_active, name='toggle_active'),
		re_path(r'^create_project/$', accounts_and_projects.create_project, name='create_project'),
		re_path(r'^create_account/$', accounts_and_projects.create_account, name='create_account'),
		re_path(r'^remove_user/(?P<user_id>\d+)/from_project/(?P<project_id>\d+)/$', accounts_and_projects.remove_user_from_project, name='remove_user_from_project'),
		re_path(r'^add_user/(?P<user_id>\d+)/to_project/(?P<project_id>\d+)/$', accounts_and_projects.add_user_to_project, name='add_user_to_project'),

		# Account, project, and user history
		re_path(r'^history/(?P<item_type>account|project|user)/(?P<item_id>\d+)/$', history.history, name='history'),

		# Remote work:
		re_path(r'^remote_work/$', remote_work.remote_work, name='remote_work'),
		re_path(r'^validate_staff_charge/(?P<staff_charge_id>\d+)/$', remote_work.validate_staff_charge, name='validate_staff_charge'),
		re_path(r'^validate_usage_event/(?P<usage_event_id>\d+)/$', remote_work.validate_usage_event, name='validate_usage_event'),
		re_path(r'^validate_area_access_record/(?P<area_access_record_id>\d+)/$', remote_work.validate_area_access_record, name='validate_area_access_record'),
		re_path(r'^validate_consumable_withdraw/(?P<consumable_withdraw_id>\d+)/$', remote_work.validate_consumable_withdraw, name='validate_consumable_withdraw'),
		re_path(r'^contest_staff_charge/(?P<staff_charge_id>\d+)/$', remote_work.contest_staff_charge, name='contest_staff_charge'),
		re_path(r'^contest_usage_event/(?P<usage_event_id>\d+)/$', remote_work.contest_usage_event, name='contest_usage_event'),
		re_path(r'^contest_area_access_record/(?P<area_access_record_id>\d+)/$', remote_work.contest_area_access_record, name='contest_area_access_record'),
		re_path(r'^contest_consumable_withdraw/(?P<consumable_withdraw_id>\d+)/$', remote_work.contest_consumable_withdraw, name='contest_consumable_withdraw'),
		re_path(r'^save_contest/$', remote_work.save_contest, name='save_contest'),
		re_path(r'^review_contested_items/$', remote_work.review_contested_items, name='review_contested_items'),
		re_path(r'^resolve_staff_charge_contest/$', remote_work.resolve_staff_charge_contest, name='resolve_staff_charge_contest'),
		re_path(r'^resolve_usage_event_contest/$', remote_work.resolve_usage_event_contest, name='resolve_usage_event_contest'),
		re_path(r'^resolve_area_access_record_contest/$', remote_work.resolve_area_access_record_contest, name='resolve_area_access_record_contest'),
		re_path(r'^resolve_consumable_withdraw_contest/$', remote_work.resolve_consumable_withdraw_contest, name='resolve_consumable_withdraw_contest'),
		re_path(r'^save_contest_resolution/$', remote_work.save_contest_resolution, name='save_contest_resolution'),
		re_path(r'^contest_transaction_entry/$', remote_work.contest_transaction_entry, name='contest_transaction_entry'),

		# Site customization:
		re_path(r'^customization/$', customization.customization, name='customization'),
		re_path(r'^customize/(?P<element>.+)/$', customization.customize, name='customize'),
	]

if settings.DEBUG:
	# Static files
	re_path(r'^static/(?P<path>.*$)', serve, {'document_root': settings.STATIC_ROOT}, name='static'),

	try:
		# Django debug toolbar
		import debug_toolbar
		urlpatterns += [
			re_path(r'^__debug__/', include(debug_toolbar.urls)),
		]
	except ImportError:
		pass

