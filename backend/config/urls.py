from django.contrib import admin
from django.urls import path,include
from django.conf import settings
from django.views.static import serve
from django.urls import re_path
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView,SpectacularSwaggerView
from apps.core import api
from apps.core import admin_api

def serve_media(request,path):
    return serve(request,path,document_root=settings.MEDIA_ROOT)

@require_GET
@never_cache
def health_live(request):
    return JsonResponse({'status': 'ok'})

@require_GET
@never_cache
def health_ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
    except Exception:
        return JsonResponse({'status': 'unavailable'}, status=503)
    return JsonResponse({'status': 'ok', 'database': 'ok'})

router=DefaultRouter()
router.register('products',api.ProductView,basename='products')
router.register('categories',api.CategoryView,basename='categories')
router.register('sales',api.SaleView,basename='sales')
urlpatterns=[path('',api.home),path('admin/',admin.site.urls),path('api/v1/',include(router.urls)),path('api/v1/debts/',api.Debts.as_view()),path('api/v1/debts/<int:pk>/',api.DebtDetail.as_view()),path('api/v1/debts/<int:pk>/payments/',api.DebtPayments.as_view()),path('api/v1/admin/dashboard/',admin_api.Dashboard.as_view()),path('api/v1/admin/users/',admin_api.UserList.as_view()),path('api/v1/admin/users/<int:pk>/',admin_api.UserDetail.as_view()),path('api/v1/admin/stores/',admin_api.StoreList.as_view()),path('api/v1/admin/plans/',admin_api.Plans.as_view()),path('api/v1/admin/plans/<int:pk>/',admin_api.PlanDetail.as_view()),path('api/v1/admin/subscriptions/',admin_api.SubscriptionList.as_view()),path('api/v1/admin/payments/',admin_api.Payments.as_view()),path('api/v1/admin/audit/',admin_api.Audit.as_view()),path('api/v1/admin/system-status/',admin_api.SystemStatus.as_view()),path('api/v1/auth/login/',api.AuthLogin.as_view()),path('api/v1/auth/activate/',api.CredentialRedeem.as_view()),path('api/v1/auth/set-password/',api.CredentialRedeem.as_view()),path('api/v1/auth/password-reset/confirm/',api.ResetRedeem.as_view()),path('api/v1/auth/change-username/',api.ChangeUsername.as_view()),path('api/v1/auth/change-password/',api.ChangePassword.as_view()),path('api/v1/auth/token/refresh/',api.TokenRefreshView.as_view()),path('api/v1/auth/logout/',api.Logout.as_view()),path('api/v1/me/',api.Me.as_view()),path('api/v1/store/',api.StoreView.as_view()),path('api/v1/inventory/',api.Inventory.as_view()),path('api/v1/inventory/movements/',api.Movements.as_view()),path('api/v1/inventory/adjustments/',api.Adjustment.as_view()),path('api/v1/sync/push/',api.SyncPush.as_view()),path('api/v1/sync/pull/',api.SyncPull.as_view()),path('api/v1/reports/summary/',api.Reports.as_view()),path('api/v1/subscription/status/',api.Status.as_view()),path('api/v1/subscriptions/history/',api.SubscriptionHistoryList.as_view()),path('api/v1/plans/',api.Plans.as_view()),path('api/v1/payments/',api.Payments.as_view()),path('api/v1/admin/issue-credential/',api.AdminIssue.as_view()),path('api/v1/schema/',SpectacularAPIView.as_view(),name='schema'),path('api/v1/docs/',SpectacularSwaggerView.as_view(url_name='schema'))]
urlpatterns += [path('api/v1/admin/payments/<int:pk>/',admin_api.PaymentDetail.as_view())]
urlpatterns += [path('health/live', health_live), path('health/ready', health_ready)]
urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve_media)]
