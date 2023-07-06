from django.urls import path
from django_rest_passwordreset.views import reset_password_request_token, reset_password_confirm

from backend.views import PartnerUpdateView, PartnerStateView, PartnerOrdersView, RegisterAccountView, \
    ConfirmAccountView, AccountDetailsView, ContactView, LoginAccountView, CategoryView, ShopView, ProductInfoView, \
    CartView, OrderView

app_name = 'backend'

urlpatterns = [
    path('partner/update', PartnerUpdateView.as_view(), name='partner-update'),
    path('partner/state', PartnerStateView.as_view(), name='partner-state'),
    path('partner/orders', PartnerOrdersView.as_view(), name='partner-orders'),
    path('user/register', RegisterAccountView.as_view(), name='user-register'),
    path('user/register/confirm', ConfirmAccountView.as_view(), name='user-register-confirm'),
    path('user/details', AccountDetailsView.as_view(), name='user-details'),
    path('user/contact', ContactView.as_view(), name='user-contact'),
    path('user/login', LoginAccountView.as_view(), name='user-login'),
    path('user/password_reset', reset_password_request_token, name='password-reset'),
    path('user/password_reset/confirm', reset_password_confirm, name='password-reset-confirm'),
    path('categories', CategoryView.as_view(), name='categories'),
    path('shops', ShopView.as_view(), name='shops'),
    path('products', ProductInfoView.as_view(), name='shops'),
    path('basket', CartView.as_view(), name='basket'),
    path('order', OrderView.as_view(), name='order'),
]
