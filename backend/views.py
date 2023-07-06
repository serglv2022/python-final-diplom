from distutils.util import strtobool

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.db import IntegrityError
from django.db.models import Q, Sum, F
from django.http import JsonResponse
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView
from ujson import loads

from backend.models import ConfirmEmailToken, Category, Shop, ProductInfo, Order, OrderItem, Contact
from backend.serializers import UserSerializer, CategorySerializer, ShopSerializer, ProductInfoSerializer, \
    OrderSerializer, OrderItemSerializer, ContactSerializer
from backend.signals import new_order
from backend.tasks import send_email, get_import


class HomeView(TemplateView):
    template_name = 'home.html'


class RegisterAccountView(APIView):

    def post(self, request, *args, **kwargs):
        if {'first_name', 'last_name', 'email', 'password', 'company', 'position'}.issubset(request.data):
            try:
                validate_password(request.data['password'])
            except Exception as error:
                error_list = list()
                for item in error:
                    error_list.append(item)
                return JsonResponse({'Status': False, 'Errors': {'password': error_list}})
            else:
                request.data._mutable = True
                request.data.update({})
                user_serializer = UserSerializer(data=request.data)
                if user_serializer.is_valid():
                    user = user_serializer.save()
                    user.set_password(request.data['password'])
                    user.save()
                    token, _ = ConfirmEmailToken.objects.get_or_create(user_id=user.id)
                    send_email.delay('Confirmation of registration',
                                     f'Token for confirmation: {token.key}',
                                     user.email
                                     )
                    return JsonResponse({'Status': True, 'Token for confirmation': token.key},
                                        status=status.HTTP_201_CREATED)
                else:
                    return JsonResponse({'Status': False, 'Errors': user_serializer.errors},
                                        status=status.HTTP_403_FORBIDDEN)

        return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                            status=status.HTTP_400_BAD_REQUEST)


class ConfirmAccountView(APIView):
    throttle_classes = (AnonRateThrottle, )

    def post(self, request, *args, **kwargs):
        if {'email', 'token'}.issubset(request.data):

            token = ConfirmEmailToken.objects.filter(user__email=request.data['email'],
                                                     key=request.data['token']
                                                     ).first()
            if token:
                token.user.is_active = True
                token.user.save()
                token.delete()
                return JsonResponse({'Status': True})
            else:
                return JsonResponse({'Status': False, 'Errors': 'The rong token or email'})

        return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                            status=status.HTTP_400_BAD_REQUEST)


class AccountDetailsView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            serializer = UserSerializer(request.user)
            return Response(serializer.data)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if 'password' in request.data:
                errors = {}
                try:
                    validate_password(request.data['password'])
                except Exception as error:
                    error_list = list()
                    for item in error:
                        error_list.append(item)
                    return JsonResponse({'Status': False, 'Errors': {'password': error_list}},
                                        status=status.HTTP_400_BAD_REQUEST)
                else:
                    request.user.set_password(request.data['password'])
            user_serializer = UserSerializer(request.user, data=request.data, partial=True)
            if user_serializer.is_valid():
                user_serializer.save()
                return JsonResponse({'Status': True}, status=status.HTTP_200_OK)
            else:
                return JsonResponse({'Status': False, 'Errors': user_serializer.errors},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)


class LoginAccountView(APIView):
    throttle_classes = (AnonRateThrottle, )

    def post(self, request, *args, **kwargs):

        if {'email', 'password'}.issubset(request.data):
            user = authenticate(request,
                                username=request.data['email'],
                                password=request.data['password']
                                )
            if user is not None:
                if user.is_active:
                    token, _ = Token.objects.get_or_create(user=user)
                    return JsonResponse({'Status': True, 'Token': token.key})
            else:
                return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                    status=status.HTTP_403_FORBIDDEN)
        else:
            return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                status=status.HTTP_400_BAD_REQUEST)


