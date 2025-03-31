from django.db.models import Q
from django.utils import timezone
from django_filters import FilterSet, IsoDateTimeFilter, BooleanFilter
from django_filters.widgets import BooleanWidget

from NEMO.models import Reservation, UsageEvent, AreaAccessRecord, User


class ReservationFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')
	missed = BooleanFilter('missed', widget=BooleanWidget())

	class Meta:
		model = Reservation
		fields = []


class UsageEventFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')
	recent_or_in_use = BooleanFilter(method='filter_recent_or_in_use', widget=BooleanWidget())

	class Meta:
		model = UsageEvent
		fields = []

	def filter_recent_or_in_use(self, queryset, name, value):
		if value:
			now = timezone.now()
			five_minutes_ago = now - timezone.timedelta(minutes=5)
			return queryset.filter(Q(end__isnull=True) | Q(end__gte=five_minutes_ago))
		return queryset


class AreaAccessRecordFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')

	class Meta:
		model = AreaAccessRecord
		fields = []


class UserFilter(FilterSet):

	class Meta:
		model = User
		fields = {
			'date_joined': ['month', 'year'],
		}
