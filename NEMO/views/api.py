from rest_framework.permissions import AllowAny
from rest_framework.viewsets import ReadOnlyModelViewSet
from django_filters import rest_framework as filters
from django.db.models import Q
from django.utils import timezone
import logging

from NEMO.filters import ReservationFilter, UsageEventFilter, AreaAccessRecordFilter, UserFilter
from NEMO.models import User, Project, Account, Reservation, UsageEvent, AreaAccessRecord, Task, ScheduledOutage, Tool
from NEMO.serializers import UserSerializer, ProjectSerializer, AccountSerializer, ReservationSerializer, UsageEventSerializer, AreaAccessRecordSerializer, TaskSerializer, ScheduledOutageSerializer, ToolSerializer

logger = logging.getLogger(__name__)

class UserViewSet(ReadOnlyModelViewSet):
	queryset = User.objects.all()
	serializer_class = UserSerializer
	filter_class = UserFilter


class ProjectViewSet(ReadOnlyModelViewSet):
	queryset = Project.objects.all()
	serializer_class = ProjectSerializer


class AccountViewSet(ReadOnlyModelViewSet):
	queryset = Account.objects.all()
	serializer_class = AccountSerializer


class ToolViewSet(ReadOnlyModelViewSet):
	queryset = Tool.objects.all()
	serializer_class = ToolSerializer


class ReservationViewSet(ReadOnlyModelViewSet):
	queryset = Reservation.objects.all()
	serializer_class = ReservationSerializer
	filter_class = ReservationFilter


class UsageEventViewSet(ReadOnlyModelViewSet):
	now = timezone.now()
	permission_classes = [AllowAny]
	serializer_class = UsageEventSerializer	
	pagination_class = None
	queryset = UsageEvent.objects.all()[:1000]
	#filter_backends = [filters.DjangoFilterBackend]
	#filter_class = UsageEventFilter

	def get_queryset(self):
		logger.debug("UsageEventViewSet: get_queryset called")
		queryset = super().get_queryset()
		now = timezone.now()
		thirty_days_ago = now - timezone.timedelta(days=30)
		queryset = queryset.filter(Q(end__isnull=True) | Q(end__gte=thirty_days_ago))
		recent_or_in_use = self.request.query_params.get('recent_or_in_use', None)
		if recent_or_in_use:
			now = timezone.now()
			five_minutes_ago = now - timezone.timedelta(minutes=5)
			queryset = queryset.filter(Q(end__isnull=True) | Q(end__gte=five_minutes_ago))
			logger.debug("UsageEventViewSet: queryset count before filtering: %d", queryset.count())
		return queryset


class AreaAccessRecordViewSet(ReadOnlyModelViewSet):
	queryset = AreaAccessRecord.objects.all()
	serializer_class = AreaAccessRecordSerializer
	filter_class = AreaAccessRecordFilter


class TaskViewSet(ReadOnlyModelViewSet):
	queryset = Task.objects.all()
	serializer_class = TaskSerializer


class ScheduledOutageViewSet(ReadOnlyModelViewSet):
	queryset = ScheduledOutage.objects.all()
	serializer_class = ScheduledOutageSerializer