class CategoryView(ListAPIView):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ShopView(ListAPIView):
    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    throttle_classes = (AnonRateThrottle, )

    def get(self, request, *args, **kwargs):
        query = Q(shop__state=True)
        shop_id = request.query_params.get('shop_id')
        category_id = request.query_params.get('category_id')
        if shop_id:
            query = query & Q(shop_id=shop_id)
        if category_id:
            query = query & Q(product__category_id=category_id)
        queryset = ProductInfo.objects.filter(query).select_related(
            'shop', 'product__category').prefetch_related(
            'product_parameters__parameter').distinct()
        serializer = ProductInfoSerializer(queryset, many=True)
        return Response(serializer.data)


class CartView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            cart = Order.objects.filter(
                user_id=request.user.id,
                state='cart').prefetch_related('ordered_items__product_info__product__category',
                                               'ordered_items__product_info__product_parameters__parameter').annotate(
                total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

            serializer = OrderSerializer(cart, many=True)
            return Response(serializer.data)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            items_sting = request.data.get('items')
            if items_sting:
                try:
                    items_dict = loads(items_sting)
                except ValueError:
                    JsonResponse({'Status': False, 'Error': 'Invalid request'})
                else:
                    cart, _ = Order.objects.get_or_create(user_id=request.user.id,
                                                          state='cart')
                    counter = 0
                    for item in items_dict:
                        item.update({'order': cart.id})
                        serializer = OrderItemSerializer(data=item)
                        if serializer.is_valid():
                            try:
                                serializer.save()
                            except IntegrityError as error:
                                return JsonResponse({'Status': False, 'Errors': str(error)})
                            else:
                                counter += 1
                        else:
                            JsonResponse({'Status': False, 'Errors': serializer.errors})
                    return JsonResponse({'Status': True, 'Objects created': counter},
                                        status.HTTP_201_CREATED)
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def delete(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            items_sting = request.data.get('items')
            if items_sting:
                items_list = items_sting.split(',')
                cart, _ = Order.objects.get_or_create(user_id=request.user.id, state='cart')
                query = Q()
                success = False
                for item in items_list:
                    if item.isdigit():
                        query = query | Q(order_id=cart.id, id=item)
                        success = True
                if success:
                    counter = OrderItem.objects.filter(query).delete()[0]
                    return JsonResponse({'Status': True, 'Objects deleted': counter},
                                        status=status.HTTP_200_OK)
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def put(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            items = request.data.get('items')
            if items:
                try:
                    items_dict = loads(items)
                except ValueError:
                    JsonResponse({'Status': False, 'Error': 'Invalid request'})
                else:
                    cart, _ = Order.objects.get_or_create(user_id=request.user.id,
                                                          state='cart')
                    counter = 0
                    for item in items_dict:
                        if type(item['id']) == int and type(item['quantity']) == int:
                            counter += OrderItem.objects.filter(order_id=cart.id,
                                                                id=item['id']).update(
                                quantity=item['quantity'])
                    return JsonResponse({'Status': True, 'Objects updated': counter},
                                        status=status.HTTP_200_OK)
            return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)


class PartnerUpdateView(APIView):
    throttle_classes = (UserRateThrottle, )

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.type == 'shop':
                url = request.data.get('url')
                if url:
                    try:
                        task = get_import.delay(url, request.user.id)
                    except IntegrityError as error:
                        return JsonResponse({'Status': False,
                                             'Errors': str(error)})
                    return JsonResponse({'Status': True}, status=status.HTTP_200_OK)

                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
            else:
                JsonResponse({'Status': False, 'Error': 'Access denied'},
                             status=status.HTTP_403_FORBIDDEN)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)


class PartnerStateView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.type == 'shop':
                shop = request.user.shop
                serializer = ShopSerializer(shop)
                return Response(serializer.data)
            else:
                JsonResponse({'Status': False, 'Error': 'Access denied'},
                             status=status.HTTP_403_FORBIDDEN)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.type == 'shop':
                state = request.data.get('state')
                if state:
                    try:
                        Shop.objects.filter(user_id=request.user.id).update(
                            state=strtobool(state))
                        return JsonResponse({'Status': True}, status=status.HTTP_200_OK)
                    except ValueError as error:
                        return JsonResponse({'Status': False, 'Errors': str(error)})
                else:
                    return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                        status=status.HTTP_400_BAD_REQUEST)
            else:
                JsonResponse({'Status': False, 'Error': 'Access denied'},
                             status=status.HTTP_403_FORBIDDEN)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)


