from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

class CustomPageNumberPagination(PageNumberPagination):
    def get_paginated_response(self, data):
        request = self.request
        host = request.get_host()
        scheme = request.scheme
        next_url = self.get_next_link()
        previous_url = self.get_previous_link()

        if next_url:
            next_url = next_url.replace(f"{scheme}://{host}", f"{scheme}://{host}:{request.get_port()}")
        if previous_url:
            previous_url = previous_url.replace(f"{scheme}://{host}", f"{scheme}://{host}:{request.get_port()}")

        return Response({
            'count': self.page.paginator.count,
            'next': next_url,
            'previous': previous_url,
            'results': data,
        })
