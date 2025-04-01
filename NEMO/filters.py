import logging
from django.db.models import Q
from django.utils import timezone
from django_filters import FilterSet, IsoDateTimeFilter, BooleanFilter
from django_filters.widgets import BooleanWidget

from NEMO.models import Reservation, UsageEvent, AreaAccessRecord, User

logger = logging.getLogger(__name__)


class ReservationFilter(FilterSet):
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')
	missed = BooleanFilter('missed', widget=BooleanWidget())

	class Meta:
		model = Reservation
		fields = []


class UsageEventFilter(FilterSet):
	logger.debug("Entering the UsageEventFilter")
	start_gte = IsoDateTimeFilter('start', lookup_expr='gte')
	start_lt = IsoDateTimeFilter('start', lookup_expr='lt')
	recent_or_in_use = BooleanFilter(method='filter_recent_or_in_use', widget=BooleanWidget())

	class Meta:
		model = UsageEvent
		fields = []

	def __init__(self, *args, **kwargs):
		logger.debug("Initializing UsageEventFilter")
		super().__init__(*args, **kwargs)


	def filter_recent_or_in_use(self, queryset, name, value):
		logger.debug("Applying recent_or_in_use filter with value: %s", value)
		if value:
			now = timezone.now()
			five_minutes_ago = now - timezone.timedelta(minutes=5)
			filtered_queryset = queryset.filter(Q(end__isnull=True) | Q(end__gte=five_minutes_ago))
			logger.debug("Filtered queryset count: %d", filtered_queryset.count())
			return filtered_queryset
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