class PartnerOrdersView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if request.user.type == 'shop':
                order = Order.objects.filter(
                    ordered_items__product_info__shop__user_id=request.user.id).exclude(
                    state='basket').prefetch_related(
                    'ordered_items__product_info__product__category',
                    'ordered_items__product_info__product_parameters__parameter').select_related(
                    'contact').annotate(
                    total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()
                serializer = OrderSerializer(order, many=True)
                return Response(serializer.data)
            else:
                JsonResponse({'Status': False, 'Error': 'Access denied'},
                             status=status.HTTP_403_FORBIDDEN)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)


class ContactView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            contact = Contact.objects.filter(user_id=request.user.id)
            serializer = ContactSerializer(contact, many=True)
            return Response(serializer.data)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if {'city', 'street', 'phone'}.issubset(request.data):
                request.data._mutable = True
                request.data.update({'user': request.user.id})
                serializer = ContactSerializer(data=request.data)
                if serializer.is_valid():
                    serializer.save()
                    return JsonResponse({'Status': True}, status=status.HTTP_201_CREATED)
                else:
                    JsonResponse({'Status': False, 'Errors': serializer.errors})
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def delete(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            items = request.data.get('items')
            if items:
                items_list = items.split(',')
                query = Q()
                success = False
                for item in items_list:
                    if item.isdigit():
                        query = query | Q(user_id=request.user.id, id=item)
                        success = True
                if success:
                    counter = Contact.objects.filter(query).delete()[0]
                    return JsonResponse({'Status': True, 'Objects deleted': counter},
                                        status=status.HTTP_200_OK)
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def put(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if 'id' in request.data:
                if request.data['id'].isdigit():
                    contact = Contact.objects.filter(id=request.data['id'],
                                                     user_id=request.user.id).first()
                    if contact:
                        serializer = ContactSerializer(contact,
                                                       data=request.data,
                                                       partial=True)
                        if serializer.is_valid():
                            serializer.save()
                            return JsonResponse({'Status': True}, status=status.HTTP_200_OK)
                        else:
                            JsonResponse({'Status': False, 'Errors': serializer.errors},
                                         status=status.HTTP_400_BAD_REQUEST)
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)







class OrderView(APIView):
    throttle_classes = (UserRateThrottle, )

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            order = Order.objects.filter(
                user_id=request.user.id).exclude(
                state='cart').prefetch_related(
                'ordered_items__product_info__product__category',
                'ordered_items__product_info__product_parameters__parameter').select_related(
                'contact').annotate(
                total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()
            serializer = OrderSerializer(order, many=True)
            return Response(serializer.data)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)

    def post(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            if {'id', 'contact'}.issubset(request.data):
                if request.data['id'].isdigit():
                    try:
                        success = Order.objects.filter(
                            user_id=request.user.id,
                            id=request.data['id']).update(
                            contact_id=request.data['contact'],
                            state='new')
                    except IntegrityError as error:
                        return JsonResponse({'Status': False, 'Error': 'Invalid request'},
                                            status=status.HTTP_400_BAD_REQUEST)
                    else:
                        if success:
                            new_order.send(sender=self.__class__,
                                           user_id=request.user.id)
                            return JsonResponse({'Status': True},
                                                status=status.HTTP_200_OK)
            else:
                return JsonResponse({'Status': False, 'Errors': "You didn't specify all the arguments"},
                                    status=status.HTTP_400_BAD_REQUEST)
        else:
            return JsonResponse({'Status': False, 'Errors': 'You have not authenticated'},
                                status=status.HTTP_403_FORBIDDEN)
